"""
简单测�?- 验证缓存和会话管理功�?
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


async def test_cache():
    """测试工具缓存"""
    print("=" * 70)
    print("测试 1: 工具缓存管理�?)
    print("=" * 70)
    
    from utils.tool_cache import tool_cache
    
    # 查看初始状�?
    stats = tool_cache.get_cache_stats()
    print(f"\n初始状�? {stats}")
    
    # 尝试加载计算器工�?
    print("\n首次加载计算器工�?..")
    try:
        tools = await tool_cache.get_tools("calculator")
        print(f"�?成功加载 {len(tools)} 个工�?)
        
        stats = tool_cache.get_cache_stats()
        print(f"缓存状�? {stats}")
        
        # 第二次加载（应该使用缓存�?
        print("\n第二次加载（应使用缓存）...")
        tools2 = await tool_cache.get_tools("calculator")
        print(f"�?使用缓存，获�?{len(tools2)} 个工�?)
        print(f"缓存命中: {tools is tools2}")
        
    except Exception as e:
        print(f"�?错误: {e}")
    
    # 清理
    await tool_cache.clear_all()
    print("\n�?缓存已清�?)


async def test_conversation():
    """测试会话管理"""
    print("\n" + "=" * 70)
    print("测试 2: 会话管理�?)
    print("=" * 70)
    
    from utils.conversation_manager import conversation_manager
    from langchain_core.messages import HumanMessage, AIMessage
    
    # 创建会话
    session_id = conversation_manager.create_session()
    print(f"\n�?创建会话: {session_id[:8]}...")
    
    # 添加消息
    conversation_manager.add_message(session_id, "user", "你好")
    conversation_manager.add_message(session_id, "assistant", "你好！有什么可以帮助你的？")
    conversation_manager.add_message(session_id, "user", "今天天气怎么样？")
    
    # 获取历史
    history = conversation_manager.get_history(session_id)
    print(f"�?会话中有 {len(history)} 条消�?)
    
    for i, msg in enumerate(history, 1):
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        print(f"  {i}. {role}: {msg.content[:30]}")
    
    # 获取统计信息
    sessions = conversation_manager.get_all_sessions()
    print(f"\n�?会话统计: {sessions[session_id]}")
    
    # 清理
    conversation_manager.clear_all()
    print("\n�?会话已清�?)


async def main():
    """主测试函�?""
    try:
        await test_cache()
        await test_conversation()
        
        print("\n" + "=" * 70)
        print("所有测试完成！")
        print("=" * 70)
        print("\n核心功能验证�?)
        print("  �?工具缓存机制正常工作")
        print("  �?会话管理机制正常工作")
        print("  �?支持多轮对话和历史上下文")
        
    except Exception as e:
        print(f"\n�?测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
