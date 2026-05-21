"""
检查服务器时区设置
用于诊断前端日志时间显示为UTC时间而非本地时间的问题
"""
import asyncio
import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()


async def check_timezone():
    """检查服务器时区设置"""
    print("\n" + "="*80)
    print("服务器时区设置检查")
    print("="*80)
    
    # 获取当前时间信息
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()
    
    print(f"\n【当前UTC时间】: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"【当前本地时间】: {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"【本地时区偏移】: {now_local.astimezone().strftime('%z')}")
    
    # 计算时差
    utc_offset = now_local.utcoffset()
    if utc_offset is not None:
        hours = utc_offset.total_seconds() / 3600
        print(f"【与UTC时差】: {hours:+.1f} 小时")
        
        if abs(hours - 8) < 0.1:
            print("✅ 时区设置正确 (UTC+8)")
        else:
            print(f"❌ 时区设置不正确，期望UTC+8，实际为UTC{hours:+.1f}")
    else:
        # Windows系统可能需要通过其他方式获取时区信息
        local_tz = now_local.astimezone().tzinfo
        tz_offset = local_tz.utcoffset(now_local)
        if tz_offset:
            hours = tz_offset.total_seconds() / 3600
            print(f"【与UTC时差】: {hours:+.1f} 小时")
            
            if abs(hours - 8) < 0.1:
                print("✅ 时区设置正确 (UTC+8)")
            else:
                print(f"❌ 时区设置不正确，期望UTC+8，实际为UTC{hours:+.1f}")
        else:
            print("⚠️ 无法确定时区偏移")
    
    # 检查系统环境变量
    print(f"\n【系统环境变量】")
    tz_env = os.environ.get('TZ', '未设置')
    print(f"TZ环境变量: {tz_env}")
    
    # 检查Python时区
    print(f"\n【Python时区信息】")
    print(f"本地时区名称: {time.tzname}")
    print(f"DST是否生效: {time.daylight}")
    print(f"时区缩写: {time.tzname[0]} / {time.tzname[1] if time.daylight else 'N/A'}")
    
    # 建议的解决方案
    print(f"\n【建议解决方案】")
    print("1. 在服务器上设置时区:")
    print("   Linux: sudo timedatectl set-timezone Asia/Shanghai")
    print("   或者: export TZ='Asia/Shanghai'")
    print("2. 在Docker容器中设置时区:")
    print("   docker run -e TZ=Asia/Shanghai ...")
    print("3. 在应用代码中显式设置时区:")
    print("   import os")
    print("   os.environ['TZ'] = 'Asia/Shanghai'")
    print("   time.tzset()  # Linux/Mac需要")


if __name__ == "__main__":
    try:
        import time
        asyncio.run(check_timezone())
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
