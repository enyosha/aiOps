"""
简单测试RAG路由功能
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from Routing.route import router_workflow


async def test_rag_routing():
    """测试RAG路由"""
    print("=" * 70)
    print("RAG路由测试")
    print("=" * 70)

    test_cases = [
        # ("2025年人工智能有哪些发展趋势?", "rag_query"),
        # ("大聪明牌口服液的功效是什�?", "rag_query"),
        ("大聪明牌定价是多�?", "rag_query"),
        # ("计算 25 + 17", "calculator"),
        
    ]

    for query, expected_intent in test_cases:
        print(f"\n问题: {query}")
        print(f"期望意图: {expected_intent}")

        try:
            state = await router_workflow.ainvoke({"input": query})
            print(f"实际决策: {state.get('decision', 'unknown')}")
            print(f"输出: {state.get('output', '')[:200]}")

            if state.get('decision') == expected_intent:
                print("状�? PASS")
            else:
                print("状�? FAIL - 意图识别错误")
        except Exception as e:
            print(f"错误: {str(e)[:200]}")
            print("状�? ERROR")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(test_rag_routing())
