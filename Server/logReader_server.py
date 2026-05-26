"""
日志读取 MCP Server - 通过SSH读取远程Docker容器日志
支持日志级别过滤、异常时间点扫描等功能
以 stdio 形式运行
"""
from fastmcp import FastMCP
import os
import re
import logging
import sys
from typing import List, Optional
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
import paramiko
from dotenv import load_dotenv

# 配置日志输出到stderr（避免干扰MCP协议）
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# SSH配置（从.env读取）
# 优先使用新的 BACKEND_SSH_* 配置，如果没有则回退到旧的 SSH_* 配置
ssh_host = os.getenv("BACKEND_SSH_HOST") or os.getenv("SSH_HOST")
ssh_port = os.getenv("BACKEND_SSH_PORT") or os.getenv("SSH_PORT", "22")
ssh_user = os.getenv("BACKEND_SSH_USER") or os.getenv("SSH_USER")
ssh_key_path = os.getenv("BACKEND_SSH_KEY_PATH") or os.getenv("SSH_KEY_PATH", "./aiOps.pem")

# 如果是相对路径，转换为绝对路径（相对于项目根目录）
if not os.path.isabs(ssh_key_path):
    ssh_key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ssh_key_path)

ssh_config = {
    "host": ssh_host,
    "port": int(ssh_port),
    "username": ssh_user,
    "key_file": ssh_key_path
}

# 验证必要配置
if not all([ssh_config["host"], ssh_config["username"]]):
    raise ValueError("缺少必要的SSH配置，请检查.env文件中的 BACKEND_SSH_HOST/SSH_HOST, BACKEND_SSH_USER/SSH_USER, BACKEND_SSH_KEY_PATH/SSH_KEY_PATH")

# 创建 FastMCP 实例
mcp = FastMCP("Log Reader MCP Server")


# ===== 辅助函数 =====

def _get_ssh_connection() -> paramiko.SSHClient:
    """建立SSH连接（使用默认配置）"""
    return _get_ssh_connection_for_host(None)


def _get_ssh_connection_for_host(target_host: Optional[str] = None) -> paramiko.SSHClient:
    """
    建立SSH连接
    
    Args:
        target_host: 目标主机地址，如果为None则使用默认配置
    """
    try:
        # 如果指定了目标主机，需要查找对应的配置
        if target_host:
            # 从环境变量中查找对应服务器的配置
            from dotenv import dotenv_values
            import os
            
            env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
            config = dotenv_values(env_file, encoding='utf-8')
            
            # 查找匹配的服务器配置
            host_key = None
            user_key = None
            port_key = None
            key_path = None
            
            # 检查是否是前端服务器
            if target_host == config.get('FRONTEND_SSH_HOST'):
                host_key = 'FRONTEND_SSH_HOST'
                user_key = 'FRONTEND_SSH_USER'
                port_key = 'FRONTEND_SSH_PORT'
                key_path = config.get('FRONTEND_SSH_KEY_PATH', '')
            # 否则使用后端服务器配置
            else:
                host_key = 'BACKEND_SSH_HOST' or 'SSH_HOST'
                user_key = 'BACKEND_SSH_USER' or 'SSH_USER'
                port_key = 'BACKEND_SSH_PORT' or 'SSH_PORT'
                key_path = config.get('BACKEND_SSH_KEY_PATH', '') or config.get('SSH_KEY_PATH', './aiOps.pem')
            
            ssh_host = config.get(host_key, target_host)
            ssh_port = int(config.get(port_key, '22'))
            ssh_user = config.get(user_key, 'root')
            
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(key_path):
                key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), key_path)
            
            logger.info(f"[SSH] Using custom host: {ssh_host}")
        else:
            # 使用默认配置
            ssh_host = ssh_config["host"]
            ssh_port = ssh_config["port"]
            ssh_user = ssh_config["username"]
            key_path = ssh_config["key_file"]
        
        # 尝试加载不同类型的SSH密钥
        private_key = None
        key_types = [
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        ]
        
        for key_type in key_types:
            try:
                private_key = key_type.from_private_key_file(key_path)
                break
            except paramiko.SSHException:
                continue
        
        if private_key is None:
            raise Exception(f"无法识别的密钥格式: {key_path}")
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=ssh_host,
            port=ssh_port,
            username=ssh_user,
            pkey=private_key,
            timeout=30
        )
        
        logger.info(f"[SSH] Connected to {ssh_host}")
        return ssh_client
    
    except Exception as e:
        logger.error(f"[SSH] Connection failed: {str(e)}")
        raise


def filter_logs_by_level(logs: str, levels: List[str] = ["ERROR", "WARN"]) -> str:
    """
    过滤日志级别
    
    Args:
        logs: 原始日志文本
        levels: 要保留的日志级别列表
    
    Returns:
        过滤后的日志文本
    """
    if not levels:
        return logs
    
    filtered_lines = []
    for line in logs.splitlines():
        # 匹配常见的日志级别格式：[ERROR], ERROR:, level=error, etc.
        pattern = r'\b(' + '|'.join(levels) + r')\b'
        if re.search(pattern, line, re.IGNORECASE):
            filtered_lines.append(line)
    
    return '\n'.join(filtered_lines)


# ===== MCP工具定义 =====

@mcp.tool()
def read_docker_logs(
    container_name: str,
    lines: int = 100,
    since_time: Optional[str] = None,
    until_time: Optional[str] = None,
    log_level: Optional[List[str]] = None,  # 默认不过滤，返回所有日志
    ssh_host: Optional[str] = None  # 可选：指定SSH主机，默认为.env中配置的BACKEND_SSH_HOST
) -> dict:
    """
    通过SSH读取远程Docker容器日志
    
    Args:
        container_name: 容器名称（必填）
        lines: 最大返回行数（默认100）
        since_time: 起始时间（ISO 8601格式，如"2024-01-15T10:30:00"或相对时间如"30m"、"1h"）
        until_time: 结束时间（ISO 8601格式，默认为当前时间）
        log_level: 日志级别过滤列表（默认None表示不过滤，传入["ERROR", "WARN"]则只返回错误和警告）
        ssh_host: SSH主机地址（可选，默认使用.env中的BACKEND_SSH_HOST配置）
    
    Returns:
        包含日志内容和元数据的字典
    """
    logger.info(f"\n[Read Logs] Container: {container_name}")
    logger.info(f"[Read Logs] Lines: {lines}, Since: {since_time}, Until: {until_time}")
    logger.info(f"[Read Logs] Log Level Filter: {log_level}")
    if ssh_host:
        logger.info(f"[Read Logs] Target SSH Host: {ssh_host}")
    
    try:
        # 构建docker logs命令
        cmd = f"docker logs {container_name}"
        if since_time:
            cmd += f" --since '{since_time}'"
        if until_time:
            cmd += f" --until '{until_time}'"
        cmd += f" --tail {lines} 2>&1"
        
        logger.info(f"[Read Logs] Executing: {cmd}")
        
        # SSH执行（根据ssh_host参数选择目标服务器）
        ssh_client = _get_ssh_connection_for_host(ssh_host)
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        raw_logs = stdout.read().decode('utf-8')
        error_output = stderr.read().decode('utf-8')
        ssh_client.close()
        
        # 检查错误（同时检查stdout和stderr）
        combined_output = raw_logs + error_output
        if "Error response from daemon" in combined_output or \
           (error_output and "error" in error_output.lower()):
            logger.error(f"[Read Logs] Docker command failed: {combined_output}")
            return {
                "status": "error",
                "message": f"Docker命令执行失败: {combined_output.strip()}"
            }
        
        # 过滤日志级别
        if log_level:
            filtered_logs = filter_logs_by_level(raw_logs, log_level)
        else:
            filtered_logs = raw_logs
        
        line_count = len(filtered_logs.splitlines())
        logger.info(f"[Read Logs] Retrieved {line_count} lines")
        
        return {
            "status": "success",
            "container": container_name,
            "time_range": {"since": since_time, "until": until_time},
            "line_count": line_count,
            "logs": filtered_logs,
            "filter_applied": log_level if log_level else "none"
        }
    
    except Exception as e:
        logger.error(f"[Read Logs] Error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
def scan_logs_for_anomalies(
    container_name: str,
    time_range_hours: int = 2
) -> dict:
    """
    快速扫描日志，识别异常时间点
    用于两阶段追溯的第一阶段：快速定位问题发生的时间点
    
    Args:
        container_name: 容器名称
        time_range_hours: 扫描的时间范围（小时），默认2小时
    
    Returns:
        包含异常时间点列表的字典
    """
    logger.info(f"\n[Scan Anomalies] Container: {container_name}, Time Range: {time_range_hours}h")
    
    try:
        # 计算起始时间
        now = datetime.now()
        since_time = (now - timedelta(hours=time_range_hours)).strftime("%Y-%m-%dT%H:%M:%S")
        
        # 读取指定时间范围内的所有ERROR/WARN日志
        cmd = f"docker logs {container_name} --since '{since_time}' 2>&1"
        
        logger.info(f"[Scan Anomalies] Executing: {cmd}")
        
        ssh_client = _get_ssh_connection()
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        raw_logs = stdout.read().decode('utf-8')
        ssh_client.close()
        
        # 过滤出ERROR和WARN级别的日志
        filtered_logs = filter_logs_by_level(raw_logs, ["ERROR", "WARN"])
        
        # 提取异常时间点（从日志行中提取时间戳）
        anomaly_timestamps = []
        for line in filtered_logs.splitlines():
            # 尝试匹配常见的时间格式
            # 格式1: 2024-01-15T10:30:45.123Z
            match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
            if match:
                timestamp = match.group(1)
                if timestamp not in anomaly_timestamps:
                    anomaly_timestamps.append(timestamp)
        
        # 按时间排序
        anomaly_timestamps.sort()
        
        logger.info(f"[Scan Anomalies] Found {len(anomaly_timestamps)} anomaly timestamps")
        for ts in anomaly_timestamps[:5]:  # 只显示前5个
            logger.info(f"  - {ts}")
        
        return {
            "status": "success",
            "container": container_name,
            "time_range_hours": time_range_hours,
            "anomaly_count": len(anomaly_timestamps),
            "anomaly_timestamps": anomaly_timestamps,
            "total_error_warn_lines": len(filtered_logs.splitlines())
        }
    
    except Exception as e:
        logger.error(f"[Scan Anomalies] Error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }



@mcp.tool()
def get_system_info() -> dict:
    """
    通过SSH获取远程服务器的系统基本信息
    
    Returns:
        包含系统基本信息的字典
    """
    try:
        cmds = {
            "hostname": "hostname",
            "os_info": "uname -a",
            "disk_usage": "df -h / | tail -1",
            "uptime": "uptime"
        }
        
        ssh_client = _get_ssh_connection()
        results = {}
        
        for key, cmd in cmds.items():
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            results[key] = stdout.read().decode('utf-8').strip()
        
        ssh_client.close()
        
        logger.info(f"[System Info] Hostname: {results.get('hostname', 'unknown')}")
        
        return {
            "status": "success",
            "system_info": results
        }
    except Exception as e:
        logger.error(f"[System Info] Error: {str(e)}")
        return {
            "status": "error",
            "message": f"获取系统信息失败: {str(e)}"
        }


if __name__ == "__main__":
    import sys
    
    # 支持两种运行模式：stdio 和 http
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    
    if mode == "http":
        # HTTP 模式：作为长运行服务器
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8005
        print(f"LogReader MCP Server starting in HTTP mode on port {port}...")
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        # stdio 模式：用于命令行工具调用
        print("LogReader Server starting...")
        mcp.run(transport="stdio")