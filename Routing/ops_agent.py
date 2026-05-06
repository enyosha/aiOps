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
    
    # 实时数据
    logs_data: Optional[str]
    memory_info: Optional[str]
    cpu_info: Optional[str]
    
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
    print(f"Container name: {extracted.get('container_name')}")
    
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
        "container_name": extracted.get('container_name'),
        "search_query": initial_query,
        "detected_issues": symptoms
    }

async def retrieve_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 2：根据当前 query 检索知识库
    """
    query = state['search_query']
    iteration = state['iteration_count']
    
    print(f"\n{'='*70}")
    print(f"[Retrieve] 第 {iteration + 1} 次检索")
    print(f"{'='*70}")
    print(f"Query: '{query}'")
    
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
        result = await search_tool.ainvoke({"query": query, "top_k": 3})
        retrieved = result.get("results", []) if result.get("status") == "success" else []
    except Exception as e:
        print(f"[Retrieve] Error: {str(e)}")
        retrieved = []
    
    print(f"Found {len(retrieved)} results")
    for i, r in enumerate(retrieved, 1):
        print(f"  [{i}] {r.get('title', 'N/A')} (相似度: {r.get('similarity_score', 0):.4f})")
    
    return {
        **state,
        "retrieved_results": retrieved,
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
    
    # 构建评估提示
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
    
    返回结构化的评估结果。
    """
    
    try:
        evaluation = await evaluator_llm.ainvoke(evaluation_prompt)
        
        print(f"Quality: {evaluation.quality}")
        print(f"Reason: {evaluation.reason}")
        
        if evaluation.quality == 'good':
            print("[Evaluate] Quality is good, proceeding to diagnosis")
            return {
                **state,
                "retrieval_quality": "good",
                "evaluator_feedback": evaluation.reason,
                "current_step": "diagnose"
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

async def diagnose_node(state: OpsDiagnosisState) -> OpsDiagnosisState:
    """
    节点 4：基于检索结果生成最终的诊断方案
    """
    print(f"\n{'='*70}")
    print(f"[Diagnose] 生成诊断方案")
    print(f"{'='*70}")
    
    results = state['retrieved_results']
    user_input = state['user_input']
    container_name = state.get('container_name')
    
    # 获取实时数据
    logs_data = None
    memory_info = None
    cpu_info = None
    
    if container_name:
        from Routing.tool_cache import tool_cache
        tools = await tool_cache.get_tools("ops-diagnosis")
        
        fetch_logs_tool = next((t for t in tools if t.name == "fetch_docker_logs"), None)
        check_memory_tool = next((t for t in tools if t.name == "check_memory_usage"), None)
        check_cpu_tool = next((t for t in tools if t.name == "check_cpu_usage"), None)
        
        if fetch_logs_tool:
            try:
                now = datetime.now()
                since_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
                
                log_result = await fetch_logs_tool.ainvoke({
                    "container_name": container_name,
                    "since_time": since_time,
                    "lines": 200
                })
                if log_result.get("status") == "success":
                    logs_data = log_result.get("logs", "")
                    print(f"[Diagnose] Fetched {log_result.get('line_count', 0)} log lines")
            except Exception as e:
                print(f"[Diagnose] Failed to fetch logs: {str(e)}")
        
        if check_memory_tool:
            try:
                mem_result = await check_memory_tool.ainvoke({})
                if mem_result.get("status") == "success":
                    memory_info = mem_result.get("memory_info", "")
            except:
                pass
        
        if check_cpu_tool:
            try:
                cpu_result = await check_cpu_tool.ainvoke({})
                if cpu_result.get("status") == "success":
                    cpu_info = cpu_result.get("cpu_info", "")
            except:
                pass
    
    # 使用 LLM 生成诊断报告
    diagnosis_prompt = f"""
    你是一个专业的运维故障诊断专家。基于以下信息生成详细的诊断报告。
    
    【用户问题】
    {user_input}
    
    【检索到的知识】
    {json.dumps(results, indent=2, ensure_ascii=False)[:1500] if results else "未找到相关知识"}
    
    【实时数据】
    容器日志（最近 30 分钟）：
    {logs_data[:1000] if logs_data else "无"}
    
    内存使用情况：
    {memory_info if memory_info else "无"}
    
    CPU 使用情况：
    {cpu_info if cpu_info else "无"}
    
    【要求】
    请生成结构化的诊断报告，包含：
    1. **问题根因分析**：详细说明导致问题的根本原因
    2. **立即执行的修复命令**：列出具体的命令，每个命令标注作用
    3. **长期优化建议**：防止问题再次发生的措施
    
    输出格式：
    ```
    【诊断结果】
    （简要总结）
    
    【根本原因】
    （详细分析）
    
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
                "confidence": "high" if state['retrieval_quality'] == 'good' else "medium",
                "iteration_count": state['iteration_count']
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
    if state['retrieval_quality'] == 'good':
        return "diagnose"
    elif state['retrieval_quality'] == 'needs_improvement':
        return "retrieve"
    else:
        return "diagnose"

# ===== 构建工作流 =====

def build_ops_diagnosis_workflow():
    """构建 OpsAgent 工作流"""
    builder = StateGraph(OpsDiagnosisState)
    
    builder.add_node("initial_analysis", initial_analysis_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("diagnose", diagnose_node)
    
    builder.add_edge(START, "initial_analysis")
    builder.add_edge("initial_analysis", "retrieve")
    builder.add_edge("retrieve", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "retrieve": "retrieve",
            "diagnose": "diagnose"
        }
    )
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
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
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
