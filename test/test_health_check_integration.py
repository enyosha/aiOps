"""
测试健康检查功能集�?
验证HTTP健康检查、端口连通性测试、性能指标获取功能
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()


def test_health_check_functions():
    """测试三个健康检查函�?""
    from Routing.diagnosis_agent import check_http_health, check_port_connectivity, get_performance_metrics
    
    print("="*80)
    print("测试健康检查功�?)
    print("="*80)
    
    # 测试1: HTTP健康检�?
    print("\n【测�?】HTTP健康检�?)
    print("-"*80)
    try:
        result = check_http_health("8.146.236.55", 80, "/", timeout=5)
        print(f"目标: 8.146.236.55:80/")
        print(f"结果: {result}")
        if result['status'] == 'healthy':
            print("�?HTTP健康检查通过")
        else:
            print(f"⚠️ HTTP健康检查状�? {result['status']}")
    except Exception as e:
        print(f"�?HTTP健康检查失�? {e}")
    
    # 测试2: 端口连通性测�?
    print("\n【测�?】端口连通性测�?)
    print("-"*80)
    try:
        result = check_port_connectivity("8.146.236.55", 80, timeout=3)
        print(f"目标: 8.146.236.55:80")
        print(f"结果: {result}")
        if result['reachable']:
            print("�?端口连通性测试通过")
        else:
            print(f"�?端口不可�? {result.get('error')}")
    except Exception as e:
        print(f"�?端口连通性测试失�? {e}")
    
    # 测试3: 性能指标获取
    print("\n【测�?】性能指标获取")
    print("-"*80)
    try:
        result = get_performance_metrics("ruoyi-app", ssh_host="8.130.131.36")
        print(f"目标容器: ruoyi-app @ 8.130.131.36")
        print(f"结果: {result}")
        if not result.get('error'):
            print(f"�?性能指标获取成功")
            print(f"   CPU: {result['cpu_percent']}%")
            print(f"   内存: {result['memory_percent']}% ({result['memory_usage_mb']:.1f}MB / {result['memory_limit_mb']:.1f}MB)")
        else:
            print(f"�?性能指标获取失败: {result['error']}")
    except Exception as e:
        print(f"�?性能指标获取失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*80)
    print("测试完成")
    print("="*80)


if __name__ == "__main__":
    test_health_check_functions()
