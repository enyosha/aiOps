"""
测试计算器Agent的链式计算功能
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

async def test_chain_calculation():
    """测试链式计算"""
    from Routing.base_agent import CalculatorAgent
    
    print("=" * 70)
    print("测试计算器Agent的链式计算功能")
    print("=" * 70)
    
    # 创建并初始化Agent
    agent = CalculatorAgent()
    await agent.initialize()
    
    # 测试用例1: 简单计算
    print("\n【测试1】简单计算: 12 + 6")
    result = await agent.ainvoke("12 + 6")
    print(f"结果: {result['response']['content']}")
    print(f"工具调用次数: {len(result.get('tool_calls', []))}")
    
    # 测试用例2: 链式计算
    print("\n【测试2】链式计算: 12 + 6 - 95")
    result = await agent.ainvoke("12 + 6 - 95")
    print(f"结果: {result['response']['content']}")
    print(f"工具调用次数: {len(result.get('tool_calls', []))}")
    if result.get('tool_results'):
        for i, tr in enumerate(result['tool_results']):
            print(f"  步骤{i+1}: {tr['tool_name']} -> {tr.get('result', {})}")
    
    # 测试用例3: 更复杂的链式
    print("\n【测试3】复杂链式: 5 * 3 + 10 - 2")
    result = await agent.ainvoke("5 * 3 + 10 - 2")
    print(f"结果: {result['response']['content']}")
    print(f"工具调用次数: {len(result.get('tool_calls', []))}")
    if result.get('tool_results'):
        for i, tr in enumerate(result['tool_results']):
            print(f"  步骤{i+1}: {tr['tool_name']} -> {tr.get('result', {})}")
    
    # 测试用例4: 运算优先级（先乘除后加减）
    print("\n【测试4】运算优先级: 59 + 8 - 8 - 9 / 7")
    result = await agent.ainvoke("59 + 8 - 8 - 9 / 7")
    print(f"结果: {result['response']['content']}")
    print(f"工具调用次数: {len(result.get('tool_calls', []))}")
    if result.get('tool_results'):
        for i, tr in enumerate(result['tool_results']):
            print(f"  步骤{i+1}: {tr['tool_name']} -> {tr.get('result', {})}")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_chain_calculation())
