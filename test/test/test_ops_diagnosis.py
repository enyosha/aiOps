"""
OpsAgent 简单测试脚�?
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_search():
    """测试知识检�?""
    print("\n" + "="*70)
    print("测试: 知识检�?)
    print("="*70)
    
    from utils.tool_cache import tool_cache
    
    tools = await tool_cache.get_tools("ops-diagnosis")
    search_tool = next((t for t in tools if t.name == "search_ops_knowledge"), None)
    
    if not search_tool:
        print("�?未找�?search_ops_knowledge 工具")
        return False
    
    result = await search_tool.ainvoke({"query": "502 Bad Gateway error", "top_k": 2})
    
    print(f"\nQuery: '502 Bad Gateway error'")
    print(f"Result type: {type(result)}")
    
    # MCP 工具返回列表，其中第一个元素是包含 JSON 字符串的字典
    if isinstance(result, list) and len(result) > 0:
        first_item = result[0]
        if isinstance(first_item, dict) and 'text' in first_item:
            # 解析 JSON 字符�?
            import json
            result_dict = json.loads(first_item['text'])
        else:
            result_dict = first_item
    elif isinstance(result, dict):
        result_dict = result
    else:
        result_dict = {"status": "error", "message": f"Unexpected result type: {type(result)}"}
    
    print(f"Status: {result_dict.get('status', 'unknown')}")
    print(f"Found {result_dict.get('count', 0)} results")
    
    if result_dict.get("status") == "success" and result_dict.get("count", 0) > 0:
        print("�?检索成�?)
        return True
    else:
        print("�?检索失�?)
        return False

async def main():
    """运行测试"""
    print("\n" + "="*70)
    print("OpsAgent 测试")
    print("="*70)
    
    try:
        success = await test_search()
        
        if success:
            print("\n" + "="*70)
            print("测试通过 �?)
            print("="*70)
        else:
            print("\n" + "="*70)
            print("测试失败 �?)
            print("="*70)
            sys.exit(1)
    except Exception as e:
        print(f"\n测试出错: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
