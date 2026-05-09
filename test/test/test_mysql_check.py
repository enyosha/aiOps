"""
测试Log-Reader MCP的MySQL检查工具
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_mysql_check():
    """测试check_mysql_status工具"""
    print("\n" + "="*80)
    print("测试MySQL状态检查工具")
    print("="*80)
    
    from Routing.tool_cache import tool_cache
    
    # 清除缓存，重新加载
    tool_cache._cache.clear()
    
    tools = await tool_cache.get_tools("log-reader")
    
    print(f"\n✅ 成功加载 {len(tools)} 个工具")
    
    # 测试check_mysql_status
    print("\n" + "-"*80)
    print("【测试】check_mysql_status")
    print("-"*80)
    mysql_tool = next((t for t in tools if t.name == "check_mysql_status"), None)
    
    if mysql_tool:
        result = await mysql_tool.ainvoke({})
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                mysql_data = json.loads(first_item['text'])
            else:
                mysql_data = first_item
        else:
            mysql_data = result
        
        if mysql_data.get('status') == 'success':
            print(f"MySQL运行状态: {'✅ 运行中' if mysql_data.get('mysql_running') else '❌ 未运行'}")
            print(f"\n进程信息:\n{mysql_data.get('process_info', 'N/A')}")
            print(f"\n端口信息:\n{mysql_data.get('port_info', 'N/A')}")
            print(f"\nDocker信息:\n{mysql_data.get('docker_info', 'N/A')}")
        else:
            print(f"❌ 错误: {mysql_data.get('message')}")
    else:
        print("❌ 未找到check_mysql_status工具")
    
    print("\n" + "="*80)
    print("✅ MySQL检查测试完成！")
    print("="*80)

if __name__ == "__main__":
    try:
        asyncio.run(test_mysql_check())
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
