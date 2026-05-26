"""
测试DiagnosisAgent - 纯LLM驱动的运维诊�?
测试场景：Grafana检测到容器异常后自动触发诊�?
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_diagnosis():
    """测试DiagnosisAgent的自动诊断能力（模拟Grafana告警触发�?""
    print("\n" + "="*80)
    print("DiagnosisAgent 测试 - Grafana告警自动触发诊断")
    print("="*80)
    
    from Routing.diagnosis_agent import run_diagnosis
    
    # 模拟Grafana告警事件（而非用户输入�?
    alert_event = {
        "alert_name": "ContainerRestartDetected",
        "container_name": "ruoyi-app",
        "alert_time": "2026-05-08T12:17:00",
        "alert_type": "container_restart",
        "description": "检测到容器在过�?分钟内发生重�?
    }
    
    print(f"\n【Grafana告警事件�?)
    print(f"告警名称: {alert_event['alert_name']}")
    print(f"容器名称: {alert_event['container_name']}")
    print(f"告警时间: {alert_event['alert_time']}")
    print(f"告警类型: {alert_event['alert_type']}")
    print(f"告警描述: {alert_event['description']}")
    print(f"\n{'='*80}")
    print("自动触发诊断...")
    print(f"{'='*80}\n")
    
    # 调用诊断Agent（传入告警事件而非用户输入�?
    result = await run_diagnosis(
        alert_event=alert_event,
        container_name=alert_event['container_name']
    )
    
    print(f"\n{'='*80}")
    print("【测试结果分析�?)
    print(f"{'='*80}")
    print(f"状�? {result['status']}")
    print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
    print(f"数据收集情况:")
    data_collected = result.get('data_collected', {})
    print(f"  - 日志: {'�? if data_collected.get('logs') else '�?}")
    print(f"  - 内存: {'�? if data_collected.get('memory') else '�?}")
    print(f"  - CPU: {'�? if data_collected.get('cpu') else '�?}")
    print(f"  - 服务状�? {'�? if data_collected.get('service_status') else '�?}")
    
    if result['status'] == 'success' and result.get('diagnosis'):
        diagnosis = result['diagnosis']
        content = diagnosis.get('content', '')
        
        print(f"\n置信�? {diagnosis.get('confidence', 'N/A')}")
        
        # 检查点
        checks = [
            ("识别到内存紧�?, any(keyword in content for keyword in ["内存", "memory", "231Mi", "可用"])),
            ("基于实时数据分析", data_collected.get('memory') or data_collected.get('logs')),
            ("给出了具体修复建�?, any(cmd in content for cmd in ["restart", "update", "kill", "docker", "增加", "扩容"])),
            ("分析了根本原�?, "根因" in content or "原因" in content or "cause" in content.lower()),
            ("提供了优化建�?, "优化" in content or "建议" in content or "长期" in content)
        ]
        
        print(f"\n{'='*80}")
        print("【检查点验证�?)
        print(f"{'='*80}")
        for i, (desc, passed) in enumerate(checks, 1):
            status = "�?通过" if passed else "�?失败"
            print(f"�?检查点 {i} - {desc}: {status}")
        
        all_passed = all(passed for _, passed in checks)
        
        print(f"\n{'='*80}")
        print(f"总体结果: {'�?全部通过' if all_passed else '⚠️ 部分通过'}")
        print(f"{'='*80}")
        
        # 显示诊断报告
        print(f"\n{'='*80}")
        print("📋 诊断报告")
        print(f"{'='*80}")
        print(content)
        
        return all_passed
    else:
        print(f"\n�?诊断失败: {result.get('message', 'Unknown error')}")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(test_diagnosis())
        
        if success:
            print("\n🎉 测试完全通过�?)
            sys.exit(0)
        else:
            print("\n⚠️ 测试部分通过，需要进一步优�?)
            sys.exit(1)
    except Exception as e:
        print(f"\n�?测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
