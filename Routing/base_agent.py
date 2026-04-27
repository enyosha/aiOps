"""
Agent 基类 - 所有专用 Agent 的公共基类

功能：
1. 统一工具加载（使用全局缓存）
2. 统一消息处理
3. 统一错误处理
4. 减少代码重复
"""

import os
import json
from typing import List, Dict, Any, TypedDict, Annotated, Optional
from abc import ABC, abstractmethod
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage, ToolMessage
from langgraph.graph import StateGraph, START, END


class AgentState(TypedDict):
    """Agent 状态定义（通用）"""
    messages: Annotated[List[BaseMessage], "对话消息列表"]
    current_step: str
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    final_response: str
    error: str


class BaseAgent(ABC):
    """
    Agent 基类
    
    子类需要实现：
    - _get_server_name(): 返回 MCP 服务器名称
    - _get_system_prompt(): 返回系统提示词
    """
    
    def __init__(self, name: str):
        self.name = name
        self.tm = None
        self.app = None
        self._initialized = False
    
    async def initialize(self):
        """初始化 Agent（延迟初始化）"""
        if self._initialized:
            return
        
        # 导入全局工具缓存
        from Routing.tool_cache import tool_cache
        
        # 获取服务器名称
        server_name = self._get_server_name()
        
        # 从缓存加载工具
        print(f"[{self.name}] 正在初始化工具...")
        tools = await tool_cache.get_tools(server_name)
        
        # 初始化模型
        self._init_model(tools)
        
        # 构建工作流
        self.app = self._build_workflow()
        
        self._initialized = True
        print(f"[{self.name}] 初始化完成")
    
    def _init_model(self, tools: List[Any]):
        """初始化 LLM 模型并绑定工具"""
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr
        
        DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
        
        llm = ChatOpenAI(
            api_key=SecretStr(DASHSCOPE_API_KEY) if DASHSCOPE_API_KEY else None,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-max",
            temperature=0
        )
        
        # 绑定工具
        self.llm_with_tools = llm.bind_tools(tools)
    
    @abstractmethod
    def _get_server_name(self) -> str:
        """返回 MCP 服务器名称（子类实现）"""
        pass
    
    @abstractmethod
    def _get_system_prompt(self) -> str:
        """返回系统提示词（子类实现）"""
        pass
    
    # ===== 节点函数 =====
    
    async def model_node(self, state: AgentState) -> AgentState:
        """模型节点 - 调用 LLM 进行推理"""
        messages = state["messages"]
        
        # 添加系统提示词（如果还没有）
        if not any(isinstance(m, SystemMessage) for m in messages):
            system_prompt = self._get_system_prompt()
            messages = [SystemMessage(content=system_prompt)] + messages
        
        try:
            # 调用 LLM
            response = await self.llm_with_tools.ainvoke(messages)
            
            # 更新状态
            return {
                **state,
                "messages": messages + [response],
                "current_step": "model_completed"
            }
        
        except Exception as e:
            error_msg = f"模型调用失败: {str(e)}"
            print(f"[{self.name}] {error_msg}")
            return {
                **state,
                "error": error_msg,
                "current_step": "error"
            }
    
    async def tools_node(self, state: AgentState) -> AgentState:
        """工具节点 - 执行工具调用"""
        messages = state["messages"]
        last_message = messages[-1] if messages else None
        
        if not isinstance(last_message, AIMessage):
            return {**state, "error": "没有 AI 消息可以执行工具调用"}
        
        tool_calls = getattr(last_message, 'tool_calls', None)
        if not tool_calls or len(tool_calls) == 0:
            return {**state, "current_step": "no_tools"}
        
        print(f"[{self.name}] 执行 {len(tool_calls)} 个工具调用")
        
        # 获取缓存的工具列表
        from .tool_cache import tool_cache
        server_name = self._get_server_name()
        cached_tools = await tool_cache.get_tools(server_name)
        
        # 构建工具名称到工具对象的映射
        tool_map = {tool.name: tool for tool in cached_tools}
        
        tool_results = []
        new_messages = []
        
        for tool_call in tool_calls:
            try:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", "")
                
                # 查找对应的工具
                if tool_name not in tool_map:
                    raise ValueError(f"工具 '{tool_name}' 未找到")
                
                tool = tool_map[tool_name]
                
                # 执行工具调用
                result = await tool.ainvoke(tool_args)
                
                # 创建工具消息
                tool_message = ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"]
                )
                
                tool_results.append({
                    "tool_name": tool_call["name"],
                    "result": result
                })
                
                new_messages.append(tool_message)
                print(f"[{self.name}] 工具 '{tool_call['name']}' 执行成功")
            
            except Exception as e:
                error_msg = f"工具执行失败: {str(e)}"
                print(f"[{self.name}] {error_msg}")
                
                tool_message = ToolMessage(
                    content=error_msg,
                    tool_call_id=tool_call["id"]
                )
                
                new_messages.append(tool_message)
                tool_results.append({
                    "tool_name": tool_call["name"],
                    "error": error_msg
                })
        
        return {
            **state,
            "messages": messages + new_messages,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "current_step": "tools_completed"
        }
    
    def route_after_model(self, state: AgentState) -> str:
        """决定模型节点之后的路由"""
        messages = state["messages"]
        last_message = messages[-1] if messages else None
        
        # 如果 AI 消息包含工具调用，转到工具节点
        if isinstance(last_message, AIMessage):
            tool_calls = getattr(last_message, 'tool_calls', None)
            if tool_calls and len(tool_calls) > 0:
                return "tools"
        
        # 否则结束
        return "__end__"
    
    def route_after_tools(self, state: AgentState) -> str:
        """决定工具节点之后的路由"""
        # 工具执行完成后，总是回到模型节点处理结果
        return "model"
    
    def _build_workflow(self):
        """构建 LangGraph 工作流"""
        builder = StateGraph(AgentState)
        
        # 添加节点
        builder.add_node("model", self.model_node)
        builder.add_node("tools", self.tools_node)
        
        # 添加边
        builder.add_edge(START, "model")
        builder.add_conditional_edges(
            "model",
            self.route_after_model,
            {"tools": "tools", "__end__": END}
        )
        builder.add_edge("tools", "model")
        
        # 编译工作流
        return builder.compile()
    
    async def ainvoke(self, user_input: str) -> dict:
        """
        调用 Agent 处理用户输入
        
        Args:
            user_input: 用户输入
            
        Returns:
            处理结果字典
        """
        # 确保已初始化
        await self.initialize()
        
        # 构建初始状态
        initial_state: AgentState = {
            "messages": [HumanMessage(content=user_input)],
            "current_step": "start",
            "tool_calls": [],
            "tool_results": [],
            "final_response": "",
            "error": ""
        }
        
        try:
            # 执行工作流
            final_state = await self.app.ainvoke(initial_state)
            
            # 提取最终响应
            messages = final_state["messages"]
            last_message = messages[-1] if messages else None
            
            if isinstance(last_message, AIMessage):
                response_content = last_message.content
            elif final_state.get("error"):
                response_content = final_state["error"]
            else:
                response_content = "抱歉，我无法处理这个请求"
            
            return {
                "status": "success" if not final_state.get("error") else "error",
                "response": {
                    "role": "assistant",
                    "content": response_content
                },
                "tool_calls": final_state.get("tool_calls", []),
                "tool_results": final_state.get("tool_results", [])
            }
        
        except Exception as e:
            error_msg = f"Agent 执行出错: {str(e)}"
            print(f"[{self.name}] {error_msg}")
            
            return {
                "status": "error",
                "error": error_msg,
                "response": {
                    "role": "assistant",
                    "content": f"发生错误: {str(e)}"
                }
            }


# ===== 具体的 Agent 实现 =====

class CalculatorAgent(BaseAgent):
    """计算器 Agent"""
    
    def __init__(self):
        super().__init__("CalculatorAgent")
    
    def _get_server_name(self) -> str:
        return "calculator"
    
    def _get_system_prompt(self) -> str:
        return """你是一个专业的数学计算助手。
当用户提出数学计算问题时，使用可用的计算工具进行精确计算。
请清晰地展示计算过程和结果。"""


class LogReaderAgent(BaseAgent):
    """日志读取 Agent"""
    
    def __init__(self):
        super().__init__("LogReaderAgent")
    
    def _get_server_name(self) -> str:
        return "log-reader"
    
    def _get_system_prompt(self) -> str:
        return """你是一个专业的日志分析助手。
当用户请求读取或分析日志文件时，使用日志读取工具获取相关信息。
请清晰地总结日志内容，特别关注错误和警告信息。"""


class AmapAgent(BaseAgent):
    """高德地图 Agent"""
    
    def __init__(self):
        super().__init__("AmapAgent")
    
    def _get_server_name(self) -> str:
        return "amap-maps-streamableHTTP"
    
    def _get_system_prompt(self) -> str:
        return """你是一个专业的地图服务助手。
当用户询问位置、导航、天气等信息时，使用高德地图工具提供准确的信息。
请用友好的语气回答，并提供有用的详细信息。"""


class RAGAgent(BaseAgent):
    """RAG 知识库 Agent"""
    
    def __init__(self):
        super().__init__("RAGAgent")
    
    def _get_server_name(self) -> str:
        return "rag-knowledge"
    
    def _get_system_prompt(self) -> str:
        return """你是一个专业的知识库查询助手。
当用户询问关于 AI 趋势、医学知识、产品介绍等问题时，使用 RAG 工具从知识库中检索相关信息。
请基于检索到的信息提供准确、详细的回答。"""


# ===== 工厂函数（保持向后兼容）=====

async def create_calculator_agent():
    """创建计算器 Agent"""
    agent = CalculatorAgent()
    await agent.initialize()
    return agent


async def create_log_reader_agent():
    """创建日志读取 Agent"""
    agent = LogReaderAgent()
    await agent.initialize()
    return agent


async def create_amap_agent():
    """创建高德地图 Agent"""
    agent = AmapAgent()
    await agent.initialize()
    return agent


async def create_rag_agent():
    """创建 RAG Agent"""
    agent = RAGAgent()
    await agent.initialize()
    return agent
