"""
查看容器重启前的日志，找出问题原�?
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def check_restart_reason():
    """检查容器重启原�?""
    print("\n" + "="*80)
    print("检查容器重启原�?)
    print("="*80)
    
    from utils.tool_cache import tool_cache
    
    tools = await tool_cache.get_tools("log-reader")
    read_tool = next((t for t in tools if t.name == "read_docker_logs"), None)
    
    if read_tool:
        # 读取最�?小时的日志，不过滤，看完整情�?
        result = await read_tool.ainvoke({
            "container_name": "ruoyi-app",
            "since_time": "2h",  # 过去2小时
            "lines": 200,  # 增加行数
            "log_level": None  # 不过�?
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
            
            print(f"\n总行�? {len(lines)}")
            
            # 查找所有包含重启、错误、异常的关键�?
            keywords = ['restart', 'exit', 'killed', 'OOM', 'OutOfMemory', 'Exception', 'Error', 'FATAL', 'crash']
            important_lines = []
            
            for i, line in enumerate(lines):
                if any(keyword.lower() in line.lower() for keyword in keywords):
                    important_lines.append((i+1, line))
            
            print(f"\n找到 {len(important_lines)} 行重要日�?")
            print("-"*80)
            for line_num, line in important_lines:
                print(f"{line_num:4d}. {line}")
            print("-"*80)
            
            # 显示最�?0行（可能包含重启信息�?
            print(f"\n最�?0行日�?")
            print("-"*80)
            for i, line in enumerate(lines[-50:], len(lines)-49):
                print(f"{i:4d}. {line}")
            print("-"*80)
            
            # 同时检查系统资�?
            print("\n" + "="*80)
            print("检查系统资源使用情�?)
            print("="*80)
            
            ops_tools = await tool_cache.get_tools("ops-diagnosis")
            
            # 检查内�?
            mem_tool = next((t for t in ops_tools if t.name == "check_memory_usage"), None)
            if mem_tool:
                mem_result = await mem_tool.ainvoke({})
                if isinstance(mem_result, list) and len(mem_result) > 0:
                    first_item = mem_result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        mem_data = json.loads(first_item['text'])
                    else:
                        mem_data = first_item
                    
                    if mem_data.get('status') == 'success':
                        print(f"\n内存使用情况:")
                        print(mem_data.get('memory_info', 'N/A'))
            
            # 检查CPU
            cpu_tool = next((t for t in ops_tools if t.name == "check_cpu_usage"), None)
            if cpu_tool:
                cpu_result = await cpu_tool.ainvoke({})
                if isinstance(cpu_result, list) and len(cpu_result) > 0:
                    first_item = cpu_result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        cpu_data = json.loads(first_item['text'])
                    else:
                        cpu_data = first_item
                    
                    if cpu_data.get('status') == 'success':
                        print(f"\nCPU使用情况:")
                        print(cpu_data.get('cpu_info', 'N/A'))
        else:
            print(f"错误: {log_data.get('message')}")

if __name__ == "__main__":
    try:
        asyncio.run(check_restart_reason())
    except Exception as e:
        print(f"\n�?错误: {str(e)}")
        import traceback
        traceback.print_exc()
