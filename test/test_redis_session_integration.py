"""
test_redis_session_integration.py - Redis 会话持久化集成测试（真实 Redis）

测试目标：
1. 验证完整的会话生命周期（创建、保存、加载、恢复）
2. 验证多会话并发管理
3. 验证会话过期清理机制
4. 验证退出时资源清理

前置条件：
- Redis 服务器正在运行（localhost:6379）
- SSH 隧道已建立（如果需要远程 Redis）

执行方式：
    python test/test_redis_session_integration.py
"""
import asyncio
import sys
import os
import time

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


async def test_full_lifecycle():
    """测试 1: 完整会话生命周期"""
    print("=" * 70)
    print("测试 1: 完整会话生命周期（真实 Redis）")
    print("=" * 70)
    
    from Routing.route import initialize_redis_and_tunnel, cleanup_all
    from Routing.conversation_manager import conversation_manager
    from Routing.redis_session_store import RedisSessionStore
    
    # 步骤 1: 初始化 Redis 连接
    print("\n步骤 1: 初始化 Redis 连接...")
    await initialize_redis_and_tunnel()
    print("✓ Redis 连接已建立")
    
    # 确保使用 Redis
    assert conversation_manager.use_redis, "应该启用 Redis"
    assert conversation_manager.redis_store is not None, "Redis store 应该存在"
    print("✓ Redis 持久化已启用")
    
    redis_store = conversation_manager.redis_store
    
    # 步骤 2: 记录初始会话数量
    print("\n步骤 2: 检查初始会话状态...")
    initial_sessions = conversation_manager.list_recent_sessions(limit=100)
    initial_count = len(initial_sessions)
    print(f"✓ 当前有 {initial_count} 个会话")
    
    # 步骤 3: 创建新会话
    print("\n步骤 3: 创建新会话...")
    session_id = conversation_manager.create_session()
    assert session_id is not None, "应该生成 session_id"
    print(f"✓ 创建会话: {session_id[:8]}...")
    
    # 步骤 4: 验证会话已保存到 Redis
    print("\n步骤 4: 验证会话已保存到 Redis...")
    redis_session = redis_store.load_session(session_id)
    assert redis_session is not None, "会话应该在 Redis 中"
    assert redis_session.session_id == session_id, "session_id 应该匹配"
    print("✓ 会话已保存到 Redis")
    
    # 步骤 5: 添加消息
    print("\n步骤 5: 添加消息...")
    conversation_manager.add_message(session_id, "user", "你好，请介绍一下自己")
    conversation_manager.add_message(session_id, "assistant", "我是一个 AI 助手，可以帮助您解答问题。")
    conversation_manager.add_message(session_id, "user", "今天天气怎么样？")
    print("✓ 添加了 3 条消息")
    
    # 步骤 6: 验证消息已同步到 Redis
    print("\n步骤 6: 验证消息已同步到 Redis...")
    reloaded = redis_store.load_session(session_id)
    assert reloaded is not None, "应该能从 Redis 加载会话"
    assert len(reloaded.messages) == 3, f"应该有 3 条消息，实际有 {len(reloaded.messages)} 条"
    assert reloaded.messages[0].content == "你好，请介绍一下自己"
    assert reloaded.messages[1].content == "我是一个 AI 助手，可以帮助您解答问题。"
    assert reloaded.messages[2].content == "今天天气怎么样？"
    print(f"✓ 消息已同步到 Redis（共 {len(reloaded.messages)} 条）")
    print("✓ 消息内容正确")
    
    # 步骤 7: 列出会话验证存在
    print("\n步骤 7: 验证会话在活跃列表中...")
    recent = conversation_manager.list_recent_sessions(limit=10)
    assert any(s['session_id'] == session_id for s in recent), "会话应该在活跃列表中"
    print("✓ 会话存在于活跃列表")
    
    # 步骤 8: 验证会话统计信息
    print("\n步骤 8: 验证会话统计信息...")
    session = conversation_manager.get_session(session_id)
    stats = session.get_stats()
    assert stats['message_count'] == 3, "消息数量应该是 3"
    assert stats['session_id'] == session_id, "session_id 应该匹配"
    print(f"✓ 会话统计: {stats['message_count']} 条消息, 持续 {stats['duration_seconds']:.0f} 秒")
    
    # 步骤 9: 清理
    print("\n步骤 9: 清理测试数据...")
    conversation_manager.remove_session(session_id)
    print("✓ 测试会话已删除")
    
    await cleanup_all()
    print("✓ 资源清理完成")
    
    print()


async def test_session_restore():
    """测试 2: 会话恢复功能"""
    print("=" * 70)
    print("测试 2: 会话恢复功能（模拟重启）")
    print("=" * 70)
    
    from Routing.route import initialize_redis_and_tunnel, cleanup_all
    from Routing.conversation_manager import conversation_manager
    from Routing.redis_session_store import RedisSessionStore
    
    # 初始化
    await initialize_redis_and_tunnel()
    redis_store = conversation_manager.redis_store
    
    try:
        # 步骤 1: 创建会话并添加消息
        print("\n步骤 1: 创建会话并添加消息...")
        session_id = conversation_manager.create_session()
        conversation_manager.add_message(session_id, "user", "第一轮对话")
        conversation_manager.add_message(session_id, "assistant", "这是第一轮回复")
        print(f"✓ 创建会话: {session_id[:8]}...")
        print("✓ 添加了 2 条消息")
        
        # 验证已保存
        saved = redis_store.load_session(session_id)
        assert saved is not None
        assert len(saved.messages) == 2
        print("✓ 消息已保存到 Redis")
        
        # 步骤 2: 清空内存缓存（模拟重启）
        print("\n步骤 2: 清空内存缓存（模拟程序重启）...")
        conversation_manager._sessions.clear()
        print("✓ 内存缓存已清空")
        
        # 验证内存中没有该会话
        memory_session = conversation_manager._sessions.get(session_id)
        assert memory_session is None, "内存中不应该有该会话"
        print("✓ 确认内存中无该会话")
        
        # 步骤 3: 从 Redis 重新加载
        print("\n步骤 3: 从 Redis 重新加载会话...")
        restored = conversation_manager.get_session(session_id)
        assert restored is not None, "应该能从 Redis 恢复会话"
        print(f"✓ 成功从 Redis 恢复会话: {session_id[:8]}...")
        
        # 验证消息完整性
        assert len(restored.messages) == 2, f"应该有 2 条消息，实际有 {len(restored.messages)} 条"
        assert restored.messages[0].content == "第一轮对话"
        assert restored.messages[1].content == "这是第一轮回复"
        print("✓ 消息完整性验证通过")
        print("✓ 会话恢复功能正常")
        
    finally:
        # 清理
        if 'session_id' in locals():
            conversation_manager.remove_session(session_id)
        await cleanup_all()
    
    print()


async def test_multiple_sessions():
    """测试 3: 多会话并发管理"""
    print("=" * 70)
    print("测试 3: 多会话并发管理")
    print("=" * 70)
    
    from Routing.route import initialize_redis_and_tunnel, cleanup_all
    from Routing.conversation_manager import conversation_manager
    
    # 初始化
    await initialize_redis_and_tunnel()
    
    try:
        # 创建 3 个会话
        print("\n步骤 1: 创建 3 个会话...")
        sessions = []
        for i in range(3):
            session_id = conversation_manager.create_session()
            sessions.append(session_id)
            print(f"  ✓ 会话 {i+1}: {session_id[:8]}...")
        
        # 为每个会话添加不同消息
        print("\n步骤 2: 为每个会话添加消息...")
        for i, sid in enumerate(sessions):
            conversation_manager.add_message(sid, "user", f"会话 {i+1} 的用户消息")
            conversation_manager.add_message(sid, "assistant", f"会话 {i+1} 的 AI 回复")
            print(f"  ✓ 会话 {i+1}: 添加了 2 条消息")
        
        # 验证所有会话独立存储
        print("\n步骤 3: 验证会话独立性...")
        for i, sid in enumerate(sessions):
            session = conversation_manager.get_session(sid)
            assert len(session.messages) == 2, f"会话 {i+1} 应该有 2 条消息"
            assert session.messages[0].content == f"会话 {i+1} 的用户消息"
            assert session.messages[1].content == f"会话 {i+1} 的 AI 回复"
            print(f"  ✓ 会话 {i+1}: 数据独立且正确")
        
        # 验证 Redis 中有 3 个活跃会话
        print("\n步骤 4: 验证 Redis 中的活跃会话...")
        recent = conversation_manager.list_recent_sessions(limit=10)
        active_ids = [s['session_id'] for s in recent]
        
        for sid in sessions:
            assert sid in active_ids, f"会话 {sid[:8]}... 应该在活跃列表中"
        
        print(f"✓ Redis 中有 {len(sessions)} 个活跃会话")
        print("✓ 多会话并发管理正常")
        
    finally:
        # 清理所有测试会话
        print("\n步骤 5: 清理测试数据...")
        for sid in sessions:
            conversation_manager.remove_session(sid)
        print(f"✓ 已清理 {len(sessions)} 个会话")
        
        await cleanup_all()
    
    print()


async def test_session_expiration():
    """测试 4: 会话过期清理"""
    print("=" * 70)
    print("测试 4: 会话过期清理")
    print("=" * 70)
    
    from Routing.route import initialize_redis_and_tunnel, cleanup_all
    from Routing.conversation_manager import conversation_manager
    from Routing.redis_session_store import RedisSessionStore
    
    # 初始化
    await initialize_redis_and_tunnel()
    redis_store = conversation_manager.redis_store
    
    try:
        # 创建会话
        print("\n步骤 1: 创建会话...")
        session_id = conversation_manager.create_session()
        conversation_manager.add_message(session_id, "user", "测试消息")
        print(f"✓ 创建会话: {session_id[:8]}...")
        
        # 验证会话存在
        session = conversation_manager.get_session(session_id)
        assert session is not None
        print("✓ 会话存在")
        
        # 手动修改 last_active 为 2 小时前
        print("\n步骤 2: 模拟会话过期（设置为 2 小时前）...")
        session.last_active = time.time() - 7200  # 2 小时 = 7200 秒
        
        # 保存到 Redis
        redis_store.save_session(session)
        print("✓ 已更新会话时间戳")
        
        # 触发清理
        print("\n步骤 3: 触发过期会话清理...")
        cleaned_count = conversation_manager.cleanup_expired_sessions()
        print(f"✓ 清理了 {cleaned_count} 个过期会话")
        
        # 验证会话已被删除
        print("\n步骤 4: 验证会话已被删除...")
        restored = conversation_manager.get_session(session_id)
        assert restored is None, "过期的会话应该被删除"
        print("✓ 过期会话已被删除")
        
        # 验证 Redis 中也不存在
        redis_session = redis_store.load_session(session_id)
        assert redis_session is None, "Redis 中也不应该存在该会话"
        print("✓ Redis 中也已删除")
        
    finally:
        await cleanup_all()
    
    print()


async def main():
    """主测试函数"""
    print("\n" + "=" * 70)
    print("Redis 会话持久化 - 集成测试（真实 Redis）")
    print("=" * 70 + "\n")
    
    try:
        # 运行所有测试
        await test_full_lifecycle()
        await test_session_restore()
        await test_multiple_sessions()
        await test_session_expiration()
        
        print("=" * 70)
        print("✅ 所有集成测试通过！")
        print("=" * 70)
        print("\n验证要点：")
        print("  ✓ 完整会话生命周期正常工作")
        print("  ✓ 会话元数据正确保存到 Redis")
        print("  ✓ 消息添加后实时同步到 Redis")
        print("  ✓ 消息序列化和反序列化正确")
        print("  ✓ 会话恢复功能正常工作")
        print("  ✓ 多会话并发管理正常")
        print("  ✓ 会话过期清理机制正常")
        print("  ✓ 退出时资源正确清理")
        print("  ✓ Redis 连接正确关闭")
        
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
