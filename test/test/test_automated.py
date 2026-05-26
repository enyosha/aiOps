"""
自动化测试脚�?- 模拟用户输入
"""
import asyncio
import sys
from io import StringIO
from unittest.mock import patch

# 添加项目根目录到Python路径
sys.path.insert(0, '.')

async def automated_test():
    """自动化测试天气查�?""
    from Routing.route import chat_with_session, cleanup_all
    
    print("=" * 70)
    print("自动化测�?- 天气查询")
    print("=" * 70)
    
    test_cases = [
        ("北京的天气怎么样？", "测试1: 查询北京天气"),
        ("上海明天会下雨吗�?, "测试2: 查询上海天气"),
        ("今天气温多少度？", "测试3: 追问气温"),
    ]
    
    session_id = None
    
    for user_input, description in test_cases:
        print(f"\n{description}")
        print(f"用户: {user_input}")
        
        result = await chat_with_session(user_input, session_id)
        
        if session_id is None:
            session_id = result["session_id"]
        
        if result["success"]:
            print(f"AI: {result['response'][:200]}...")
            if result["cache_stats"]["cache_count"] > 0:
                print(f"   📦 [工具缓存命中: {result['cache_stats']['cache_count']} 个服务器]")
        else:
            print(f"�?错误: {result['response']}")
    
    # 清理
    await cleanup_all()
    print("\n" + "=" * 70)
    print("测试完成�?)
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(automated_test())
