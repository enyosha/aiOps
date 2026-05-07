"""
OpsAgent 完整诊断流程测试
测试 Evaluator-Optimizer 工作流和实际工具调用
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_full_diagnosis():
    """测试完整的诊断流程"""
    print("\n" + "="*70)
    print("OpsAgent 完整诊断流程测试")
    print("="*70)
    
    from Routing.ops_agent import run_ops_diagnosis
    
    # 测试场景：502 错误诊断
    user_input = "8.130.131.36:8080 sent back an error. Error code: 502 Bad Gateway"
    
    print(f"\n用户输入: {user_input}")
    print("\n开始诊断...\n")
    
    result = await run_ops_diagnosis(
        user_input=user_input,
        container_name="ruoyi-app"
    )
    
    print("\n" + "="*70)
    print("诊断结果")
    print("="*70)
    print(f"状态: {result['status']}")
    print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
    print(f"检索质量: {result.get('retrieval_quality', 'N/A')}")
    
    if result['status'] == 'success' and result.get('diagnosis'):
        diagnosis = result['diagnosis']
        print(f"\n置信度: {diagnosis.get('confidence', 'N/A')}")
        print(f"\n诊断内容:\n{diagnosis.get('content', '')}")
    else:
        print(f"\n错误信息: {result.get('message', 'Unknown error')}")
    
    return result

if __name__ == "__main__":
    try:
        result = asyncio.run(test_full_diagnosis())
        
        if result['status'] == 'success':
            print("\n✅ 测试通过！")
        else:
            print("\n❌ 测试失败")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
