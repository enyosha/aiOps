"""
快速启动脚本 - 演示如何使用 MCP Agent
"""
import json
from mcp_client.mcp_client import create_agent


def main():
    """主函数"""
    print("\n" + "=" * 70)
    print(" " * 20 + "MCP Agent 快速启动")
    print("=" * 70)
    
    # 创建 Agent
    print("\n[1/3] 正在创建 Agent...")
    agent = create_agent()
    print(f"✓ Agent 创建成功")
    print(f"✓ 加载了 {len(agent.mcp_client.tools)} 个工具")
    
    # 显示可用工具
    print(f"\n[2/3] 可用工具列表:")
    for i, tool in enumerate(agent.mcp_client.tools, 1):
        print(f"   {i}. {tool.name}: {tool.description}")
    
    # 示例对话
    print(f"\n[3/3] 开始对话测试...")
    print("-" * 70)
    
    examples = [
        # "你好！",
        # "计算 100 + 250 等于多少？",
        # "余姚和房山之间的直线距离是多少？",
        # "给我一个步行以及骑车的路径规划,从北京的天安门到望京。",
        # "我的IP定位在哪里？",
        "日志信息里面 DEBUG 级别的日志有哪些？列举出三个出来",
        # "辽宁省现在哪些城市在下雨",
        # "202.96.69.38，这个 IP 地址所对应的地理位置在哪里。",
        "我大连, 从小平岛到中山广场,公交+步行的方式,应该如何走？耗时多时间?"
    ]
    
    for example in examples:
        print(f"\n👤 用户：{example}")
        result = agent.invoke(example)
        
        if result["status"] == "success":
            response_content = result.get("response", {}).get("content", "无回复")
            print(f"🤖 助手：{response_content[:300]}")
        else:
            print(f"❌ 错误：{result.get('error', '未知错误')}")
        
        print("-" * 70)
    
    # 交互模式提示
    print(f"\n{'='*70}")
    print("💡 提示：如需交互式对话，请运行:")
    print("   python interactive_chat.py")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 发生错误：{str(e)}")
        print("\n请确保:")
        print("  1. 已激活虚拟环境：.venv\\Scripts\\activate")
        print("  2. 已安装依赖：pip install -r requirements.txt")
        print("  3. .env 文件中配置了正确的 API Keys\n")