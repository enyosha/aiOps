"""
路由模块 - 负责意图识别和路由到适当的代理
使用 LangGraph 完整结构实现
"""
import os
import sys
import asyncio
from typing import Literal, TypedDict

# 添加项目根目录到Python路径，解决模块导入问题
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from Routing.calculator import create_calculator_agent
from Routing.log_reader import create_log_reader_agent
from Routing.amap import create_amap_agent
from Routing.rag_agent import create_rag_agent

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")


# Schema for structured output to use as routing logic
from pydantic import BaseModel, Field

class Route(BaseModel):
    step: Literal["calculator", "log_reader", "amap", "rag_query"] = Field(
        description="The next step in the routing process"
    )


# State
class State(TypedDict):
    input: str
    decision: str
    output: str


# 节点函数
async def handle_calculator_request(state: State):
    """处理计算器请求"""
    print("路由到计算器代理")
    agent = await create_calculator_agent()
    result = await agent.ainvoke(state["input"])
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_log_reader_request(state: State):
    """处理日志读取请求"""
    print("路由到日志读取代理")
    agent = await create_log_reader_agent()
    result = await agent.ainvoke(state["input"])
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_amap_request(state: State):
    """处理高德地图请求"""
    print("路由到高德地图代理")
    agent = await create_amap_agent()
    result = await agent.ainvoke(state["input"])
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def handle_rag_request(state: State):
    """处理RAG知识库查询请求"""
    print("路由到RAG知识库代理")
    agent = await create_rag_agent()
    result = await agent.ainvoke(state["input"])
    output = result.get("response", {}).get("content", "") if result.get("status") == "success" else result.get("error", "")
    return {"output": output}


async def route_request(state: State):
    """路由请求到适当的节点"""
    from langchain_openai import ChatOpenAI
    import json
    
    llm = ChatOpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-max",
        temperature=0
    )
    
    # 使用 SystemMessage 和 HumanMessage 进行区分
    messages = [
        SystemMessage(
            content="""请分析以下用户输入的意图类别，严格按照以下JSON格式返回结果：
{"step": "intent_type"}

其中 intent_type 只能是以下值之一：
- "calculator": 数学计算问题
- "log_reader": 日志读取或分析问题
- "amap": 地图、位置、导航或天气等问题
- "rag_query": 关于AI趋势、医学知识、产品介绍等知识库内容的问题

不要返回其他任何内容，只需要上述格式的JSON。"""
        ),
        HumanMessage(content=f"用户输入: {state['input']}")
    ]
    
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
            "error_handler": "error_handler"
        },
    )
    builder.add_edge("handle_calculator_request", END)
    builder.add_edge("handle_log_reader_request", END)
    builder.add_edge("handle_amap_request", END)
    builder.add_edge("handle_rag_request", END)
    builder.add_edge("error_handler", END)

    # 编译工作流
    return builder.compile()


# 创建全局工作流实例
router_workflow = build_router_workflow()


async def main():
    """主函数 - 演示路由功能"""
    print("=" * 70)
    print("Router 演示程序 (LangGraph 结构)")
    print("=" * 70)
    
    # 测试用例
    test_inputs = [
        "计算 25 * 17 + 45 / 3 的结果",
        "2025年人工智能有哪些发展趋势?",
        "大聪明牌口服液的功效是什么?",
        # "帮我读取一下 application.log 文件的最后 10 行",
        # "今天北京的天气怎么样？",
        # "从上海到杭州的最佳路线是什么？",
        # "分析一下 error.log 文件中有什么错误信息"
    ]
    
    for i, test_input in enumerate(test_inputs, 1):
        print(f"\n测试 {i}: {test_input}")
        print("-" * 50)
        
        try:
            # 调用工作流
            state = await router_workflow.ainvoke({"input": test_input})
            print(f"回应：{state['output']}")
        except Exception as e:
            print(f"错误：{str(e)}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())