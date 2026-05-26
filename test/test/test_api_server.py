"""
测试REST API服务
"""
import asyncio
import sys
import os
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

API_BASE_URL = "http://localhost:8004"  # 使用8004端口


def test_health_check():
    """测试健康检�?""
    print("\n" + "="*80)
    print("【测�?】健康检�?)
    print("="*80)
    
    try:
        response = requests.get(f"{API_BASE_URL}/api/health")
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"�?错误: {str(e)}")
        return False


def test_trigger_diagnosis():
    """测试触发诊断"""
    print("\n" + "="*80)
    print("【测�?】触发诊断任�?)
    print("="*80)
    
    # 构造告警事�?
    alert_event = {
        "alert_name": "ContainerRestartDetected",
        "container_name": "ruoyi-app",
        "alert_time": "2026-05-08T14:30:00",
        "alert_type": "container_restart",
        "description": "检测到容器在过�?分钟内发生重�?
    }
    
    payload = {
        "alert_event": alert_event,
        "container_name": "ruoyi-app"
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/diagnose",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"状态码: {response.status_code}")
        result = response.json()
        print(f"任务ID: {result['task_id']}")
        print(f"状�? {result['status']}")
        print(f"消息: {result['message']}")
        
        return result['task_id']
        
    except Exception as e:
        print(f"�?错误: {str(e)}")
        return None


def test_query_result(task_id: str):
    """查询诊断结果"""
    print("\n" + "="*80)
    print("【测�?】查询诊断结�?)
    print("="*80)
    
    max_retries = 30  # 增加�?0次，总共150�?
    retry_interval = 5  # 每次间隔5�?
    
    for i in range(max_retries):
        try:
            response = requests.get(f"{API_BASE_URL}/api/diagnose/{task_id}")
            result = response.json()
            
            print(f"\n第{i+1}次查�?")
            print(f"  状�? {result['status']}")
            
            if result['status'] == 'completed':
                print(f"\n{'='*80}")
                print("[OK] 诊断完成�?)
                
                diagnosis = result.get('result', {})
                if diagnosis.get('status') == 'success':
                    print(f"迭代次数: {diagnosis.get('iteration_count')}")
                    
                    diag_result = diagnosis.get('diagnosis', {})
                    content = diag_result.get('content', '')
                    
                    # 提取markdown代码块内�?
                    import re
                    markdown_match = re.search(r'```markdown\s*\n(.*?)\n```', content, re.DOTALL)
                    if markdown_match:
                        # 如果找到markdown代码块，只提取其中的内容
                        content = markdown_match.group(1).strip()
                    else:
                        # 如果没有markdown标记，尝试移除所有代码块标记
                        content = content.replace('```markdown', '').replace('```', '').strip()
                        # 移除可能的额外总结文字（在最后一个```之后的内容）
                        if '```' in content:
                            parts = content.split('```')
                            content = parts[0].strip()
                    
                    print(f"\n{'='*80}")
                    print("诊断报告")
                    print(f"{'='*80}")
                    print(content)
                    print(f"{'='*80}\n")
                    
                    return True
                else:
                    print(f"\n[ERROR] 诊断失败: {diagnosis.get('message')}")
                    return False
                    
            elif result['status'] == 'failed':
                print(f"\n[ERROR] 诊断失败: {result.get('error')}")
                return False
                
            else:
                print(f"  等待�?.. ({i+1}/{max_retries})")
                time.sleep(retry_interval)
                
        except Exception as e:
            print(f"\n[ERROR] 查询错误: {str(e)}")
            return False
    
    print(f"\n[WARNING] 超时：诊断任务未在预期时间内完成")
    return False


def test_list_tasks():
    """列出诊断任务"""
    print("\n" + "="*80)
    print("【测�?】列出诊断任�?)
    print("="*80)
    
    try:
        response = requests.get(f"{API_BASE_URL}/api/diagnose/list?limit=5")
        result = response.json()
        
        print(f"总任务数: {result.get('total', 'N/A')}")
        print(f"\n最近的任务:")
        
        tasks = result.get('tasks', [])
        for task in tasks:
            print(f"  - {task['task_id'][:8]}... | 状�? {task['status']} | 创建时间: {task['created_at']}")
        
        return True
        
    except Exception as e:
        print(f"�?错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def _stop_api_server(process):
    """停止API服务�?""
    try:
        # 发�?Ctrl+C 信号（Windows�?
        if os.name == 'nt':
            import signal
            process.send_signal(signal.CTRL_C_EVENT)
        else:
            process.terminate()
        
        try:
            process.wait(timeout=5)
            print("API服务器已停止")
        except subprocess.TimeoutExpired:
            print("[提示] API服务器窗口保持打开，请手动关闭")
    except Exception as e:
        print(f"停止API服务器时出错: {str(e)}")


def _kill_process_on_port(port: int):
    """强制终止占用指定端口的进�?""
    try:
        if os.name == 'nt':
            # Windows: 使用 netstat 查找占用端口�?PID
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True
            )
            for line in result.stdout.splitlines():
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        try:
                            pid = int(pid)
                            print(f"[清理] 发现占用端口 {port} 的进�?(PID: {pid})，正在终�?..")
                            subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                         capture_output=True, check=True)
                            print(f"[清理] 已终止进�?{pid}")
                            return True
                        except (ValueError, subprocess.CalledProcessError):
                            continue
        else:
            # Linux/Mac: 使用 lsof
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        print(f"[清理] 终止进程 {pid}")
                        subprocess.run(['kill', '-9', pid], check=True)
                    except:
                        pass
                return True
        return False
    except Exception as e:
        print(f"[清理] 清理端口 {port} 时出�? {e}")
        return False


def main():
    """运行所有测�?""
    import subprocess
    import signal
    import threading
    from datetime import datetime
    
    print("\n" + "="*80)
    print("REST API 服务测试")
    print("="*80)
    
    # 检查并清理端口
    port = 8004
    print(f"\n检查端�?{port}...")
    if _kill_process_on_port(port):
        print(f"[OK] 端口 {port} 已清�?)
        time.sleep(1)  # 等待端口释放
    else:
        print(f"[OK] 端口 {port} 可用")
    
    # 自动启动API服务器（在新窗口中）
    print("\n正在启动API服务�?..")
    
    # 获取api_server.py的绝对路�?
    api_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Server', 'api_server.py')
    api_script = os.path.normpath(api_script)
    
    # 创建带时间戳的日志文�?
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', f'api_server_test_{timestamp}.log')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # 启动API服务器，输出重定向到日志文件
    # 使用utf-8-sig编码确保中文正确显示
    with open(log_file, 'w', encoding='utf-8-sig') as log:
        if os.name == 'nt':
            # Windows: 使用start命令打开新窗�?
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            api_process = subprocess.Popen(
                ['python', api_script],
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                startupinfo=startupinfo,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}  # 设置Python输出编码
            )
        else:
            # Linux/Mac: 使用nohup或其他方�?
            api_process = subprocess.Popen(
                ['python', api_script],
                stdout=log,
                stderr=log,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
            )
    
    # 等待几秒让服务启�?
    time.sleep(3)
    print(f"\nAPI服务器已启动 (PID: {api_process.pid})")
    print(f"日志文件: {log_file}")
    print(f"\n提示: API服务器日志将实时显示在独立窗口中")
    print(f"      当前窗口仅显示测试脚本的输出")
    print("="*80)
    
    try:
        # 等待服务启动（带重试�?
        print("\n等待API服务就绪...")
        max_wait = 10  # 最多等�?0�?
        for i in range(max_wait):
            try:
                response = requests.get(f"{API_BASE_URL}/api/health", timeout=2)
                if response.status_code == 200:
                    print(f"API服务已就�?(耗时{i+1}�?")
                    break
            except:
                pass
            time.sleep(1)
        else:
            print(f"\n[ERROR] API服务未在{max_wait}秒内启动")
            _stop_api_server(api_process)
            return False
        
        print("\n" + "="*80)
        
        # 测试1: 健康检�?
        if not test_health_check():
            print("\n[ERROR] API服务未启�?)
            _stop_api_server(api_process)
            return False
        
        # 测试2: 触发诊断
        task_id = test_trigger_diagnosis()
        if not task_id:
            print("\n[ERROR] 触发诊断失败")
            _stop_api_server(api_process)
            return False
        
        # 测试3: 查询结果
        if not test_query_result(task_id):
            print("\n[ERROR] 查询结果失败")
            _stop_api_server(api_process)
            return False
        
        # 测试4: 列出任务
        test_list_tasks()
        
        print("\n" + "="*80)
        print("[OK] 所有测试通过�?)
        print("="*80)
        
        return True
        
    finally:
        # 测试结束后停止API服务�?
        print("\n正在停止API服务�?..")
        _stop_api_server(api_process)


if __name__ == "__main__":
    import subprocess
    api_process = None
    
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[WARNING] 测试被中�?)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
