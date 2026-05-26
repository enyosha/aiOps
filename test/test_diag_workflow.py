"""
测试 diagnosis_agent 的完整工作流�?
模拟 Client_test.py 中的 diag 命令调用
"""
import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from Routing.diagnosis_agent import run_diagnosis
from datetime import datetime


async def test_frontend_issue():
    """测试前端无法加载页面的诊断场�?""
    print("=" * 70)
    print("测试场景: 前端无法加载页面")
    print("=" * 70)
    
    # 构造告警事件（模拟用户输入�?
    alert_event = {
        "alert_name": "前端访问异常",
        "alert_type": "frontend_error",
        "alert_time": datetime.now().isoformat(),
        "description": "服务有问�?前端无法加载页面"
    }
    
    print(f"\n📋 告警信息:")
    print(f"   名称: {alert_event['alert_name']}")
    print(f"   类型: {alert_event['alert_type']}")
    print(f"   描述: {alert_event['description']}")
    print(f"   时间: {alert_event['alert_time']}")
    
    print("\n" + "=" * 70)
    print("开始执行诊断工作流...")
    print("=" * 70)
    
    # 调用诊断函数
    result = await run_diagnosis(alert_event, container_name="ruoyi-app")
    
    print("\n" + "=" * 70)
    print("诊断结果")
    print("=" * 70)
    
    if result["status"] == "success":
        print(f"\n�?诊断完成")
        print(f"\n📋 诊断报告:\n")
        print(result['diagnosis']['content'])
        
        print("\n" + "=" * 70)
        print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
        data_collected = result.get('data_collected', {})
        print(f"数据收集状�?")
        print(f"  - 日志: {'�? if data_collected.get('logs') else '�?}")
        print(f"  - 内存: {'�? if data_collected.get('memory') else '�?}")
        print(f"  - CPU: {'�? if data_collected.get('cpu') else '�?}")
        print(f"  - 服务状�? {'�? if data_collected.get('service_status') else '�?}")
        
        # 显示配置状�?
        diagnosis = result.get('diagnosis', {})
        if diagnosis.get('stopped_services'):
            print(f"\n⚠️  未启动的服务: {diagnosis['stopped_services']}")
        
        print("=" * 70)
    else:
        print(f"\n�?诊断失败")
        print(f"错误信息: {result.get('message', '未知错误')}")
        print("=" * 70)


if __name__ == "__main__":
    print("\n开始测�?diagnosis_agent 工作流程\n")
    asyncio.run(test_frontend_issue())
    print("\n测试完成！\n")
