"""
路由模块 - 负责意图识别和路由到适当的代理
使用 LangGraph 完整结构实现，支持会话管理和历史上下文
"""
import os
import sys
import asyncio
from typing import Literal, TypedDict, List, Optional
from datetime import datetime

# 添加项目根目录到Python路径，解决模块导入问题
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langgraph.graph import StateGraph, START, END
from Routing.calculator import create_calculator_agent
from Routing.log_reader import create_log_reader_agent
from Routing.amap import create_amap_agent
from Routing.rag_agent import create_rag_agent

# 导入缓存和会话管理器
from Routing.tool_cache import tool_cache
from Routing.conversation_manager import conversation_manager
from Routing.ssh_tunnel_manager import SSHTunnelManager

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# LLM 配置（从环境变量读取）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# 全局 SSH 隧道管理器实例
tunnel_manager: Optional[SSHTunnelManager] = None


# Schema for structured output to use as routing logic
from pydantic import BaseModel, Field

class Route(BaseModel):
    step: Literal["calculator", "log_reader", "amap", "rag_query", "ops_diagnosis"] = Field(
        description="The next step in the routing process"
    )


# State - 扩展以支持会话和历史
class State(TypedDict):
    input: str
    session_id: Optional[str]  # 新增：会话 ID
    rag_backend: int  # 新增：RAG 向量后端 (0=ChromaDB, 1=Milvus)
    decision: str
    output: str
    history: Optional[List[BaseMessage]]  # 新增：历史消息


# 节点函数（更新为支持历史上下文）
async def handle_calculator_request(state: State):
    """处理计算器请求"""
    print("路由到计算器代理")
    agent = await create_calculator_agent()
    
    # 构建包含历史的输入
    input_with_context = _build_input_with_history(state)
    
    result = await agent.ainvoke(input_with_context)
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_log_reader_request(state: State):
    """处理日志读取请求"""
    print("路由到日志读取代理")
    agent = await create_log_reader_agent()
    
    input_with_context = _build_input_with_history(state)
    
    result = await agent.ainvoke(input_with_context)
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_amap_request(state: State):
    """处理高德地图请求"""
    print("路由到高德地图代理")
    agent = await create_amap_agent()
    
    input_with_context = _build_input_with_history(state)
    
    result = await agent.ainvoke(input_with_context)
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_rag_request(state: State):
    """处理RAG知识库查询请求"""
    print("路由到RAG知识库代理")
    rag_backend = state.get("rag_backend", 0)
    agent = await create_rag_agent(backend=rag_backend)
    
    input_with_context = _build_input_with_history(state)
    
    result = await agent.ainvoke(input_with_context)
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_ops_diagnosis_request(state: State):
    """处理运维诊断请求"""
    print("\n" + "="*70)
    print("🔍 启动运维诊断流程")
    print("="*70)
    print(f"诊断目标: {state['input']}")
    print(f"容器名称: ruoyi-app")
    print("-"*70)
    print("诊断过程将实时显示如下:")
    print("-"*70)
    
    from Routing.diagnosis_agent import run_diagnosis
    
    # 构造告警事件（alert_name 和 alert_type 为空）
    alert_event = {
        "alert_name": "",
        "alert_type": "",
        "alert_time": datetime.now().isoformat(),
        "description": state["input"]
    }
    
    # 提取容器名称（使用默认值）
    container_name = "ruoyi-app"
    
    result = await run_diagnosis(
        alert_event=alert_event,
        container_name=container_name
    )
    
    print("\n" + "="*70)
    if result.get("status") == "success":
        print("✅ 诊断完成")
        print("="*70)
        print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
        data_collected = result.get('data_collected', {})
        print(f"数据收集状态:")
        print(f"  - 日志: {'✓' if data_collected.get('logs') else '✗'}")
        print(f"  - 内存: {'✓' if data_collected.get('memory') else '✗'}")
        print(f"  - CPU: {'✓' if data_collected.get('cpu') else '✗'}")
        print(f"  - 服务状态: {'✓' if data_collected.get('service_status') else '✗'}")
        print("="*70)
    else:
        print("❌ 诊断失败")
        print("="*70)
        print(f"错误信息: {result.get('message', '未知错误')}")
        print("="*70)
    
    output = result.get("diagnosis", {}).get("content", "") if result.get("status") == "success" else result.get("message", "")
    return {"output": output}


def _build_input_with_history(state: State) -> str:
    """
    构建包含历史上下文的输入
    
    Args:
        state: 当前状态
        
    Returns:
        包含历史上下文的输入文本
    """
    session_id = state.get("session_id")
    current_input = state["input"]
    
    # 如果没有会话 ID，直接返回当前输入
    if not session_id:
        return current_input
    
    # 获取历史消息
    history = conversation_manager.get_recent_history(session_id, n=6)
    
    if not history:
        return current_input
    
    # 构建带上下文的输入
    context_parts = []
    context_parts.append("【对话历史】")
    
    for msg in history[-6:]:  # 最近 3 轮对话
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        content = msg.content[:200]  # 限制每条历史消息长度
        context_parts.append(f"{role}: {content}")
    
    context_parts.append("\n【当前问题】")
    context_parts.append(current_input)
    
    return "\n".join(context_parts)


async def route_request(state: State):
    """路由请求到适当的节点（支持历史上下文）"""
    from langchain_openai import ChatOpenAI
    import json
    
    llm = ChatOpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE
    )
    
    # 获取历史消息用于意图识别
    session_id = state.get("session_id")
    history_messages = []
    
    if session_id:
        history_messages = conversation_manager.get_recent_history(session_id, n=4)
    
    # 构建消息列表
    messages = [
        SystemMessage(
            content="""请分析以下用户输入的意图类别，严格按照以下JSON格式返回结果：
{"step": "intent_type"}

其中 intent_type 只能是以下值之一：
- "calculator": 数学计算问题（如 5+2, 10*3等）
- "log_reader": 日志读取或分析问题
- "amap": 地图、位置、导航或天气等问题
- "rag_query": 关于AI趋势、医学知识、产品介绍等知识库内容的问题
- "ops_diagnosis": 运维故障诊断问题

**ops_diagnosis 触发条件**：
- 包含错误代码：500, 502, 503, 404, timeout等
- 包含故障描述：服务不可用、网页打不开、容器崩溃、OOM、内存溢出等
- 包含诊断关键词：diagnose, 诊断, 排查, 检查服务等
- 用户明确要求诊断某个问题

注意：结合对话历史来判断用户的真实意图。如果用户在追问之前的问题，应该路由到相同的代理。

不要返回其他任何内容，只需要上述格式的JSON。"""
        ),
    ]
    
    # 添加历史消息（如果有）
    messages.extend(history_messages)
    
    # 添加当前用户输入
    messages.append(HumanMessage(content=f"用户输入: {state['input']}"))
    
    # 调用模型获取原始响应
    response = llm.invoke(messages)
    
    # 解析响应中的JSON
    try:
        # 从AI消息中提取内容
        response_text = response.content.strip()
        # 查找JSON部分
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            json_str = response_text[start_idx:end_idx+1]
            parsed_response = json.loads(json_str)
            decision = parsed_response.get("step", "unknown")
        else:
            # 如果找不到JSON，使用正则表达式或其他方式尝试解析
            if "calculator" in response_text.lower():
                decision = "calculator"
            elif "log_reader" in response_text.lower():
                decision = "log_reader"
            elif "amap" in response_text.lower():
                decision = "amap"
            elif "rag_query" in response_text.lower():
                decision = "rag_query"
            else:
                decision = "unknown"
    except json.JSONDecodeError:
        # 如果JSON解析失败，尝试简单字符串匹配
        response_text = response.content.lower()
        if "calculator" in response_text:
            decision = "calculator"
        elif "log_reader" in response_text:
            decision = "log_reader"
        elif "amap" in response_text:
            decision = "amap"
        elif "rag_query" in response_text:
            decision = "rag_query"
        else:
            decision = "unknown"
    
    return {"decision": decision}


# 添加错误处理节点
def error_handler(state: State):
    """处理错误情况"""
    return {"output": f"无法识别的意图: {state['decision']}"}


# 条件边函数，用于路由到适当的节点
def route_decision(state: State):
    # 返回下一步要访问的节点名称
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
        # 如果无法识别意图，返回错误节点
        return "error_handler"


# 构建工作流
def build_router_workflow():
    """构建路由工作流"""
    builder = StateGraph(State)

    # 添加节点
    builder.add_node("handle_calculator_request", handle_calculator_request)
    builder.add_node("handle_log_reader_request", handle_log_reader_request)
    builder.add_node("handle_amap_request", handle_amap_request)
    builder.add_node("handle_rag_request", handle_rag_request)
    builder.add_node("handle_ops_diagnosis_request", handle_ops_diagnosis_request)
    builder.add_node("route_request", route_request)
    builder.add_node("error_handler", error_handler)

    # 添加边
    builder.add_edge(START, "route_request")
    builder.add_conditional_edges(
        "route_request",
        route_decision,
        {
            "handle_calculator_request": "handle_calculator_request",
            "handle_log_reader_request": "handle_log_reader_request",
            "handle_amap_request": "handle_amap_request",
            "handle_rag_request": "handle_rag_request",
            "handle_ops_diagnosis_request": "handle_ops_diagnosis_request",
            "error_handler": "error_handler"
        },
    )
    builder.add_edge("handle_calculator_request", END)
    builder.add_edge("handle_log_reader_request", END)
    builder.add_edge("handle_amap_request", END)
    builder.add_edge("handle_rag_request", END)
    builder.add_edge("handle_ops_diagnosis_request", END)
    builder.add_edge("error_handler", END)

    # 编译工作流
    return builder.compile()


# 创建全局工作流实例
router_workflow = build_router_workflow()


async def initialize_redis_and_tunnel():
    """初始化 SSH 隧道和 Redis 连接"""
    global tunnel_manager

    # 读取配置
    ssh_host = os.getenv("SSH_HOST", "8.130.131.36")
    ssh_port = int(os.getenv("SSH_PORT", "22"))
    ssh_user = os.getenv("SSH_USER", "root")
    ssh_key_path = os.path.expanduser(os.getenv("SSH_KEY_PATH", "~/.ssh/id_rsa"))
    remote_redis_port = int(os.getenv("SSH_REMOTE_REDIS_PORT", "6379"))
    local_redis_port = int(os.getenv("SSH_LOCAL_REDIS_PORT", "6379"))

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", local_redis_port))
    redis_password = os.getenv("REDIS_PASSWORD") or None
    redis_ttl = int(os.getenv("REDIS_SESSION_TTL", "604800"))

    # 创建 SSH 隧道
    tunnel_manager = SSHTunnelManager()
    tunnel_success = tunnel_manager.create_tunnel(
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key_path,
        remote_redis_port=remote_redis_port,
        local_redis_port=local_redis_port
    )

    if not tunnel_success:
        print("[警告] SSH 隧道创建失败，将尝试直接连接 Redis")
        # 如果有捕获的错误详情，输出详细信息
        from Routing.ssh_tunnel_manager import error_capture
        if error_capture and error_capture.last_error:
            print(f"详细:\n{error_capture.last_error}")

    # 配置 ConversationManager 使用 Redis
    redis_config = {
        "host": redis_host,
        "port": redis_port,
        "password": redis_password,
        "ttl": redis_ttl
    }

    # 重新初始化 ConversationManager（由于是单例，需要特殊处理）
    # 这里我们通过修改全局实例的方式来实现
    conversation_manager.use_redis = True
    try:
        from Routing.redis_session_store import RedisSessionStore
        conversation_manager.redis_store = RedisSessionStore(**redis_config)
        print("[ConversationManager] Redis 持久化已启用")
    except Exception as e:
        print(f"[ConversationManager] Redis 初始化失败，将使用内存模式: {e}")
        conversation_manager.use_redis = False


# ===== 新增：高级 API 支持循环对话 =====

async def chat_with_session(user_input: str, session_id: Optional[str] = None, rag_backend: int = 0) -> dict:
    """
    与 AI 进行对话（支持多轮对话）
    
    Args:
        user_input: 用户输入
        session_id: 会话 ID（可选，不提供则创建新会话）
        rag_backend: RAG 向量后端 (0=ChromaDB, 1=Milvus)
        
    Returns:
        包含回复和会话信息的字典
    """
    from Routing.tool_cache import tool_cache
    
    # 如果没有提供会话 ID，创建新会话
    if session_id is None:
        session_id = conversation_manager.create_session()
        print(f"\n[新会话] 会话 ID: {session_id}")
    
    # 保存用户消息到历史
    conversation_manager.add_message(session_id, "user", user_input)
    
    # 获取缓存统计
    cache_stats = tool_cache.get_cache_stats()
    
    # 构建状态
    state = {
        "input": user_input,
        "session_id": session_id,
        "rag_backend": rag_backend,
        "decision": "",
        "output": "",
        "history": None
    }
    
    # 执行工作流
    try:
        result_state = await router_workflow.ainvoke(state)
        output = result_state.get("output", "")
        
        # 保存 AI 回复到历史
        conversation_manager.add_message(session_id, "assistant", output)
        
        # 获取最新的缓存统计信息
        cache_stats = tool_cache.get_cache_stats()
        
        return {
            "success": True,
            "response": output,
            "session_id": session_id,
            "cache_stats": cache_stats
        }
    
    except Exception as e:
        error_msg = f"处理请求时出错: {str(e)}"
        print(f"[错误] {error_msg}")
        
        return {
            "success": False,
            "response": error_msg,
            "session_id": session_id,
            "error": str(e),
            "cache_stats": cache_stats
        }


async def clear_session(session_id: str):
    """清空指定会话的历史"""
    conversation_manager.clear_session(session_id)
    print(f"[会话管理] 已清空会话: {session_id}")


async def get_session_info(session_id: str) -> dict:
    """获取会话信息"""
    session = conversation_manager.get_session(session_id)
    if session:
        return {
            "exists": True,
            "stats": session.get_stats()
        }
    return {"exists": False}


async def cleanup_all():
    """清理所有资源（应用关闭时调用）"""
    print("\n[清理] 开始清理资源...")

    # 清理工具缓存
    await tool_cache.clear_all()

    # 清理会话
    conversation_manager.clear_all()

    # 关闭 Redis 连接
    if hasattr(conversation_manager, 'redis_store') and conversation_manager.redis_store:
        conversation_manager.redis_store.close()
        print("[清理] Redis 连接已关闭")

    # 关闭 SSH 隧道
    global tunnel_manager
    if tunnel_manager:
        tunnel_manager.close_tunnel()
        print("[清理] SSH 隧道已关闭")

    print("[清理] 资源清理完成")


async def main():
    """主函数 - 演示路由功能（支持循环对话）"""
    print("=" * 70)
    print("Router 演示程序 (LangGraph 结构 + 会话管理)")
    print("=" * 70)
    print("\n提示：")
    print("- 输入问题开始对话")
    print("- 输入 'quit' 或 'exit' 退出")
    print("- 输入 'clear' 清空当前会话历史")
    print("- 输入 'info' 查看会话信息")
    print("- 输入 'stats' 查看缓存统计\n")
    
    session_id = None
    
    try:
        while True:
            # 获取用户输入
            user_input = input("\n您: ").strip()
            
            if not user_input:
                continue
            
            # 检查退出命令
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\n再见！")
                break
            
            # 检查清空命令
            if user_input.lower() == 'clear':
                if session_id:
                    await clear_session(session_id)
                    print("✓ 会话历史已清空")
                else:
                    print("当前没有活跃的会话")
                continue
            
            # 检查信息命令
            if user_input.lower() == 'info':
                if session_id:
                    info = await get_session_info(session_id)
                    if info["exists"]:
                        stats = info["stats"]
                        print(f"\n会话信息:")
                        print(f"  会话 ID: {stats['session_id']}")
                        print(f"  消息数量: {stats['message_count']}")
                        print(f"  持续时间: {stats['duration_seconds']:.0f} 秒")
                    else:
                        print("会话不存在")
                else:
                    print("当前没有活跃的会话")
                continue
            
            # 检查统计命令
            if user_input.lower() == 'stats':
                cache_stats = tool_cache.get_cache_stats()
                print(f"\n缓存统计:")
                print(f"  缓存服务器: {cache_stats['cached_servers']}")
                print(f"  缓存数量: {cache_stats['cache_count']}")
                print(f"  活跃会话: {cache_stats['active_sessions']}")
                continue
            
            # 正常对话
            print("\nAI 思考中...", end="", flush=True)
            result = await chat_with_session(user_input, session_id)
            
            # 更新会话 ID
            if session_id is None:
                session_id = result["session_id"]
            
            # 显示结果
            if result["success"]:
                print(f"\rAI: {result['response']}")
                
                # 显示缓存命中信息
                if result["cache_stats"]["cache_count"] > 0:
                    print(f"   [工具缓存: {result['cache_stats']['cache_count']} 个服务器]")
            else:
                print(f"\r错误: {result['response']}")
    
    except KeyboardInterrupt:
        print("\n\n检测到中断，正在清理...")
    
    finally:
        # 清理资源
        await cleanup_all()


if __name__ == "__main__":
    load_dotenv()

    # 初始化 Redis 和 SSH 隧道
    asyncio.run(initialize_redis_and_tunnel())

    # 运行主程序
    asyncio.run(main())
