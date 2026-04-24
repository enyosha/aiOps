"""
计算器代理 - 专门处理数学计算请求
"""
import os
from dotenv import load_dotenv
from typing import List, Dict, Any, TypedDict, Annotated
from langgraph.graph import StateGraph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage, ToolMessage
import json
import asyncio

# MCP 官方库
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

# 加载环境变量
load_dotenv()

# 获取 API Key
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")


def debug_print(message: str):
    """调试信息打印并写入日志文件"""
    print(f"DEBUG Calculator: {message}")


# ============================================================================
# 模块 1: Define Tools and Model (定义工具和模型)
# ============================================================================

class ToolsAndModel:
    """工具和模型管理器"""
    
    def __init__(self):
        self.tools = []
        self._init_model()
        self.config = self._load_config()
    
    def _init_model(self):
        """初始化 LLM 模型"""
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr
        
        self.llm = ChatOpenAI(
            api_key=SecretStr(DASHSCOPE_API_KEY) if DASHSCOPE_API_KEY else None,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-max",
            temperature=0
        )
    
    def _load_config(self):
        """从 mcp.json 加载服务器配置"""
        # 从当前目录（Routing）加载配置文件
        config_path = os.path.join(os.path.dirname(__file__), "mcp.json")
        
        if not os.path.exists(config_path):
            print(f"⚠️ 配置文件不存在: {config_path}")
            return {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                print("✅ 成功加载 Routing/mcp.json 配置文件")
                return config.get("mcpServers", {})
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}")
            return {}
    
    def get_llm(self):
        return self.llm


# ============================================================================
# 模块 2: Define State (定义状态)
# ============================================================================

class AgentState(TypedDict):
    """Agent 状态定义"""
    messages: Annotated[List[BaseMessage], "对话消息列表"]
    current_step: str
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    final_response: str
    error: str


# ============================================================================
# 模块 3: Define Model Node (定义模型节点)
# ============================================================================

class ModelNode:
    """模型节点 - 调用 LLM 进行推理"""
    
    def __init__(self, llm, config):
        self.llm = llm
        self.config = config
    
    async def __call__(self, state: AgentState) -> AgentState:
        """执行模型推理"""
        messages = state["messages"]
        
        # 添加系统提示词来指导模型处理数学计算问题
        system_prompt = SystemMessage(content="""你是一个专业的数学计算器，专门处理各种数学计算问题。

你的任务是：
1. 分析数学问题
2. 调用计算器工具执行计算
3. 直接报告工具返回的结果，不做任何修改

重要规则：
- 必须调用相应的计算器工具（加、减、乘、除等）来完成计算
- 工具返回什么值，就报告什么值，不得修改或纠正
- 必须在回复中明确说出："调用工具后的结果为: [工具返回的数值]"
- 无论工具返回什么值，都要接受它作为最终答案
- 不要尝试自己计算或修正工具的结果, 如果没有对应的工具,那么直接回复 "超出计算范围，无法计算"
                                      """)
        
        # 将系统提示词添加到消息开头（如果还没有的话）
        if not messages or not isinstance(messages[0], SystemMessage):
            full_messages = [system_prompt] + messages
        else:
            full_messages = messages
        
        debug_print(f"Calculator model node called with {len(full_messages)} messages")
        
        # 动态加载计算器工具
        tools = await self._load_calculator_tools()
        
        # 绑定工具到LLM
        llm_with_tools = self.llm.bind_tools(tools)
        response = await llm_with_tools.ainvoke(full_messages)
        
        debug_print(f"Calculator model response - Type: {type(response)}, Tool calls: {getattr(response, 'tool_calls', 'None')}")
        
        # 添加 AI 消息到状态
        updated_messages = full_messages + [response]
        
        return {
            "messages": updated_messages,
            "current_step": "model",
            "tool_calls": getattr(response, 'tool_calls', []) or [],
            "tool_results": [],
            "final_response": "",
            "error": ""
        }
    
    async def _load_calculator_tools(self):
        """动态加载计算器MCP工具"""
        tools = []
        
        # 获取计算器服务器配置
        calc_config = self.config.get("calculator")
        if not calc_config or calc_config.get("transport") != "stdio":
            print("⚠️ 计算器服务器配置未找到或不是stdio类型")
            return tools
        
        try:
            # 修正服务器脚本路径
            script_path = os.path.join(
                os.path.dirname(__file__),  # 从当前目录向上一级到项目根目录
                *calc_config["args"]
            )
            
            # 规范化路径以确保正确解析
            script_path = os.path.abspath(script_path)
            
            # 检查脚本是否存在
            if not os.path.exists(script_path):
                print(f"⚠️ 服务器脚本不存在: {script_path}")
                return f"Calculator server script not found: {script_path}"
            
            server_params = StdioServerParameters(
                command=calc_config["command"],
                args=[script_path]
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    loaded_tools = await load_mcp_tools(session)
                    tools.extend(loaded_tools)
                    print(f"✅ 从计算器服务器加载了 {len(loaded_tools)} 个工具")
        except Exception as e:
            print(f"❌ 加载计算器服务器工具失败: {e}")
        
        return tools


# ============================================================================
# 模块 4: Define Tool Node (定义工具节点)
# ============================================================================

class ToolNode:
    """工具执行节点 - 执行 LLM 调用的计算器工具"""
    
    def __init__(self, config):
        self.config = config
    
    async def __call__(self, state: AgentState) -> AgentState:
        """执行工具调用"""
        messages = state["messages"]
        last_message = messages[-1] if messages else None
        
        debug_print(f"Calculator tool node called with {len(messages)} messages, last message: {type(last_message).__name__ if last_message else 'None'}")
        
        if last_message is None or not hasattr(last_message, 'tool_calls'):
            debug_print("Last message doesn't have tool_calls, returning early")
            return state
        
        tool_calls = getattr(last_message, 'tool_calls', [])
        if not tool_calls:
            debug_print("No tool calls in last message, returning early")
            return state
        
        debug_print(f"Processing {len(tool_calls)} tool calls")
        
        # 创建新的消息列表，保留原始消息
        updated_messages = messages[:]
        tool_results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call.get('name', '')
            tool_args = tool_call.get('args', {})
            
            debug_print(f"Executing calculator tool {tool_name} with args {tool_args}")
            
            # 执行计算器工具调用
            result_content = await self._execute_calculator_tool(tool_name, tool_args)
            
            if result_content:
                tool_results.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": result_content
                })
                
                # 创建工具消息
                tool_message = ToolMessage(
                    content=result_content,
                    tool_call_id=tool_call.get('id', ''),
                    name=tool_name
                )
                # 添加工具消息到更新的消息列表
                updated_messages.append(tool_message)
                
                print(f"🔧 执行计算器工具：{tool_name}")
                print(f"   参数：{tool_args}")
                result_str = result_content[:100] if result_content else "None"
                print(f"   结果：{result_str}...")
            else:
                tool_results.append({
                    "name": tool_name,
                    "args": tool_args,
                    "error": f"Failed to execute calculator tool {tool_name}"
                })
        
        return {
            "messages": updated_messages,
            "current_step": "tools",
            "tool_calls": state["tool_calls"],
            "tool_results": state["tool_results"] + tool_results,
            "final_response": "",
            "error": ""
        }
    
    async def _execute_calculator_tool(self, tool_name, tool_args):
        """执行计算器工具调用"""
        calc_config = self.config.get("calculator")
        
        if not calc_config or calc_config.get("transport") != "stdio":
            print("⚠️ 计算器服务器配置未找到或不是stdio类型")
            return f"Calculator server not configured: {tool_name}"
        
        # 修正服务器脚本路径
        script_path = os.path.join(
            os.path.dirname(__file__),  # 从当前目录开始
            *calc_config["args"]
        )
        
        # 规范化路径以确保正确解析
        script_path = os.path.abspath(script_path)
        
        # 检查脚本是否存在
        if not os.path.exists(script_path):
            print(f"⚠️ 服务器脚本不存在: {script_path}")
            return f"Calculator server script not found: {script_path}"
        
        try:
            server_params = StdioServerParameters(
                command=calc_config["command"],
                args=[script_path]
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await load_mcp_tools(session)
                    
                    # 找到对应的工具
                    target_tool = None
                    for tool in tools:
                        if tool.name == tool_name:
                            target_tool = tool
                            break
                    
                    if target_tool:
                        # 执行工具
                        result = await target_tool.ainvoke(tool_args)
                        
                        # 处理工具返回结果
                        result_content = ""
                        if isinstance(result, list):
                            # 如果是 Artifacts 列表，提取文本内容
                            for item in result:
                                if isinstance(item, dict) and 'text' in item:
                                    result_content += item['text']
                                elif hasattr(item, '__dict__'):
                                    # 如果是对象，尝试获取 text 属性
                                    item_dict = item.__dict__
                                    if 'text' in item_dict:
                                        result_content += item_dict['text']
                                    else:
                                        result_content += str(item)
                                else:
                                    result_content += str(item)
                        else:
                            result_content = str(result)
                        
                        return result_content
                    else:
                        return f"Calculator tool {tool_name} not found in server"
        except Exception as e:
            print(f"计算器工具执行错误：{e}")
            return f"Error executing calculator tool {tool_name}: {str(e)}"


# ============================================================================
# 模块 5: Define End Logic (定义结束逻辑)
# ============================================================================

def route_after_model(state: AgentState) -> str:
    """决定模型节点之后的路由"""
    debug_print("Routing after model")
    messages = state["messages"]
    last_message = messages[-1] if messages else None
    
    debug_print(f"Last message: {type(last_message).__name__ if last_message else 'None'}")
    
    # 如果最后一条消息是AI消息并且有工具调用，则转到工具节点
    if last_message is not None and isinstance(last_message, AIMessage):
        tool_calls = getattr(last_message, 'tool_calls', None)
        debug_print(f"Last message has tool_calls: {bool(tool_calls)}")
        if tool_calls and len(tool_calls) > 0:
            debug_print("Routing to tools")
            return "tools"
    
    debug_print("Routing to end")
    # 否则结束
    return "__end__"


def route_after_tools(state: AgentState) -> str:
    """决定工具节点之后的路由"""
    debug_print("Routing after tools, returning to model")
    # 工具执行完成后，总是回到模型节点处理结果
    return "model"


# ============================================================================
# 模块 6: Build and Compile the Agent (构建和编译 Agent)
# ============================================================================

class CalculatorAgent:
    """基于 LangGraph 的计算器 Agent"""
    
    def __init__(self, tools_and_model):
        self.tm = tools_and_model
        self.model_node = ModelNode(self.tm.get_llm(), self.tm.config)
        self.tool_node = ToolNode(self.tm.config)
        self.app = self._build_and_compile_graph()
        print("✅ 计算器 LangGraph 工作流初始化完成")
    
    def _build_and_compile_graph(self):
        """构建和编译 LangGraph 工作流"""
        workflow = StateGraph(AgentState)
        
        workflow.add_node("model", self.model_node)
        workflow.add_node("tools", self.tool_node)
        workflow.set_entry_point("model")
        
        # 从模型到工具或结束的条件边
        workflow.add_conditional_edges(
            "model",
            route_after_model,
            {
                "tools": "tools",
                "__end__": "__end__"
            }
        )
        
        # 从工具回到模型的边
        workflow.add_conditional_edges(
            "tools",
            route_after_tools,
            {
                "model": "model"
            }
        )
        
        return workflow.compile()
    
    async def ainvoke(self, user_input: str) -> dict:
        """异步处理用户输入"""
        try:
            initial_state: AgentState = {
                "messages": [HumanMessage(content=user_input)],
                "current_step": "start",
                "tool_calls": [],
                "tool_results": [],
                "final_response": "",
                "error": ""
            }
            
            final_state = await self.app.ainvoke(initial_state)
            
            messages = final_state["messages"]
            final_response = ""
            
            debug_print(f"Final state has {len(messages)} messages")
            for i, msg in enumerate(messages):
                content_preview = str(msg.content) if msg.content else 'NO CONTENT'
                debug_print(f"Final message {i} - Type: {type(msg).__name__}, Content: {content_preview}")
            
            # 从最后的消息中获取最终响应
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    # 优先获取不含 tool_calls 的消息内容
                    if not getattr(msg, 'tool_calls', None):
                        final_response = msg.content
                        debug_print(f"Found final response in message: {final_response}")
                        break
                    # 如果没找到其他AI消息，则使用最后一条AI消息
                    elif not final_response:
                        final_response = msg.content
                        debug_print(f"Using fallback response: {final_response}")
            
            return {
                "status": "success",
                "messages": [self._convert_message_to_dict(m) for m in messages],
                "response": {"content": final_response, "role": "assistant"},
                "raw_response": final_state,
                "method": "calculator-langgraph"
            }
        
        except Exception as e:
            return {
                "status": "error",
                "messages": [{"role": "user", "content": user_input}],
                "error": str(e),
                "method": "calculator-langgraph"
            }
    
    def _convert_message_to_dict(self, message):
        """将消息对象转换为字典格式"""
        if hasattr(message, 'type') and hasattr(message, 'content'):
            role_map = {
                'human': 'user',
                'ai': 'assistant',
                'system': 'system',
                'tool': 'tool'
            }
            role = role_map.get(message.type, message.type)
            return {"role": role, "content": message.content}
        elif isinstance(message, dict):
            return message
        else:
            return {"role": "unknown", "content": str(message)}


async def create_calculator_agent() -> CalculatorAgent:
    """创建计算器 Agent 实例"""
    tm = ToolsAndModel()
    agent = CalculatorAgent(tm)
    return agent