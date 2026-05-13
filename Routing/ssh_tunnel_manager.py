"""
SSH 隧道管理器

用于安全连接远程 Redis 服务器，通过 SSH 隧道将远程端口转发到本地。
"""

# 屏蔽 paramiko 的弃用警告
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')

# 屏蔽 sshtunnel 的重试错误日志（Redis 不可用时会频繁重试）
import logging
logging.getLogger('sshtunnel').setLevel(logging.CRITICAL)

import paramiko
from sshtunnel import SSHTunnelForwarder
from typing import Optional


class SSHTunnelManager:
    """SSH 隧道管理器，用于安全连接远程 Redis"""

    def __init__(self):
        self.tunnel: Optional[SSHTunnelForwarder] = None
        self.ssh_client: Optional[paramiko.SSHClient] = None

    def create_tunnel(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        ssh_key_path: str,
        remote_redis_port: int,
        local_redis_port: int
    ) -> bool:
        """创建 SSH 隧道

        Args:
            ssh_host: SSH 服务器地址
            ssh_port: SSH 服务器端口
            ssh_user: SSH 用户名
            ssh_key_path: SSH 私钥文件路径（PEM 格式）
            remote_redis_port: 远程 Redis 端口
            local_redis_port: 本地转发端口

        Returns:
            bool: 是否成功创建隧道
        """
        try:
            # 尝试加载不同类型的 SSH 密钥
            private_key = None
            key_types = [
                paramiko.RSAKey,
                paramiko.ECDSAKey,
                paramiko.Ed25519Key,
            ]

            for key_type in key_types:
                try:
                    private_key = key_type.from_private_key_file(ssh_key_path)
                    break
                except paramiko.SSHException:
                    continue

            if private_key is None:
                print(f"[警告] SSH 密钥格式不正确: {ssh_key_path}")
                return False

            # 创建隧道
            self.tunnel = SSHTunnelForwarder(
                (ssh_host, ssh_port),
                ssh_username=ssh_user,
                ssh_pkey=private_key,
                remote_bind_address=('localhost', remote_redis_port),
                local_bind_address=('localhost', local_redis_port)
            )

            # 启动隧道
            self.tunnel.start()
            print(f"[SSH Tunnel] 隧道已建立: localhost:{local_redis_port} -> {ssh_host}:{remote_redis_port}")
            return True

        except FileNotFoundError:
            print(f"[警告] SSH 密钥文件不存在: {ssh_key_path}")
            return False
        except Exception as e:
            print(f"[警告] SSH 隧道创建失败: {e}")
            return False

    def close_tunnel(self):
        """关闭 SSH 隧道"""
        if self.tunnel:
            try:
                self.tunnel.stop()
                print("[SSH Tunnel] 隧道已关闭")
            except Exception as e:
                print(f"[SSH Tunnel] 关闭隧道时出错: {e}")
            finally:
                self.tunnel = None

        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            finally:
                self.ssh_client = None
