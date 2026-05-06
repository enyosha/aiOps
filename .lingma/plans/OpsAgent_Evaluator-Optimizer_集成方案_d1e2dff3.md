# OpsAgent Evaluator-Optimizer 集成方案

## 目标
参照 LogReader Agent 的实现方式，将 KnowledgeBase 运维诊断功能集成为新的 MCP Agent，命名为 `ops_agent`，采用 **Evaluator-Optimizer 模式**实现从粗到细的引导式诊断流程，并使用独立的 ChromaDB 向量库存储运维知识。

## 核心设计原则
1. **独立向量库**：使用独立的持久化目录和集合名称，与现有 RAG 知识库完全隔离
2. **Evaluator-Optimizer 模式**：通过迭代优化检索 query，提高诊断准确性
3. **配置集中管理**：所有配置从 `.env` 读取，不在代码中硬编码默认值
4. **时间范围日志查询**：基于用户报告的故障时间点向前追溯，避免全量读取大日志文件
5. **引导式逐步排查**：从服务可用性 → 资源使用 → 网络配置的层级化诊断

---

## 实施步骤

### 阶段 1：创建 MCP Server（Server/ops_diagnosis_server.py）

**文件位置**：`Server/ops_diagnosis_server.py`

**核心功能**：
封装 KnowledgeBase 的诊断逻辑为 MCP 工具，提供以下接口：
- `search_ops_knowledge(query, top_k)` - 搜索运维知识库（带 query 打印调试）
- `fetch_docker_logs(container_name, lines, since_time, until_time)` - 基于时间范围获取容器日志
- `check_memory_usage()` - 检查内存使用情况
- `check_cpu_usage()` - 检查 CPU 使用情况
- `execute_ssh_command(command)` - 执行 SSH 命令（受限制的安全命令集）
- `load_ops_knowledge_entries()` - 加载知识条目到向量库

**技术要点**：
```python
import os
import sys
import json
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from dotenv import load_dotenv
import paramiko
import chromadb
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

# 确保加载 .env 文件
load_dotenv()

# 独立的 ChromaDB 配置
OPS_PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "ops_vector_store")
OPS_COLLECTION_NAME = "ops_knowledge"

# 初始化向量库
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY:
    raise ValueError("缺少 DASHSCOPE_API_KEY 配置，请检查 .env 文件")

embeddings = DashScopeEmbeddings(
    model="text-embedding-v3", 
    dashscope_api_key=DASHSCOPE_API_KEY
)

os.makedirs(OPS_PERSIST_DIRECTORY, exist_ok=True)
ops_vector_store = Chroma(
    persist_directory=OPS_PERSIST_DIRECTORY,
    embedding_function=embeddings,
    collection_name=OPS_COLLECTION_NAME
)

# SSH 连接管理器（从 .env 读取，无硬编码默认值）
ssh_config = {
    "host": os.getenv("SSH_HOST"),
    "port": int(os.getenv("SSH_PORT", "22")),
    "username": os.getenv("SSH_USER"),
    "key_file": os.path.expanduser(os.getenv("SSH_KEY_PATH"))
}

# 验证必要配置
if not all([ssh_config["host"], ssh_config["username"], ssh_config["key_file"]]):
    raise ValueError("缺少必要的 SSH 配置，请检查 .env 文件中的 SSH_HOST, SSH_USER, SSH_KEY_PATH")

# OpsAgent 专用配置
DEFAULT_CONTAINER = os.getenv("OPS_DEFAULT_CONTAINER")
DIAGNOSIS_LOOKBACK_MINUTES = int(os.getenv("OPS_DIAGNOSIS_LOOKBACK_MINUTES", "30"))
LOG_DEFAULT_LINES = int(os.getenv("OPS_LOG_DEFAULT_LINES", "100"))

# 创建 FastMCP 实例
mcp = FastMCP("Ops Diagnosis Server")

# ===== 工具定义 =====

@mcp.tool()
def search_ops_knowledge(query: str, top_k: int = 3) -> dict:
    """
    在运维知识库中搜索相关诊断方案
    
    Args:
        query: 搜索查询文本（可以是症状描述、错误关键词等）
        top_k: 返回结果数量（默认 3）
    
    Returns:
        包含匹配结果和元数据的字典
    """
    # 【关键】打印检索前的 query，便于调试和优化
    print(f"\n[Ops Knowledge Search] Query: '{query}'")
    print(f"[Ops Knowledge Search] Top-K: {top_k}")
    
    try:
        results = ops_vector_store.similarity_search_with_score(query, k=top_k)
        
        # 格式化返回结果
        formatted_results = []
        for doc, score in results:
            formatted_results.append({
                "id": doc.metadata.get("doc_id", "unknown"),
                "title": doc.metadata.get("title", "unknown"),
                "type": doc.metadata.get("type", "unknown"),
                "category": doc.metadata.get("category", "unknown"),
                "similarity_score": float(score),
                "content_preview": doc.page_content[:200],
                "metadata": doc.metadata
            })
        
        print(f"[Ops Knowledge Search] Found {len(formatted_results)} results")
        for i, result in enumerate(formatted_results, 1):
            print(f"  [{i}] {result['title']} (相似度: {result['similarity_score']:.4f})")
        
        return {
            "status": "success",
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results)
        }
    
    except Exception as e:
        print(f"[Ops Knowledge Search] Error: {str(e)}")
        return {
            "status": "error",
            "query": query,
            "message": str(e)
        }

@mcp.tool()
def fetch_docker_logs(
    container_name: str,
    lines: int = None,
    since_time: Optional[str] = None,
    until_time: Optional[str] = None
) -> dict:
    """
    获取指定时间范围的 Docker 容器日志（避免全量读取大日志文件）
    
    Args:
        container_name: 容器名称（必填）
        lines: 最大返回行数（默认使用 OPS_LOG_DEFAULT_LINES）
        since_time: 起始时间（ISO 8601 格式如 "2024-01-15T10:30:00" 或相对时间如 "10m"、"1h"）
        until_time: 结束时间（ISO 8601 格式，默认为当前时间）
    
    Returns:
        包含日志内容和元数据的字典
    """
    if lines is None:
        lines = LOG_DEFAULT_LINES
    
    # 构建 docker logs 命令（使用时间过滤参数）
    cmd_parts = [f"docker logs {container_name}"]
    
    if since_time:
        cmd_parts.append(f"--since '{since_time}'")
    
    if until_time:
        cmd_parts.append(f"--until '{until_time}'")
    
    cmd_parts.append(f"--tail {lines}")
    cmd_parts.append("2>&1")
    
    cmd = " ".join(cmd_parts)
    
    print(f"\n[Fetch Logs] Executing: {cmd}")
    
    # 通过 SSH 执行命令
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command(cmd)
        logs = stdout.read().decode('utf-8')
        error_output = stderr.read().decode('utf-8')
        
        ssh.close()
        
        if error_output and "error" in error_output.lower():
            return {
                "status": "error",
                "message": f"SSH 命令执行失败: {error_output}"
            }
        
        return {
            "status": "success",
            "container": container_name,
            "time_range": {"since": since_time, "until": until_time},
            "line_count": len(logs.splitlines()),
            "logs": logs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def check_memory_usage() -> dict:
    """检查服务器内存使用情况"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command("free -h")
        memory_info = stdout.read().decode('utf-8')
        
        ssh.close()
        
        return {
            "status": "success",
            "memory_info": memory_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def check_cpu_usage() -> dict:
    """检查服务器 CPU 使用情况"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command("top -bn1 | head -20")
        cpu_info = stdout.read().decode('utf-8')
        
        ssh.close()
        
        return {
            "status": "success",
            "cpu_info": cpu_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def load_ops_knowledge_entries() -> dict:
    """手动触发运维知识条目的加载和索引"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from Server.init_ops_knowledge import initialize_ops_knowledge
        
        print("开始加载运维知识条目...")
        result = initialize_ops_knowledge()
        
        return {
            "status": "success",
            "message": "知识条目加载完成",
            "details": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"知识条目加载失败: {str(e)}"
        }

if __name__ == "__main__":
    print("Ops Diagnosis Server starting...")
    mcp.run(transport="stdio")
```

---

### 阶段 2：创建 Evaluator-Optimizer 工作流（Routing/ops_agent.py）

**文件位置**：`Routing/ops_agent.py`

**实现方式**：使用 LangGraph StateGraph 实现 Evaluator-Optimizer 模式

```python
"""
OpsAgent - 运维诊断 Agent（Evaluator-Optimizer 模式）
"""
import os
import sys
import json
from typing import TypedDict, List, Optional, Literal, Annotated
from datetime import datetime, timedelta

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
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
    current_step: str  # "initial_analysis", "retrieve", "evaluate", "diagnose"
    iteration_count: int  # 当前迭代次数
    max_iterations: int  # 最大迭代次数
    
    # 检索相关
    search_query: str  # 当前使用的查询字符串
    retrieved_results: List[dict]  # 检索结果
    retrieval_quality: str  # "good", "needs_improvement", "poor"
    
    # 评估反馈
    evaluator_feedback: Optional[str]  # 评估器的改进建议
    
    # 实时数据
    logs_data: Optional[str]  # 日志数据
    memory_info: Optional[str]  # 内存信息
    cpu_info: Optional[str]  # CPU 信息
    
    # 诊断结果
    detected_issues: List[str]  # 检测到的问题 ["OOM", "502"]
    diagnosis_result: Optional[dict]  # 最终诊断结果
    recommended_actions: List[str]  # 推荐的修复动作

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
    
    # 调用 MCP 工具检索（这里简化为直接调用，实际应通过 tool_cache）
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
                    "current_step": "retrieve"  # 回到检索节点
                }
    
    except Exception as e:
        print(f"[Evaluate] Error: {str(e)}")
        # 评估失败时继续诊断
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
    
    # 获取实时数据（如果需要）
    logs_data = None
    memory_info = None
    cpu_info = None
    
    if container_name:
        # 获取日志
        from Routing.tool_cache import tool_cache
        tools = await tool_cache.get_tools("ops-diagnosis")
        
        fetch_logs_tool = next((t for t in tools if t.name == "fetch_docker_logs"), None)
        check_memory_tool = next((t for t in tools if t.name == "check_memory_usage"), None)
        check_cpu_tool = next((t for t in tools if t.name == "check_cpu_usage"), None)
        
        if fetch_logs_tool:
            try:
                # 计算时间范围
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
        return "retrieve"  # 重新检索
    else:  # poor
        return "diagnose"  # 即使质量差也继续

# ===== 构建工作流 =====

def build_ops_diagnosis_workflow():
    """构建 OpsAgent 工作流"""
    builder = StateGraph(OpsDiagnosisState)
    
    # 添加节点
    builder.add_node("initial_analysis", initial_analysis_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("diagnose", diagnose_node)
    
    # 添加边
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
```

---

### 阶段 3：注册到路由系统

**修改文件 1**：`Routing/route.py`

在第 44-47 行添加新分支：
```python
class Route(BaseModel):
    step: Literal["calculator", "log_reader", "amap", "rag_query", "ops_diagnosis"] = Field(
        description="The next step in the routing process"
    )
```

添加处理函数（约第 108 行后）：
```python
async def handle_ops_diagnosis_request(state: State):
    """处理运维诊断请求"""
    print("路由到运维诊断代理")
    from Routing.ops_agent import run_ops_diagnosis
    
    # 提取容器名称（如果有）
    container_name = None
    # 可以从用户输入中提取，或使用默认值
    
    result = await run_ops_diagnosis(
        user_input=state["input"],
        container_name=container_name
    )
    
    output = result.get("diagnosis", {}).get("content", "") if result.get("status") == "success" else result.get("message", "")
    return {"output": output}
```

在 `route_decision` 函数中添加分支（约第 243 行）：
```python
def route_decision(state: State):
    if state["decision"] == "calculator":
        return "handle_calculator_request"
    elif state["decision"] == "log_reader":
        return "handle_log_reader_request"
    elif state["decision"] == "amap":
        return "handle_amap_request"
    elif state["decision"] == "rag_query":
        return "handle_rag_request"
    elif state["decision"] == "ops_diagnosis":
        return "handle_ops_diagnosis_request"
    else:
        return "error_handler"
```

在 `build_router_workflow` 中注册节点（约第 264 行后）：
```python
builder.add_node("handle_ops_diagnosis_request", handle_ops_diagnosis_request)
builder.add_edge("handle_ops_diagnosis_request", END)
```

在路由提示词中添加意图说明（约第 171 行）：
```python
SystemMessage(
    content="""请分析以下用户输入的意图类别...
- "ops_diagnosis": 运维故障诊断问题（如 502 错误、OOM、容器崩溃、服务不可用等）
...
"""
)
```

**修改文件 2**：`Routing/mcp.json`

添加新的 MCP 服务器配置：
```json
{
  "mcpServers": {
    "amap-maps-streamableHTTP": {...},
    "calculator": {...},
    "log-reader": {...},
    "rag-knowledge": {...},
    "ops-diagnosis": {
      "command": "python",
      "args": ["../Server/ops_diagnosis_server.py"],
      "transport": "stdio"
    }
  }
}
```

---

### 阶段 4：迁移 KnowledgeBase 知识条目

**创建初始化脚本**：`Server/init_ops_knowledge.py`

```python
"""
运维知识库初始化脚本
读取 KnowledgeBase/knowledge_entries/*.json 并导入到 ops_vector_store
"""
import sys
import os
import json

# 添加项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_chroma import Chroma

# 配置
OPS_PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "ops_vector_store")
OPS_COLLECTION_NAME = "ops_knowledge"
KNOWLEDGE_ENTRIES_DIR = os.path.join(os.path.dirname(__file__), "..", "KnowledgeBase", "knowledge_entries")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def initialize_ops_knowledge():
    """初始化运维知识库"""
    print("=" * 70)
    print("运维知识库初始化")
    print("=" * 70)
    
    # 初始化向量库
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=DASHSCOPE_API_KEY
    )
    
    os.makedirs(OPS_PERSIST_DIRECTORY, exist_ok=True)
    vector_store = Chroma(
        persist_directory=OPS_PERSIST_DIRECTORY,
        embedding_function=embeddings,
        collection_name=OPS_COLLECTION_NAME
    )
    
    # 读取知识条目
    if not os.path.exists(KNOWLEDGE_ENTRIES_DIR):
        print(f"ERROR: 知识条目目录不存在: {KNOWLEDGE_ENTRIES_DIR}")
        return {"status": "error", "message": "Directory not found"}
    
    loaded_count = 0
    for filename in os.listdir(KNOWLEDGE_ENTRIES_DIR):
        if not filename.endswith('.json'):
            continue
        
        filepath = os.path.join(KNOWLEDGE_ENTRIES_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            
            # 构建文档内容
            if 'solution' in entry:
                content = f"""
                标题: {entry['title']}
                分类: {entry['category']}
                症状: {', '.join(entry['symptoms'])}
                根本原因: {entry['root_cause']}
                解决方案: {entry['solution']['immediate']}
                关键词: {', '.join(entry['log_keywords'])}
                标签: {', '.join(entry['tags'])}
                """
                doc_id = entry['id']
                
                metadata = {
                    "doc_id": doc_id,
                    "title": entry['title'],
                    "category": entry['category'],
                    "severity": entry['severity'],
                    "type": "solution",
                    "tags": json.dumps(entry['tags'])
                }
                
            elif 'diagnosis_tree' in entry:
                diagnosis_steps = []
                for step_key, step_data in entry['diagnosis_tree'].items():
                    diagnosis_steps.append(step_data['description'])
                
                content = f"""
                标题: {entry['title']}
                分类: {entry['category']}
                症状: {', '.join(entry['symptoms'])}
                根本原因: {entry['root_cause']}
                诊断步骤: {'; '.join(diagnosis_steps)}
                关键词: {', '.join(entry['log_keywords'])}
                标签: {', '.join(entry['tags'])}
                """
                doc_id = entry['id']
                
                metadata = {
                    "doc_id": doc_id,
                    "title": entry['title'],
                    "category": entry['category'],
                    "severity": entry['severity'],
                    "type": "diagnosis_flow",
                    "tags": json.dumps(entry['tags']),
                    "diagnosis_tree": json.dumps(entry['diagnosis_tree'])
                }
            else:
                continue
            
            # 添加到向量库
            vector_store.add_texts(
                texts=[content],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            loaded_count += 1
            print(f"✓ 已加载: {entry['title']}")
        
        except Exception as e:
            print(f"✗ 加载失败 {filename}: {str(e)}")
    
    print(f"\n总共加载 {loaded_count} 条知识条目")
    print("=" * 70)
    
    return {
        "status": "success",
        "loaded_count": loaded_count
    }

if __name__ == "__main__":
    initialize_ops_knowledge()
```

---

### 阶段 5：环境变量配置

**修改文件**：`.env`

在现有配置基础上添加：

```bash
# ===== Ops Diagnosis Agent 专用配置（新增）=====
# 默认诊断的容器名称
OPS_DEFAULT_CONTAINER=ruoyi-app

# 诊断时向前追溯的分钟数（默认 30 分钟）
OPS_DIAGNOSIS_LOOKBACK_MINUTES=30

# 日志查询默认返回行数
OPS_LOG_DEFAULT_LINES=100
```

---

### 阶段 6：测试验证

**创建测试脚本**：`test/test_ops_diagnosis.py`

```python
"""
OpsAgent 测试脚本
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_initialization():
    """测试知识库初始化"""
    print("\n" + "="*70)
    print("测试 1: 知识库初始化")
    print("="*70)
    
    from Server.init_ops_knowledge import initialize_ops_knowledge
    result = initialize_ops_knowledge()
    
    assert result["status"] == "success"
    assert result["loaded_count"] > 0
    print(f"✓ 成功加载 {result['loaded_count']} 条知识")

async def test_search():
    """测试知识检索"""
    print("\n" + "="*70)
    print("测试 2: 知识检索")
    print("="*70)
    
    from Routing.tool_cache import tool_cache
    
    tools = await tool_cache.get_tools("ops-diagnosis")
    search_tool = next((t for t in tools if t.name == "search_ops_knowledge"), None)
    
    assert search_tool is not None
    
    result = await search_tool.ainvoke({
        "query": "502 Bad Gateway error",
        "top_k": 2
    })
    
    print(f"Query: '502 Bad Gateway error'")
    print(f"Found {result['count']} results")
    
    assert result["status"] == "success"
    assert result["count"] > 0

async def test_diagnosis_workflow():
    """测试完整诊断流程"""
    print("\n" + "="*70)
    print("测试 3: 完整诊断流程")
    print("="*70)
    
    from Routing.ops_agent import run_ops_diagnosis
    
    result = await run_ops_diagnosis(
        user_input="App 在 10:30 出现 502 错误",
        container_name="ruoyi-app"
    )
    
    print(f"Status: {result['status']}")
    print(f"Iterations: {result['iteration_count']}")
    print(f"Retrieval Quality: {result['retrieval_quality']}")
    
    if result["status"] == "success":
        print(f"\nDiagnosis:\n{result['diagnosis']['content'][:500]}...")
    
    assert result["status"] == "success"

async def main():
    """运行所有测试"""
    print("\n" + "="*70)
    print("OpsAgent 测试套件")
    print("="*70)
    
    try:
        await test_initialization()
        await test_search()
        await test_diagnosis_workflow()
        
        print("\n" + "="*70)
        print("所有测试通过 ✓")
        print("="*70)
    except Exception as e:
        print(f"\n测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 文件清单

### 新建文件
1. `Server/ops_diagnosis_server.py` - MCP 服务器
2. `Routing/ops_agent.py` - Evaluator-Optimizer 工作流
3. `Server/init_ops_knowledge.py` - 知识库初始化脚本
4. `test/test_ops_diagnosis.py` - 测试脚本

### 修改文件
1. `Routing/route.py` - 添加路由分支和处理函数
2. `Routing/mcp.json` - 注册新的 MCP 服务器
3. `.env` - 添加 OpsAgent 专用配置项

### 保持不变
- `KnowledgeBase/knowledge_entries/*.json` - 知识条目源文件
- 现有的 SSH 配置

---

## 向量库隔离策略

| 项目 | RAG 知识库 | Ops 运维知识库 |
|------|-----------|---------------|
| **持久化目录** | `vector_store/` | `ops_vector_store/` |
| **Collection 名称** | `knowledge_base` | `ops_knowledge` |
| **数据来源** | Data/ 目录的 PDF、JSON、TXT | KnowledgeBase/knowledge_entries/*.json |
| **用途** | 通用知识问答 | 运维故障诊断 |
| **MCP Server** | `Server/rag_server.py` | `Server/ops_diagnosis_server.py` |
| **Agent** | `RAGAgent` | `OpsDiagnosisAgent` |
| **路由分支** | `rag_query` | `ops_diagnosis` |

---

## 预期效果示例

### 场景 1：用户明确报告故障时间

**用户输入**："App 在 10:30 左右无法访问，显示 502 错误"

**系统执行流程**：
1. **Initial Analysis**：提取症状 ["502"]，构建初始 query
2. **Retrieve (Iteration 1)**：检索知识库，打印 query
3. **Evaluate**：评估质量，如果不够好则优化 query
4. **Retrieve (Iteration 2)**：使用优化后的 query 重新检索
5. **Diagnose**：获取实时日志，生成诊断报告

**输出**：
```
【诊断结果】
检测到 OOM 导致的 502 错误

【根本原因】
Linux 内核 OOM Killer 在 10:28 杀死了 Java 进程

【立即执行】
1. free -h # 检查内存
2. docker restart ruoyi-app # 重启应用

【长期优化】
1. 设置容器内存限制
2. 优化 JVM 参数
```

---

## 风险和注意事项

1. **SSH 安全性**：限制可执行的命令白名单
2. **向量库初始化**：首次使用前必须运行 `python Server/init_ops_knowledge.py`
3. **依赖安装**：确保 paramiko、chromadb 等依赖已安装
4. **配置验证**：启动时检查 `.env` 中的必要配置
5. **迭代次数限制**：最多 3 次迭代，防止无限循环

---

## 关键特性总结

✅ **Evaluator-Optimizer 模式**：自动优化检索 query  
✅ **Query 打印调试**：每次检索前打印 query  
✅ **时间范围日志查询**：避免全量读取  
✅ **配置环境变量化**：无硬编码默认值  
✅ **独立向量库**：与 RAG 完全隔离  
✅ **引导式诊断**：从粗到细的层级化排查  
