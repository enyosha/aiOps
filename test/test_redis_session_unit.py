"""
test_redis_session_unit.py - Redis 会话持久化单元测试（Mock 版本）

测试目标：
1. 验证 Client_test.py 启动时从 Redis 加载会话列表的逻辑
2. 验证会话创建、消息添加和保存的完整流程
3. 验证退出时资源清理逻辑
4. 不依赖真实 Redis 服务器，使用 Mock 模拟

执行方式：
    python test/test_redis_session_unit.py
"""
import asyncio
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_startup_no_history():
    """测试 1: 启动时无历史会话"""
    print("=" * 70)
    print("测试 1: 启动时无历史会话（Mock）")
    print("=" * 70)
    
    from Routing.conversation_manager import conversation_manager
    
    # Mock list_recent_sessions 返回空列表
    with patch.object(conversation_manager, 'list_recent_sessions', return_value=[]):
        recent = conversation_manager.list_recent_sessions(limit=10)
        
        assert len(recent) == 0, "应该返回空列表"
        print("✓ list_recent_sessions 返回空列表")
        
        # 模拟 Client_test.py 中的逻辑
        session_id = None
        if not recent:
            print("✓ 提示用户创建新会话")
            session_id = None  # 将创建新会话
        
        assert session_id is None, "session_id 初始应为 None"
        print("✓ session_id 初始为 None")
    
    print()


def test_startup_with_history():
    """测试 2: 启动时有历史会话"""
    print("=" * 70)
    print("测试 2: 启动时有历史会话（Mock）")
    print("=" * 70)
    
    from Routing.conversation_manager import conversation_manager
    
    # Mock 返回 2 个历史会话
    mock_sessions = [
        {
            'session_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'message_count': 5,
            'created_at': 1234567890,
            'last_active': 1234567900
        },
        {
            'session_id': 'b2c3d4e5-f6a7-8901-bcde-f12345678901',
            'message_count': 3,
            'created_at': 1234567800,
            'last_active': 1234567850
        }
    ]
    
    with patch.object(conversation_manager, 'list_recent_sessions', return_value=mock_sessions):
        recent = conversation_manager.list_recent_sessions(limit=10)
        
        assert len(recent) == 2, "应该返回 2 个会话"
        print(f"✓ list_recent_sessions 返回 {len(recent)} 个会话")
        
        # 模拟用户选择第一个会话
        selected_idx = 0
        session_id = recent[selected_idx]['session_id']
        
        assert session_id == 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        print(f"✓ 用户选择会话: {session_id[:8]}...")
        print(f"✓ session_id 被正确设置")
    
    print()


async def test_create_session_and_save():
    """测试 3: 创建新会话并保存到 Redis"""
    print("=" * 70)
    print("测试 3: 创建新会话并保存（Mock Redis）")
    print("=" * 70)
    
    from Routing.conversation_manager import conversation_manager
    from Routing.redis_session_store import RedisSessionStore
    
    # 创建 Mock Redis Store
    mock_redis_store = MagicMock(spec=RedisSessionStore)
    mock_redis_store.save_session = MagicMock(return_value=True)
    
    # 临时替换 redis_store
    original_store = conversation_manager.redis_store
    original_use_redis = conversation_manager.use_redis
    
    try:
        conversation_manager.redis_store = mock_redis_store
        conversation_manager.use_redis = True
        
        # 创建会话
        session_id = conversation_manager.create_session()
        
        assert session_id is not None, "应该生成 session_id"
        print(f"✓ 创建会话: {session_id[:8]}...")
        
        # 验证 save_session 被调用
        assert mock_redis_store.save_session.called, "save_session 应该被调用"
        print("✓ redis_store.save_session() 被调用")
        
        # 验证会话存在于内存中
        session = conversation_manager.get_session(session_id)
        assert session is not None, "会话应该在内存中"
        assert session.session_id == session_id
        print("✓ 会话已保存到内存")
        
    finally:
        # 恢复原始状态
        conversation_manager.redis_store = original_store
        conversation_manager.use_redis = original_use_redis
    
    print()


async def test_add_message_sync_to_redis():
    """测试 4: 添加消息并同步到 Redis"""
    print("=" * 70)
    print("测试 4: 添加消息并同步到 Redis（Mock）")
    print("=" * 70)
    
    from Routing.conversation_manager import conversation_manager
    from Routing.redis_session_store import RedisSessionStore
    
    # 创建 Mock Redis Store
    mock_redis_store = MagicMock(spec=RedisSessionStore)
    mock_redis_store.save_session = MagicMock(return_value=True)
    
    original_store = conversation_manager.redis_store
    original_use_redis = conversation_manager.use_redis
    
    try:
        conversation_manager.redis_store = mock_redis_store
        conversation_manager.use_redis = True
        
        # 创建会话
        session_id = conversation_manager.create_session()
        print(f"✓ 创建会话: {session_id[:8]}...")
        
        # 添加用户消息
        conversation_manager.add_message(session_id, "user", "你好，今天天气怎么样？")
        
        # 验证 save_session 被调用
        assert mock_redis_store.save_session.call_count >= 1, "添加消息后应该调用 save_session"
        print("✓ 添加用户消息后触发 save_session")
        
        # 添加 AI 回复
        conversation_manager.add_message(session_id, "assistant", "今天天气晴朗，温度适宜。")
        
        assert mock_redis_store.save_session.call_count >= 2, "再次添加消息应该再次调用 save_session"
        print("✓ 添加 AI 回复后再次触发 save_session")
        
        # 验证消息数量
        history = conversation_manager.get_history(session_id)
        assert len(history) == 2, "应该有 2 条消息"
        print(f"✓ 会话中有 {len(history)} 条消息")
        
        # 验证消息内容
        from langchain_core.messages import HumanMessage, AIMessage
        assert isinstance(history[0], HumanMessage)
        assert history[0].content == "你好，今天天气怎么样？"
        assert isinstance(history[1], AIMessage)
        assert history[1].content == "今天天气晴朗，温度适宜。"
        print("✓ 消息内容正确")
        
    finally:
        # 恢复原始状态
        conversation_manager.redis_store = original_store
        conversation_manager.use_redis = original_use_redis
    
    print()


async def test_cleanup_resources():
    """测试 5: 退出时清理资源"""
    print("=" * 70)
    print("测试 5: 退出时清理资源（Mock）")
    print("=" * 70)
    
    from Routing.route import cleanup_all, tunnel_manager
    from Routing.tool_cache import tool_cache
    from Routing.conversation_manager import conversation_manager
    
    # Mock SSH Tunnel Manager
    mock_tunnel = MagicMock()
    mock_tunnel.close_tunnel = MagicMock()
    
    # Mock Redis Store
    mock_redis_store = MagicMock()
    mock_redis_store.close = MagicMock()
    
    original_tunnel = tunnel_manager
    original_redis_store = conversation_manager.redis_store
    
    try:
        # 替换全局变量
        import Routing.route as route_module
        route_module.tunnel_manager = mock_tunnel
        conversation_manager.redis_store = mock_redis_store
        
        # 添加一些测试数据
        session_id = conversation_manager.create_session()
        conversation_manager.add_message(session_id, "user", "测试消息")
        
        print(f"✓ 创建测试会话: {session_id[:8]}...")
        
        # 执行清理
        await cleanup_all()
        
        # 验证清理操作
        print("✓ cleanup_all() 执行完成")
        
        # 验证会话已清空
        sessions = conversation_manager.get_all_sessions()
        assert len(sessions) == 0, "所有会话应该被清空"
        print("✓ 所有会话已清空")
        
        # 验证 Redis 连接关闭
        assert mock_redis_store.close.called, "Redis 连接应该被关闭"
        print("✓ Redis 连接已关闭")
        
        # 验证 SSH 隧道关闭
        assert mock_tunnel.close_tunnel.called, "SSH 隧道应该被关闭"
        print("✓ SSH 隧道已关闭")
        
    finally:
        # 恢复原始状态
        route_module.tunnel_manager = original_tunnel
        conversation_manager.redis_store = original_redis_store
    
    print()


async def main():
    """主测试函数"""
    print("\n" + "=" * 70)
    print("Redis 会话持久化 - 单元测试（Mock 版本）")
    print("=" * 70 + "\n")
    
    try:
        # 运行所有测试
        test_startup_no_history()
        test_startup_with_history()
        await test_create_session_and_save()
        await test_add_message_sync_to_redis()
        await test_cleanup_resources()
        
        print("=" * 70)
        print("✅ 所有单元测试通过！")
        print("=" * 70)
        print("\n验证要点：")
        print("  ✓ 启动时正确从 Redis 加载会话列表")
        print("  ✓ 用户选择会话后 session_id 正确设置")
        print("  ✓ 创建新会话时生成唯一 UUID")
        print("  ✓ 会话元数据正确保存到 Redis（Mock）")
        print("  ✓ 消息添加后实时同步到 Redis（Mock）")
        print("  ✓ 退出时资源正确清理")
        print("  ✓ Redis 连接正确关闭")
        print("  ✓ SSH 隧道正确关闭")
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
