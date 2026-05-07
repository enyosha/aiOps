"""
OpsAgent - 运维诊断 Agent（Evaluator-Optimizer 模式）
"""
import os
import sys
import json
from typing import TypedDict, List, Optional, Literal
from datetime import datetime, timedelta

from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# ===== State 定义 =====

class OpsDiagnosisState(TypedDict):
    """运维诊断状态"""
    # 用户输入
    user_input: str
    container_name: Optional[str]
    
    # 诊断过程
    current_step: str
    iteration_count: int
    max_iterations: int
    
    # 检索相关
    search_query: str
    retrieved_results: List[dict]
    retrieval_quality: str
    
    # 评估反馈
    evaluator_feedback: Optional[str]
    
    # 诊断树相关
    diagnosis_tree: Optional[dict]  # 从知识库加载的诊断树
    current_tree_step: Optional[str]  # 当前执行的步骤
    step_execution_results: dict  # 各步骤的执行结果
    
    # 解决方案检索结果（第二阶段）
    solution_results: List[dict]
    
    # 实时数据
    logs_data: Optional[str]
    memory_info: Optional[str]
    cpu_info: Optional[str]
    service_status: Optional[str]  # 服务运行状态
    
    # 诊断结果
    detected_issues: List[str]
    diagnosis_result: Optional[dict]
    recommended_actions: List[str]

# ===== LLM 初始化 =====

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE
)

# 结构化输出的评估器
class EvaluationResult(BaseModel):
    quality: Literal["good", "needs_improvement", "poor"] = Field(
        description="检索结果的质量评估"
    )
    reason: str = Field(
        description="评估原因说明"
    )
    suggested_query: Optional[str] = Field(
        default=None,
        description="如果需要改进，建议的优化 query"
    )

evaluator_llm = llm.with_structured_output(EvaluationResult)

# ===== 节点函数 =====

async def initial_analysis_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 1：初步分析用户输入，提取关键信息并构建初始 query
    """
    print(f"\n{'='*70}")
    print(f"[Initial Analysis] 开始分析用户输入")
    print(f"{'='*70}")
    print(f"User input: {state['user_input']}")
    
    # 使用 LLM 提取关键信息
    analysis_prompt = f"""
    分析用户的运维问题描述，提取以下信息：
    
    用户输入：{state['user_input']}
    
    请以 JSON 格式返回：
    {{
        "symptoms": ["502", "timeout", "crash"],
        "container_name": "ruoyi-app 或 null",
        "time_context": "最近半小时 或具体时间点",
        "severity": "high/medium/low"
    }}
    
    只返回 JSON，不要其他内容。
    """
    
    try:
        response = await llm.ainvoke(analysis_prompt)
        extracted = json.loads(response.content)
    except:
        # 解析失败时使用默认值
        extracted = {
            "symptoms": ["unknown"],
            "container_name": None,
            "time_context": "recent",
            "severity": "medium"
        }
    
    print(f"Extracted symptoms: {extracted.get('symptoms')}")
    print(f"Container name from LLM: {extracted.get('container_name')}")
    
    # 【关键】优先使用 state 中的 container_name（用户显式传入），LLM 提取的作为备选
    final_container_name = state.get('container_name') or extracted.get('container_name')
    print(f"Final container name: {final_container_name}")
    
    # 构建初始查询
    symptoms = extracted.get('symptoms', [])
    time_context = extracted.get('time_context', 'recent')
    
    initial_query = f"{' '.join(symptoms)} error diagnosis troubleshooting"
    if time_context != 'recent':
        initial_query += f" {time_context}"
    
    print(f"Initial query: '{initial_query}'")
    
    return {
        **state,
        "current_step": "retrieve",
        "iteration_count": 0,
        "max_iterations": 3,
        "container_name": final_container_name,  # 使用合并后的容器名
        "search_query": initial_query,
        "detected_issues": symptoms
    }

async def retrieve_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 2：第一阶段检索 - 查找诊断树 (diagnosis_flow)
    """
    query = state['search_query']
    iteration = state['iteration_count']
    
    print(f"\n{'='*70}")
    print(f"[Retrieve Phase 1] 第 {iteration + 1} 次检索 查找合适的诊断树")
    print(f"{'='*70}")
    print(f"Query: '{query}'")
    print(f"Filter: type='diagnosis_flow'")
    
    # 调用 MCP 工具检索
    from Routing.tool_cache import tool_cache
    
    tools = await tool_cache.get_tools("ops-diagnosis")
    search_tool = next((t for t in tools if t.name == "search_ops_knowledge"), None)
    
    if not search_tool:
        return {
            **state,
            "retrieved_results": [],
            "retrieval_quality": "poor",
            "current_step": "diagnose"
        }
    
    try:
        # 【关键】传入 filter_type 参数，只检索 diagnosis_flow
        print(f"[Retrieve] Calling search_ops_knowledge tool...")
        result = await search_tool.ainvoke({
            "query": query, 
            "top_k": 3,
            "filter_type": "diagnosis_flow"
        })
        print(f"[Retrieve] Tool returned type: {type(result)}, length: {len(result) if isinstance(result, list) else 'N/A'}")
        
        # MCP 工具返回的是列表，需要解析
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json as json_module
                result_dict = json_module.loads(first_item['text'])
            else:
                result_dict = first_item
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {"status": "error", "message": f"Unexpected result type: {type(result)}"}
        
        retrieved = result_dict.get("results", []) if result_dict.get("status") == "success" else []
    except Exception as e:
        print(f"[Retrieve] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        retrieved = []
    
    print(f"Found {len(retrieved)} results")
    for i, r in enumerate(retrieved, 1):
        print(f"  [{i}] {r.get('title', 'N/A')} (相似度: {r.get('similarity_score', 0):.4f})")
    
    # 从第一个结果中提取 diagnosis_tree
    diagnosis_tree = None
    if retrieved:
        first_result = retrieved[0]
        metadata = first_result.get('metadata', {})
        if 'diagnosis_tree' in metadata:
            dt = metadata['diagnosis_tree']
            if isinstance(dt, str):
                import json as json_module
                try:
                    diagnosis_tree = json_module.loads(dt)
                    print(f"[Retrieve] Extracted diagnosis_tree from metadata (JSON string)")
                except:
                    print(f"[Retrieve] Failed to parse diagnosis_tree JSON string")
            else:
                diagnosis_tree = dt
                print(f"[Retrieve] Extracted diagnosis_tree from metadata (dict)")
    
    return {
        **state,
        "retrieved_results": retrieved,
        "diagnosis_tree": diagnosis_tree,
        "current_step": "evaluate"
    }

async def evaluate_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 3：评估检索结果的质量，决定是否需要优化 query 重新检索
    """
    results = state['retrieved_results']
    query = state['search_query']
    user_input = state['user_input']
    
    print(f"\n{'='*70}")
    print(f"[Evaluate] 评估检索质量")
    print(f"{'='*70}")
    
    if not results:
        print("[Evaluate] No results found, marking as poor quality")
        return {
            **state,
            "retrieval_quality": "poor",
            "current_step": "diagnose"
        }
    
    # 构建评估提示（必须包含 "json" 关键词以符合 DashScope API 要求）
    evaluation_prompt = f"""
    评估以下检索结果是否能够有效解决用户的问题。
    
    用户问题：{user_input}
    检索 Query：{query}
    
    检索结果：
    {json.dumps(results, indent=2, ensure_ascii=False)[:1000]}
    
    请评估：
    1. 检索结果的相关性（是否能解决用户问题）
    2. 是否包含了具体的诊断步骤或解决方案
    3. 如果需要改进，应该如何优化 query
    
    请以 JSON 格式返回评估结果，包含以下字段：
    - quality: "good"、"needs_improvement" 或 "poor"
    - reason: 评估原因说明
    - suggested_query: 如果需要改进，建议的优化 query
    
    只返回 json 格式的结果，不要其他内容。
    """
    
    try:
        evaluation = await evaluator_llm.ainvoke(evaluation_prompt)
        
        print(f"Quality: {evaluation.quality}")
        print(f"Reason: {evaluation.reason}")
        
        if evaluation.quality == 'good':
            print("[Evaluate] Quality is good, proceeding to load diagnosis tree")
            
            # 提取第一个结果的 diagnosis_tree（如果有）
            diagnosis_tree = None
            for result in results:
                # diagnosis_tree 可能直接在结果中，或者在 metadata 中（作为 JSON 字符串）
                if 'diagnosis_tree' in result:
                    # 直接包含
                    dt = result['diagnosis_tree']
                    if isinstance(dt, str):
                        import json as json_module
                        try:
                            diagnosis_tree = json_module.loads(dt)
                        except:
                            continue
                    else:
                        diagnosis_tree = dt
                    print(f"[Evaluate] Found diagnosis_tree in result: {result.get('title', 'N/A')}")
                    break
                elif 'metadata' in result and 'diagnosis_tree' in result['metadata']:
                    # 在 metadata 中（JSON 字符串）
                    dt_str = result['metadata']['diagnosis_tree']
                    if isinstance(dt_str, str):
                        import json as json_module
                        try:
                            diagnosis_tree = json_module.loads(dt_str)
                            print(f"[Evaluate] Found diagnosis_tree in metadata: {result.get('title', 'N/A')}")
                            break
                        except Exception as e:
                            print(f"[Evaluate] Failed to parse diagnosis_tree: {str(e)}")
                            continue
            
            if diagnosis_tree:
                print(f"[Evaluate] Diagnosis tree loaded with {len(diagnosis_tree)} steps")
            else:
                print("[Evaluate] No diagnosis tree found in results")
            
            return {
                **state,
                "retrieval_quality": "good",
                "evaluator_feedback": evaluation.reason,
                "diagnosis_tree": diagnosis_tree,
                "current_step": "execute_tree" if diagnosis_tree else "diagnose"
            }
        else:
            # 检查迭代次数
            if state['iteration_count'] >= state['max_iterations']:
                print(f"[Evaluate] Max iterations ({state['max_iterations']}) reached")
                return {
                    **state,
                    "retrieval_quality": "poor",
                    "evaluator_feedback": evaluation.reason,
                    "current_step": "diagnose"
                }
            else:
                # 优化 query 并重新检索
                optimized_query = evaluation.suggested_query or query
                print(f"[Evaluate] Optimizing query: '{optimized_query}'")
                
                return {
                    **state,
                    "search_query": optimized_query,
                    "iteration_count": state['iteration_count'] + 1,
                    "evaluator_feedback": evaluation.reason,
                    "retrieval_quality": "needs_improvement",
                    "current_step": "retrieve"
                }
    
    except Exception as e:
        print(f"[Evaluate] Error: {str(e)}")
        return {
            **state,
            "retrieval_quality": "poor",
            "current_step": "diagnose"
        }

async def execute_tree_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 4：执行诊断树中的步骤
    """
    print(f"\n{'='*70}")
    print(f"[Execute Tree] 开始执行诊断树")
    print(f"{'='*70}")
    
    diagnosis_tree = state.get('diagnosis_tree')
    container_name = state.get('container_name') or os.getenv('OPS_DEFAULT_CONTAINER', 'ruoyi-app')
    
    if not diagnosis_tree:
        print("[Execute Tree] No diagnosis tree found, skipping to diagnose")
        return {
            **state,
            "current_step": "diagnose"
        }
    
    print(f"[Execute Tree] Container: {container_name}")
    print(f"[Execute Tree] Total steps: {len(diagnosis_tree)}")
    
    # 获取 MCP 工具
    from Routing.tool_cache import tool_cache
    tools = await tool_cache.get_tools("ops-diagnosis")
    fetch_logs_tool = next((t for t in tools if t.name == "fetch_docker_logs"), None)
    
    step_results = {}
    current_service_status = "unknown"
    
    # 执行 step_1_check_service
    if 'step_1_check_service' in diagnosis_tree:
        step = diagnosis_tree['step_1_check_service']
        print(f"\n[Execute Tree] Executing: {step['description']}")
        
        # 执行命令：docker ps | grep <container_name>
        try:
            cmd = f"docker ps | grep {container_name}"
            print(f"[Execute Tree] Running: {cmd}")
            
            # 通过 SSH 执行命令
            import paramiko
            ssh_host = os.getenv("SSH_HOST", "8.130.131.36")
            ssh_port = int(os.getenv("SSH_PORT", "22"))
            ssh_user = os.getenv("SSH_USER", "root")
            ssh_key_path = os.getenv("SSH_KEY_PATH", "./aiOps.pem")
            
            private_key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(hostname=ssh_host, port=ssh_port, username=ssh_user, pkey=private_key)
            
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            output = stdout.read().decode('utf-8').strip()
            exit_code = stdout.channel.recv_exit_status()
            
            ssh_client.close()
            
            service_running = exit_code == 0 and len(output) > 0
            current_service_status = "running" if service_running else "stopped"
            
            step_results['step_1_check_service'] = {
                "command": cmd,
                "output": output[:500] if output else "No output",
                "service_running": service_running,
                "exit_code": exit_code
            }
            
            print(f"[Execute Tree] Service status: {current_service_status}")
            
            # 根据结果决定下一步
            if service_running:
                print("[Execute Tree] Service is running, proceeding to check resources")
                next_step = 'step_2_check_resources'
            else:
                print("[Execute Tree] Service is NOT running, checking crash reason")
                next_step = 'step_3_check_crash_reason'
            
        except Exception as e:
            print(f"[Execute Tree] Error executing step 1: {str(e)}")
            step_results['step_1_check_service'] = {
                "error": str(e),
                "service_running": False
            }
            current_service_status = "error"
            next_step = 'step_3_check_crash_reason'
    else:
        next_step = 'step_2_check_resources'
    
    # 执行 step_2_check_resources（如果服务在运行）
    if next_step == 'step_2_check_resources' and 'step_2_check_resources' in diagnosis_tree:
        step = diagnosis_tree['step_2_check_resources']
        print(f"\n[Execute Tree] Executing: {step['description']}")
        
        try:
            # 获取内存和 CPU 信息
            memory_info = None
            cpu_info = None
            
            check_memory_tool = next((t for t in tools if t.name == "check_memory_usage"), None)
            check_cpu_tool = next((t for t in tools if t.name == "check_cpu_usage"), None)
            
            if check_memory_tool:
                mem_result = await check_memory_tool.ainvoke({})
                print(f"[Execute Tree] Raw mem_result type: {type(mem_result)}, length: {len(mem_result) if isinstance(mem_result, list) else 'N/A'}")
                
                if isinstance(mem_result, list) and len(mem_result) > 0:
                    import json as json_module
                    first_item = mem_result[0]
                    print(f"[Execute Tree] First item type: {type(first_item)}")
                    
                    if isinstance(first_item, dict) and 'text' in first_item:
                        print(f"[Execute Tree] Parsing JSON from 'text' field, length: {len(first_item['text'])}")
                        mem_data = json_module.loads(first_item['text'])
                    else:
                        mem_data = first_item
                    
                    print(f"[Execute Tree] mem_data keys: {list(mem_data.keys()) if isinstance(mem_data, dict) else 'Not a dict'}")
                    
                    if mem_data.get("status") == "success":
                        memory_info = mem_data.get("memory_info", "")
                        print(f"[Execute Tree] memory_info length: {len(memory_info) if memory_info else 0}")
            
            if check_cpu_tool:
                cpu_result = await check_cpu_tool.ainvoke({})
                if isinstance(cpu_result, list) and len(cpu_result) > 0:
                    import json as json_module
                    first_item = cpu_result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        cpu_data = json_module.loads(first_item['text'])
                    else:
                        cpu_data = first_item
                    if cpu_data.get("status") == "success":
                        cpu_info = cpu_data.get("cpu_info", "")
            
            step_results['step_2_check_resources'] = {
                "memory_info": memory_info,
                "cpu_info": cpu_info
            }
            
            print(f"[Execute Tree] Resource check completed")
            
            # 判断内存是否不足（可用内存 < 200MB）
            memory_critical = False
            if memory_info:
                print(f"[Execute Tree] Memory info (full): {repr(memory_info)}")  # 打印完整内容用于调试
                
                # 尝试从内存信息中提取可用内存数值
                import re
                # free -h 输出格式：Mem: total used free shared buff/cache available
                # 需要匹配 Mem 行最后一个数字（available 列）
                match = re.search(r'Mem:\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)Mi', memory_info)
                
                if match:
                    available_mb = int(match.group(1))
                    print(f"[Execute Tree] Extracted available memory: {available_mb}Mi")
                    if available_mb < 250:  # 可用内存 < 250MB 视为紧张
                        memory_critical = True
                        print(f"[Execute Tree] Memory critical: {available_mb}Mi available (< 250MB)")
                else:
                    print(f"[Execute Tree] Failed to extract available memory with regex")
            
            if memory_critical:
                print("[Execute Tree] Memory is low, setting current_step to retrieve_solution")
                next_step = 'retrieve_solution'
            else:
                print("[Execute Tree] Resources seem normal, proceeding to network check")
                next_step = 'step_4_check_network'
                
        except Exception as e:
            print(f"[Execute Tree] Error executing step 2: {str(e)}")
            step_results['step_2_check_resources'] = {"error": str(e)}
            next_step = 'diagnose'
    
    # 执行 step_3_check_crash_reason（如果服务未运行）
    if next_step == 'step_3_check_crash_reason' and 'step_3_check_crash_reason' in diagnosis_tree:
        step = diagnosis_tree['step_3_check_crash_reason']
        print(f"\n[Execute Tree] Executing: {step['description']}")
        
        try:
            # 获取容器日志
            logs_data = None
            if fetch_logs_tool:
                now = datetime.now()
                lookback_minutes = int(os.getenv('OPS_DIAGNOSIS_LOOKBACK_MINUTES', '30'))
                since_time = (now - timedelta(minutes=lookback_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
                
                log_result = await fetch_logs_tool.ainvoke({
                    "container_name": container_name,
                    "since_time": since_time,
                    "lines": 100
                })
                
                if isinstance(log_result, list) and len(log_result) > 0:
                    import json as json_module
                    first_item = log_result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        log_data = json_module.loads(first_item['text'])
                    else:
                        log_data = first_item
                    if log_data.get("status") == "success":
                        logs_data = log_data.get("logs", "")
            
            # 检查 dmesg 是否有 OOM
            oom_detected = False
            if logs_data:
                oom_keywords = ["Out of memory", "oom-kill", "Killed process"]
                oom_detected = any(keyword.lower() in logs_data.lower() for keyword in oom_keywords)
            
            step_results['step_3_check_crash_reason'] = {
                "logs_preview": logs_data[:500] if logs_data else "No logs",
                "oom_detected": oom_detected
            }
            
            if oom_detected:
                print("[Execute Tree] OOM detected! Setting current_step to retrieve_solution")
                next_step = 'retrieve_solution'
            else:
                print("[Execute Tree] No OOM detected, proceeding to collect_data")
                next_step = 'collect_data'
                
        except Exception as e:
            print(f"[Execute Tree] Error executing step 3: {str(e)}")
            step_results['step_3_check_crash_reason'] = {"error": str(e)}
            next_step = 'diagnose'
    
    print(f"\n[Execute Tree] Next step: {next_step}")
    
    return {
        **state,
        "step_execution_results": step_results,
        "service_status": current_service_status,
        "current_step": next_step,
        "_next_node": next_step  # 添加一个专门的字段用于路由决策
    }


async def retrieve_solution_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 5：第二阶段检索 - 基于诊断结果查找解决方案 (solution)
    """
    print(f"\n{'='*70}")
    print(f"[Retrieve Phase 2] 第二阶段检索")
    print(f"{'='*70}")
    
    # 构建解决方案检索 query
    step_results = state.get('step_execution_results', {})
    user_input = state['user_input']
    
    # 从诊断树执行结果中提取关键信息
    solution_keywords = []
    
    # 检查是否有 OOM 检测
    if 'step_3_check_crash_reason' in step_results:
        if step_results['step_3_check_crash_reason'].get('oom_detected'):
            solution_keywords.append("OOM killer java process memory insufficient")
    
    # 检查是否有内存不足
    if 'step_2_check_resources' in step_results:
        resource_info = step_results['step_2_check_resources'].get('memory_info', '')
        if '1.7GiB' in resource_info or '紧张' in resource_info:
            solution_keywords.append("memory insufficient low available")
    
    # 默认使用用户输入 + 诊断结果
    if not solution_keywords:
        solution_query = f"{user_input} solution fix"
    else:
        solution_query = ' '.join(solution_keywords)
    
    print(f"Solution Query: '{solution_query}'")
    print(f"Filter: type='solution'")
    
    # 调用 MCP 工具检索
    from Routing.tool_cache import tool_cache
    tools = await tool_cache.get_tools("ops-diagnosis")
    search_tool = next((t for t in tools if t.name == "search_ops_knowledge"), None)
    
    if not search_tool:
        print("[Retrieve Phase 2] Search tool not found")
        return {
            **state,
            "solution_results": [],
            "current_step": "collect_data"
        }
    
    try:
        # 【关键】传入 filter_type 参数，只检索 solution
        print(f"[Retrieve Phase 2] Calling search_ops_knowledge tool...")
        result = await search_tool.ainvoke({
            "query": solution_query,
            "top_k": 2,
            "filter_type": "solution"
        })
        print(f"[Retrieve Phase 2] Tool returned type: {type(result)}, length: {len(result) if isinstance(result, list) else 'N/A'}")
        
        # 解析结果
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json as json_module
                result_dict = json_module.loads(first_item['text'])
            else:
                result_dict = first_item
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {"status": "error", "message": f"Unexpected result type: {type(result)}"}
        
        solutions = result_dict.get("results", []) if result_dict.get("status") == "success" else []
    except Exception as e:
        print(f"[Retrieve Phase 2] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        solutions = []
    
    print(f"Found {len(solutions)} solutions")
    for i, s in enumerate(solutions, 1):
        print(f"  [{i}] {s.get('title', 'N/A')} (相似度: {s.get('similarity_score', 0):.4f})")
    
    return {
        **state,
        "solution_results": solutions,
        "current_step": "collect_data"
    }


async def collect_data_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 5：收集实时数据（日志、内存、CPU）
    """
    print(f"\n{'='*70}")
    print(f"[Collect Data] 收集实时数据")
    print(f"{'='*70}")
    
    container_name = state.get('container_name') or os.getenv('OPS_DEFAULT_CONTAINER', 'ruoyi-app')
    print(f"[Collect Data] Container name: {container_name}")
    
    # 获取实时数据
    logs_data = None
    memory_info = None
    cpu_info = None
    
    from Routing.tool_cache import tool_cache
    tools = await tool_cache.get_tools("ops-diagnosis")
    
    fetch_logs_tool = next((t for t in tools if t.name == "fetch_docker_logs"), None)
    check_memory_tool = next((t for t in tools if t.name == "check_memory_usage"), None)
    check_cpu_tool = next((t for t in tools if t.name == "check_cpu_usage"), None)
    
    # 获取容器日志
    if fetch_logs_tool:
        try:
            now = datetime.now()
            lookback_minutes = int(os.getenv('OPS_DIAGNOSIS_LOOKBACK_MINUTES', '30'))
            since_time = (now - timedelta(minutes=lookback_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
            
            print(f"[Collect Data] Fetching logs from {since_time}...")
            log_result = await fetch_logs_tool.ainvoke({
                "container_name": container_name,
                "since_time": since_time,
                "lines": int(os.getenv('OPS_LOG_DEFAULT_LINES', '200'))
            })
            
            # 解析返回结果
            if isinstance(log_result, list) and len(log_result) > 0:
                first_item = log_result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    import json as json_module
                    log_data = json_module.loads(first_item['text'])
                else:
                    log_data = first_item
            elif isinstance(log_result, dict):
                log_data = log_result
            else:
                log_data = {}
            
            if log_data.get("status") == "success":
                logs_data = log_data.get("logs", "")
                print(f"[Collect Data] ✓ Fetched {log_data.get('line_count', 0)} log lines")
            else:
                print(f"[Collect Data] ✗ Failed to fetch logs: {log_data.get('message', 'Unknown error')}")
        except Exception as e:
            print(f"[Collect Data] ✗ Failed to fetch logs: {str(e)}")
    
    # 获取内存使用情况
    if check_memory_tool:
        try:
            print(f"[Collect Data] Checking memory usage...")
            mem_result = await check_memory_tool.ainvoke({})
            
            # 解析返回结果
            if isinstance(mem_result, list) and len(mem_result) > 0:
                first_item = mem_result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    import json as json_module
                    mem_data = json_module.loads(first_item['text'])
                else:
                    mem_data = first_item
            elif isinstance(mem_result, dict):
                mem_data = mem_result
            else:
                mem_data = {}
            
            if mem_data.get("status") == "success":
                memory_info = mem_data.get("memory_info", "")
                print(f"[Collect Data] ✓ Memory info retrieved")
            else:
                print(f"[Collect Data] ✗ Failed to get memory info")
        except Exception as e:
            print(f"[Collect Data] ✗ Failed to get memory info: {str(e)}")
    
    # 获取 CPU 使用情况
    if check_cpu_tool:
        try:
            print(f"[Collect Data] Checking CPU usage...")
            cpu_result = await check_cpu_tool.ainvoke({})
            
            # 解析返回结果
            if isinstance(cpu_result, list) and len(cpu_result) > 0:
                first_item = cpu_result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    import json as json_module
                    cpu_data = json_module.loads(first_item['text'])
                else:
                    cpu_data = first_item
            elif isinstance(cpu_result, dict):
                cpu_data = cpu_result
            else:
                cpu_data = {}
            
            if cpu_data.get("status") == "success":
                cpu_info = cpu_data.get("cpu_info", "")
                print(f"[Collect Data] ✓ CPU info retrieved")
            else:
                print(f"[Collect Data] ✗ Failed to get CPU info")
        except Exception as e:
            print(f"[Collect Data] ✗ Failed to get CPU info: {str(e)}")
    
    return {
        **state,
        "logs_data": logs_data,
        "memory_info": memory_info,
        "cpu_info": cpu_info,
        "current_step": "diagnose"
    }


async def diagnose_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 6：基于诊断树执行结果、解决方案和实时数据生成最终诊断报告
    """
    print(f"\n{'='*70}")
    print(f"[Diagnose] 生成最终诊断报告")
    print(f"{'='*70}")
    
    results = state['retrieved_results']
    solution_results = state.get('solution_results', [])
    user_input = state['user_input']
    logs_data = state.get('logs_data')
    memory_info = state.get('memory_info')
    cpu_info = state.get('cpu_info')
    step_results = state.get('step_execution_results', {})
    service_status = state.get('service_status', 'unknown')
    
    print(f"[Diagnose] Service status: {service_status}")
    print(f"[Diagnose] Step results keys: {list(step_results.keys())}")
    print(f"[Diagnose] Solution results count: {len(solution_results)}")
    
    # 使用 LLM 生成诊断报告
    diagnosis_prompt = f"""
    你是一个专业的运维故障诊断专家。基于以下信息生成详细的诊断报告。
    
    【用户问题】
    {user_input}
    
    【诊断树执行结果】
    {json.dumps(step_results, indent=2, ensure_ascii=False)[:1000] if step_results else "未执行诊断树"}
    
    【检索到的诊断流程】
    {json.dumps(results, indent=2, ensure_ascii=False)[:500] if results else "未找到相关知识"}
    
    【检索到的解决方案】
    {json.dumps(solution_results, indent=2, ensure_ascii=False)[:800] if solution_results else "未找到特定解决方案"}
    
    【实时数据】
    容器日志（最近 30 分钟）：
    {logs_data[:800] if logs_data else "无"}
    
    内存使用情况：
    {memory_info if memory_info else "无"}
    
    CPU 使用情况：
    {cpu_info if cpu_info else "无"}
    
    【要求】
    请生成结构化的诊断报告，必须结合以下内容：
    1. **问题根因分析**：基于诊断树执行结果和实时数据，详细说明导致问题的根本原因
    2. **立即执行的修复命令**：从【检索到的解决方案】中提取具体的命令，每个命令标注作用
    3. **长期优化建议**：防止问题再次发生的措施
    
    输出格式：
    ```
    【诊断结果】
    （简要总结）
    
    【根本原因】
    （详细分析，引用具体的数据和执行结果）
    
    【立即执行】
    1. 命令1 # 作用说明
    2. 命令2 # 作用说明
    
    【长期优化】
    1. 建议1
    2. 建议2
    ```
    """
    
    try:
        diagnosis = await llm.ainvoke(diagnosis_prompt)
        
        return {
            **state,
            "diagnosis_result": {
                "content": diagnosis.content,
                "confidence": "high" if state['retrieval_quality'] == 'good' and step_results else "medium",
                "iteration_count": state['iteration_count'],
                "steps_executed": list(step_results.keys())
            },
            "current_step": "complete"
        }
    except Exception as e:
        return {
            **state,
            "diagnosis_result": {
                "content": f"诊断失败: {str(e)}",
                "confidence": "low"
            },
            "current_step": "complete"
        }

# ===== 路由逻辑 =====

def route_after_evaluate(state: OpsDiagnosisState) -> str:
    """评估后的路由决策"""
    # 如果 evaluator 已经设置了 current_step，直接使用
    if state.get('current_step') in ['execute_tree', 'diagnose']:
        return state['current_step']
    
    # 否则根据检索质量决定
    if state['retrieval_quality'] == 'good':
        return "execute_tree"  # 有诊断树时执行
    elif state['retrieval_quality'] == 'needs_improvement':
        return "retrieve"
    else:
        return "diagnose"


def route_after_execute_tree(state: OpsDiagnosisState) -> str:
    """诊断树执行后的路由决策"""
    # 检查专门的 _next_node 字段
    next_node = state.get('_next_node')
    if next_node == 'retrieve_solution':
        print(f"[Route] Routing to retrieve_solution based on _next_node")
        return "retrieve_solution"
    elif next_node == 'collect_data':
        print(f"[Route] Routing to collect_data based on _next_node")
        return "collect_data"
    elif next_node == 'diagnose':
        print(f"[Route] Routing to diagnose based on _next_node")
        return "diagnose"
    else:
        # 默认行为：根据 current_step 判断
        if state.get('current_step') == 'retrieve_solution':
            return "retrieve_solution"
        else:
            return "collect_data"

# ===== 构建工作流 =====

def build_ops_diagnosis_workflow():
    """构建 OpsAgent 工作流"""
    builder = StateGraph(OpsDiagnosisState)
    
    # 添加节点
    builder.add_node("initial_analysis", initial_analysis_node)
    builder.add_node("retrieve", retrieve_node)              # 阶段1：检索诊断树
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("execute_tree", execute_tree_node)      # 执行诊断树
    builder.add_node("retrieve_solution", retrieve_solution_node)  # 阶段2：检索解决方案
    builder.add_node("collect_data", collect_data_node)      # 收集实时数据
    builder.add_node("diagnose", diagnose_node)              # 生成报告
    
    # 定义边
    builder.add_edge(START, "initial_analysis")
    builder.add_edge("initial_analysis", "retrieve")
    builder.add_edge("retrieve", "evaluate")
    
    # 评估后的路由
    builder.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "retrieve": "retrieve",           # 需要优化 query
            "execute_tree": "execute_tree",   # 执行诊断树
            "diagnose": "diagnose"            # 直接诊断（无诊断树）
        }
    )
    
    # 诊断树执行后的路由
    builder.add_conditional_edges(
        "execute_tree",
        route_after_execute_tree,
        {
            "retrieve_solution": "retrieve_solution",  # 需要检索解决方案
            "collect_data": "collect_data"             # 直接收集数据
        }
    )
    
    builder.add_edge("retrieve_solution", "collect_data")
    builder.add_edge("collect_data", "diagnose")
    builder.add_edge("diagnose", END)
    
    return builder.compile()

# 创建工作流实例
ops_diagnosis_workflow = build_ops_diagnosis_workflow()

# ===== 对外接口 =====

async def run_ops_diagnosis(user_input: str, container_name: str = None) -> dict:
    """
    运行运维诊断工作流
    
    Args:
        user_input: 用户输入的问题描述
        container_name: 可选的容器名称
    
    Returns:
        诊断结果
    """
    initial_state: OpsDiagnosisState = {
        "user_input": user_input,
        "container_name": container_name,
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 3,
        "search_query": "",
        "retrieved_results": [],
        "retrieval_quality": "",
        "evaluator_feedback": None,
        "diagnosis_tree": None,
        "current_tree_step": None,
        "step_execution_results": {},
        "solution_results": [],  # 第二阶段检索结果
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
        "service_status": None,
        "detected_issues": [],
        "diagnosis_result": None,
        "recommended_actions": []
    }
    
    try:
        final_state = await ops_diagnosis_workflow.ainvoke(initial_state)
        
        return {
            "status": "success",
            "diagnosis": final_state.get("diagnosis_result"),
            "iteration_count": final_state.get("iteration_count"),
            "retrieval_quality": final_state.get("retrieval_quality")
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
