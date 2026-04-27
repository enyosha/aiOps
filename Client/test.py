"""
test.py - 支持循环对话的测试客户端

功能：
1. 支持连续提问，保持会话上下文
2. 显示工具缓存状态
3. 提供会话管理命令
"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio

# 添加项目根目录到Python路径，以便正确导入模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入新的聊天 API
from Routing.route import chat_with_session, clear_session, get_session_info, cleanup_all


async def main():
    """主函数 - 支持循环对话"""
    print("=" * 70)
    print("AI Assistant - 循环对话模式")
    print("=" * 70)
    print("\n💡 使用提示：")
    print("  • 直接输入问题开始对话")
    print("  • 输入 'quit' 或 'exit' 退出程序")
    print("  • 输入 'clear' 清空当前会话历史")
    print("  • 输入 'info' 查看会话信息")
    print("  • 输入 'stats' 查看工具缓存统计")
    print("  • 输入 'help' 显示此帮助信息")
    print("\n" + "=" * 70)
    
    session_id = None
    
    try:
        while True:
            # 获取用户输入
            try:
                user_input = input("\n👤 您: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n再见！")
                break
            
            if not user_input:
                continue
            
            # 检查命令
            cmd = user_input.lower()
            
            if cmd in ['quit', 'exit', 'q']:
                print("\n👋 再见！")
                break
            
            if cmd == 'help':
                print("\n" + "=" * 70)
                print("💡 使用提示：")
                print("  • 直接输入问题开始对话")
                print("  • 输入 'quit' 或 'exit' 退出程序")
                print("  • 输入 'clear' 清空当前会话历史")
                print("  • 输入 'info' 查看会话信息")
                print("  • 输入 'stats' 查看工具缓存统计")
                print("  • 输入 'help' 显示此帮助信息")
                print("=" * 70)
                continue
            
            if cmd == 'clear':
                if session_id:
                    await clear_session(session_id)
                    print("✅ 会话历史已清空")
                else:
                    print("⚠️ 当前没有活跃的会话")
                continue
            
            if cmd == 'info':
                if session_id:
                    info = await get_session_info(session_id)
                    if info["exists"]:
                        stats = info["stats"]
                        print(f"\n📊 会话信息:")
                        print(f"   会话 ID: {stats['session_id']}")
                        print(f"   消息数量: {stats['message_count']}")
                        print(f"   持续时间: {stats['duration_seconds']:.0f} 秒")
                    else:
                        print("❌ 会话不存在")
                else:
                    print("⚠️ 当前没有活跃的会话")
                continue
            
            if cmd == 'stats':
                from Routing.tool_cache import tool_cache
                cache_stats = tool_cache.get_cache_stats()
                print(f"\n📦 工具缓存统计:")
                print(f"   缓存服务器: {cache_stats['cached_servers']}")
                print(f"   缓存数量: {cache_stats['cache_count']}")
                print(f"   活跃会话: {cache_stats['active_sessions']}")
                continue
            
            # 正常对话处理
            print("\n🤖 AI 思考中...", end="", flush=True)
            
            result = await chat_with_session(user_input, session_id)
            
            # 更新会话 ID
            if session_id is None:
                session_id = result["session_id"]
            
            # 显示结果
            if result["success"]:
                print(f"\r🤖 AI: {result['response']}")
                
                # 显示缓存命中信息
                if result["cache_stats"]["cache_count"] > 0:
                    print(f"   📦 [工具缓存命中: {result['cache_stats']['cache_count']} 个服务器]")
            else:
                print(f"\r❌ 错误: {result['response']}")
    
    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
    
    finally:
        # 清理资源
        await cleanup_all()


if __name__ == "__main__":
    asyncio.run(main())
