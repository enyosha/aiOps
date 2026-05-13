"""
快速测试 Client_test.py 的诊断功能
"""
# 屏蔽 paramiko 和 cryptography 的弃用警告
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='cryptography')

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
from Routing.diagnosis_agent import run_diagnosis, load_servers_config, determine_config_status
from datetime import datetime

async def test():
    # 加载 .env 文件
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(env_path)
    
    print("=" * 70)
    print("测试: Client_test.py 诊断功能")
    print("=" * 70)
    
    # 检查配置加载
    config = load_servers_config(env_path)
    status = determine_config_status(config)
    configured_count = sum(1 for v in config.values() if v)
    
    print(f"\n📋 配置状态:")
    print(f"   状态: {status}")
    print(f"   已配置服务: {configured_count}/4")
    print(f"   - Frontend: {'✓' if config['frontend'] else '✗'}")
    print(f"   - Backend: {'✓' if config['backend'] else '✗'}")
    print(f"   - Database: {'✓' if config['database'] else '✗'}")
    print(f"   - Redis: {'✓' if config['redis'] else '✗'}")
    
    if status == 'none':
        print("\n❌ 错误: 配置信息不足，无法进行诊断")
        return
    
    print("\n🔍 开始诊断...")
    
    # 创建告警事件
    alert_event = {
        "alert_name": "",
        "alert_type": "",
        "alert_time": datetime.now().isoformat(),
        "description": "应用响应缓慢"
    }
    
    # 运行诊断
    result = await run_diagnosis(alert_event, container_name="ruoyi-app", env_file_path=env_path)
    
    print("\n" + "=" * 70)
    print("测试结果")
    print("=" * 70)
    
    if result["status"] == "success":
        print(f"✅ 诊断成功")
        print(f"   迭代次数: {result.get('iteration_count', 'N/A')}")
        
        data_collected = result.get('data_collected', {})
        print(f"\n📊 数据收集状态:")
        print(f"   - 日志: {'✓' if data_collected.get('logs') else '✗'}")
        print(f"   - 内存: {'✓' if data_collected.get('memory') else '✗'}")
        print(f"   - CPU: {'✓' if data_collected.get('cpu') else '✗'}")
        print(f"   - 服务状态: {'✓' if data_collected.get('service_status') else '✗'}")
    else:
        print(f"❌ 诊断失败")
        print(f"   错误: {result.get('message', '未知错误')}")
    
    print("=" * 70)

if __name__ == "__main__":
    try:
        asyncio.run(test())
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被中断")
    except Exception as e:
        print(f"\n❌ 测试出错: {str(e)}")
        import traceback
        traceback.print_exc()
