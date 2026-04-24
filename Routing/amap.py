"""
高德地图代理 - 专门处理地图和地理位置相关请求
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
from mcp.client.streamable_http import streamable_http_client
from langchain_mcp_adapters.tools import load_mcp_tools

# 加载环境变量
load_dotenv()

# 获取 API Key
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
AMAP_API_KEY = os.getenv("AMAP_API_KEY")


def debug_print(message: str):
    """调试信息打印并写入日志文件"""
    print(f"DEBUG Amap: {message}")


# ============================================================================
# 模块 1: Define Tools and Model (定义工具和模型)
# ============================================================================

class ToolsAndModel:
    """工具和模型管理器"""
    
    def __init__(self):
        self.tools = []
        self._init_model()
        self.config = self._load_config()
        self.amap_tools_cache = None  # 缓存高德工具列表
    
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
        
        # 获取高德工具列表用于生成系统提示词
        amap_tools = await self._get_amap_tools()
        amap_tool_names = [tool.name for tool in amap_tools] if amap_tools else []
        
        debug_print("开始加载高德地图工具...")
        # 动态加载高德地图工具
        tools = await self._load_amap_tools()
        
        # 如果没有工具，返回错误信息
        if not tools:
            print("⚠️ 无法加载高德地图工具，无法处理请求")
            error_response = AIMessage(
                content="抱歉，无法连接到高德地图服务，无法处理您的请求。",
                tool_calls=[]
            )
            
            # 添加 AI 消息到状态
            updated_messages = messages + [error_response]
            
            return {
                "messages": updated_messages,
                "current_step": "model",
                "tool_calls": [],
                "tool_results": [],
                "final_response": "抱歉，无法连接到高德地图服务。",
                "error": "无法加载高德地图工具"
            }
        
        debug_print(f"成功加载 {len(tools)} 个工具，准备添加系统提示词")
        
        # 在确认可以使用工具后，才添加系统提示词
        system_prompt = SystemMessage(content=f"""你是一个智能出行和生活助手，专门处理地图和地理位置相关的问题。在使用工具时请注意：

【重要 - 路径规划工具使用规范】
1. 所有路径规划工具都要求：
   - origin 和 destination 必须是 "经度，纬度" 格式的字符串
   - 例如："116.39745,39.908717"

2. 如果用户提供的是地名（如"小平岛"、"中山广场"、"天安门"等）：
   - 第一步：调用地理编码工具（如 {'/'.join([name for name in amap_tool_names if 'geo' in name or 'location' in name or 'search' in name][:3]) or 'maps_geo'}) 获取经纬度
   - 第二步：从返回结果中提取 location 字段（格式："经度，纬度"）
   - 第三步：使用得到的经纬度调用相应的路径规划工具

3. 高德地图可用工具列表：
   - 地理编码: {', '.join([name for name in amap_tool_names if 'geo' in name or 'location' in name or 'search' in name][:3]) or 'maps_geo, maps_location_search'}
   - 路径规划: {', '.join([name for name in amap_tool_names if 'direction' in name or 'route' in name][:3]) or 'maps_direction_transit_integrated, maps_direction_driving, maps_direction_walking'}
   - 天气查询: {', '.join([name for name in amap_tool_names if 'weather' in name][:2]) or 'maps_weather'}
   - 其他工具: {', '.join([name for name in amap_tool_names if 'geo' not in name and 'direction' not in name and 'weather' not in name and 'location' not in name and 'route' not in name][:5]) or 'maps_distance, maps_poi_search'}

4. 公交路径规划 ({next((name for name in amap_tool_names if 'transit' in name or 'integrated' in name), 'maps_direction_transit_integrated')}) 完整参数：
   **必需参数**:
   - origin: 起点经纬度（"经度，纬度"格式）
   - destination: 终点经纬度（"经度，纬度"格式）
   - city: 起点城市名称或 citycode
   
   **重要可选参数**（主动提供以获得更好结果）:
   - cityd: 跨城时的终点城市（同城可不填）
   - extensions: 'all'（返回详细信息）或 'base'（基本信息），建议使用'all'以获取详细路线
   - strategy: 公交策略（0-最快捷/1-最经济/2-最少换乘/3-最少步行/5-不乘地铁），默认 0
   - nightflag: 是否计算夜班车（0-否/1-是），默认 0
   - date: 出发日期（格式：2024-3-19），可选
   - time: 出发时间（格式：2024-3-19），可选

5. ⚠️ **关键注意事项**：
   - 如果 API 返回的结果为空，说明没有匹配的路线或数据
   - 此时应该：
     a) 检查是否设置了 extensions='all'
     b) 尝试不同的 strategy 值（如 0,1,2,3）
     c) 检查是否是夜间时间，设置 nightflag=1
     d) 考虑推荐用户使用驾车或步行等其他方案

【示例流程】
用户：我大连，从小平岛到中山广场，公交 + 步行的方式，应该如何走？耗时多时间？

你可以考虑以下步骤：
1. 调用地理编码工具获取小平岛的经纬度
2. 调用地理编码工具获取中山广场的经纬度  
3. 调用公交路径规划工具获取路线
4. 根据返回结果，整理并告知用户详细的乘车路线、换乘信息、耗时等

【其他工具】
- 天气查询：直接提供城市名称即可
- 距离测量：同样需要先将地名转换为经纬度
- POI 搜索：可以直接使用关键词

请根据用户需求和可用工具合理选择！""")
        
        # 将系统提示词添加到消息开头（如果还没有的话）
        if not messages or not isinstance(messages[0], SystemMessage):
            full_messages = [system_prompt] + messages
        else:
            full_messages = messages
        
        debug_print(f"Amap model node called with {len(full_messages)} messages")
        for i, msg in enumerate(full_messages):
            if isinstance(msg, SystemMessage):
                continue  # 跳过系统消息的详细打印
            debug_print(f"Message {i} - Type: {type(msg).__name__}, Content: {str(msg.content)}")
        
        # 绑定工具到LLM
        llm_with_tools = self.llm.bind_tools(tools)
        response = await llm_with_tools.ainvoke(full_messages)
        
        debug_print(f"Amap model response - Type: {type(response)}, Tool calls: {getattr(response, 'tool_calls', 'None')}")
        
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
    
    async def _get_amap_tools(self):
        """获取高德地图工具列表"""
        if hasattr(self, 'tm') and hasattr(self.tm, 'amap_tools_cache') and self.tm.amap_tools_cache:
            return self.tm.amap_tools_cache
            
        if not AMAP_API_KEY:
            return None
        
        # 从配置中获取高德服务器URL
        amap_config = None
        for name, config in self.config.items():
            if "amap" in name and config.get("url"):
                amap_config = config
                break
        
        if not amap_config:
            return None
        
        # 替换 URL 中的 API KEY
        amap_url = amap_config["url"].replace("{AMAP_API_KEY}", AMAP_API_KEY)
        
        try:
            # 使用 Streamable HTTP 客户端连接高德 MCP 服务
            from mcp.client.streamable_http import streamable_http_client
            from mcp import ClientSession
            
            # 正确处理 streamable_http_client 返回的三元组
            async with streamable_http_client(amap_url) as connection:
                # 根据实际返回值数量进行处理
                if isinstance(connection, tuple) and len(connection) == 3:
                    read, write, extra = connection
                elif isinstance(connection, tuple) and len(connection) == 2:
                    read, write = connection
                else:
                    # 如果不是元组或长度不符合预期，直接使用
                    if hasattr(connection, '__iter__'):
                        connection_tuple = tuple(connection)
                        if len(connection_tuple) >= 2:
                            read, write = connection_tuple[0], connection_tuple[1]
                        else:
                            print("⚠️ 无法从连接中提取读写接口")
                            return None
                    else:
                        print("⚠️ 连接对象格式不符合预期")
                        return None
                
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    all_tools = await load_mcp_tools(session)
                    
                    # 缓存结果
                    if hasattr(self, 'tm'):
                        self.tm.amap_tools_cache = all_tools
                    
                    return all_tools
        except Exception as e:
            # 捕获异常但不中断执行，返回 None
            print(f"获取高德工具列表失败：{e}")
            return None

    async def _load_amap_tools(self):
        """动态加载MCP工具 - 只加载高德地图相关的工具"""
        tools = []
        
        # 遍历配置文件中的服务器，仅处理高德地图服务器
        for server_name, server_config in self.config.items():
            try:
                if server_config.get("url") and "amap" in server_name:
                    # 高德地图远程服务器配置
                    amap_url = server_config["url"].replace("{AMAP_API_KEY}", AMAP_API_KEY)
                    
                    if not AMAP_API_KEY:
                        print("⚠️ 高德 API 密钥未配置")
                        continue
                    
                    # 使用 Streamable HTTP 客户端连接高德 MCP 服务
                    from mcp.client.streamable_http import streamable_http_client
                    from mcp import ClientSession
                    
                    # 正确处理 streamable_http_client 返回的三元组
                    async with streamable_http_client(amap_url) as connection:
                        # 根据实际返回值数量进行处理
                        if isinstance(connection, tuple) and len(connection) == 3:
                            read, write, extra = connection
                        elif isinstance(connection, tuple) and len(connection) == 2:
                            read, write = connection
                        else:
                            # 如果不是元组或长度不符合预期，直接使用
                            if hasattr(connection, '__iter__'):
                                connection_tuple = tuple(connection)
                                if len(connection_tuple) >= 2:
                                    read, write = connection_tuple[0], connection_tuple[1]
                                else:
                                    print("⚠️ 无法从连接中提取读写接口")
                                    continue
                            else:
                                print("⚠️ 连接对象格式不符合预期")
                                continue
                        
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            loaded_tools = await load_mcp_tools(session)
                            tools.extend(loaded_tools)
                            print(f"✅ 从 {server_name} 高德服务器加载了 {len(loaded_tools)} 个工具")
                elif server_config.get("transport") == "streamable-http":
                    # 本地服务器配置 - 修正路径
                    script_path = os.path.join(
                        os.path.dirname(__file__),  # 从当前目录向上一级到项目根目录
                        *server_config["args"]
                    )
                    
                    # 规范化路径以确保正确解析
                    script_path = os.path.abspath(script_path)
                    
                    # 检查脚本是否存在
                    if not os.path.exists(script_path):
                        print(f"⚠️ 服务器脚本不存在: {script_path}")
                        continue
                    
                    server_params = StdioServerParameters(
                        command=server_config["command"],
                        args=[script_path]
                    )

                    async with stdio_client(server_params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            loaded_tools = await load_mcp_tools(session)
                            tools.extend(loaded_tools)
                            print(f"✅ 从 {server_name} 服务器加载了 {len(loaded_tools)} 个工具")
                elif "amap" not in server_name:
                    # 非高德地图服务器，跳过
                    continue
            except Exception as e:
                print(f"❌ 加载 {server_name} 服务器工具失败: {e}")
        
        return tools


# ============================================================================
# 模块 4: Define Tool Node (定义工具节点)
# ============================================================================

class ToolNode:
    """工具执行节点 - 执行 LLM 调用的高德地图工具"""
    
    def __init__(self, config):
        self.config = config
    
    async def __call__(self, state: AgentState) -> AgentState:
        """执行工具调用"""
        messages = state["messages"]
        last_message = messages[-1] if messages else None
        
        debug_print(f"Amap tool node called with {len(messages)} messages, last message: {type(last_message).__name__ if last_message else 'None'}")
        
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
            
            debug_print(f"Executing amap tool {tool_name} with args {tool_args}")
            
            # 执行高德地图工具调用
            result_content = await self._execute_amap_tool(tool_name, tool_args)
            
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
                
                print(f"🔧 执行高德地图工具：{tool_name}")
                print(f"   参数：{tool_args}")
                result_str = result_content[:100] if result_content else "None"
                print(f"   结果：{result_str}...")
            else:
                tool_results.append({
                    "name": tool_name,
                    "args": tool_args,
                    "error": f"Failed to execute amap tool {tool_name}"
                })
        
        return {
            "messages": updated_messages,
            "current_step": "tools",
            "tool_calls": state["tool_calls"],
            "tool_results": state["tool_results"] + tool_results,
            "final_response": "",
            "error": ""
        }
    
    async def _execute_amap_tool(self, tool_name, tool_args):
        """执行高德地图工具调用"""
        # 检查是否配置了API密钥
        if not AMAP_API_KEY:
            return "高德 API 密钥未配置，无法调用高德服务"
        
        # 从配置中获取高德服务器URL
        amap_config = None
        for name, config in self.config.items():
            if "amap" in name and config.get("url"):
                amap_config = config
                break
        
        if not amap_config:
            return "高德服务器配置未找到"
        
        # 替换 URL 中的 API KEY
        amap_url = amap_config["url"].replace("{AMAP_API_KEY}", AMAP_API_KEY)
        
        try:
            # 使用 Streamable HTTP 客户端连接高德 MCP 服务
            from mcp.client.streamable_http import streamable_http_client
            from mcp import ClientSession
            
            # 正确处理 streamable_http_client 返回的三元组
            async with streamable_http_client(amap_url) as connection:
                # 根据实际返回值数量进行处理
                if isinstance(connection, tuple) and len(connection) == 3:
                    read, write, extra = connection
                elif isinstance(connection, tuple) and len(connection) == 2:
                    read, write = connection
                else:
                    # 如果不是元组或长度不符合预期，直接使用
                    if hasattr(connection, '__iter__'):
                        connection_tuple = tuple(connection)
                        if len(connection_tuple) >= 2:
                            read, write = connection_tuple[0], connection_tuple[1]
                        else:
                            return f"无法从连接中提取读写接口"
                    else:
                        return f"连接对象格式不符合预期: {type(connection)}"
                
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    all_tools = await load_mcp_tools(session)
                    
                    # 查找匹配的工具
                    target_tool = None
                    for tool in all_tools:
                        if tool.name == tool_name:
                            target_tool = tool
                            break
                    
                    if target_tool:
                        # 如果找到了工具定义，使用 langchain-mcp-adapters 调用
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
                        return f"在高德服务中找不到工具 {tool_name}"
        except Exception as e:
            # 捕获具体的异常并返回
            import traceback
            error_details = traceback.format_exc()
            print(f"高德工具执行错误详情：{error_details}")
            error_msg = f"执行高德工具 {tool_name} 时发生错误: {str(e)}"
            # 检查是否是 TaskGroup 错误
            if "unhandled errors in a TaskGroup" in str(e):
                print("⚠️ 检测到 Streamable HTTP 连接的 TaskGroup 异常。这通常是由于 mcp 库在关闭连接时的竞态条件导致的。")
                print("   建议：检查 mcp 库版本，或尝试在网络更稳定的环境下运行。")
            return error_msg


# ============================================================================
# 模块 5: Define End Logic (定义结束逻辑)
# ============================================================================

def route_after_model(state: AgentState) -> str:
    """决定模型节点之后的路由"""
    debug_print("Amap routing after model")
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
    debug_print("Amap routing after tools, returning to model")
    # 工具执行完成后，总是回到模型节点处理结果
    return "model"


# ============================================================================
# 模块 6: Build and Compile the Agent (构建和编译 Agent)
# ============================================================================

class AmapAgent:
    """基于 LangGraph 的高德地图 Agent"""
    
    def __init__(self, tools_and_model):
        self.tm = tools_and_model
        self.model_node = ModelNode(self.tm.get_llm(), self.tm.config)
        # 设置tm引用，使ModelNode可以访问ToolsAndModel实例
        self.model_node.tm = tools_and_model
        self.tool_node = ToolNode(self.tm.config)
        self.app = self._build_and_compile_graph()
        print("✅ 高德地图 LangGraph 工作流初始化完成")
    
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
                "method": "amap-langgraph"
            }
        
        except Exception as e:
            return {
                "status": "error",
                "messages": [{"role": "user", "content": user_input}],
                "error": str(e),
                "method": "amap-langgraph"
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


async def create_amap_agent() -> AmapAgent:
    """创建高德地图 Agent 实例"""
    tm = ToolsAndModel()
    agent = AmapAgent(tm)
    return agent