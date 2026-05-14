"""
测试优化后的诊断逻辑
验证：
1. 可疑容器检测
2. 空日志智能处理
3. 准确的诊断报告生成
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from Routing.diagnosis_agent import run_diagnosis

async def test_optimized_diagnosis():
    """测试优化后的诊断逻辑"""
    
    print("="*70)
    print("测试：优化后的诊断逻辑")
    print("="*70)
    
    # 测试场景：应用无响应（但实际所有服务正常）
    alert_event = {
        "alert_name": "应用无响应",
        "alert_type": "application_unresponsive",
        "alert_time": "2026-05-13T19:30:00",
        "description": "用户反馈前端页面无法访问"
    }
    
    container_name = "ruoyi-app"
    
    print(f"\n开始诊断: {alert_event['alert_name']}")
    print(f"容器名称: {container_name}")
    print("-"*70)
    
    try:
        result = await run_diagnosis(alert_event, container_name)
        
        print("\n" + "="*70)
        print("诊断结果:")
        print("="*70)
        
        if result.get('status') == 'success' and result.get('diagnosis'):
            diagnosis = result['diagnosis']
            print(f"\n置信度: {diagnosis.get('confidence', 'N/A')}")
            print(f"\n诊断内容:\n{diagnosis.get('content', '')}")
            
            # 检查是否提到了可疑容器
            content = diagnosis.get('content', '')
            if '可疑容器' in content or 'frontend' in content.lower():
                print("\n[OK] 检测到前端相关问题的分析")
            else:
                print("\n[WARN] 未检测到前端相关问题的分析")
                
        else:
            print(f"状态: {result.get('status', 'unknown')}")
            if result.get('status') == 'error':
                print(f"错误信息: {result.get('message', '')}")
            else:
                print("未获取到诊断结果")
            
    except Exception as e:
        print(f"\n[ERROR] 诊断过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_optimized_diagnosis())
