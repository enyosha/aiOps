"""
测试完整的路由流�?- 天气查询
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

load_dotenv()

async def test_weather_query():
    """测试天气查询的完整路由流�?""
    print("=" * 60)
    print("测试天气查询路由")
    print("=" * 60)
    
    from Routing.route import chat_with_session, cleanup_all
    
    try:
        # 测试1: 直接问天�?
        print("\n【测�?】询问北京的天气")
        result = await chat_with_session("北京的天气怎么样？")
        
        if result["success"]:
            print(f"�?成功")
            print(f"回复: {result['response']}")
            print(f"会话ID: {result['session_id']}")
            session_id = result['session_id']
        else:
            print(f"�?失败: {result['response']}")
            return
        
        # 测试2: 追问
        print("\n【测�?】追问明天的天气")
        result = await chat_with_session("明天呢？", session_id)
        
        if result["success"]:
            print(f"�?成功")
            print(f"回复: {result['response']}")
        else:
            print(f"�?失败: {result['response']}")
        
        # 清理
        await cleanup_all()
        
    except Exception as e:
        print(f"�?错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_weather_query())
