"""
测试 diagnosis_agent 的多服务环境支持功能
"""
import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from Routing.diagnosis_agent import (
    load_servers_config,
    determine_config_status,
    get_stopped_services,
    has_stopped_services,
    check_logs_for_service_stop,
    format_stopped_services,
    identify_container_type,
    run_diagnosis
)


def test_config_loading():
    """测试配置加载功能"""
    print("=" * 70)
    print("测试1: 配置加载功能")
    print("=" * 70)
    
    # 加载配置
    servers_config = load_servers_config(".env")
    
    print("\n加载的配置:")
    for service_type, config in servers_config.items():
        if config:
            print(f"  {service_type}: {list(config.keys())}")
        else:
            print(f"  {service_type}: 未配置")
    
    # 判断配置状态
    config_status = determine_config_status(servers_config)
    print(f"\n配置状态: {config_status}")
    print(f"  - none: 无配置")
    print(f"  - partial: 部分配置")
    print(f"  - complete: 完整配置")
    
    return servers_config, config_status


def test_container_identification():
    """测试容器类型识别"""
    print("\n" + "=" * 70)
    print("测试2: 容器类型识别")
    print("=" * 70)
    
    test_cases = [
        ("ruoyi-frontend", "80/tcp", "frontend"),
        ("ruoyi-app", "8080/tcp", "backend"),
        ("mysql-db", "3306/tcp", "database"),
        ("redis-cache", "6379/tcp", "redis"),
        ("nginx-server", "443/tcp", "frontend"),
        ("spring-boot-app", "8080/tcp", "backend"),
    ]
    
    for name, ports, expected in test_cases:
        result = identify_container_type(name, ports)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {name:20s} {ports:15s} -> {result:10s} (期望: {expected})")


def test_service_stop_detection():
    """测试服务未启动检测"""
    print("\n" + "=" * 70)
    print("测试3: 服务未启动检测")
    print("=" * 70)
    
    # 模拟状态：只发现了 backend 容器
    mock_state = {
        "discovered_containers": [
            {"name": "ruoyi-app", "type": "backend", "ports": "8080/tcp"}
        ],
        "logs_data": """
2024-01-15 10:30:00 ERROR Connection refused: 3306
2024-01-15 10:30:01 WARN mysql shutdown unexpectedly
2024-01-15 10:30:02 ERROR redis-server stop failed
2024-01-15 10:30:03 INFO Application started
"""
    }
    
    stopped = get_stopped_services(mock_state)
    print(f"\n已发现的容器: {[c['name'] for c in mock_state['discovered_containers']]}")
    print(f"未启动的服务: {stopped}")
    print(f"has_stopped_services: {has_stopped_services(mock_state)}")
    
    # 检查日志证据
    logs_evidence = check_logs_for_service_stop(mock_state, stopped)
    print(f"\n日志证据 ({len(logs_evidence.splitlines())} 行):")
    for line in logs_evidence.splitlines()[:5]:
        print(f"  {line}")
    
    # 格式化摘要
    summary = format_stopped_services(stopped, logs_evidence)
    print(f"\n格式化摘要:\n{summary[:200]}...")


async def test_diagnosis_workflow():
    """测试诊断工作流（配置不足场景）"""
    print("\n" + "=" * 70)
    print("测试4: 诊断工作流 - 配置不足场景")
    print("=" * 70)
    
    # 创建一个临时的空配置文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write("# Empty config\n")
        temp_env = f.name
    
    try:
        alert_event = {
            "alert_name": "Test Alert",
            "alert_type": "container_restart",
            "alert_time": "2024-01-15T10:30:00",
            "description": "Test alert for config validation"
        }
        
        print("\n执行诊断（无配置）...")
        result = await run_diagnosis(alert_event, env_file_path=temp_env)
        
        print(f"\n诊断结果:")
        print(f"  状态: {result['status']}")
        if result.get('diagnosis'):
            print(f"  置信度: {result['diagnosis'].get('confidence')}")
            print(f"  错误类型: {result['diagnosis'].get('error_type')}")
            print(f"\n报告内容预览:")
            content = result['diagnosis'].get('content', '')
            print(content[:300])
    finally:
        os.unlink(temp_env)


async def main():
    """运行所有测试"""
    print("\n开始测试 diagnosis_agent 多服务环境支持功能\n")
    
    # 测试1: 配置加载
    test_config_loading()
    
    # 测试2: 容器识别
    test_container_identification()
    
    # 测试3: 服务未启动检测
    test_service_stop_detection()
    
    # 测试4: 诊断工作流
    await test_diagnosis_workflow()
    
    print("\n" + "=" * 70)
    print("所有测试完成！")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
