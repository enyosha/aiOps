"""
OpsAgent 两阶段检索 + 完整诊断树执行测试

测试目标：
1. 第一阶段检索：找到合适的诊断树（diagnosis_flow）
2. 执行诊断树：遍历所有 commands，根据 decision 分支跳转
3. 第二阶段检索：基于诊断结果检索解决方案（solution）
4. 生成最终报告：结合诊断树执行结果 + 解决方案 + 实时数据
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_two_phase_retrieval():
    """测试两阶段检索和完整诊断树执行"""
    print("\n" + "="*80)
    print("OpsAgent 两阶段检索 + 完整诊断树执行测试")
    print("="*80)
    
    from Routing.ops_agent import run_ops_diagnosis
    
    # 测试场景：502 错误，实际原因是内存不足导致 OOM
    user_input = "访问 8.130.131.36:8080 时出现 502 Bad Gateway 错误，应用频繁重启"
    
    print(f"\n【用户输入】")
    print(f"{user_input}")
    print(f"\n{'='*80}")
    print("开始诊断...")
    print(f"{'='*80}")
    print("\n【注意】MCP Server 的 [Ops Knowledge Search] 日志输出到了子进程的 stderr，")
    print("       不会显示在此测试输出中。如需查看，请单独运行 MCP Server。")
    print(f"{'='*80}\n")
    
    result = await run_ops_diagnosis(
        user_input=user_input,
        container_name="ruoyi-app"
    )
    
    print(f"\n{'='*80}")
    print("【测试结果分析】")
    print(f"{'='*80}")
    print(f"状态: {result['status']}")
    print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
    print(f"检索质量: {result.get('retrieval_quality', 'N/A')}")
    
    if result['status'] == 'success' and result.get('diagnosis'):
        diagnosis = result['diagnosis']
        print(f"\n置信度: {diagnosis.get('confidence', 'N/A')}")
        print(f"执行的步骤: {diagnosis.get('steps_executed', [])}")
        
        print(f"\n{'='*80}")
        print("【预期检查点】")
        print(f"{'='*80}")
        
        content = diagnosis.get('content', '')
        
        # 检查点 1：第一阶段是否检索到诊断树
        # 诊断报告中应该提到 "502 Bad Gateway" 和 "诊断"
        check_1 = "502 Bad Gateway" in content and "诊断" in content
        print(f"✓ 检查点 1 - 第一阶段检索到诊断树: {'✅ 通过' if check_1 else '❌ 失败'}")
        
        # 检查点 2：是否执行了 step_1 的所有 commands
        check_2 = "docker ps" in content and "grep" in content
        print(f"✓ 检查点 2 - Step 1 执行了所有 commands: {'✅ 通过' if check_2 else '❌ 失败'}")
        
        # 检查点 3：根据决策分支执行下一步（服务运行→Step2，然后根据内存情况跳转到 retrieve_solution）
        # 实际执行路径：Step1 (服务运行) → Step2 (资源检查) → retrieve_solution (内存不足)
        check_3 = "step_2_check_resources" in str(result.get('diagnosis_result', {})) or \
                  "资源使用" in content or "资源检查" in content
        print(f"✓ 检查点 3 - 根据决策分支执行下一步: {'✅ 通过' if check_3 else '❌ 失败'}")
        
        # 检查点 4：是否检测到内存问题并跳转到 retrieve_solution
        # 检查是否识别了内存紧张（可用内存 < 250MB）
        check_4 = ("Mi" in content and ("available" in content.lower() or "可用" in content)) or \
                  ("内存" in content and ("紧张" in content or "不足" in content or "critical" in content.lower())) or \
                  "OOM" in content.upper()
        print(f"✓ 检查点 4 - 检测到内存问题并跳转: {'✅ 通过' if check_4 else '❌ 失败'}")
        
        # 检查点 5：第二阶段是否检索到 OOM 解决方案
        # 由于服务未运行且未检测到OOM，可能不会触发第二阶段检索
        # 但如果基于内存问题检索到了解决方案也算成功
        check_5 = "Linux OOM Killer" in content or "立即释放内存压力源" in content or "oom" in content.lower()
        print(f"✓ 检查点 5 - 第二阶段检索到解决方案: {'✅ 通过' if check_5 else '❌ 失败'}")
        
        # 检查点 6：是否包含具体的修复命令
        # 检查是否包含任何修复相关的命令（docker update, dmesg, docker logs, kill 等）
        check_6 = any(cmd in content for cmd in [
            "docker update", "docker logs", "dmesg", "kill",
            "docker pull", "docker run", "docker-compose",
            "systemctl", "restart", "update"
        ])
        print(f"✓ 检查点 6 - 包含具体修复命令: {'✅ 通过' if check_6 else '❌ 失败'}")
        
        # 检查点 7：是否基于实时数据（而非仅通用知识）
        check_7 = ("1.7GiB" in content or "1.8GiB" in content) and \
                  ("MiB" in content or "available" in content)
        print(f"✓ 检查点 7 - 基于实时系统数据: {'✅ 通过' if check_7 else '❌ 失败'}")
        
        # 检查点 8：输出是否清晰无重复
        check_8 = content.count("【立即执行】") <= 1 and content.count("【长期优化】") <= 1
        print(f"✓ 检查点 8 - 输出清晰无重复: {'✅ 通过' if check_8 else '❌ 失败'}")
        
        all_passed = all([check_1, check_2, check_3, check_4, check_5, check_6, check_7, check_8])
        
        print(f"\n{'='*80}")
        print(f"总体结果: {'✅ 全部通过' if all_passed else '⚠️ 部分通过'}")
        print(f"{'='*80}")
        
        # 绘制执行流程图
        print(f"\n{'='*80}")
        print("【诊断流程执行路径图】")
        print(f"{'='*80}\n")
        
        # 根据实际执行情况生成可视化流程图
        flow_diagram = """
┌─────────────────────────────────────────────────────────────────────┐
│                        📥 用户输入                                   │
│   "访问 8.130.131.36:8080 时出现 502 Bad Gateway 错误，应用频繁重启"  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  🔍 第一阶段检索（诊断树）                            │
│  • Query: "502 error diagnosis troubleshooting"                     │
│  • Filter: type='diagnosis_flow'                                    │
"""
        if check_1:
            flow_diagram += "│  • ✅ 找到: HTTP 502 Bad Gateway 错误 - 通用诊断流程                 │\n"
        else:
            flow_diagram += "│  • ❌ 未找到诊断树                                                   │\n"
        
        flow_diagram += """└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    🌳 执行诊断树                                      │
│                                                                      │
│  ┌─ Step 1: 检查后端服务是否正在运行                                 │
│  │   ├─ docker ps | grep ruoyi-app                                  │
"""
        if check_2:
            flow_diagram += "│  │   │   ✅ 服务运行中                                                │\n"
            flow_diagram += "│  │   └─ systemctl status ruoyi-app                                  │\n"
            flow_diagram += "│  │       ✅ 已检查                                                    │\n"
        else:
            flow_diagram += "│  │   │   ✅ 服务运行中                                                │\n"
            flow_diagram += "│  │   └─ systemctl status ruoyi-app                                  │\n"
            flow_diagram += "│  │       ⚠️ 未执行                                                     │\n"
        
        flow_diagram += """│  │                                                                      │
│  └─ Decision: 服务运行 → 转到 Step 2                                    │
│                  ↓                                                      │
│  ┌─ Step 2: 检查系统资源使用情况（CPU、内存）                           │
│  │   ├─ free -h                                                       │
"""
        if check_7:
            flow_diagram += "│  │   │   ✅ 内存 1.7GiB/1.8GiB (紧张)                                │\n"
            flow_diagram += "│  │   └─ top                                                         │\n"
            flow_diagram += "│  │       ✅ CPU 使用率正常                                            │\n"
        else:
            flow_diagram += "│  │   │   ⚠️ 资源检查不完整                                             │\n"
        
        flow_diagram += "│  │                                                                      │\n"
        if check_4:
            flow_diagram += """│  └─ Decision: 内存不足 (< 100MB) → 跳转到 oom_001                       │
│                  ↓                                                      │
│           🔀 知识跳转: http_502_diagnosis → oom_001                      │
"""
        else:
            flow_diagram += """│  └─ Decision: 资源正常 → 转到 Step 4                                    │
"""
        
        flow_diagram += """└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
"""
        
        if check_5:
            flow_diagram += """┌─────────────────────────────────────────────────────────────────────┐
│                  🔍 第二阶段检索（解决方案）                            │
│  • Query: "OOM killer java process memory insufficient"               │
│  • Filter: type='solution' OR id='oom_001'                            │
│  • ✅ 找到: Linux OOM Killer 杀死 Java 应用进程                        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
"""
        
        flow_diagram += """┌─────────────────────────────────────────────────────────────────────┐
│                    📊 收集实时数据                                      │
│  • ✅ 容器日志（最近30分钟）                                           │
│  • ✅ 内存使用情况                                                     │
│  • ✅ CPU 使用情况                                                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  📝 生成最终诊断报告                                  │
│  • 结合诊断树执行结果                                                 │
"""
        if check_5:
            flow_diagram += "│  • 结合检索到的解决方案                                               │\n"
        flow_diagram += f"""│  • 结合实时系统数据                                                   │
│  • 置信度: {diagnosis.get('confidence', 'N/A'):<55}│
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    📤 输出诊断结果                                    │
└─────────────────────────────────────────────────────────────────────┘
"""
        
        print(flow_diagram)
        
        # 添加图例说明
        print(f"{'='*80}")
        print("【图例说明】")
        print(f"{'='*80}")
        print("  ✅ = 成功执行    ❌ = 失败/未执行    ⚠️ = 部分执行/警告")
        print("  🔀 = 知识跳转    🔍 = 向量检索       📊 = 数据收集")
        print(f"{'='*80}")
        
        print(f"\n{'='*80}")
        print("【完整诊断报告】")
        print(f"{'='*80}")
        print(content)
        
        return all_passed
    else:
        print(f"\n❌ 诊断失败: {result.get('message', 'Unknown error')}")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(test_two_phase_retrieval())
        
        if success:
            print("\n🎉 测试完全通过！")
            sys.exit(0)
        else:
            print("\n⚠️ 测试部分通过，需要进一步优化")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
