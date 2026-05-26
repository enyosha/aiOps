"""
SSH 隧道管理器

用于安全连接远程 Redis 服务器，通过 SSH 隧道将远程端口转发到本地。
"""

# 屏蔽 paramiko 的弃用警告
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')

# 自定义日志处理器：捕获 sshtunnel 的最后一次错误
import logging
import sys
from io import StringIO

class LastErrorCapture(logging.Handler):
    """捕获并存储最后一次错误日志"""
    def __init__(self):
        super().__init__()
        self.last_error = None
    
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            self.last_error = self.format(record)

# 设置 sshtunnel 日志捕获
sshtunnel_logger = logging.getLogger('sshtunnel')
sshtunnel_logger.setLevel(logging.ERROR)
error_capture = LastErrorCapture()
error_capture.setFormatter(logging.Formatter('%(asctime)s| %(levelname)-7s | %(message)s'))
sshtunnel_logger.addHandler(error_capture)
# 阻止日志传播到根日志器（避免重复输出）
sshtunnel_logger.propagate = False

# 同时屏蔽 paramiko 的日志
paramiko_logger = logging.getLogger('paramiko')
paramiko_logger.setLevel(logging.CRITICAL)
paramiko_logger.propagate = False

import paramiko
from sshtunnel import SSHTunnelForwarder
from typing import Optional


class SSHTunnelManager:
    """SSH 隧道管理器，用于安全连接远程 Redis"""

    def __init__(self):
        self.tunnel: Optional[SSHTunnelForwarder] = None
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.error_capture: Optional[LastErrorCapture] = error_capture

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
            # 如果有捕获的错误详情，输出详细信息
            if self.error_capture and self.error_capture.last_error:
                print(f"详细:\n{self.error_capture.last_error}")
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
