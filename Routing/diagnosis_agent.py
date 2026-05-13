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
import re
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
    
    # === 新增字段：多服务环境支持 ===
    config_status: str                 # "none" | "partial" | "complete"
    servers_config: dict               # 四组件配置 {frontend, backend, database, redis}
    discovered_containers: List[dict]  # Docker ps 发现的容器
    service_status_summary: str        # 服务未启动时的摘要信息

# ===== LLM 初始化 =====

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE
)

# ===== 辅助函数 =====

def load_servers_config(env_file_path: str = ".env") -> dict:
    """从 .env 文件加载服务器配置"""
    from dotenv import dotenv_values
    
    config = dotenv_values(env_file_path)
    
    servers = {
        "frontend": {},
        "backend": {},
        "database": {},
        "redis": {}
    }
    
    # 前端配置
    if config.get("FRONTEND_SSH_HOST"):
        servers["frontend"] = {
            "ssh_host": config["FRONTEND_SSH_HOST"],
            "ssh_port": int(config.get("FRONTEND_SSH_PORT", "22")),
            "ssh_user": config.get("FRONTEND_SSH_USER", "root"),
            "ssh_key_path": config.get("FRONTEND_SSH_KEY_PATH", ""),
            "container_name": config.get("FRONTEND_CONTAINER_NAME", "")
        }
    
    # 后端配置
    if config.get("BACKEND_SSH_HOST"):
        servers["backend"] = {
            "ssh_host": config["BACKEND_SSH_HOST"],
            "ssh_port": int(config.get("BACKEND_SSH_PORT", "22")),
            "ssh_user": config.get("BACKEND_SSH_USER", "root"),
            "ssh_key_path": config.get("BACKEND_SSH_KEY_PATH", ""),
            "container_name": config.get("BACKEND_CONTAINER_NAME", "ruoyi-app")
        }
    
    # 数据库配置
    if config.get("DATABASE_HOST"):
        servers["database"] = {
            "host": config["DATABASE_HOST"],
            "port": int(config.get("DATABASE_PORT", "3306")),
            "user": config.get("DATABASE_USER", "root"),
            "password": config.get("DATABASE_PASSWORD", ""),
            "name": config.get("DATABASE_NAME", "")
        }
    
    # Redis 配置
    if config.get("REDIS_HOST"):
        servers["redis"] = {
            "host": config["REDIS_HOST"],
            "port": int(config.get("REDIS_PORT", "6379")),
            "password": config.get("REDIS_PASSWORD", "")
        }
    
    return servers

def determine_config_status(servers_config: dict) -> str:
    """判断配置状态"""
    configured_count = sum(1 for v in servers_config.values() if v)
    
    if configured_count == 0:
        return "none"
    elif configured_count < 4:
        return "partial"
    else:
        return "complete"

def get_stopped_services(state: DiagnosisState) -> List[str]:
    """获取未启动的服务列表"""
    required_types = ['frontend', 'backend', 'database', 'redis']
    discovered = state.get('discovered_containers', [])
    found_types = {c['type'] for c in discovered if c.get('type')}
    
    return list(set(required_types) - found_types)

def has_stopped_services(state: DiagnosisState) -> bool:
    """检查是否有服务未启动"""
    return len(get_stopped_services(state)) > 0

def check_logs_for_service_stop(state: DiagnosisState, stopped_services: List[str]) -> str:
    """检查日志中是否有服务停止的证据"""
    logs_data = state.get('logs_data', '')
    if not logs_data:
        return ""
    
    evidence_keywords = {
        'frontend': ['nginx.*stop', 'frontend.*exit', 'connection refused.*80'],
        'backend': ['java.*exit', 'spring.*shutdown', 'application.*failed', 'connection refused.*8080'],
        'database': ['mysql.*shutdown', 'mysqld.*stop', 'connection refused.*3306'],
        'redis': ['redis.*exit', 'redis-server.*stop', 'connection refused.*6379']
    }
    
    evidence_lines = []
    for service in stopped_services:
        keywords = evidence_keywords.get(service, [])
        for line in logs_data.splitlines():
            if any(re.search(kw, line, re.IGNORECASE) for kw in keywords):
                evidence_lines.append(line)
    
    return '\n'.join(evidence_lines[:20])  # 最多返回20条证据

def format_stopped_services(stopped_services: List[str], logs_evidence: str) -> str:
    """格式化服务未启动的摘要信息"""
    summary = f"检测到以下服务未启动: {', '.join(stopped_services)}\n\n"
    if logs_evidence:
        summary += f"日志证据:\n{logs_evidence}"
    return summary

def identify_container_type(name: str, ports: str) -> str:
    """根据容器名称和端口识别容器类型"""
    name_lower = name.lower()
    ports_lower = ports.lower()
    
    # 前端识别（优先级较低，避免误判）
    if '80/tcp' in ports_lower and '8080/tcp' not in ports_lower:
        return 'frontend'
    if '443/tcp' in ports_lower:
        return 'frontend'
    if any(kw in name_lower for kw in ['frontend', 'vue', 'nginx']):
        return 'frontend'
    
    # 后端识别（优先级较高）
    if '8080/tcp' in ports_lower:
        return 'backend'
    if any(kw in name_lower for kw in ['app', 'backend', 'java', 'spring']):
        return 'backend'
    
    # 数据库识别
    if any(kw in name_lower for kw in ['mysql', 'mariadb', 'postgres']):
        return 'database'
    if '3306/tcp' in ports_lower or '5432/tcp' in ports_lower:
        return 'database'
    
    # Redis 识别
    if 'redis' in name_lower or '6379/tcp' in ports_lower:
        return 'redis'
    
    return 'unknown'

# ===== 节点函数 =====

async def analyze_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点1：分析当前状态，决定下一步要做什么
    """
    print(f"\n{'='*70}")
    print(f"[Analyze] 分析当前状态 (迭代 {state['iteration_count']}/{state['max_iterations']})")
    print(f"{'='*70}")
    
    # === 强制检查最大迭代次数 ===
    if state['iteration_count'] >= state['max_iterations']:
        print(f"[Analyze] ⚠️ 已达到最大迭代次数 ({state['max_iterations']}),强制生成报告")
        return {
            **state,
            "current_step": "generate_report",
            "actions_taken": state.get('actions_taken', []) + ["force_stop_by_max_iterations"]
        }
    
    # === 新增:服务未启动的快速判断 ===
    if state.get('config_status') == 'complete' and has_stopped_services(state):
        stopped_services = get_stopped_services(state)
        logs_data = state.get('logs_data', '')
        
        # 如果已有日志数据,检查是否有服务停止的证据
        if logs_data:
            logs_evidence = check_logs_for_service_stop(state, stopped_services)
            
            if logs_evidence:  # 日志中有相关证据
                print(f"[Analyze] 检测到 {len(stopped_services)} 个服务未启动,直接生成报告")
                return {
                    **state,
                    "current_step": "generate_report",
                    "service_status_summary": format_stopped_services(stopped_services, logs_evidence),
                    "actions_taken": state.get('actions_taken', []) + ["detect_stopped_services"]
                }
    
    # === 新增:配置不足的快速判断 ===
    if state.get('config_status') == 'none':
        print("[Analyze] 配置信息不足,返回错误")
        return {
            **state,
            "current_step": "error_no_config",
            "actions_taken": state.get('actions_taken', []) + ["check_config"]
        }
    
    # === 新增:部分配置时触发 Docker 发现 ===
    if state.get('config_status') == 'partial' and not state.get('discovered_containers'):
        print("[Analyze] 配置不完整,触发 Docker 容器发现")
        return {
            **state,
            "current_step": "discover_containers",
            "actions_taken": state.get('actions_taken', []) + ["trigger_discovery"]
        }
    
    # === 原有逻辑保持不变 ===
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


async def discover_containers_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点:Docker 容器发现
    通过 SSH 连接到所有已配置的服务器,获取所有运行中的容器信息
    """
    print(f"\n{'='*70}")
    print(f"[Discover Containers] 开始 Docker 容器发现")
    print(f"{'='*70}")
    
    # 从已配置的服务器中遍历所有有 SSH 配置的服务器
    servers_config = state.get('servers_config', {})
    
    # 收集所有有 SSH 配置的服务器
    ssh_servers = []
    for server_type in ['frontend', 'backend']:
        server = servers_config.get(server_type)
        if server and server.get('ssh_host'):
            ssh_servers.append((server_type, server))
    
    if not ssh_servers:
        print("[Discover Containers] 没有可用的服务器配置")
        return {
            **state,
            "discovered_containers": [],
            "iteration_count": state['iteration_count'] + 1
        }
    
    all_discovered = []
    
    # 遍历所有服务器
    for server_type, target_server in ssh_servers:
        try:
            # 使用 paramiko 建立 SSH 连接
            import warnings
            warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
            import paramiko
            
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 加载 SSH 密钥
            private_key = None
            key_types = [
                paramiko.RSAKey,
                paramiko.ECDSAKey,
                paramiko.Ed25519Key,
            ]
            
            key_path = target_server.get('ssh_key_path', '')
            for key_type in key_types:
                try:
                    private_key = key_type.from_private_key_file(key_path)
                    break
                except paramiko.SSHException:
                    continue
            
            if not private_key:
                print(f"[Discover Containers] 警告: 无法识别的密钥格式: {key_path}")
                continue
            
            # 建立连接
            ssh_client.connect(
                hostname=target_server['ssh_host'],
                port=target_server.get('ssh_port', 22),
                username=target_server.get('ssh_user', 'root'),
                pkey=private_key,
                timeout=30
            )
            
            print(f"[Discover Containers] SSH 连接成功: {target_server['ssh_host']}")
            
            # 执行 docker ps 命令
            stdin, stdout, stderr = ssh_client.exec_command(
                "docker ps --format '{{.Names}}\\t{{.Ports}}\\t{{.Status}}'"
            )
            
            output = stdout.read().decode('utf-8').strip()
            error_output = stderr.read().decode('utf-8').strip()
            
            if error_output:
                print(f"[Discover Containers] Docker 命令错误: {error_output}")
                ssh_client.close()
                continue
            
            # 解析输出
            discovered = []
            for line in output.splitlines():
                if not line.strip():
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 2:
                    container_name = parts[0].strip()
                    ports = parts[1].strip()
                    
                    # 识别容器类型
                    container_type = identify_container_type(container_name, ports)
                    
                    discovered.append({
                        "name": container_name,
                        "ports": ports,
                        "type": container_type,
                        "status": parts[2].strip() if len(parts) > 2 else "running",
                        "server": target_server['ssh_host']
                    })
            
            if discovered:
                print(f"[Discover Containers] 在 {target_server['ssh_host']} 上发现 {len(discovered)} 个容器:")
                for c in discovered:
                    print(f"  - {c['name']} ({c['type']}): {c['ports']}")
                all_discovered.extend(discovered)
            else:
                print(f"[Discover Containers] 在 {target_server['ssh_host']} 上未发现容器")
            
            # 关闭 SSH 连接
            ssh_client.close()
        
        except Exception as e:
            print(f"[Discover Containers] 连接 {target_server['ssh_host']} 失败: {str(e)}")
            continue
    
    # 汇总结果
    print(f"\n[Discover Containers] Docker 容器发现结束，一共发现了 {len(all_discovered)} 个容器:")
    if all_discovered:
        for c in all_discovered:
            print(f"  - {c['name']} ({c['type']}): {c['ports']} [服务器: {c['server']}]")
    else:
        print("  (无)")
    
    # 更新 servers_config 中的容器名称
    updated_config = state.get('servers_config', {}).copy()
    for container in all_discovered:
        if container['type'] == 'frontend' and not updated_config.get('frontend', {}).get('container_name'):
            updated_config.setdefault('frontend', {})['container_name'] = container['name']
        elif container['type'] == 'backend' and not updated_config.get('backend', {}).get('container_name'):
            updated_config.setdefault('backend', {})['container_name'] = container['name']
    
    return {
        **state,
        "discovered_containers": all_discovered,
        "servers_config": updated_config,
        "config_status": "complete",  # 发现后升级为 complete
        "iteration_count": state['iteration_count'] + 1
    }
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
                print(f"[Collect Data] CPU使用情况:")
                print(f"{cpu_info}")
                
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
                container_name = state['container_name']
                service_status = f"运行中: {status_data.get('running')}, 详情: {status_data.get('status_detail')}"
                print(f"[Collect Data] 服务状态 [{container_name}]:")
                print(f"  {service_status}")
                
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
                
                print(f"[Collect Data] MySQL 数据库状态:")
                print(f"  运行状态: {'✓ 运行中' if mysql_running else '✗ 未运行'}")
                if process_info:
                    print(f"  进程信息: {process_info}")
                if port_info:
                    print(f"  端口监听: {port_info}")
                if docker_info:
                    print(f"  Docker 容器: {docker_info}")
                
                mysql_status = f"运行状态: {'运行中' if mysql_running else '未运行'}\n进程: {process_info}\n端口: {port_info}\nDocker: {docker_info}"
                
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


async def generate_error_report_node(state: DiagnosisState) -> DiagnosisState:
    """生成配置不足的错误报告"""
    print(f"\n{'='*70}")
    print(f"[Error Report] 生成配置错误报告")
    print(f"{'='*70}")
    
    error_content = """## 错误:配置信息不足

请至少提供一个服务器的 SSH 配置信息(前端、后端、数据库或 Redis)。

### 配置说明:

请在 `.env` 文件中添加以下配置项(根据实际情况填写):

```bash
# 后端服务配置(推荐至少配置此项)
BACKEND_SSH_HOST=<你的服务器IP>
BACKEND_SSH_PORT=22
BACKEND_SSH_USER=<SSH用户名>
BACKEND_SSH_KEY_PATH=<SSH密钥文件路径>
BACKEND_CONTAINER_NAME=<后端容器名称>

# 前端服务配置(可选,系统会自动发现)
FRONTEND_SSH_HOST=<前端服务器IP>
FRONTEND_SSH_PORT=22
FRONTEND_SSH_USER=<SSH用户名>
FRONTEND_SSH_KEY_PATH=<SSH密钥文件路径>
FRONTEND_CONTAINER_NAME=<前端容器名称>

# 数据库配置(可选)
DATABASE_HOST=<数据库主机地址>
DATABASE_PORT=3306
DATABASE_USER=<数据库用户名>
DATABASE_PASSWORD=<数据库密码>

# Redis 配置(可选)
REDIS_HOST=<Redis主机地址>
REDIS_PORT=6379
REDIS_PASSWORD=<Redis密码>
```

### 说明:
- 至少配置一个服务器的 SSH 信息即可, 并保证前后端、数据库和 Redis 的配置正确, 以便系统自动发现
- 系统会通过 Docker 自动发现其他相关服务
- 确保 SSH 密钥文件路径正确且有读取权限
- 请参考当前 `.env` 文件中已有的配置格式
"""
    
    return {
        **state,
        "diagnosis_result": {
            "content": error_content,
            "confidence": "low",
            "error_type": "missing_config"
        },
        "current_step": "complete"
    }


async def generate_report_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点4：基于收集的所有数据生成诊断报告
    """
    print(f"\n{'='*70}")
    print(f"[Generate Report] 生成最终诊断报告")
    print(f"{'='*70}")
    
    # === 新增:服务未启动的快速报告 ===
    service_status_summary = state.get('service_status_summary', '')
    if service_status_summary:
        print("[Generate Report] 生成服务未启动的快速报告")
        
        prompt = f"""你是运维诊断专家。检测到以下服务未启动：

{service_status_summary}

请基于以上信息生成诊断报告：
1. 明确指出哪些服务未启动
2. 分析可能的原因（基于日志证据）
3. 给出恢复步骤

【输出格式要求】
```markdown
## 问题根因
（精炼描述服务未启动的原因，引用日志证据）

## 立即执行
1. `docker start <container_name>` - 启动未运行的服务
2. `docker logs <container_name> --tail 50` - 查看启动日志确认正常
3. （根据实际情况补充其他步骤）...

## 长期优化
1. 配置容器自动重启策略：docker update --restart=unless-stopped <container>
2. 添加健康检查和监控告警
3. ...
```

**注意：只输出上述格式的内容，不要有任何其他文字！**
"""
        response = await llm.ainvoke(prompt)
        
        stopped_services = get_stopped_services(state)
        
        return {
            **state,
            "diagnosis_result": {
                "content": response.content,
                "confidence": "high",
                "data_sources": {
                    "service_status": True,
                    "logs": bool(state.get('logs_data'))
                },
                "stopped_services": stopped_services
            },
            "current_step": "complete"
        }
    
    # === 原有逻辑:正常诊断流程的报告生成 ===
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
    
    # === 新增:配置错误和服务未启动的快速路由 ===
    if action == "error_no_config":
        return "generate_error_report"
    
    if action == "discover_containers":
        return "discover_containers"
    
    # 如果 analyze_node 已经决定生成报告(服务未启动场景),直接路由
    if action == "generate_report":
        return "generate_report"
    
    # === 原有路由逻辑保持不变 ===
    if action in ["read_logs", "check_memory", "check_cpu", "check_service", "check_mysql"]:
        return "collect_data"
    
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
    
    # 原有节点
    builder.add_node("analyze", analyze_node)
    builder.add_node("collect_data", collect_data_node)
    builder.add_node("generate_report", generate_report_node)
    
    # 新增节点
    builder.add_node("discover_containers", discover_containers_node)
    builder.add_node("generate_error_report", generate_error_report_node)
    
    # 路由边
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges("analyze", route_after_analyze)
    builder.add_edge("discover_containers", "analyze")  # 发现后回到分析
    builder.add_edge("collect_data", "analyze")
    builder.add_edge("generate_report", END)
    builder.add_edge("generate_error_report", END)  # 新增
    
    return builder.compile()


# 创建工作流实例
diagnosis_workflow = build_diagnosis_workflow()


# ===== 对外接口 =====

async def run_diagnosis(
    alert_event: dict, 
    container_name: str = "ruoyi-app",  # 保持原有默认值
    env_file_path: str = ".env"
) -> dict:
    """
    运行诊断工作流（由Grafana告警自动触发）
    
    Args:
        alert_event: Grafana告警事件，包含以下字段：
            - alert_name: 告警名称
            - alert_type: 告警类型（container_restart, memory_high, cpu_high等）
            - alert_time: 告警时间
            - description: 告警描述
        container_name: 容器名称
        env_file_path: 配置文件路径
    
    Returns:
        诊断结果
    """
    # 1. 加载并验证配置
    servers_config = load_servers_config(env_file_path)
    config_status = determine_config_status(servers_config)
    
    # 2. 如果未指定容器名，尝试从配置推断
    if container_name == "ruoyi-app" and config_status != "none":
        # 根据告警类型推断目标容器
        alert_type = alert_event.get('alert_type', '')
        if 'frontend' in alert_type:
            container_name = servers_config.get('frontend', {}).get('container_name', container_name)
        elif 'backend' in alert_type or 'app' in alert_type:
            container_name = servers_config.get('backend', {}).get('container_name', container_name)
    
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
        "diagnosis_result": None,
        # 新增字段
        "config_status": config_status,
        "servers_config": servers_config,
        "discovered_containers": [],
        "service_status_summary": ""
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
