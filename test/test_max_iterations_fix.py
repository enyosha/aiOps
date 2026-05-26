"""
test_max_iterations.py - 测试 max_iterations 修复

验证诊断 Agent 在达到最大迭代次数后能够正确停止
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
from Routing.diagnosis_agent import run_diagnosis
from datetime import datetime


async def test_max_iterations():
    """测试 max_iterations 限制"""
    print("=" * 70)
    print("测试: max_iterations 修复验证")
    print("=" * 70)
    
    # 加载环境变量（使用项目根目录�?.env 文件�?
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(env_path)
    print(f"�?已加载配置文�? {os.path.abspath(env_path)}")
    
    # 创建测试告警事件
    alert_event = {
        "alert_name": "",
        "alert_type": "",
        "alert_time": datetime.now().isoformat(),
        "description": "应用响应缓慢"
    }
    
    print(f"\n📋 测试场景:")
    print(f"   告警类型: {alert_event['alert_name']}")
    print(f"   描述: {alert_event['description']}")
    print(f"   容器: ruoyi-app")
    print(f"   预期最大迭代次�? 8")
    print("-" * 70)
    print("\n开始诊�?..\n")
    
    # 运行诊断（传递正确的 .env 文件路径�?
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    result = await run_diagnosis(alert_event, container_name="ruoyi-app", env_file_path=env_path)
    
    print("\n" + "=" * 70)
    print("测试结果")
    print("=" * 70)
    
    if result["status"] == "success":
        iteration_count = result.get('iteration_count', 'N/A')
        print(f"�?诊断完成")
        print(f"   迭代次数: {iteration_count}")
        
        # 检查是否超过最大迭代次�?
        if isinstance(iteration_count, int):
            if iteration_count <= 8:
                print(f"   �?PASS: 迭代次数 ({iteration_count}) 未超过限�?(8)")
            else:
                print(f"   �?FAIL: 迭代次数 ({iteration_count}) 超过了限�?(8)")
        else:
            print(f"   ⚠️  WARNING: 无法获取迭代次数")
        
        # 显示数据收集状�?
        data_collected = result.get('data_collected', {})
        print(f"\n📊 数据收集状�?")
        print(f"   - 日志: {'�? if data_collected.get('logs') else '�?}")
        print(f"   - 内存: {'�? if data_collected.get('memory') else '�?}")
        print(f"   - CPU: {'�? if data_collected.get('cpu') else '�?}")
        print(f"   - 服务状�? {'�? if data_collected.get('service_status') else '�?}")
        
        # 显示诊断报告摘要
        diagnosis = result.get('diagnosis', {})
        if diagnosis:
            content = diagnosis.get('content', '')
            # 只显示前500字符
            preview = content[:500] + "..." if len(content) > 500 else content
            print(f"\n📋 诊断报告摘要:\n{preview}")
    else:
        print(f"�?诊断失败")
        print(f"   错误信息: {result.get('message', '未知错误')}")
    
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(test_max_iterations())
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被用户中�?)
    except Exception as e:
        print(f"\n�?测试出错: {str(e)}")
        import traceback
        traceback.print_exc()
