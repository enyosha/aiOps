"""
test.py - 支持循环对话的测试客户端

功能：
1. 支持连续提问，保持会话上下文
2. 显示工具缓存状态
3. 提供会话管理命令
4. 支持从 Redis 加载历史会话
"""
import os
import sys
import io
import time
import signal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio

# 添加项目根目录到Python路径，以便正确导入模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入新的聊天 API
from Routing.route import chat_with_session, clear_session, get_session_info, cleanup_all
from Routing.conversation_manager import conversation_manager


def signal_handler(sig, frame):
    """处理 Ctrl+C 信号"""
    print("\n\n⚠️ 检测到中断信号，正在清理资源...")
    raise KeyboardInterrupt()


# 注册信号处理器（双重保障）
try:
    signal.signal(signal.SIGINT, signal_handler)
except (ValueError, OSError):
    # 在某些环境下可能无法注册信号处理器（如非主线程）
    pass


async def main():
    """主函数 - 支持循环对话"""
    print("=" * 70)
    print("AI Assistant - 循环对话模式")
    print("=" * 70)

    # 显示最近的会话列表
    recent_sessions = conversation_manager.list_recent_sessions(limit=10)

    if recent_sessions:
        print("\n📋 最近的会话历史：")
        print("-" * 70)
        for idx, sess in enumerate(recent_sessions, 1):
            created_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sess['created_at']))
            session_id = sess['session_id']
            print(f"{idx}. Session ID: {session_id}")
            print(f"   消息数: {sess['message_count']} | 创建时间: {created_time}")
        print("-" * 70)

        # 询问用户选择
        choice = input("\n请选择会话（输入编号 / 'new' 创建新会话 / 直接输入 Session ID）: ").strip()

        if choice.lower() == 'new':
            session_id = None
            print("\n✅ 将创建新会话")
        elif choice.isdigit() and 1 <= int(choice) <= len(recent_sessions):
            selected_idx = int(choice) - 1
            session_id = recent_sessions[selected_idx]['session_id']
            print(f"\n✅ 已加载会话: {session_id}")
        else:
            # 尝试直接输入 session_id
            session_id = choice if len(choice) > 0 else None
            if session_id:
                print(f"\n✅ 尝试加载会话: {session_id}")
    else:
        print("\nℹ️  没有找到历史会话，将创建新会话")
        session_id = None

    print("\n" + "=" * 70)
    print("💡 使用提示：")
    print("  • 直接输入问题开始对话")
    print("  • 输入 'quit' 或 'exit' 退出程序")
    print("  • 输入 'clear' 清空当前会话历史")
    print("  • 输入 'info' 查看会话信息")
    print("  • 输入 'stats' 查看工具缓存统计")
    print("  • 输入 'help' 显示此帮助信息")
    print("=" * 70)
    
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

        # 关闭 Redis 连接
        if hasattr(conversation_manager, 'redis_store') and conversation_manager.redis_store:
            conversation_manager.redis_store.close()
            print("[Client] Redis 连接已关闭")

        # 关闭 SSH 隧道
        from Routing.route import tunnel_manager
        if tunnel_manager:
            tunnel_manager.close_tunnel()
            print("[Client] SSH 隧道已关闭")


if __name__ == "__main__":
    from dotenv import load_dotenv
    from Routing.route import initialize_redis_and_tunnel
    
    # 加载环境变量
    load_dotenv()
    
    # 初始化 Redis 和 SSH 隧道
    asyncio.run(initialize_redis_and_tunnel())
    
    # 运行主程序
    asyncio.run(main())
