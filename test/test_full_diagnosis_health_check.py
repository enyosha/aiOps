"""
完整诊断流程测试 - 验证健康检查功能集成
模拟真实告警事件，触发完整的诊断流程
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()


async def test_full_diagnosis_with_health_check():
    """测试完整诊断流程，包含健康检查"""
    from Routing.diagnosis_agent import diagnosis_workflow
    
    print("="*80)
    print("完整诊断流程测试 - 健康检查功能验证")
    print("="*80)
    
    # 构造测试告警事件
    alert_event = {
        "alert_name": "服务访问超时",
        "alert_type": "timeout",
        "description": "前端服务响应缓慢，部分请求超时",
        "timestamp": "2026-05-19T12:40:00Z"
    }
    
    # 构造初始状态
    initial_state = {
        "alert_event": alert_event,
        "container_name": "ruoyi-app",
        "messages": [],
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 15,  # 增加迭代次数以允许执行健康检查
        "actions_taken": [],
        "anomaly_timestamps": [],
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
        "service_status": None,
        "mysql_status": None,
        "log_search_range_minutes": 30,
        "logs_collected_ranges": [],
        "diagnosis_result": None,
        "config_status": "complete",
        "servers_config": {
            "frontend": {
                "ssh_host": "8.146.236.55",
                "ssh_port": 22,
                "ssh_user": "root",
                "ssh_key_path": "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps_Server.pem",
                "container_name": "ruoyi-frontend"
            },
            "backend": {
                "ssh_host": "8.130.131.36",
                "ssh_port": 22,
                "ssh_user": "root",
                "ssh_key_path": "c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/aiOps_Server.pem",
                "container_name": "ruoyi-app"
            },
            "database": {
                "host": "8.130.131.36",
                "port": 3306,
                "user": "root",
                "password": "",
                "name": ""
            },
            "redis": {
                "host": "8.130.131.36",
                "port": 6379,
                "password": ""
            }
        },
        "discovered_containers": [
            {
                "name": "ruoyi-frontend",
                "type": "frontend",
                "ports": "80->80/tcp",
                "status": "running",
                "server": "8.146.236.55",
                "issue": None
            },
            {
                "name": "ruoyi-app",
                "type": "backend",
                "ports": "8080->8080/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            },
            {
                "name": "mysql",
                "type": "database",
                "ports": "3306->3306/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            },
            {
                "name": "redis",
                "type": "redis",
                "ports": "6379->6379/tcp",
                "status": "running",
                "server": "8.130.131.36",
                "issue": None
            }
        ],
        "service_status_summary": "",
        "docker_stats_info": "",
        "next_action": None,
        "health_check_results": None,
        "port_check_results": None,
        "performance_metrics": None,
        "health_check_summary": None
    }
    
    print("\n🔄 开始执行诊断流程...")
    print("="*80)
    
    try:
        # 执行诊断工作流
        result = await diagnosis_workflow.ainvoke(initial_state)
        
        print("\n" + "="*80)
        print("✅ 诊断完成!")
        print("="*80)
        
        # 检查诊断结果
        diagnosis_result = result.get('diagnosis_result', {})
        content = diagnosis_result.get('content', '')
        
        if content:
            print("\n📊 诊断报告:")
            print("-"*80)
            print(content)
            print("-"*80)
            
            # 验证健康检查是否执行
            print("\n🔍 健康检查功能验证:")
            checks = {
                "包含健康检查摘要": "【健康检查摘要】" in content or "健康检查" in content,
                "包含性能指标详情": "【性能指标详情】" in content or "CPU=" in content,
                "明确区分历史/当前问题": "已恢复的历史问题" in content or "当前活跃" in content or "系统未发现当前错误" in content,
                "引用具体日志证据": any(keyword in content for keyword in ["upstream timed out", "504", "SocketTimeoutException"]),
            }
            
            all_passed = True
            for check_name, passed in checks.items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check_name}: {'通过' if passed else '未通过'}")
                if not passed:
                    all_passed = False
            
            # 检查state中是否有健康检查数据
            print("\n📋 State中的健康检查数据:")
            print(f"  health_check_results: {'✅ 存在' if result.get('health_check_results') else '❌ 不存在'}")
            print(f"  port_check_results: {'✅ 存在' if result.get('port_check_results') else '❌ 不存在'}")
            print(f"  performance_metrics: {'✅ 存在' if result.get('performance_metrics') else '❌ 不存在'}")
            print(f"  health_check_summary: {'✅ 存在' if result.get('health_check_summary') else '❌ 不存在'}")
            
            if result.get('health_check_summary'):
                print(f"\n  健康检查摘要内容:\n{result['health_check_summary']}")
            
            if all_passed:
                print("\n🎉 所有质量检查通过! 健康检查功能已成功集成!")
            else:
                print("\n⚠️  部分检查未通过，可能需要进一步调试")
        else:
            print("\n❌ 诊断结果为空!")
            print(f"完整结果keys: {list(result.keys())}")
    
    except Exception as e:
        print(f"\n❌ 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_full_diagnosis_with_health_check())
