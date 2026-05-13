"""
Redis 会话存储管理器

提供会话数据的持久化存储功能，支持保存、加载、删除和列出会话。
"""

import redis
import json
import time
from typing import List, Dict, Optional
from .conversation_manager import Session, Message


class RedisSessionStore:
    """Redis 会话存储管理器"""

    def __init__(self, host='localhost', port=6379, db=0, password=None, ttl=604800):
        """初始化 Redis 连接

        Args:
            host: Redis 服务器地址
            port: Redis 服务器端口
            db: Redis 数据库编号
            password: Redis 密码（可选）
            ttl: 会话过期时间（秒），默认 7 天
        """
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True
        )
        self.ttl = ttl  # 会话过期时间（秒）

    def save_session(self, session: Session) -> bool:
        """保存会话到 Redis

        Args:
            session: Session 对象

        Returns:
            bool: 是否保存成功
        """
        try:
            session_id = session.session_id

            # 1. 保存会话元数据
            meta_key = f"session:{session_id}:meta"
            meta_data = {
                "session_id": session_id,
                "created_at": str(session.created_at),
                "last_active": str(session.last_active),
                "max_history": str(session.max_history),
                "message_count": str(len(session.messages))
            }
            self.redis_client.hset(meta_key, mapping=meta_data)
            self.redis_client.expire(meta_key, self.ttl)

            # 2. 保存消息列表
            messages_key = f"session:{session_id}:messages"
            # 先删除旧数据
            self.redis_client.delete(messages_key)
            # 批量插入消息
            for msg in session.messages:
                msg_data = {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp
                }
                self.redis_client.rpush(messages_key, json.dumps(msg_data))
            self.redis_client.expire(messages_key, self.ttl)

            # 3. 更新活跃会话索引
            active_key = "sessions:active"
            self.redis_client.zadd(active_key, {session_id: session.last_active})

            # 4. 更新会话历史（保留最近 50 个）
            history_key = "sessions:history"
            self.redis_client.lrem(history_key, 0, session_id)  # 移除旧的
            self.redis_client.lpush(history_key, session_id)
            self.redis_client.ltrim(history_key, 0, 49)  # 保留最近 50 个

            return True

        except Exception as e:
            # Redis 连接失败时提示用户
            print(f"[警告] Redis 连接失败，会话将无法持久化: {e}")
            return False

    def load_session(self, session_id: str) -> Optional[Session]:
        """从 Redis 加载会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 对象，如果不存在则返回 None
        """
        try:
            # 1. 加载元数据
            meta_key = f"session:{session_id}:meta"
            meta_data = self.redis_client.hgetall(meta_key)

            if not meta_data:
                return None

            # 2. 创建 Session 对象
            session = Session(
                session_id=session_id,
                max_history=int(meta_data.get("max_history", 20))
            )
            session.created_at = float(meta_data["created_at"])
            session.last_active = float(meta_data["last_active"])

            # 3. 加载消息列表
            messages_key = f"session:{session_id}:messages"
            messages_data = self.redis_client.lrange(messages_key, 0, -1)

            for msg_json in messages_data:
                msg_data = json.loads(msg_json)
                session.messages.append(Message(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    timestamp=msg_data["timestamp"]
                ))

            return session

        except Exception as e:
            # Redis 连接失败时提示用户
            print(f"[警告] Redis 连接失败，无法加载历史会话: {e}")
            return None

    def list_recent_sessions(self, limit: int = 10) -> List[Dict]:
        """列出最近的会话

        Args:
            limit: 返回的会话数量限制

        Returns:
            会话信息列表，按最后活跃时间降序排列
        """
        try:
            active_key = "sessions:active"
            # 获取最近活跃的 session_id（按 last_active 降序）
            session_ids = self.redis_client.zrevrange(
                active_key, 0, limit - 1, withscores=True
            )

            sessions = []
            for session_id, last_active in session_ids:
                meta_key = f"session:{session_id}:meta"
                meta_data = self.redis_client.hgetall(meta_key)

                if meta_data:
                    sessions.append({
                        "session_id": session_id,
                        "message_count": int(meta_data.get("message_count", 0)),
                        "created_at": float(meta_data["created_at"]),
                        "last_active": float(meta_data["last_active"])
                    })

            return sessions

        except Exception as e:
            # Redis 连接失败时提示用户，但不影响主流程
            print(f"[警告] Redis 连接失败，会话将无法持久化: {e}")
            return []

    def delete_session(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否删除成功
        """
        try:
            # 删除元数据和消息
            meta_key = f"session:{session_id}:meta"
            messages_key = f"session:{session_id}:messages"
            self.redis_client.delete(meta_key, messages_key)

            # 从活跃索引中移除
            active_key = "sessions:active"
            self.redis_client.zrem(active_key, session_id)

            return True

        except Exception as e:
            # Redis 连接失败时提示用户
            print(f"[警告] Redis 连接失败，无法删除会话: {e}")
            return False

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话

        Returns:
            清理的会话数量
        """
        try:
            active_key = "sessions:active"
            current_time = time.time()
            timeout = 3600  # 1小时

            # 获取所有会话
            all_sessions = self.redis_client.zrange(
                active_key, 0, -1, withscores=True
            )

            expired_count = 0
            for session_id, last_active in all_sessions:
                if current_time - last_active > timeout:
                    self.delete_session(session_id)
                    expired_count += 1

            return expired_count

        except Exception as e:
            # Redis 连接失败时提示用户
            print(f"[警告] Redis 连接失败，无法清理过期会话: {e}")
            return 0

    def close(self):
        """关闭 Redis 连接"""
        if self.redis_client:
            try:
                self.redis_client.close()
            except Exception as e:
                print(f"[Redis] 关闭连接时出错: {e}")
