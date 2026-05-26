"""
快速检查系统资�?
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def check_resources():
    """检查系统资�?""
    print("\n" + "="*80)
    print("系统资源检�?)
    print("="*80)
    
    from utils.tool_cache import tool_cache
    
    ops_tools = await tool_cache.get_tools("ops-diagnosis")
    
    # 检查内�?
    print("\n【内存使用情况�?)
    mem_tool = next((t for t in ops_tools if t.name == "check_memory_usage"), None)
    if mem_tool:
        result = await mem_tool.ainvoke({})
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                mem_data = json.loads(first_item['text'])
            else:
                mem_data = first_item
            
            if mem_data.get('status') == 'success':
                print(mem_data.get('memory_info', 'N/A'))
    
    # 检查CPU
    print("\n【CPU使用情况�?)
    cpu_tool = next((t for t in ops_tools if t.name == "check_cpu_usage"), None)
    if cpu_tool:
        result = await cpu_tool.ainvoke({})
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                cpu_data = json.loads(first_item['text'])
            else:
                cpu_data = first_item
            
            if cpu_data.get('status') == 'success':
                print(cpu_data.get('cpu_info', 'N/A'))
    
    # 检查Docker容器状�?
    print("\n【Docker容器状态�?)
    log_tools = await tool_cache.get_tools("log-reader")
    status_tool = next((t for t in log_tools if t.name == "get_container_status"), None)
    if status_tool:
        result = await status_tool.ainvoke({"container_name": "ruoyi-app"})
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                status_data = json.loads(first_item['text'])
            else:
                status_data = first_item
            
            if status_data.get('status') == 'success':
                print(f"容器: {status_data.get('container')}")
                print(f"运行�? {'�? if status_data.get('running') else '�?}")
                print(f"详情: {status_data.get('status_detail')}")

if __name__ == "__main__":
    try:
        asyncio.run(check_resources())
    except Exception as e:
        print(f"\n�?错误: {str(e)}")
        import traceback
        traceback.print_exc()
