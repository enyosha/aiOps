"""
测试Log-Reader MCP的新工具（内存、CPU、系统信息）
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_new_tools():
    """测试新增的工�?""
    print("\n" + "="*80)
    print("测试Log-Reader MCP新增工具")
    print("="*80)
    
    from utils.tool_cache import tool_cache
    
    # 清除缓存，重新加�?
    tool_cache._cache.clear()
    
    tools = await tool_cache.get_tools("log-reader")
    
    print(f"\n�?成功加载 {len(tools)} 个工�?")
    for t in tools:
        print(f"  - {t.name}")
    
    # 1. 测试check_memory_usage
    print("\n" + "-"*80)
    print("【测�?】check_memory_usage")
    print("-"*80)
    mem_tool = next((t for t in tools if t.name == "check_memory_usage"), None)
    if mem_tool:
        result = await mem_tool.ainvoke({})
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                mem_data = json.loads(first_item['text'])
            else:
                mem_data = first_item
        else:
            mem_data = result
        
        if mem_data.get('status') == 'success':
            print(mem_data.get('memory_info', 'N/A'))
        else:
            print(f"�?错误: {mem_data.get('message')}")
    
    # 2. 测试check_cpu_usage
    print("\n" + "-"*80)
    print("【测�?】check_cpu_usage")
    print("-"*80)
    cpu_tool = next((t for t in tools if t.name == "check_cpu_usage"), None)
    if cpu_tool:
        result = await cpu_tool.ainvoke({})
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                cpu_data = json.loads(first_item['text'])
            else:
                cpu_data = first_item
        else:
            cpu_data = result
        
        if cpu_data.get('status') == 'success':
            print(f"Uptime: {cpu_data.get('uptime', 'N/A')}")
            print(f"CPU Info: {cpu_data.get('cpu_info', 'N/A')}")
        else:
            print(f"�?错误: {cpu_data.get('message')}")
    
    # 3. 测试get_system_info
    print("\n" + "-"*80)
    print("【测�?】get_system_info")
    print("-"*80)
    sys_tool = next((t for t in tools if t.name == "get_system_info"), None)
    if sys_tool:
        result = await sys_tool.ainvoke({})
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                sys_data = json.loads(first_item['text'])
            else:
                sys_data = first_item
        else:
            sys_data = result
        
        if sys_data.get('status') == 'success':
            info = sys_data.get('system_info', {})
            for key, value in info.items():
                print(f"{key}: {value}")
        else:
            print(f"�?错误: {sys_data.get('message')}")
    
    print("\n" + "="*80)
    print("�?所有工具测试完成！")
    print("="*80)

if __name__ == "__main__":
    try:
        asyncio.run(test_new_tools())
    except Exception as e:
        print(f"\n�?错误: {str(e)}")
        import traceback
        traceback.print_exc()
