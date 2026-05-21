"""
测试多服务器日志读取功能
验证前端容器日志能否正确从前端服务器获取
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_multi_server_logs():
    """测试多服务器日志读取"""
    print("\n" + "="*80)
    print("测试多服务器日志读取功能")
    print("="*80)
    
    from Routing.tool_cache import tool_cache
    
    # 获取 log-reader 工具
    log_tools = await tool_cache.get_tools("log-reader")
    read_tool = next((t for t in log_tools if t.name == "read_docker_logs"), None)
    
    if not read_tool:
        print("❌ 未找到 read_docker_logs 工具")
        return
    
    print("\n✅ 找到 read_docker_logs 工具\n")
    
    # 测试1: 读取后端服务器上的容器日志（默认）
    print("="*80)
    print("测试1: 读取后端服务器 (8.130.131.36) 上的 ruoyi-app 容器日志")
    print("="*80)
    try:
        result = await read_tool.ainvoke({
            "container_name": "ruoyi-app",
            "lines": 5,
            "log_level": None
        })
        
        # 解析结果
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                log_data = json.loads(first_item['text'])
            else:
                log_data = first_item
        else:
            log_data = result
        
        if log_data.get('status') == 'success':
            line_count = log_data.get('line_count', 0)
            print(f"✅ 成功读取 {line_count} 行日志")
            if line_count > 0:
                logs = log_data.get('logs', '')
                print("\n日志预览:")
                for line in logs.split('\n')[:3]:
                    print(f"  {line}")
        else:
            print(f"❌ 读取失败: {log_data.get('message')}")
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 测试2: 读取前端服务器上的容器日志（指定 ssh_host）
    print("\n" + "="*80)
    print("测试2: 读取前端服务器 (8.146.236.55) 上的 ruoyi-frontend 容器日志")
    print("="*80)
    try:
        result = await read_tool.ainvoke({
            "container_name": "ruoyi-frontend",
            "lines": 5,
            "log_level": None,
            "ssh_host": "8.146.236.55"  # ← 关键：指定前端服务器
        })
        
        # 解析结果
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                log_data = json.loads(first_item['text'])
            else:
                log_data = first_item
        else:
            log_data = result
        
        if log_data.get('status') == 'success':
            line_count = log_data.get('line_count', 0)
            print(f"✅ 成功读取 {line_count} 行日志")
            if line_count > 0:
                logs = log_data.get('logs', '')
                print("\n日志预览:")
                for line in logs.split('\n')[:5]:
                    print(f"  {line}")
        else:
            print(f"❌ 读取失败: {log_data.get('message')}")
            print("\n⚠️  这是预期的行为，如果前端容器不存在或无法访问")
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 测试3: 验证错误检测（尝试读取不存在的容器）
    print("\n" + "="*80)
    print("测试3: 验证错误检测 - 读取不存在的容器")
    print("="*80)
    try:
        result = await read_tool.ainvoke({
            "container_name": "nonexistent-container",
            "lines": 5,
            "log_level": None
        })
        
        # 解析结果
        if isinstance(result, list) and len(result) > 0:
            first_item = result[0]
            if isinstance(first_item, dict) and 'text' in first_item:
                import json
                log_data = json.loads(first_item['text'])
            else:
                log_data = first_item
        else:
            log_data = result
        
        if log_data.get('status') == 'error':
            print(f"✅ 正确识别为错误")
            print(f"错误信息: {log_data.get('message')[:100]}...")
        else:
            print(f"❌ 未能识别错误，返回 status: {log_data.get('status')}")
            print(f"返回内容: {log_data.get('logs', '')[:100]}")
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
    
    print("\n" + "="*80)
    print("测试完成")
    print("="*80)


if __name__ == "__main__":
    try:
        asyncio.run(test_multi_server_logs())
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
