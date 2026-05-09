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
ssh_key_path = os.getenv("SSH_KEY_PATH", "./aiOps.pem")
# 如果是相对路径，转换为绝对路径（相对于项目根目录）
if not os.path.isabs(ssh_key_path):
    ssh_key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ssh_key_path)

ssh_config = {
    "host": os.getenv("SSH_HOST"),
    "port": int(os.getenv("SSH_PORT", "22")),
    "username": os.getenv("SSH_USER"),
    "key_file": ssh_key_path
}

# 验证必要配置
if not all([ssh_config["host"], ssh_config["username"]]):
    raise ValueError("缺少必要的SSH配置，请检查.env文件中的SSH_HOST, SSH_USER, SSH_KEY_PATH")

# 创建 FastMCP 实例
mcp = FastMCP("Log Reader MCP Server")


# ===== 辅助函数 =====

def _get_ssh_connection() -> paramiko.SSHClient:
    """建立SSH连接"""
    try:
        # 尝试加载不同类型的SSH密钥
        private_key = None
        key_types = [
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        ]
        
        for key_type in key_types:
            try:
                private_key = key_type.from_private_key_file(ssh_config["key_file"])
                break
            except paramiko.SSHException:
                continue
        
        if private_key is None:
            raise Exception(f"无法识别的密钥格式: {ssh_config['key_file']}")
        
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            pkey=private_key,
            timeout=30
        )
        
        logger.info(f"[SSH] Connected to {ssh_config['host']}")
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
    log_level: Optional[List[str]] = None  # 默认不过滤，返回所有日志
) -> dict:
    """
    通过SSH读取远程Docker容器日志
    
    Args:
        container_name: 容器名称（必填）
        lines: 最大返回行数（默认100）
        since_time: 起始时间（ISO 8601格式，如"2024-01-15T10:30:00"或相对时间如"30m"、"1h"）
        until_time: 结束时间（ISO 8601格式，默认为当前时间）
        log_level: 日志级别过滤列表（默认None表示不过滤，传入["ERROR", "WARN"]则只返回错误和警告）
    
    Returns:
        包含日志内容和元数据的字典
    """
    logger.info(f"\n[Read Logs] Container: {container_name}")
    logger.info(f"[Read Logs] Lines: {lines}, Since: {since_time}, Until: {until_time}")
    logger.info(f"[Read Logs] Log Level Filter: {log_level}")
    
    try:
        # 构建docker logs命令
        cmd = f"docker logs {container_name}"
        if since_time:
            cmd += f" --since '{since_time}'"
        if until_time:
            cmd += f" --until '{until_time}'"
        cmd += f" --tail {lines} 2>&1"
        
        logger.info(f"[Read Logs] Executing: {cmd}")
        
        # SSH执行
        ssh_client = _get_ssh_connection()
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        raw_logs = stdout.read().decode('utf-8')
        error_output = stderr.read().decode('utf-8')
        ssh_client.close()
        
        # 检查错误
        if error_output and "error" in error_output.lower():
            return {
                "status": "error",
                "message": f"Docker命令执行失败: {error_output}"
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
def get_container_status(container_name: str) -> dict:
    """
    获取Docker容器的运行状态
    
    Args:
        container_name: 容器名称
    
    Returns:
        包含容器状态的字典
    """
    logger.info(f"\n[Container Status] Checking: {container_name}")
    
    try:
        # 检查容器是否运行
        cmd = f"docker ps --filter name={container_name} --format '{{{{.Names}}}}\t{{{{.Status}}}}'"
        
        ssh_client = _get_ssh_connection()
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        output = stdout.read().decode('utf-8').strip()
        ssh_client.close()
        
        if output:
            parts = output.split('\t')
            name = parts[0] if len(parts) > 0 else container_name
            status = parts[1] if len(parts) > 1 else "unknown"
            
            logger.info(f"[Container Status] {name}: {status}")
            
            return {
                "status": "success",
                "container": name,
                "running": True,
                "status_detail": status
            }
        else:
            # 容器可能已停止，检查是否存在
            cmd_check = f"docker ps -a --filter name={container_name} --format '{{{{.Names}}}}\t{{{{.Status}}}}'"
            
            ssh_client = _get_ssh_connection()
            stdin, stdout, stderr = ssh_client.exec_command(cmd_check)
            output = stdout.read().decode('utf-8').strip()
            ssh_client.close()
            
            if output:
                parts = output.split('\t')
                name = parts[0] if len(parts) > 0 else container_name
                status = parts[1] if len(parts) > 1 else "unknown"
                
                logger.info(f"[Container Status] {name}: {status} (stopped)")
                
                return {
                    "status": "success",
                    "container": name,
                    "running": False,
                    "status_detail": status
                }
            else:
                logger.warning(f"[Container Status] Container not found: {container_name}")
                return {
                    "status": "error",
                    "message": f"容器 '{container_name}' 不存在"
                }
    
    except Exception as e:
        logger.error(f"[Container Status] Error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@mcp.tool()
def check_memory_usage() -> dict:
    """
    通过SSH检查远程服务器的内存使用情况
    
    Returns:
        包含内存使用信息的字典
    """
    try:
        cmd = "free -h"
        ssh_client = _get_ssh_connection()
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        output = stdout.read().decode('utf-8').strip()
        ssh_client.close()
        
        # 解析free命令输出
        lines = output.splitlines()
        if len(lines) >= 2:
            mem_line = lines[1].split()
            swap_line = lines[2] if len(lines) > 2 else ""
            
            memory_info = {
                "total": mem_line[1],
                "used": mem_line[2],
                "free": mem_line[3],
                "shared": mem_line[4] if len(mem_line) > 4 else "N/A",
                "buff_cache": mem_line[5] if len(mem_line) > 5 else "N/A",
                "available": mem_line[6] if len(mem_line) > 6 else "N/A"
            }
            
            logger.info(f"[Memory Check] Total: {memory_info['total']}, Used: {memory_info['used']}, Available: {memory_info['available']}")
            
            return {
                "status": "success",
                "memory_info": output,
                "parsed": memory_info
            }
        else:
            return {
                "status": "error",
                "message": "无法解析内存信息"
            }
    except Exception as e:
        logger.error(f"[Memory Check] Error: {str(e)}")
        return {
            "status": "error",
            "message": f"检查内存失败: {str(e)}"
        }


@mcp.tool()
def check_cpu_usage() -> dict:
    """
    通过SSH检查远程服务器的CPU使用情况
    
    Returns:
        包含CPU使用信息的字典
    """
    try:
        # 获取负载和CPU使用率
        cmd1 = "uptime"
        cmd2 = "top -bn1 | grep 'Cpu(s)' || top -bn1 | grep '%Cpu'"
        
        ssh_client = _get_ssh_connection()
        
        stdin, stdout, stderr = ssh_client.exec_command(cmd1)
        uptime_output = stdout.read().decode('utf-8').strip()
        
        stdin, stdout, stderr = ssh_client.exec_command(cmd2)
        cpu_output = stdout.read().decode('utf-8').strip()
        
        ssh_client.close()
        
        logger.info(f"[CPU Check] Uptime: {uptime_output}")
        
        return {
            "status": "success",
            "uptime": uptime_output,
            "cpu_info": cpu_output
        }
    except Exception as e:
        logger.error(f"[CPU Check] Error: {str(e)}")
        return {
            "status": "error",
            "message": f"检查CPU失败: {str(e)}"
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


@mcp.tool()
def check_mysql_status() -> dict:
    """
    通过SSH检查MySQL服务状态
    
    Returns:
        包含MySQL服务状态的字典
    """
    try:
        ssh_client = _get_ssh_connection()
        
        # 检查MySQL进程
        cmd1 = "ps aux | grep mysql | grep -v grep"
        stdin, stdout, stderr = ssh_client.exec_command(cmd1)
        process_output = stdout.read().decode('utf-8').strip()
        
        # 检查MySQL端口
        cmd2 = "netstat -tlnp | grep :3306 || ss -tlnp | grep :3306"
        stdin, stdout, stderr = ssh_client.exec_command(cmd2)
        port_output = stdout.read().decode('utf-8').strip()
        
        # 检查Docker中的MySQL容器（如果使用Docker）
        cmd3 = "docker ps --filter name=mysql --format '{{.Names}}\t{{.Status}}'"
        stdin, stdout, stderr = ssh_client.exec_command(cmd3)
        docker_output = stdout.read().decode('utf-8').strip()
        
        ssh_client.close()
        
        mysql_running = bool(process_output or port_output or docker_output)
        
        result = {
            "status": "success",
            "mysql_running": mysql_running,
            "process_info": process_output if process_output else "未找到MySQL进程",
            "port_info": port_output if port_output else "3306端口未监听",
            "docker_info": docker_output if docker_output else "未找到MySQL容器"
        }
        
        logger.info(f"[MySQL Check] Running: {mysql_running}")
        
        return result
    except Exception as e:
        logger.error(f"[MySQL Check] Error: {str(e)}")
        return {
            "status": "error",
            "message": f"检查MySQL状态失败: {str(e)}"
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