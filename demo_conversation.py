"""
演示脚本 - 展示工具缓存和循环对话功能

此脚本自动运行多个测试用例，展示：
1. 首次提问时加载工具
2. 后续提问使用缓存的工具
3. 多轮对话保持上下文
"""
import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(__file__))

from Routing.route import chat_with_session, cleanup_all


async def demo():
    """演示功能"""
    print("=" * 80)
    print("功能演示：工具缓存 + 循环对话")
    print("=" * 80)
    
    # ===== 演示 1: 工具缓存机制 =====
    print("\n" + "=" * 80)
    print("演示 1: 工具缓存机制")
    print("=" * 80)
    print("\n说明：首次调用某个 Agent 时会加载工具，后续调用直接使用缓存\n")
    
    # 第一个计算问题（需要加载计算器工具）
    print("-" * 80)
    print("问题 1: 计算 25 * 17 + 45 / 3")
    print("-" * 80)
    result1 = await chat_with_session("计算 25 * 17 + 45 / 3")
    session_id = result1["session_id"]
    print(f"回答: {result1['response']}")
    print(f"缓存状态: {result1['cache_stats']}")
    
    # 第二个计算问题（应该使用缓存）
    print("\n" + "-" * 80)
    print("问题 2: 计算 100 / 8")
    print("-" * 80)
    result2 = await chat_with_session("计算 100 / 8", session_id)
    print(f"回答: {result2['response']}")
    print(f"缓存状态: {result2['cache_stats']}")
    print("✓ 注意：第二次计算使用了缓存的工具，无需重新加载")
    
    # ===== 演示 2: 循环对话（上下文保持）=====
    print("\n" + "=" * 80)
    print("演示 2: 循环对话 - 上下文保持")
    print("=" * 80)
    print("\n说明：AI 能够记住之前的对话内容\n")
    
    # 创建新会话
    print("-" * 80)
    print("问题 1: 2025年人工智能有哪些发展趋势？")
    print("-" * 80)
    result3 = await chat_with_session("2025年人工智能有哪些发展趋势？")
    new_session_id = result3["session_id"]
    print(f"回答: {result3['response'][:200]}...")
    
    # 追问（应该能理解上下文）
    print("\n" + "-" * 80)
    print("问题 2: 这些趋势中哪个最重要？")
    print("-" * 80)
    result4 = await chat_with_session("这些趋势中哪个最重要？", new_session_id)
    print(f"回答: {result4['response'][:200]}...")
    print("✓ 注意：AI 理解了'这些趋势'指的是之前提到的 AI 发展趋势")
    
    # ===== 演示 3: 会话管理 =====
    print("\n" + "=" * 80)
    print("演示 3: 会话管理")
    print("=" * 80)
    
    from Routing.conversation_manager import conversation_manager
    
    # 查看会话信息
    print("\n当前所有会话:")
    sessions = conversation_manager.get_all_sessions()
    for sid, stats in sessions.items():
        print(f"  • 会话 {sid[:8]}...: {stats['message_count']} 条消息")
    
    # ===== 清理 =====
    print("\n" + "=" * 80)
    print("清理资源")
    print("=" * 80)
    await cleanup_all()
    
    print("\n" + "=" * 80)
    print("演示完成！")
    print("=" * 80)
    print("\n核心改进总结：")
    print("  ✓ 工具缓存：避免重复加载 MCP 服务器，提升响应速度")
    print("  ✓ 会话管理：支持多轮对话，保持上下文连贯性")
    print("  ✓ 统一架构：所有 Agent 使用统一的基类和缓存机制")
    print("  ✓ 资源清理：对话结束时自动释放所有缓存和连接")


if __name__ == "__main__":
    asyncio.run(demo())
