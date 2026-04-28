"""
Milvus SSH 隧道管理器

用于安全连接远程 Milvus 服务器，通过 SSH 隧道将远程 gRPC 端口转发到本地。
与 Redis SSH 隧道管理器 (ssh_tunnel_manager.py) 模式一致。
"""

import os
import paramiko
from sshtunnel import SSHTunnelForwarder
from typing import Optional


class MilvusTunnelManager:
    """SSH 隧道管理器，用于安全连接远程 Milvus"""

    def __init__(self):
        self.tunnel: Optional[SSHTunnelForwarder] = None

    def create_tunnel(
        self,
        ssh_host: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_user: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        remote_port: Optional[int] = None,
        local_port: Optional[int] = None
    ) -> bool:
        """创建 SSH 隧道连接到远程 Milvus

        Args:
            ssh_host: SSH 服务器地址
            ssh_port: SSH 服务器端口
            ssh_user: SSH 用户名
            ssh_key_path: SSH 私钥文件路径（PEM 格式）
            remote_port: 远程 Milvus gRPC 端口
            local_port: 本地转发端口

        Returns:
            bool: 是否成功创建隧道
        """
        # 从环境变量获取默认值（与 Redis 共享 SSH 凭证）
        ssh_host = ssh_host or os.getenv("MILVUS_SSH_HOST") or os.getenv("SSH_HOST", "8.130.131.36")
        ssh_port = ssh_port or int(os.getenv("MILVUS_SSH_PORT") or os.getenv("SSH_PORT", "22"))
        ssh_user = ssh_user or os.getenv("MILVUS_SSH_USER") or os.getenv("SSH_USER", "root")
        ssh_key_path = ssh_key_path or os.getenv("MILVUS_SSH_KEY_PATH") or os.getenv("SSH_KEY_PATH", "./aiOps.pem")
        remote_port = remote_port or int(os.getenv("MILVUS_REMOTE_PORT", "19530"))
        local_port = local_port or int(os.getenv("MILVUS_LOCAL_PORT", "19531"))

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
                print(f"[Milvus Tunnel] 错误: 无法识别的密钥格式: {ssh_key_path}")
                return False

            # 创建隧道
            self.tunnel = SSHTunnelForwarder(
                (ssh_host, ssh_port),
                ssh_username=ssh_user,
                ssh_pkey=private_key,
                remote_bind_address=('127.0.0.1', remote_port),
                local_bind_address=('127.0.0.1', local_port)
            )

            # 启动隧道
            self.tunnel.start()
            print(f"[Milvus Tunnel] 隧道已建立: localhost:{local_port} -> {ssh_host}:{remote_port}")
            return True

        except FileNotFoundError:
            print(f"[Milvus Tunnel] 错误: 找不到 SSH 密钥文件: {ssh_key_path}")
            return False
        except Exception as e:
            print(f"[Milvus Tunnel] 创建隧道失败: {e}")
            return False

    def close_tunnel(self):
        """关闭 SSH 隧道"""
        if self.tunnel:
            try:
                self.tunnel.stop()
                print("[Milvus Tunnel] 隧道已关闭")
            except Exception as e:
                print(f"[Milvus Tunnel] 关闭隧道时出错: {e}")
            finally:
                self.tunnel = None
