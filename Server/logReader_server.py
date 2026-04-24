"""
日志读取 MCP Server - 实现日志读取和搜索功能
以 stdio 形式运行
"""
from fastmcp import FastMCP
import os
from dotenv import load_dotenv
import re
from datetime import datetime

# 加载环境变量
load_dotenv()

# 创建 FastMCP 实例
mcp = FastMCP("Log Reader MCP Server")


@mcp.tool()
def read_logs(lines: int = 10) -> list:
    """
    读取最新的日志条目
    
    Args:
        lines: 要读取的行数，默认为10
    
    Returns:
        日志条目的列表
    """
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    # 检查可能的日志文件名
    log_file_options = ["app.log", "Logs.txt"]
    log_file_path = None
    
    for log_file in log_file_options:
        potential_path = os.path.join(logs_dir, log_file)
        if os.path.exists(potential_path):
            log_file_path = potential_path
            break
    
    # 如果都没有找到，返回错误信息
    if log_file_path is None:
        # 尝试列出logs目录中的所有文件
        available_files = os.listdir(logs_dir) if os.path.exists(logs_dir) else []
        return [{"error": f"日志文件不存在于预期位置。可用文件: {available_files}"}]
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as file:
            all_lines = file.readlines()
            latest_lines = all_lines[-lines:] if len(all_lines) >= lines else all_lines
            
            logs = []
            for line in latest_lines:
                logs.append({"log_entry": line.strip()})
            
            return logs
    except Exception as e:
        return [{"error": f"读取日志文件时发生错误: {str(e)}"}]


@mcp.tool()
def search_logs(keyword: str) -> list:
    """
    根据关键词搜索日志条目

    Args:
        keyword: 要搜索的关键词

    Returns:
        包含关键词的日志条目的列表
    """
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    # 检查可能的日志文件名
    log_file_options = ["app.log", "Logs.txt"]
    log_file_path = None
    
    for log_file in log_file_options:
        potential_path = os.path.join(logs_dir, log_file)
        if os.path.exists(potential_path):
            log_file_path = potential_path
            break

    # 如果都没有找到，返回错误信息
    if log_file_path is None:
        # 尝试列出logs目录中的所有文件
        available_files = os.listdir(logs_dir) if os.path.exists(logs_dir) else []
        return [{"error": f"日志文件不存在于预期位置。可用文件: {available_files}"}]

    try:
        with open(log_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            matched_lines = []

            for line in lines:
                if keyword.lower() in line.lower():
                    matched_lines.append({"log_entry": line.strip()})

            if not matched_lines:
                return [{"result": f"在日志中未找到关键词 '{keyword}' 的匹配项"}]

            return matched_lines
    except Exception as e:
        return [{"error": f"搜索日志文件时发生错误: {str(e)}"}]


@mcp.tool()
def get_log_stats() -> dict:
    """
    获取日志文件的基本统计信息

    Returns:
        包含日志文件统计信息的字典
    """
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    # 检查可能的日志文件名
    log_file_options = ["app.log", "Logs.txt"]
    log_file_path = None
    
    for log_file in log_file_options:
        potential_path = os.path.join(logs_dir, log_file)
        if os.path.exists(potential_path):
            log_file_path = potential_path
            break

    # 如果都没有找到，返回错误信息
    if log_file_path is None:
        # 尝试列出logs目录中的所有文件
        available_files = os.listdir(logs_dir) if os.path.exists(logs_dir) else []
        return {"error": f"日志文件不存在于预期位置。可用文件: {available_files}"}

    try:
        stat_info = os.stat(log_file_path)
        log_stats = {
            "file_size_bytes": stat_info.st_size,
            "last_modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "file_path": log_file_path
        }

        # 计算行数
        with open(log_file_path, 'r', encoding='utf-8') as file:
            line_count = sum(1 for _ in file)
            log_stats["line_count"] = line_count

        return log_stats
    except Exception as e:
        return {"error": f"获取日志统计信息时发生错误: {str(e)}"}


if __name__ == "__main__":
    print("LogReader Server starting...")
    # 以 stdio 模式运行
    mcp.run(transport="stdio")