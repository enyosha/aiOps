"""
调试：查看所有日志（不过滤），找出时间戳格式问题
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def debug_logs():
    """查看所有日志，分析时间戳格式"""
    print("\n" + "="*80)
    print("调试：查看原始日志格式")
    print("="*80)
    
    from Routing.tool_cache import tool_cache
    
    tools = await tool_cache.get_tools("log-reader")
    read_tool = next((t for t in tools if t.name == "read_docker_logs"), None)
    
    if read_tool:
        from datetime import datetime, timedelta
        
        now = datetime.now()
        since_time = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        
        # 读取所有日志（不过滤）
        result = await read_tool.ainvoke({
            "container_name": "ruoyi-app",
            "since_time": since_time,
            "lines": 100,
            "log_level": None  # 不过滤
        })
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                log_data = json.loads(first_item['text'])
            else:
                log_data = first_item
        else:
            log_data = result
        
        if log_data.get('status') == 'success':
            logs = log_data.get('logs', '')
            lines = logs.splitlines()
            
            print(f"\n总行数: {len(lines)}")
            print(f"\n前20行日志:")
            print("-"*80)
            for i, line in enumerate(lines[:20], 1):
                print(f"{i:3d}. {line}")
            print("-"*80)
            
            # 查找包含ERROR或WARN的行
            print(f"\n包含ERROR或WARN的行:")
            error_lines = [line for line in lines if 'ERROR' in line or 'WARN' in line or 'error' in line.lower() or 'warn' in line.lower()]
            print(f"共找到 {len(error_lines)} 行")
            for i, line in enumerate(error_lines, 1):
                print(f"{i}. {line}")
        else:
            print(f"错误: {log_data.get('message')}")

if __name__ == "__main__":
    try:
        asyncio.run(debug_logs())
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
