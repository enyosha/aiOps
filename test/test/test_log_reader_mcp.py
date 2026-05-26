"""
测试Log-Reader MCP服务
验证SSH连接、日志读取、异常扫描等功能
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_log_reader_mcp():
    """测试Log-Reader MCP服务的各个工�?""
    print("\n" + "="*80)
    print("Log-Reader MCP 服务测试")
    print("="*80)
    
    from utils.tool_cache import tool_cache
    
    # 获取log-reader的工�?
    print("\n【步�?】加载log-reader工具...")
    tools = await tool_cache.get_tools("log-reader")
    print(f"�?成功加载 {len(tools)} 个工�?)
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:50]}...")
    
    # 测试1: 检查容器状�?
    print("\n" + "="*80)
    print("【测�?】检查容器状�?)
    print("="*80)
    
    status_tool = next((t for t in tools if t.name == "get_container_status"), None)
    if status_tool:
        result = await status_tool.ainvoke({"container_name": "ruoyi-app"})
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                status_data = json.loads(first_item['text'])
            else:
                status_data = first_item
        else:
            status_data = result
        
        print(f"状�? {status_data.get('status')}")
        if status_data.get('status') == 'success':
            print(f"容器: {status_data.get('container')}")
            print(f"运行�? {'�? if status_data.get('running') else '�?}")
            print(f"详情: {status_data.get('status_detail')}")
        else:
            print(f"错误: {status_data.get('message')}")
    else:
        print("�?未找到get_container_status工具")
    
    # 测试2: 快速扫描异常时间点
    print("\n" + "="*80)
    print("【测�?】快速扫描异常时间点（过�?小时�?)
    print("="*80)
    
    scan_tool = next((t for t in tools if t.name == "scan_logs_for_anomalies"), None)
    if scan_tool:
        result = await scan_tool.ainvoke({
            "container_name": "ruoyi-app",
            "time_range_hours": 2
        })
        
        # 解析MCP返回格式
        if isinstance(result, list) and len(result) > 0:
            import json
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                scan_data = json.loads(first_item['text'])
            else:
                scan_data = first_item
        else:
            scan_data = result
        
        print(f"状�? {scan_data.get('status')}")
        if scan_data.get('status') == 'success':
            print(f"异常时间点数�? {scan_data.get('anomaly_count')}")
            print(f"ERROR/WARN总行�? {scan_data.get('total_error_warn_lines')}")
            
            timestamps = scan_data.get('anomaly_timestamps', [])
            if timestamps:
                print(f"\n�?0个异常时间点:")
                for i, ts in enumerate(timestamps[:10], 1):
                    print(f"  {i}. {ts}")
            else:
                print("\n未检测到异常时间�?)
        else:
            print(f"错误: {scan_data.get('message')}")
    else:
        print("�?未找到scan_logs_for_anomalies工具")
    
    # 测试3: 读取指定时间范围的日�?
    print("\n" + "="*80)
    print("【测�?】读取最�?0分钟的ERROR/WARN日志")
    print("="*80)
    
    read_tool = next((t for t in tools if t.name == "read_docker_logs"), None)
    if read_tool:
        from datetime import datetime, timedelta
        
        now = datetime.now()
        since_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
        
        result = await read_tool.ainvoke({
            "container_name": "ruoyi-app",
            "since_time": since_time,
            "lines": 50,
            "log_level": ["ERROR", "WARN"]
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
        
        print(f"状�? {log_data.get('status')}")
        if log_data.get('status') == 'success':
            print(f"容器: {log_data.get('container')}")
            print(f"时间范围: {log_data.get('time_range')}")
            print(f"日志行数: {log_data.get('line_count')}")
            print(f"过滤级别: {log_data.get('filter_applied')}")
            
            logs = log_data.get('logs', '')
            if logs:
                print(f"\n日志预览（前500字符�?")
                print("-"*80)
                print(logs[:500])
                print("-"*80)
            else:
                print("\n未找到符合条件的日志")
        else:
            print(f"错误: {log_data.get('message')}")
    else:
        print("�?未找到read_docker_logs工具")
    
    print("\n" + "="*80)
    print("测试完成")
    print("="*80)

if __name__ == "__main__":
    try:
        asyncio.run(test_log_reader_mcp())
        print("\n�?测试成功")
    except Exception as e:
        print(f"\n�?测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
