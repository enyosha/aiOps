"""
全局工具缓存管理器

功能：
1. 缓存 MCP 服务器连接和工具列表，避免重复加载
2. 支持 TTL 过期策略
3. 线程安全的缓存访问
4. 统一管理所有 Agent 的工具加载
"""

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
    load_mcp_tools,
)
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


class ToolCacheEntry:
    """缓存条目，包含工具和元数据"""
    
    def __init__(self, tools: List[Any], timestamp: float):
        self.tools = tools
        self.timestamp = timestamp
    
    def is_expired(self, ttl: int) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > ttl


class GlobalToolCache:
    """
    全局工具缓存管理器（单例模式）
    
    生命周期：从应用启动到对话结束
    缓存策略：基于服务器名称的 TTL 缓存
    """
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._cache: Dict[str, ToolCacheEntry] = {}
        self._sessions: Dict[str, ClientSession] = {}
        self._default_ttl = 300  # 默认 5 分钟
        # mcp.json 在 Routing 目录下
        self._mcp_config_path = Path(__file__).parent.parent / "Routing" / "mcp.json"
        self._mcp_config: Optional[Dict] = None
        self._initialized = True
    
    def _load_mcp_config(self) -> Dict:
        """加载 MCP 服务器配置"""
        if self._mcp_config is None:
            try:
                with open(self._mcp_config_path, 'r', encoding='utf-8') as f:
                    self._mcp_config = json.load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f"MCP 配置文件不存在: {self._mcp_config_path}")
            except json.JSONDecodeError as e:
                raise ValueError(f"MCP 配置文件格式错误: {e}")
        
        return self._mcp_config
    
    def _get_server_config(self, server_name: str) -> Optional[Dict]:
        """获取指定服务器的配置"""
        config = self._load_mcp_config()
        return config.get("mcpServers", {}).get(server_name)
    
    async def get_tools(self, server_name: str, ttl: Optional[int] = None) -> List[Any]:
        """
        获取指定服务器的工具列表（带缓存）
        
        Args:
            server_name: MCP 服务器名称
            ttl: 缓存过期时间（秒），None 使用默认值
            
        Returns:
            工具列表
        """
        ttl = ttl or self._default_ttl
        
        # 检查缓存
        if server_name in self._cache:
            entry = self._cache[server_name]
            if not entry.is_expired(ttl):
                print(f"[ToolCache] 使用缓存的工具: {server_name} (PID保持)")
                return entry.tools
            else:
                print(f"[ToolCache] 缓存已过期，重新加载: {server_name}")
                # 清理过期缓存
                await self._cleanup_server(server_name)
        
        # 加载新工具
        print(f"[ToolCache] 首次加载工具: {server_name}")
        tools = await self._load_tools_from_server(server_name)
        
        # 更新缓存
        self._cache[server_name] = ToolCacheEntry(tools, time.time())
        
        return tools
    
    async def _load_tools_from_server(self, server_name: str) -> List[Any]:
        """
        从指定服务器加载工具
        
        Args:
            server_name: MCP 服务器名称
            
        Returns:
            工具列表
        """
        server_config = self._get_server_config(server_name)
        if not server_config:
            raise ValueError(f"未找到服务器配置: {server_name}")
        
        transport = server_config.get("transport", "stdio")
        
        if transport == "stdio":
            return await self._load_stdio_tools(server_name, server_config)
        elif transport == "streamable-http":
            return await self._load_streamable_http_tools(server_name, server_config)
        else:
            raise ValueError(f"不支持的传输协议: {transport}")
    
    async def _load_stdio_tools(self, server_name: str, config: Dict) -> List[Any]:
        """通过 stdio 协议加载工具"""
        command = config.get("command", "python")
        args = config.get("args", [])
        
        # 修正路径：从 Routing 目录解析相对路径
        routing_dir = os.path.join(os.path.dirname(__file__), "..", "Routing")  # Routing 目录
        
        # 解析环境变量和路径
        processed_args = []
        for arg in args:
            if "{AMAP_API_KEY}" in arg:
                api_key = os.getenv("AMAP_API_KEY", "")
                arg = arg.replace("{AMAP_API_KEY}", api_key)
            
            # 如果是相对路径（以 .. 开头），转换为绝对路径
            if arg.startswith(".."):
                full_path = os.path.normpath(os.path.join(routing_dir, arg))
                if os.path.exists(full_path):
                    arg = full_path
                    print(f"[ToolCache] 路径转换: {arg}")
            
            processed_args.append(arg)
        
        print(f"[ToolCache] 启动服务器: {command} {' '.join(processed_args)}")
        
        try:
            # 使用 MultiServerMCPClient 来管理连接
            client = MultiServerMCPClient({
                server_name: {
                    "transport": "stdio",
                    "command": command,
                    "args": processed_args
                }
            })
            
            # 获取工具
            tools = await client.get_tools()
            
            # 保存客户端引用以保持连接
            self._sessions[server_name] = {
                "client": client,
            }
            
            print(f"[ToolCache] 成功加载 {len(tools)} 个工具: {server_name}")
            return tools
        
        except Exception as e:
            print(f"[ToolCache] 加载工具失败 [{server_name}]: {e}")
            raise
    
    async def _load_streamable_http_tools(self, server_name: str, config: Dict) -> List[Any]:
        """通过 streamable-http 协议加载工具"""
        url = config.get("url", "")
        
        # 解析环境变量
        if "{AMAP_API_KEY}" in url:
            api_key = os.getenv("AMAP_API_KEY", "")
            if not api_key:
                raise ValueError("AMAP_API_KEY 环境变量未设置")
            url = url.replace("{AMAP_API_KEY}", api_key)
        
        print(f"[ToolCache] 连接 HTTP 服务器: {url[:50]}...")
        
        try:
            # 添加超时处理
            import asyncio
            http_transport = streamable_http_client(url=url)
            
            # 设置超时
            try:
                read, write, get_session_id = await asyncio.wait_for(
                    http_transport.__aenter__(),
                    timeout=10.0  # 10秒超时
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"连接超时: {server_name} (10秒)")
            
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            
            tools = await load_mcp_tools(session)
            
            # 保存会话
            self._sessions[server_name] = {
                "session": session,
                "transport": http_transport
            }
            
            print(f"[ToolCache] 成功加载 {len(tools)} 个工具: {server_name}")
            return tools
            
        except Exception as e:
            print(f"[ToolCache] 加载 HTTP 工具失败 [{server_name}]: {e}")
            raise
    
    async def _cleanup_server(self, server_name: str):
        """清理指定服务器的连接和缓存"""
        if server_name in self._cache:
            del self._cache[server_name]
        
        if server_name in self._sessions:
            session_info = self._sessions[server_name]
            try:
                # 关闭会话（针对 streamable-http）
                session = session_info.get("session")
                if session and hasattr(session, '__aexit__'):
                    try:
                        await session.__aexit__(None, None, None)
                    except Exception:
                        pass  # 忽略清理时的异常
                
                # 关闭客户端（针对 stdio）
                client = session_info.get("client")
                if client and hasattr(client, 'close'):
                    try:
                        await client.close()
                    except Exception:
                        pass  # 忽略清理时的异常
                        
                # 关闭 transport
                transport = session_info.get("transport")
                if transport and hasattr(transport, '__aexit__'):
                    try:
                        await transport.__aexit__(None, None, None)
                    except Exception:
                        pass  # 忽略清理时的异常
            except Exception:
                # 静默处理清理错误，避免干扰用户
                pass
            
            del self._sessions[server_name]
    
    async def clear_all(self):
        """清空所有缓存（对话结束时调用）"""
        print("[ToolCache] 清空所有缓存...")
        
        for server_name in list(self._sessions.keys()):
            await self._cleanup_server(server_name)
        
        self._cache.clear()
        self._sessions.clear()
    
    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        return {
            "cached_servers": list(self._cache.keys()),
            "cache_count": len(self._cache),
            "active_sessions": len(self._sessions)
        }


# 全局单例实例
tool_cache = GlobalToolCache()
