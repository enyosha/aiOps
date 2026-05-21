"""
快速时区检查脚本
快速诊断前端日志时间显示问题
"""
import sys
import os
from datetime import datetime, timezone

print("="*80)
print("快速时区检查")
print("="*80)

# 获取时间信息
now_utc = datetime.now(timezone.utc)
now_local = datetime.now()

print(f"\nUTC时间:   {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
print(f"本地时间:   {now_local.strftime('%Y-%m-%d %H:%M:%S')}")

# 计算时差
local_tz = now_local.astimezone().tzinfo
tz_offset = local_tz.utcoffset(now_local)
if tz_offset:
    hours = tz_offset.total_seconds() / 3600
    print(f"时区偏移:   UTC{hours:+.1f}")
    
    if abs(hours - 8) < 0.1:
        print("\n✅ 时区设置正确 (UTC+8)")
        print("如果前端仍显示UTC时间，请检查:")
        print("  1. 服务器/容器时区设置")
        print("  2. 应用代码中的时间处理逻辑")
        print("  3. Nginx日志格式配置")
    else:
        print(f"\n❌ 时区设置不正确，期望UTC+8，实际为UTC{hours:+.1f}")
        print("建议执行: python test/check_timezone.py 获取详细信息")
else:
    print("\n⚠️ 无法确定时区偏移")

print("\n" + "="*80)
print("详细检查请运行:")
print("  python test/check_timezone.py")
print("  python test/check_server_timezone.py")
print("="*80)
