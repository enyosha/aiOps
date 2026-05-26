"""
测试amap MCP连接和工具加�?
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

load_dotenv()

async def test_amap_connection():
    """测试amap MCP连接"""
    print("=" * 60)
    print("测试 amap MCP 连接")
    print("=" * 60)
    
    # 检查环境变�?
    api_key = os.getenv("AMAP_API_KEY")
    print(f"AMAP_API_KEY: {api_key[:10]}..." if api_key else "AMAP_API_KEY: 未设�?)
    
    if not api_key:
        print("�?错误: AMAP_API_KEY 未设�?)
        return
    
    # 测试工具缓存加载
    from utils.tool_cache import tool_cache
    
    try:
        print("\n正在加载 amap 工具...")
        tools = await tool_cache.get_tools("amap-maps-streamableHTTP")
        print(f"�?成功加载 {len(tools)} 个工�?)
        
        for i, tool in enumerate(tools):
            print(f"  工具 {i+1}: {tool.name}")
            if hasattr(tool, 'description'):
                print(f"    描述: {tool.description[:100]}...")
        
        # 测试调用一个工具（例如获取天气�?
        if tools:
            print("\n测试调用天气工具...")
            weather_tool = None
            for tool in tools:
                if 'weather' in tool.name.lower() or '天气' in str(tool.description):
                    weather_tool = tool
                    break
            
            if weather_tool:
                print(f"找到天气工具: {weather_tool.name}")
                # 尝试调用（需要城市参数）
                try:
                    result = await weather_tool.ainvoke({"city": "北京"})
                    print(f"天气工具返回: {result}")
                except Exception as e:
                    print(f"天气工具调用失败: {e}")
            else:
                print("未找到天气相关工�?)
                
    except Exception as e:
        print(f"�?加载工具失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_amap_connection())
