"""
test.py
"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import asyncio

# 添加项目根目录到Python路径，以便正确导入模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入路由工作流
from Routing.route import router_workflow


async def main():
    """主函数 - 演示路由功能"""
    print("=" * 70)
    print("Router 演示程序 (LangGraph 结构)")
    print("=" * 70)
    
    # 测试用例
    test_inputs = [
        "计算 25 * 17 + 45 / 3 的结果",
        # "计算 25 的对数10  的结果",
        "今天北京的天气怎么样？",
        # "从上海到杭州的最佳路线是什么？",
        # "分析一下 error.log 文件中有什么错误信息"
        "日志信息里面 DEBUG 级别的日志有哪些？列举出三个出来",
        "大聪明口服液多少钱?"
    ]
    
    for i, test_input in enumerate(test_inputs, 1):
        print(f"\n测试 {i}: {test_input}")
        print("-" * 50)
        
        try:
            # 调用工作流
            state = await router_workflow.ainvoke({"input": test_input})
            print(f"🤖 回应：{state['output']}")
        except Exception as e:
            print(f"错误：{str(e)}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())