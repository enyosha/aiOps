"""
DiagnosisAgent - 纯LLM驱动的运维诊断Agent（与OpsAgent完全隔离）

设计原则：
- 不使用知识库检索
- 不执行诊断树
- 完全依赖LLM的推理能力
- 通过MCP工具获取实时数据
- 简单的ReAct循环：观察 → 思考 → 行动 → 重复
"""
import os
import sys
import json
from typing import TypedDict, List, Optional, Literal
from datetime import datetime, timedelta

from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# ===== State 定义 =====

class DiagnosisState(TypedDict):
    """诊断状态"""
    alert_event: dict                  # Grafana告警事件
    container_name: str                # 容器名称
    
    # 诊断过程
    messages: List                     # 对话历史
    current_step: str                  # 当前步骤
    iteration_count: int               # 迭代次数
    max_iterations: int                # 最大迭代次数
    actions_taken: List[str]           # 已执行的行动列表
    
    # 收集的数据
    anomaly_timestamps: List[str]      # 异常时间点列表(暂时保留)
    logs_data: Optional[str]           # 日志数据
    memory_info: Optional[str]         # 内存信息
    cpu_info: Optional[str]            # CPU信息
    service_status: Optional[str]      # 服务状态
    mysql_status: Optional[str]        # MySQL状态
    
    # 日志追溯
    log_search_range_minutes: int      # 当前日志搜索范围(分钟),初始30
    logs_collected_ranges: List[dict]  # 已收集的日志范围列表 [{"range": 30, "logs": "..."}, ...]
    
    # 诊断结果
    diagnosis_result: Optional[dict]   # 最终诊断结果

# ===== LLM 初始化 =====

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE
)

# ===== 节点函数 =====

async def analyze_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点1：分析当前状态，决定下一步要做什么
    """
    print(f"\n{'='*70}")
    print(f"[Analyze] 分析当前状态 (迭代 {state['iteration_count']}/{state['max_iterations']})")
    print(f"{'='*70}")
    
    # 构建分析提示
    actions_taken_str = ', '.join(state.get('actions_taken', [])) if state.get('actions_taken') else '无'
    
    alert = state.get('alert_event', {})
    alert_desc = f"{alert.get('alert_name', 'Unknown')} - {alert.get('description', '')}"
    
    prompt = f"""你是运维诊断专家。请基于当前已收集的数据决定下一步行动。

【已执行的行动】: {actions_taken_str}
【当前数据状态】:
- 内存信息: {'已收集' if state.get('memory_info') else '未收集'}
- CPU信息: {'已收集' if state.get('cpu_info') else '未收集'}
- 服务状态: {'已收集' if state.get('service_status') else '未收集'}
- MySQL状态: {'已收集' if state.get('mysql_status') else '未收集'}
- 日志数据: {'已收集' if state.get('logs_data') else '未收集'}
- 当前日志追溯范围: {state.get('log_search_range_minutes', 0)}分钟
- 已收集的日志范围: {len(state.get('logs_collected_ranges', []))}个

请决定下一步行动（只返回一个行动名称，不要其他内容）：
1. check_memory - 检查内存使用情况（如果还没有执行过）
2. check_cpu - 检查CPU使用情况（如果还没有执行过）
3. check_service - 检查服务运行状态（如果还没有执行过）
4. check_mysql - 检查MySQL数据库状态（如果还没有执行过）
5. read_logs - 读取或扩大日志追溯范围
6. generate_report - 生成诊断报告

决策规则：
1. 如果check_memory未执行 → check_memory
2. 如果check_memory已执行但check_cpu未执行 → check_cpu
3. 如果内存和CPU都已检查，但check_service未执行 → check_service
4. 如果核心资源指标已检查：
   a. 如果还未读取任何日志 → read_logs (首次读取30分钟)
   b. 如果已读取日志但范围 < 180分钟，且你认为需要更多信息 → read_logs (扩大范围)
   c. 如果已有足够信息或达到最大迭代次数 → generate_report
5. 如果达到最大迭代次数 → generate_report

重要判断逻辑：
- **先通过内存/CPU/服务状态进行初步判断**
- 如果资源状态异常(内存紧张/CPU高/服务异常) → 必须读取日志确认根因
- 如果已读取日志但未发现明显问题,但告警仍存在 → 考虑扩大追溯范围
- **日志是诊断的核心依据,不可跳过**

重要：
- **严禁重复执行已执行过的行动**
- 从“已执行的行动”列表中排除已经做过的
"""
    
    response = await llm.ainvoke(prompt)
    next_action = response.content.strip()
    
    print(f"[Analyze] 决定下一步行动: {next_action}")
    
    return {
        **state,
        "current_step": next_action,
        "actions_taken": state.get('actions_taken', []) + [next_action]
    }


# async def scan_anomalies_node(state: DiagnosisState) -> DiagnosisState:
#     """
#     节点2：快速扫描日志，识别异常时间点
#     """
#     print(f"\n{'='*70}")
#     print(f"[Scan Anomalies] 快速扫描异常时间点")
#     print(f"{'='*70}")
#     
#     from Routing.tool_cache import tool_cache
#     tools = await tool_cache.get_tools("log-reader")
#     scan_tool = next((t for t in tools if t.name == "scan_logs_for_anomalies"), None)
#     
#     if not scan_tool:
#         print("[Scan Anomalies] 未找到scan_logs_for_anomalies工具")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }
#     
#     try:
#         result = await scan_tool.ainvoke({
#             "container_name": state['container_name'],
#             "time_range_hours": 2  # 扫描过去2小时
#         })
#         
#         # 解析MCP返回格式
#         if isinstance(result, list) and len(result) > 0:
#             first_item = result[0]
#             if isinstance(first_item, dict) and 'text' in first_item:
#                 scan_data = json.loads(first_item['text'])
#             else:
#                 scan_data = first_item
#         else:
#             scan_data = result
#         
#         if scan_data.get('status') == 'success':
#             timestamps = scan_data.get('anomaly_timestamps', [])
#             print(f"[Scan Anomalies] 找到 {len(timestamps)} 个异常时间点")
#             for ts in timestamps[:5]:
#                 print(f"  - {ts}")
#             
#             return {
#                 **state,
#                 "anomaly_timestamps": timestamps,
#                 "iteration_count": state['iteration_count'] + 1
#             }
#         else:
#             print(f"[Scan Anomalies] 扫描失败: {scan_data.get('message')}")
#             return {
#                 **state,
#                 "anomaly_timestamps": [],
#                 "iteration_count": state['iteration_count'] + 1
#             }
#     
#     except Exception as e:
#         print(f"[Scan Anomalies] 错误: {str(e)}")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }


async def collect_data_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点3：根据当前步骤收集相应的数据
    """
    action = state['current_step']
    print(f"\n{'='*70}")
    print(f"[Collect Data] 执行行动: {action}")
    print(f"{'='*70}")
    
    from Routing.tool_cache import tool_cache
    
    if action == "read_logs":
        # 读取或扩大日志追溯范围
        log_tools = await tool_cache.get_tools("log-reader")
        read_tool = next((t for t in log_tools if t.name == "read_docker_logs"), None)
        
        if read_tool:
            # 确定本次读取的时间范围
            current_range = state.get('log_search_range_minutes', 0)
            
            if current_range == 0:
                # 首次读取,从30分钟开始
                new_range = 30
                print(f"[Collect Data] 首次读取最近{new_range}分钟日志")
            elif current_range < 180:
                # 扩大追溯范围: 30 → 60 → 120 → 180
                if current_range == 30:
                    new_range = 60
                elif current_range == 60:
                    new_range = 120
                else:
                    new_range = 180
                print(f"[Collect Data] 扩大追溯范围至{new_range}分钟")
            else:
                # 已达到最大范围
                print(f"[Collect Data] 已达到最大追溯范围(180分钟)")
                return {
                    **state,
                    "iteration_count": state['iteration_count'] + 1
                }
            
            now = datetime.now()
            since = (now - timedelta(minutes=new_range)).strftime("%Y-%m-%dT%H:%M:%S")
            until = now.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[Collect Data] 读取时间范围: {since} 到 {until}")
            
            result = await read_tool.ainvoke({
                "container_name": state['container_name'],
                "since_time": since,
                "until_time": until,
                "lines": 500,  # 增加行数,获取更多日志
                "log_level": None  # 不过滤，获取所有日志
            })
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    log_data = json.loads(first_item['text'])
                else:
                    log_data = first_item
            else:
                log_data = result
            
            if log_data.get('status') == 'success':
                new_logs = log_data.get('logs', '')
                line_count = log_data.get('line_count', 0)
                print(f"[Collect Data] 读取到 {line_count} 行日志")
                
                # 累积合并日志
                existing_ranges = state.get('logs_collected_ranges', [])
                existing_logs = state.get('logs_data', '')
                
                # 将新日志追加到现有日志
                if existing_logs:
                    combined_logs = existing_logs + "\n\n--- 扩大追溯范围至" + str(new_range) + "分钟 ---\n\n" + new_logs
                else:
                    combined_logs = new_logs
                
                # 记录已收集的范围
                existing_ranges.append({
                    "range_minutes": new_range,
                    "line_count": line_count,
                    "timestamp": datetime.now().isoformat()
                })
                
                print(f"[Collect Data] 累积日志总数: {len(combined_logs.splitlines())} 行")
                print(f"[Collect Data] 已收集范围: {[r['range_minutes'] for r in existing_ranges]}")
                
                return {
                    **state,
                    "logs_data": combined_logs,
                    "log_search_range_minutes": new_range,
                    "logs_collected_ranges": existing_ranges,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_memory":
        # 检查内存使用情况
        log_tools = await tool_cache.get_tools("log-reader")
        mem_tool = next((t for t in log_tools if t.name == "check_memory_usage"), None)
        
        if mem_tool:
            print(f"[Collect Data] 检查内存使用情况")
            
            result = await mem_tool.ainvoke({})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    mem_data = json.loads(first_item['text'])
                else:
                    mem_data = first_item
            else:
                mem_data = result
            
            if mem_data.get('status') == 'success':
                memory_info = mem_data.get('memory_info', '')
                print(f"[Collect Data] 内存信息:\n{memory_info}")
                
                return {
                    **state,
                    "memory_info": memory_info,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_cpu":
        # 检查CPU使用情况
        log_tools = await tool_cache.get_tools("log-reader")
        cpu_tool = next((t for t in log_tools if t.name == "check_cpu_usage"), None)
        
        if cpu_tool:
            print(f"[Collect Data] 检查CPU使用情况")
            
            result = await cpu_tool.ainvoke({})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    cpu_data = json.loads(first_item['text'])
                else:
                    cpu_data = first_item
            else:
                cpu_data = result
            
            if cpu_data.get('status') == 'success':
                cpu_info = cpu_data.get('cpu_info', '')
                print(f"[Collect Data] CPU信息已获取")
                
                return {
                    **state,
                    "cpu_info": cpu_info,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_service":
        # 检查服务状态
        log_tools = await tool_cache.get_tools("log-reader")
        status_tool = next((t for t in log_tools if t.name == "get_container_status"), None)
        
        if status_tool:
            print(f"[Collect Data] 检查服务状态")
            
            result = await status_tool.ainvoke({"container_name": state['container_name']})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    status_data = json.loads(first_item['text'])
                else:
                    status_data = first_item
            else:
                status_data = result
            
            if status_data.get('status') == 'success':
                service_status = f"运行中: {status_data.get('running')}, 详情: {status_data.get('status_detail')}"
                print(f"[Collect Data] 服务状态: {service_status}")
                
                return {
                    **state,
                    "service_status": service_status,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_mysql":
        # 检查MySQL状态
        log_tools = await tool_cache.get_tools("log-reader")
        mysql_tool = next((t for t in log_tools if t.name == "check_mysql_status"), None)
        
        if mysql_tool:
            print(f"[Collect Data] 检查MySQL数据库状态")
            
            result = await mysql_tool.ainvoke({})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    mysql_data = json.loads(first_item['text'])
                else:
                    mysql_data = first_item
            else:
                mysql_data = result
            
            if mysql_data.get('status') == 'success':
                mysql_running = mysql_data.get('mysql_running', False)
                process_info = mysql_data.get('process_info', '')
                port_info = mysql_data.get('port_info', '')
                docker_info = mysql_data.get('docker_info', '')
                
                mysql_status = f"运行中: {mysql_running}\n进程: {process_info}\n端口: {port_info}\nDocker: {docker_info}"
                print(f"[Collect Data] MySQL状态: {'运行中' if mysql_running else '未运行'}")
                
                return {
                    **state,
                    "mysql_status": mysql_status,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    # 如果没有执行任何操作，仍然增加迭代计数
    return {
        **state,
        "iteration_count": state['iteration_count'] + 1
    }


async def generate_report_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点4：基于收集的所有数据生成诊断报告
    """
    print(f"\n{'='*70}")
    print(f"[Generate Report] 生成最终诊断报告")
    print(f"{'='*70}")
    
    alert = state.get('alert_event', {})
    
    # 构建简洁的数据摘要
    memory_available = 'N/A'
    if state.get('memory_info'):
        try:
            # free -h 输出格式: total used free shared buff/cache available
            mem_line = state['memory_info'].splitlines()[1].split()
            memory_available = mem_line[6] if len(mem_line) > 6 else 'N/A'
        except:
            memory_available = 'N/A'
    
    # 日志追溯信息
    log_ranges = state.get('logs_collected_ranges', [])
    log_trace_info = ""
    logs_content = ""
    if log_ranges:
        ranges_str = ", ".join([f"{r['range_minutes']}min({r['line_count']}行)" for r in log_ranges])
        total_lines = sum(r['line_count'] for r in log_ranges)
        log_trace_info = f"\n日志追溯: 共{len(log_ranges)}次读取, 范围[{ranges_str}], 总计{total_lines}行"
        
        # 添加日志内容给LLM分析
        logs_data = state.get('logs_data', '')
        if logs_data:
            log_lines = logs_data.splitlines()
            if len(log_lines) <= 500:
                # 日志较少,直接包含全部内容
                logs_content = f"\n\n【日志内容】(共{len(log_lines)}行):\n{logs_data}"
            else:
                # 日志较多,提取关键错误和警告行
                error_keywords = ['error', 'exception', 'fatal', 'outofmemory', 'heap space', 
                                 'gc overhead', 'timeout', 'critical', 'warn', 'failed']
                key_lines = []
                for line in log_lines:
                    if any(keyword in line.lower() for keyword in error_keywords):
                        key_lines.append(line)
                
                # 如果找到关键行,取最多200行;否则取最后200行
                if key_lines:
                    selected_lines = key_lines[:200]
                    logs_content = f"\n\n【日志中的关键错误/警告】(共{len(key_lines)}条异常,显示前200条):\n" + "\n".join(selected_lines)
                else:
                    selected_lines = log_lines[-200:]
                    logs_content = f"\n\n【日志最后200行】:\n" + "\n".join(selected_lines)
    
    data_summary = f"""告警信息：
- 名称：{alert.get('alert_name', 'N/A')}
- 类型：{alert.get('alert_type', 'N/A')}
- 时间：{alert.get('alert_time', 'N/A')}
- 描述：{alert.get('description', 'N/A')}

容器：{state['container_name']}

关键指标：
- 内存可用：{memory_available}
- CPU状态：{'正常' if state.get('cpu_info') else '未收集'}
- MySQL状态：{'运行中' if state.get('mysql_status') and '运行中: True' in state.get('mysql_status', '') else '未检查或异常'}
- 服务状态：{state.get('service_status', '未收集')}{log_trace_info}{logs_content}
"""
    
    prompt = f"""你是运维诊断专家。请基于以下实时数据分析问题根因并给出解决方案。

{data_summary}

【重要要求】
1. 严格基于上述真实数据，不要编造信息
2. **综合分析所有收集的日志**,检查是否存在异常模式:
   - 错误信息(Exception, Error, Fatal, OutOfMemoryError等)
   - 警告信息(Warning, Timeout, Slow query等)
   - 异常重启或服务崩溃迹象
   - 性能退化(响应时间增加、资源使用率飙升等)
   - 任何与正常行为不符的模式
3. **结合内存、CPU、服务状态等资源指标进行综合判断**
4. 如果发现任何问题,必须在“问题根因”中明确指出
5. **只输出Markdown格式的诊断报告，不要添加任何额外的解释、总结或说明文字**
6. **不要在```markdown代码块之外添加任何内容**
7. 输出必须简洁明了，避免重复

【输出格式示例】
```markdown
## 问题根因
（语言精炼,引用具体数据和日志中的关键信息,不限字数）

## 立即执行
1. `命令1` - 作用说明
2. `命令2` - 作用说明
...

## 长期优化
1. 建议1
2. 建议2
3. 建议3
...
```

**注意：只输出上述格式的内容，不要有任何其他文字！**
"""
    
    response = await llm.ainvoke(prompt)
    
    print(f"[Generate Report] 诊断完成")
    
    return {
        **state,
        "diagnosis_result": {
            "content": response.content,
            "confidence": "high" if state.get('logs_data') and state.get('memory_info') else "medium",
            "data_sources": {
                "logs": bool(state.get('logs_data')),
                "memory": bool(state.get('memory_info')),
                "cpu": bool(state.get('cpu_info')),
                "service_status": bool(state.get('service_status'))
            }
        },
        "current_step": "complete"
    }


# ===== 路由逻辑 =====

def route_after_analyze(state: DiagnosisState) -> str:
    """根据分析结果路由到相应节点"""
    action = state['current_step']
    
    # if action == "scan_logs":
    #     return "scan_anomalies"
    if action in ["read_logs", "check_memory", "check_cpu", "check_service", "check_mysql"]:
        return "collect_data"
    elif action == "generate_report":
        return "generate_report"
    else:
        # 默认生成报告
        return "generate_report"


def route_after_collect(state: DiagnosisState) -> str:
    """数据收集后回到分析节点"""
    if state['iteration_count'] >= state['max_iterations']:
        print(f"[Route] 达到最大迭代次数，生成报告")
        return "generate_report"
    return "analyze"


# ===== 构建工作流 =====

def build_diagnosis_workflow():
    """构建诊断工作流"""
    builder = StateGraph(DiagnosisState)
    
    builder.add_node("analyze", analyze_node)
    # builder.add_node("scan_anomalies", scan_anomalies_node)  # 暂时注释
    builder.add_node("collect_data", collect_data_node)
    builder.add_node("generate_report", generate_report_node)
    
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges("analyze", route_after_analyze)
    # builder.add_edge("scan_anomalies", "analyze")  # 暂时注释
    builder.add_edge("collect_data", "analyze")
    builder.add_edge("generate_report", END)
    
    return builder.compile()


# 创建工作流实例
diagnosis_workflow = build_diagnosis_workflow()


# ===== 对外接口 =====

async def run_diagnosis(alert_event: dict, container_name: str = "ruoyi-app") -> dict:
    """
    运行诊断工作流（由Grafana告警自动触发）
    
    Args:
        alert_event: Grafana告警事件，包含以下字段：
            - alert_name: 告警名称
            - alert_type: 告警类型（container_restart, memory_high, cpu_high等）
            - alert_time: 告警时间
            - description: 告警描述
        container_name: 容器名称
    
    Returns:
        诊断结果
    """
    initial_state: DiagnosisState = {
        "alert_event": alert_event,
        "container_name": container_name,
        "messages": [],
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 8,  # 最多8次迭代
        "actions_taken": [],  # 已执行的行动列表
        "anomaly_timestamps": [],
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
        "service_status": None,
        "mysql_status": None,
        "log_search_range_minutes": 0,  # 初始为0,首次读取时设为30
        "logs_collected_ranges": [],  # 已收集的日志范围列表
        "diagnosis_result": None
    }
    
    try:
        final_state = await diagnosis_workflow.ainvoke(initial_state)
        
        return {
            "status": "success",
            "diagnosis": final_state.get("diagnosis_result"),
            "iteration_count": final_state.get("iteration_count"),
            "data_collected": {
                "logs": bool(final_state.get('logs_data')),
                "memory": bool(final_state.get('memory_info')),
                "cpu": bool(final_state.get('cpu_info')),
                "service_status": bool(final_state.get('service_status'))
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
