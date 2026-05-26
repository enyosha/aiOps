"""
快速设置前端容器时�?- 简化版
直接通过SSH连接到前端服务器并设置容器时�?
"""
import sys
import os
import paramiko
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv()


def execute_command(ssh_client, command, timeout=30):
    """执行SSH命令并返回结�?""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        return output, error
    except Exception as e:
        return "", str(e)


def main():
    """主函�?""
    print("\n" + "="*80)
    print("快速设置前端容器时区为 UTC+8")
    print("="*80)
    
    # 从环境变量获取配�?
    ssh_host = os.getenv('FRONTEND_SSH_HOST', '8.146.236.55')
    ssh_port = int(os.getenv('FRONTEND_SSH_PORT', '22'))
    ssh_user = os.getenv('FRONTEND_SSH_USER', 'root')
    ssh_key_path = os.getenv('FRONTEND_SSH_KEY_PATH', '')
    container_name = os.getenv('FRONTEND_CONTAINER_NAME', 'ruoyi-frontend')
    
    print(f"\n📋 配置信息:")
    print(f"   服务�? {ssh_host}:{ssh_port}")
    print(f"   用户: {ssh_user}")
    print(f"   容器: {container_name}")
    print(f"   密钥: {ssh_key_path if ssh_key_path else '未配�?}")
    
    # 检查密钥文�?
    if not ssh_key_path or not os.path.exists(ssh_key_path):
        print(f"\n�?错误: 找不到SSH密钥文件: {ssh_key_path}")
        print("💡 请在 .env 文件中正确配�?FRONTEND_SSH_KEY_PATH")
        return
    
    ssh_client = None
    try:
        # 建立SSH连接
        print(f"\n🔗 连接到服务器...")
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        private_key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
        ssh_client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=ssh_user,
            pkey=private_key,
            timeout=10
        )
        print("�?SSH连接成功\n")
        
        # 步骤1: 检查容器状�?
        print("1️⃣  检查容器状�?..")
        cmd = f"docker ps | grep {container_name}"
        output, error = execute_command(ssh_client, cmd)
        
        if container_name in output:
            print(f"   �?容器 {container_name} 正在运行")
            container_exists = True
        else:
            print(f"   ⚠️ 容器 {container_name} 未运行或不存�?)
            container_exists = False
            
            # 检查是否有已停止的容器
            cmd = f"docker ps -a | grep {container_name}"
            output, _ = execute_command(ssh_client, cmd)
            if container_name in output:
                print(f"   ℹ️  找到已停止的容器，将先删�?)
                cmd = f"docker rm {container_name}"
                execute_command(ssh_client, cmd)
                print(f"   �?旧容器已删除")
            else:
                print(f"   ℹ️  容器不存在，将直接创建新容器")
        
        # 步骤2: 显示当前时间（如果容器存在）
        if container_exists:
            print("\n2️⃣  当前容器时间:")
            cmd = f"docker exec {container_name} date"
            output, _ = execute_command(ssh_client, cmd)
            print(f"   {output}")
            
            cmd = f"docker exec {container_name} cat /etc/timezone 2>/dev/null || echo '未设�?"
            output, _ = execute_command(ssh_client, cmd)
            print(f"   时区: {output}\n")
        else:
            print("\n2️⃣  容器不存在，将创建新容器")
        
        # 步骤3: 询问用户确认
        print("⚠️  即将执行以下操作:")
        print("   1. 停止并删除当前容�?)
        print("   2. 使用相同时区和配置重新启动容器（添加 TZ=Asia/Shanghai�?)
        print("   3. 验证新容器的时区设置")
        
        confirm = input("\n是否继续? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("�?操作已取�?)
            return
        
        # 步骤4: 获取容器的镜像和配置
        print("\n3️⃣  获取容器配置信息...")
        
        if container_exists:
            cmd = f"docker inspect --format='{{{{.Config.Image}}}}' {container_name}"
            image, _ = execute_command(ssh_client, cmd)
            print(f"   镜像: {image}")
            
            # 获取端口映射
            cmd = "docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{$p}} -> {{(index $conf 0).HostPort}} {{end}}' " + container_name
            ports, _ = execute_command(ssh_client, cmd)
            print(f"   端口: {ports}")
            
            # 获取环境变量
            cmd = "docker inspect --format='{{range .Config.Env}}{{.}} {{end}}' " + container_name
            env_vars, _ = execute_command(ssh_client, cmd)
            print(f"   环境变量数量: {len(env_vars.split()) if env_vars else 0}")
            
            # 获取卷挂�?
            cmd = "docker inspect --format='{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' " + container_name
            volumes, _ = execute_command(ssh_client, cmd)
            if volumes:
                print(f"   卷挂�? {volumes[:100]}..." if len(volumes) > 100 else f"   卷挂�? {volumes}")
        else:
            # 容器不存在，使用默认配置
            print("   ⚠️  容器不存在，使用默认配置")
            image = "ruoyi-vue-ruoyi-frontend"
            ports = "80/tcp -> 80"
            volumes = "/opt/source/RuoYi-VUE/nginx.conf:/etc/nginx/conf.d/default.conf"
            env_vars = ""
            print(f"   镜像: {image}")
            print(f"   端口: {ports}")
            print(f"   卷挂�? {volumes}")
        
        # 步骤5: 停止并删除容器（如果容器存在�?
        if container_exists:
            print(f"\n4️⃣  停止容器 {container_name}...")
            cmd = f"docker stop {container_name}"
            output, error = execute_command(ssh_client, cmd, timeout=60)
            if error:
                print(f"   ⚠️ 警告: {error}")
            else:
                print("   �?容器已停�?)
            
            print(f"\n5️⃣  删除容器 {container_name}...")
            cmd = f"docker rm {container_name}"
            output, error = execute_command(ssh_client, cmd)
            if error:
                print(f"   ⚠️ 警告: {error}")
            else:
                print("   �?容器已删�?)
        else:
            print(f"\n4️⃣  跳过停止/删除步骤（容器不存在�?)
        
        # 步骤6: 重建容器（带时区配置�?
        print(f"\n6️⃣  重建容器（添�?TZ=Asia/Shanghai�?..")
        
        # 构建docker run命令
        docker_cmd = f"docker run -d --name {container_name} --restart always -e TZ=Asia/Shanghai"
        
        # 添加端口映射
        if ports and '->' in ports:
            # 解析格式: "80/tcp -> 80 "
            port_mappings = ports.strip().split()
            for mapping in port_mappings:
                if '->' in mapping:
                    parts = mapping.split('->')
                    if len(parts) == 2:
                        container_port = parts[0].strip().split('/')[0]  # 移除 /tcp
                        host_port = parts[1].strip()
                        if host_port:  # 确保主机端口不为�?
                            docker_cmd += f" -p {host_port}:{container_port}"
                            print(f"   添加端口映射: {host_port}:{container_port}")
        
        # 添加卷挂�?
        if volumes:
            for volume_mapping in volumes.split():
                if ':' in volume_mapping:
                    docker_cmd += f" -v {volume_mapping}"
        
        # 添加其他环境变量（排除TZ，因为我们已经添加了�?
        if env_vars:
            for env in env_vars.split():
                if '=' in env and not env.startswith('TZ='):
                    docker_cmd += f" -e {env}"
        
        # 添加镜像名称
        docker_cmd += f" {image}"
        
        print(f"   执行命令: {docker_cmd[:200]}..." if len(docker_cmd) > 200 else f"   执行命令: {docker_cmd}")
        
        output, error = execute_command(ssh_client, docker_cmd, timeout=120)
        if error:
            print(f"   �?启动失败: {error}")
            print("\n💡 建议手动执行以下命令:")
            print(f"   docker run -d \\")
            print(f"     --name {container_name} \\")
            print(f"     --restart always \\")
            print(f"     -e TZ=Asia/Shanghai \\")
            print(f"     <其他必要参数> \\")
            print(f"     {image}")
            return
        else:
            print(f"   �?容器已启�? {output[:20]}")
        
        # 步骤7: 等待容器启动
        print(f"\n7️⃣  等待容器启动(�?0�?...")
        import time
        for i in range(20, 0, -5):
            print(f"   �?剩余 {i} �?..", end='\r')
            time.sleep(5)
        print("   �?容器启动完成")
        
        # 步骤8: 验证时区设置
        print(f"\n8️⃣  验证时区设置...")
        cmd = f"docker exec {container_name} date"
        output, _ = execute_command(ssh_client, cmd)
        print(f"   容器时间: {output}")
        
        cmd = f"docker exec {container_name} cat /etc/timezone"
        output, _ = execute_command(ssh_client, cmd)
        print(f"   时区配置: {output}")
        
        if '+0800' in output or 'CST' in output or 'Asia/Shanghai' in output:
            print("   �?时区设置成功 (UTC+8)")
        else:
            print("   ⚠️ 请检查输出确认时区是否正�?)
        
        # 步骤9: 查看日志
        print(f"\n9️⃣  查看最新日�?..")
        cmd = f"docker logs {container_name} --tail 10"
        output, _ = execute_command(ssh_client, cmd)
        if output:
            print("   最新日�?")
            for line in output.splitlines()[:10]:
                print(f"     {line}")
        
        print("\n" + "="*80)
        print("�?前端容器时区设置完成!")
        print("="*80)
        print("\n💡 下一�?")
        print(f"   1. 在前端页面执行一些操�?)
        print(f"   2. 运行: docker logs {container_name} --tail 20")
        print(f"   3. 确认日志时间显示为北京时�?(UTC+8)")
        print()
        
    except FileNotFoundError:
        print(f"\n�?错误: 找不到SSH密钥文件: {ssh_key_path}")
        print("💡 请检�?.env 文件中的 FRONTEND_SSH_KEY_PATH 配置")
    except paramiko.AuthenticationException:
        print("\n�?错误: SSH认证失败")
        print("💡 请检查密钥文件和权限")
    except paramiko.SSHException as e:
        print(f"\n�?错误: SSH连接失败 - {str(e)}")
    except Exception as e:
        print(f"\n�?错误: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if ssh_client:
            ssh_client.close()
            print("\n�?SSH连接已关�?)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
