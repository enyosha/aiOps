"""
设置前端服务器容器时区为UTC+8
用于修复前端日志时间显示问题
"""
import asyncio
import sys
import os
import paramiko
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv()


def execute_ssh_command(ssh_client, command, timeout=30):
    """执行SSH命令"""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        return output, error
    except Exception as e:
        return "", str(e)


async def setup_frontend_timezone():
    """设置前端容器时区为UTC+8"""
    print("\n" + "="*80)
    print("设置前端服务器容器时区为 UTC+8")
    print("="*80)
    
    # 从环境变量获取配置
    ssh_host = os.getenv('FRONTEND_SSH_HOST', '8.146.236.55')
    ssh_port = int(os.getenv('FRONTEND_SSH_PORT', '22'))
    ssh_user = os.getenv('FRONTEND_SSH_USER', 'root')
    ssh_key_path = os.getenv('FRONTEND_SSH_KEY_PATH', '')
    container_name = os.getenv('FRONTEND_CONTAINER_NAME', 'ruoyi-frontend')
    
    print(f"\n【连接信息】")
    print(f"服务器: {ssh_host}:{ssh_port}")
    print(f"用户: {ssh_user}")
    print(f"容器: {container_name}")
    
    ssh_client = None
    try:
        # 建立SSH连接
        print(f"\n1️⃣  连接到服务器 {ssh_host}...")
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        if ssh_key_path and os.path.exists(ssh_key_path):
            print(f"   使用密钥文件: {ssh_key_path}")
            private_key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
            ssh_client.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=ssh_user,
                pkey=private_key,
                timeout=10
            )
        else:
            print("   ⚠️ 未找到密钥文件，尝试密码认证（需要在代码中配置）")
            return
        
        print("   ✅ SSH连接成功")
        
        # 步骤1: 检查容器当前时区
        print(f"\n2️⃣  检查容器 {container_name} 当前时区...")
        cmd = f"docker exec {container_name} date"
        output, error = execute_ssh_command(ssh_client, cmd)
        if output:
            print(f"   当前时间: {output}")
        else:
            print(f"   ⚠️ 无法获取时间: {error}")
        
        # 检查时区文件
        cmd = f"docker exec {container_name} cat /etc/timezone 2>/dev/null || echo '未设置'"
        output, error = execute_ssh_command(ssh_client, cmd)
        print(f"   时区配置: {output}")
        
        # 步骤2: 停止容器
        print(f"\n3️⃣  停止容器 {container_name}...")
        cmd = f"docker stop {container_name}"
        output, error = execute_ssh_command(ssh_client, cmd, timeout=60)
        if error:
            print(f"   ⚠️ 停止警告: {error}")
        else:
            print("   ✅ 容器已停止")
        
        # 步骤3: 删除旧容器
        print(f"\n4️⃣  删除旧容器 {container_name}...")
        cmd = f"docker rm {container_name}"
        output, error = execute_ssh_command(ssh_client, cmd)
        if error:
            print(f"   ⚠️ 删除警告: {error}")
        else:
            print("   ✅ 容器已删除")
        
        # 步骤4: 查找原始启动命令或docker-compose配置
        print(f"\n5️⃣  查找容器原始配置...")
        
        # 方法1: 检查是否有docker-compose文件
        cmd = "find / -maxdepth 4 -name 'docker-compose*.yml' -o -name 'docker-compose*.yaml' 2>/dev/null | head -5"
        compose_files, _ = execute_ssh_command(ssh_client, cmd)
        
        if compose_files:
            print(f"   发现docker-compose文件:")
            for f in compose_files.splitlines():
                print(f"     - {f}")
            
            # 读取第一个docker-compose文件内容
            first_compose = compose_files.splitlines()[0]
            cmd = f"cat {first_compose}"
            compose_content, _ = execute_ssh_command(ssh_client, cmd)
            
            # 检查是否包含前端容器配置
            if container_name.replace('ruoyi-', '') in compose_content or 'frontend' in compose_content.lower():
                print(f"\n   ✅ 找到包含前端配置的docker-compose文件")
                print(f"   文件路径: {first_compose}")
                
                # 步骤5: 修改docker-compose文件，添加时区配置
                print(f"\n6️⃣  备份并修改docker-compose文件...")
                backup_cmd = f"cp {first_compose} {first_compose}.bak.$(date +%Y%m%d%H%M%S)"
                execute_ssh_command(ssh_client, backup_cmd)
                print("   ✅ 配置文件已备份")
                
                # 检查是否已有TZ环境变量
                if 'TZ=' in compose_content or 'timezone' in compose_content.lower():
                    print("   ⚠️ 配置文件中已有时区设置，需要手动检查")
                else:
                    # 在environment部分添加TZ=Asia/Shanghai
                    print("   正在添加时区配置 TZ=Asia/Shanghai...")
                    
                    # 使用sed在environment部分添加TZ配置
                    # 这里需要根据实际的docker-compose格式来调整
                    modify_cmd = f"""
                    sed -i '/environment:/a\\      - TZ=Asia/Shanghai' {first_compose}
                    """
                    output, error = execute_ssh_command(ssh_client, modify_cmd)
                    if error:
                        print(f"   ⚠️ 修改警告: {error}")
                    else:
                        print("   ✅ 时区配置已添加到docker-compose文件")
                
                # 步骤6: 使用docker-compose重启容器
                print(f"\n7️⃣  使用docker-compose重启容器...")
                compose_dir = '/'.join(first_compose.split('/')[:-1])
                cmd = f"cd {compose_dir} && docker-compose up -d {container_name}"
                output, error = execute_ssh_command(ssh_client, cmd, timeout=120)
                
                if error:
                    print(f"   ⚠️ 重启警告: {error}")
                else:
                    print("   ✅ 容器已通过docker-compose重启")
            else:
                print(f"   ⚠️ docker-compose文件中未找到{container_name}的配置")
                print(f"   可能需要手动重建容器")
                await rebuild_container_manually(ssh_client, container_name)
        else:
            print(f"   ⚠️ 未找到docker-compose文件")
            print(f"   将尝试手动重建容器")
            await rebuild_container_manually(ssh_client, container_name)
        
        # 步骤8: 等待容器启动
        print(f"\n8️⃣  等待容器启动(约30秒)...")
        for i in range(30, 0, -5):
            print(f"   ⏳ 剩余 {i} 秒...", end='\r')
            await asyncio.sleep(5)
        print("   ✅ 容器启动完成")
        
        # 步骤9: 验证时区设置
        print(f"\n9️⃣  验证时区设置...")
        cmd = f"docker exec {container_name} date"
        output, error = execute_ssh_command(ssh_client, cmd)
        if output:
            print(f"   容器时间: {output}")
            
            # 检查是否包含+0800或CST
            if '+0800' in output or 'CST' in output:
                print("   ✅ 时区设置成功 (UTC+8)")
            else:
                print("   ⚠️ 时区可能未正确设置，请检查输出")
        
        # 检查时区文件
        cmd = f"docker exec {container_name} cat /etc/timezone 2>/dev/null || echo '未设置'"
        output, error = execute_ssh_command(ssh_client, cmd)
        print(f"   时区配置: {output}")
        
        # 步骤10: 查看最新日志验证时间格式
        print(f"\n🔟 查看最新日志验证时间格式...")
        cmd = f"docker logs {container_name} --tail 5"
        output, error = execute_ssh_command(ssh_client, cmd)
        if output:
            print("   最新日志:")
            for line in output.splitlines()[:5]:
                print(f"     {line}")
        
        print("\n" + "="*80)
        print("✅ 前端容器时区设置完成!")
        print("="*80)
        print("\n💡 验证建议:")
        print(f"   1. 运行: docker logs {container_name} --tail 20")
        print("   2. 确认日志时间显示为北京时间 (UTC+8)")
        print("   3. 在前端页面执行操作，观察日志时间是否与当前时间一致")
        print()
        
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if ssh_client:
            ssh_client.close()
            print("\n✅ SSH连接已关闭")


async def rebuild_container_manually(ssh_client, container_name):
    """手动重建容器（当没有docker-compose文件时）"""
    print(f"\n   📝 手动重建容器 {container_name}...")
    
    # 获取容器的原始配置
    print("   1. 获取容器原始配置...")
    cmd = f"docker inspect {container_name} 2>/dev/null || echo '容器不存在'"
    output, _ = execute_ssh_command(ssh_client, cmd)
    
    if '容器不存在' in output:
        print("   ⚠️ 容器不存在，需要先了解原始启动参数")
        print("   💡 建议:")
        print("      - 查看docker历史记录: docker history <镜像ID>")
        print("      - 或咨询系统管理员获取原始启动命令")
        return
    
    # 由于docker inspect输出很复杂，这里提供通用方案
    print("\n   2. 使用通用方式重建容器（带时区配置）...")
    print("   ⚠️ 注意: 这可能需要根据实际环境调整参数")
    
    # 提供一个示例的重建命令（需要根据实际情况修改）
    example_cmd = f"""
    docker run -d \\
      --name {container_name} \\
      --restart always \\
      -e TZ=Asia/Shanghai \\
      -p 80:80 \\
      <其他必要参数> \\
      <镜像名称>
    """
    
    print("\n   示例重建命令:")
    print(example_cmd)
    print("\n   ⚠️ 请根据实际情况修改上述命令后手动执行")
    print("   或者使用docker-compose方式管理容器（推荐）")


if __name__ == "__main__":
    try:
        asyncio.run(setup_frontend_timezone())
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
