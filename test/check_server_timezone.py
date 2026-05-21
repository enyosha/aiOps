"""
检查远程服务器时区设置
用于诊断前端日志时间显示为UTC时间而非本地时间的问题
支持通过SSH检查远程服务器或Docker容器的时区配置
"""
import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()


async def check_remote_timezone():
    """检查远程服务器时区设置"""
    print("\n" + "="*80)
    print("远程服务器时区设置检查")
    print("="*80)
    
    # 获取SSH隧道管理器
    from Routing.ssh_tunnel_manager import ssh_tunnel_manager
    
    # 从环境变量获取SSH配置
    ssh_host = os.getenv('SSH_HOST', 'localhost')
    ssh_port = int(os.getenv('SSH_PORT', '22'))
    ssh_user = os.getenv('SSH_USER', 'root')
    ssh_password = os.getenv('SSH_PASSWORD', '')
    
    print(f"\n【SSH连接信息】")
    print(f"主机: {ssh_host}")
    print(f"端口: {ssh_port}")
    print(f"用户: {ssh_user}")
    
    try:
        # 建立SSH连接
        tunnel = await ssh_tunnel_manager.create_tunnel(
            host=ssh_host,
            port=ssh_port,
            username=ssh_user,
            password=ssh_password
        )
        
        if not tunnel:
            print("❌ 无法建立SSH连接")
            return
        
        print("✅ SSH连接成功")
        
        # 执行时区检查命令
        commands = [
            ("date", "当前系统时间"),
            ("timedatectl", "系统时区配置 (systemd)"),
            ("cat /etc/timezone", "时区文件内容"),
            ("echo $TZ", "TZ环境变量"),
            ("ls -la /etc/localtime", "本地时间链接"),
        ]
        
        print(f"\n【远程服务器时区信息】")
        for cmd, description in commands:
            try:
                result = await ssh_tunnel_manager.execute_command(tunnel, cmd)
                print(f"\n{description}:")
                print(f"命令: {cmd}")
                print(f"输出: {result.strip() if result else '无输出'}")
            except Exception as e:
                print(f"\n{description}:")
                print(f"命令: {cmd}")
                print(f"错误: {str(e)}")
        
        # 检查Docker容器时区
        print(f"\n【Docker容器时区检查】")
        container_names = ['ruoyi-app', 'ruoyi-nginx', 'ruoyi-mysql', 'ruoyi-redis']
        
        for container in container_names:
            try:
                # 检查容器是否存在
                status_cmd = f"docker inspect --format='{{{{.State.Running}}}}' {container}"
                status_result = await ssh_tunnel_manager.execute_command(tunnel, status_cmd)
                
                if status_result.strip() == 'true':
                    print(f"\n容器 {container}:")
                    
                    # 检查容器内时间
                    time_cmd = f"docker exec {container} date"
                    time_result = await ssh_tunnel_manager.execute_command(tunnel, time_cmd)
                    print(f"  容器时间: {time_result.strip()}")
                    
                    # 检查容器时区
                    tz_cmd = f"docker exec {container} cat /etc/timezone 2>/dev/null || echo '未设置'"
                    tz_result = await ssh_tunnel_manager.execute_command(tunnel, tz_cmd)
                    print(f"  容器时区: {tz_result.strip()}")
                else:
                    print(f"\n容器 {container}: 未运行")
            except Exception as e:
                print(f"\n容器 {container}: 检查失败 - {str(e)}")
        
        # 关闭SSH连接
        await ssh_tunnel_manager.close_tunnel(tunnel)
        print("\n✅ SSH连接已关闭")
        
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()


async def check_local_docker_timezone():
    """检查本地Docker容器时区"""
    print("\n" + "="*80)
    print("本地Docker容器时区检查")
    print("="*80)
    
    import subprocess
    
    container_names = ['ruoyi-app', 'ruoyi-nginx', 'ruoyi-mysql', 'ruoyi-redis']
    
    for container in container_names:
        try:
            # 检查容器是否运行
            result = subprocess.run(
                ['docker', 'inspect', '--format={{.State.Running}}', container],
                capture_output=True, text=True, timeout=10
            )
            
            if result.stdout.strip() == 'true':
                print(f"\n【容器: {container}】")
                
                # 获取容器时间
                time_result = subprocess.run(
                    ['docker', 'exec', container, 'date'],
                    capture_output=True, text=True, timeout=10
                )
                print(f"容器时间: {time_result.stdout.strip()}")
                
                # 获取容器时区
                tz_result = subprocess.run(
                    ['docker', 'exec', container, 'cat', '/etc/timezone'],
                    capture_output=True, text=True, timeout=10
                )
                if tz_result.returncode == 0:
                    print(f"容器时区: {tz_result.stdout.strip()}")
                else:
                    print("容器时区: 未设置")
            else:
                print(f"\n【容器: {container}】: 未运行")
        except subprocess.TimeoutExpired:
            print(f"\n【容器: {container}】: 命令超时")
        except FileNotFoundError:
            print("\n❌ Docker未安装或不在PATH中")
            break
        except Exception as e:
            print(f"\n【容器: {container}】: 检查失败 - {str(e)}")


if __name__ == "__main__":
    try:
        print("选择检查模式:")
        print("1. 检查远程服务器 (通过SSH)")
        print("2. 检查本地Docker容器")
        print("3. 两者都检查")
        
        choice = input("\n请输入选择 (1/2/3, 默认2): ").strip() or "2"
        
        if choice == "1":
            asyncio.run(check_remote_timezone())
        elif choice == "2":
            asyncio.run(check_local_docker_timezone())
        elif choice == "3":
            asyncio.run(check_local_docker_timezone())
            asyncio.run(check_remote_timezone())
        else:
            print("无效选择")
            
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
