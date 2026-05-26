"""
验证前端容器时区设置
"""
import paramiko
import os
from dotenv import load_dotenv

load_dotenv()

ssh_host = os.getenv('FRONTEND_SSH_HOST', '8.146.236.55')
ssh_port = int(os.getenv('FRONTEND_SSH_PORT', '22'))
ssh_user = os.getenv('FRONTEND_SSH_USER', 'root')
ssh_key_path = os.getenv('FRONTEND_SSH_KEY_PATH', '')

print("="*80)
print("验证前端容器时区设置")
print("="*80)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
ssh.connect(ssh_host, ssh_port, ssh_user, pkey=key)

# 1. 检查容器状�?
print("\n1️⃣  容器状�?")
stdin, stdout, stderr = ssh.exec_command('docker ps | grep ruoyi-frontend')
status = stdout.read().decode().strip()
if status:
    print(f"   �?{status}")
else:
    print("   �?容器未运�?)
    ssh.close()
    exit(1)

# 2. 检查容器时�?
print("\n2️⃣  容器时间:")
stdin, stdout, stderr = ssh.exec_command('docker exec ruoyi-frontend date')
container_time = stdout.read().decode().strip()
print(f"   {container_time}")

# 3. 检查时区配�?
print("\n3️⃣  时区配置:")
stdin, stdout, stderr = ssh.exec_command('docker exec ruoyi-frontend cat /etc/timezone 2>/dev/null || echo "未设�?')
timezone = stdout.read().decode().strip()
print(f"   {timezone}")

# 4. 检查环境变�?
print("\n4️⃣  TZ环境变量:")
stdin, stdout, stderr = ssh.exec_command('docker exec ruoyi-frontend printenv TZ')
tz_env = stdout.read().decode().strip()
print(f"   {tz_env if tz_env else '未设�?}")

# 5. 验证时区是否正确
print("\n5️⃣  验证结果:")
if 'CST' in container_time or '+0800' in container_time or 'Asia/Shanghai' in timezone or 'Asia/Shanghai' in tz_env:
    print("   �?时区设置正确 (UTC+8 北京时间)")
    print("   📝 日志时间将显示为北京时间")
else:
    print("   ⚠️  时区可能未正确设�?)
    print(f"   当前时间: {container_time}")

# 6. 端口映射
print("\n6️⃣  端口映射:")
if '0.0.0.0:80->80/tcp' in status or ':80->80' in status:
    print("   �?端口映射正确 (80:80)")
else:
    print("   ⚠️  端口映射可能有问�?)
    print(f"   {status}")

print("\n" + "="*80)
print("�?验证完成!")
print("="*80)
print("\n💡 下一�?")
print("   1. 在前端页面执行一些操作（登录、查询等�?)
print("   2. 运行以下命令查看日志:")
print("      docker logs ruoyi-frontend --tail 20")
print("   3. 确认日志中的时间显示为北京时�?(例如: 19/May/2026:11:xx:xx +0800)")
print()

ssh.close()
