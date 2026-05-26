"""
修复前端容器端口映射
"""
import paramiko
import os
import time
from dotenv import load_dotenv

load_dotenv()

ssh_host = os.getenv('FRONTEND_SSH_HOST', '8.146.236.55')
ssh_port = int(os.getenv('FRONTEND_SSH_PORT', '22'))
ssh_user = os.getenv('FRONTEND_SSH_USER', 'root')
ssh_key_path = os.getenv('FRONTEND_SSH_KEY_PATH', '')

print("连接到服务器...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
ssh.connect(ssh_host, ssh_port, ssh_user, pkey=key)

print("停止并删除当前容�?..")
ssh.exec_command('docker stop ruoyi-frontend')
time.sleep(2)
ssh.exec_command('docker rm ruoyi-frontend')
time.sleep(2)

print("重新创建容器（带端口映射和时区配置）...")
cmd = 'docker run -d --name ruoyi-frontend --restart always -e TZ=Asia/Shanghai -p 80:80 -v /opt/source/RuoYi-VUE/nginx.conf:/etc/nginx/conf.d/default.conf ruoyi-vue-ruoyi-frontend'
stdin, stdout, stderr = ssh.exec_command(cmd)
output = stdout.read().decode().strip()
error = stderr.read().decode().strip()

if output:
    print(f"�?容器已启�? {output[:20]}")
if error:
    print(f"�?错误: {error}")

time.sleep(5)

print("\n验证容器状�?..")
stdin, stdout, stderr = ssh.exec_command('docker ps | grep ruoyi-frontend')
print(stdout.read().decode().strip())

print("\n验证时区设置...")
stdin, stdout, stderr = ssh.exec_command('docker exec ruoyi-frontend date')
print(f"容器时间: {stdout.read().decode().strip()}")

ssh.close()
print("\n�?完成�?)
