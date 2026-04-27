"""
会话管理器

功能：
1. 管理多轮对话的历史上下文
2. 支持多个并发会话
3. 自动清理过期会话
4. 提供历史消息的获取和添加接口
"""

import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage


@dataclass
class Message:
    """消息对象"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    
    def to_langchain_message(self) -> BaseMessage:
        """转换为 LangChain 消息对象"""
        if self.role == "user":
            return HumanMessage(content=self.content)
        elif self.role == "assistant":
            return AIMessage(content=self.content)
        else:
            raise ValueError(f"不支持的消息角色: {self.role}")


class Session:
    """单个会话对象"""
    
    def __init__(self, session_id: str, max_history: int = 20):
        self.session_id = session_id
        self.messages: List[Message] = []
        self.max_history = max_history
        self.created_at = time.time()
        self.last_active = time.time()
    
    def add_message(self, role: str, content: str):
        """添加消息到会话"""
        self.messages.append(Message(role=role, content=content))
        self.last_active = time.time()
        
        # 限制历史长度（保留最近的 max_history 轮对话）
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def get_history_messages(self) -> List[BaseMessage]:
        """获取所有历史消息（LangChain 格式）"""
        return [msg.to_langchain_message() for msg in self.messages]
    
    def get_recent_messages(self, n: int) -> List[BaseMessage]:
        """获取最近 n 条消息"""
        recent = self.messages[-n:] if len(self.messages) > n else self.messages
        return [msg.to_langchain_message() for msg in recent]
    
    def is_expired(self, timeout: int = 3600) -> bool:
        """检查会话是否过期（默认 1 小时）"""
        return time.time() - self.last_active > timeout
    
    def clear(self):
        """清空会话历史"""
        self.messages.clear()
    
    def get_stats(self) -> Dict:
        """获取会话统计信息"""
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "created_at": self.created_at,
            "last_active": self.last_active,
            "duration_seconds": time.time() - self.created_at
        }


class ConversationManager:
    """
    会话管理器（单例模式）
    
    功能：
    - 创建和管理多个会话
    - 自动清理过期会话
    - 提供统一的会话访问接口
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._sessions: Dict[str, Session] = {}
        self._default_max_history = 20  # 默认保留 20 条消息
        self._session_timeout = 3600  # 会话超时时间（秒）
        self._initialized = True
    
    def create_session(self, session_id: Optional[str] = None) -> str:
        """
        创建新会话
        
        Args:
            session_id: 可选的会话 ID，不提供则自动生成
            
        Returns:
            会话 ID
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        self._sessions[session_id] = Session(
            session_id=session_id,
            max_history=self._default_max_history
        )
        
        print(f"[ConversationManager] 创建新会话: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话对象"""
        session = self._sessions.get(session_id)
        if session:
            session.last_active = time.time()
        return session
    
    def add_message(self, session_id: str, role: str, content: str):
        """
        添加消息到指定会话
        
        Args:
            session_id: 会话 ID
            role: 消息角色 ("user" 或 "assistant")
            content: 消息内容
        """
        if session_id not in self._sessions:
            self.create_session(session_id)
        
        self._sessions[session_id].add_message(role, content)
    
    def get_history(self, session_id: str) -> List[BaseMessage]:
        """
        获取会话的历史消息
        
        Args:
            session_id: 会话 ID
            
        Returns:
            LangChain 消息列表
        """
        session = self._sessions.get(session_id)
        if session:
            return session.get_history_messages()
        return []
    
    def get_recent_history(self, session_id: str, n: int = 10) -> List[BaseMessage]:
        """
        获取会话的最近 n 条消息
        
        Args:
            session_id: 会话 ID
            n: 消息数量
            
        Returns:
            LangChain 消息列表
        """
        session = self._sessions.get(session_id)
        if session:
            return session.get_recent_messages(n)
        return []
    
    def clear_session(self, session_id: str):
        """清空指定会话的历史"""
        session = self._sessions.get(session_id)
        if session:
            session.clear()
            print(f"[ConversationManager] 清空会话: {session_id}")
    
    def remove_session(self, session_id: str):
        """删除指定会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            print(f"[ConversationManager] 删除会话: {session_id}")
    
    def cleanup_expired_sessions(self):
        """清理过期的会话"""
        expired_ids = [
            sid for sid, session in self._sessions.items()
            if session.is_expired(self._session_timeout)
        ]
        
        for sid in expired_ids:
            self.remove_session(sid)
        
        if expired_ids:
            print(f"[ConversationManager] 清理了 {len(expired_ids)} 个过期会话")
    
    def get_all_sessions(self) -> Dict[str, Dict]:
        """获取所有会话的统计信息"""
        return {
            sid: session.get_stats()
            for sid, session in self._sessions.items()
        }
    
    def clear_all(self):
        """清空所有会话（应用关闭时调用）"""
        print(f"[ConversationManager] 清空所有会话（共 {len(self._sessions)} 个）")
        self._sessions.clear()


# 全局单例实例
conversation_manager = ConversationManager()
