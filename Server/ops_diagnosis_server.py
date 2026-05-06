"""
Ops Diagnosis MCP Server - 提供运维故障诊断服务
支持基于时间范围的日志查询、知识库检索、资源检查等功能
以 stdio 形式运行
"""
import os
import sys
import json
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from dotenv import load_dotenv
import paramiko
import chromadb
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

# 确保加载 .env 文件
load_dotenv()

# 独立的 ChromaDB 配置
OPS_PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "vector_store", "ops_vector_store")
OPS_COLLECTION_NAME = "ops_knowledge"

# 初始化向量库
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY:
    raise ValueError("缺少 DASHSCOPE_API_KEY 配置，请检查 .env 文件")

embeddings = DashScopeEmbeddings(
    model="text-embedding-v3", 
    dashscope_api_key=DASHSCOPE_API_KEY
)

os.makedirs(OPS_PERSIST_DIRECTORY, exist_ok=True)
ops_vector_store = Chroma(
    persist_directory=OPS_PERSIST_DIRECTORY,
    embedding_function=embeddings,
    collection_name=OPS_COLLECTION_NAME
)

# SSH 连接管理器（从 .env 读取，无硬编码默认值）
ssh_config = {
    "host": os.getenv("SSH_HOST"),
    "port": int(os.getenv("SSH_PORT", "22")),
    "username": os.getenv("SSH_USER"),
    "key_file": os.path.expanduser(os.getenv("SSH_KEY_PATH"))
}

# 验证必要配置
if not all([ssh_config["host"], ssh_config["username"], ssh_config["key_file"]]):
    raise ValueError("缺少必要的 SSH 配置，请检查 .env 文件中的 SSH_HOST, SSH_USER, SSH_KEY_PATH")

# OpsAgent 专用配置
DEFAULT_CONTAINER = os.getenv("OPS_DEFAULT_CONTAINER")
DIAGNOSIS_LOOKBACK_MINUTES = int(os.getenv("OPS_DIAGNOSIS_LOOKBACK_MINUTES", "30"))
LOG_DEFAULT_LINES = int(os.getenv("OPS_LOG_DEFAULT_LINES", "100"))

# 创建 FastMCP 实例
mcp = FastMCP("Ops Diagnosis Server")

# ===== 工具定义 =====

@mcp.tool()
def search_ops_knowledge(query: str, top_k: int = 3) -> dict:
    """
    在运维知识库中搜索相关诊断方案
    
    Args:
        query: 搜索查询文本（可以是症状描述、错误关键词等）
        top_k: 返回结果数量（默认 3）
    
    Returns:
        包含匹配结果和元数据的字典
    """
    # 【关键】打印检索前的 query，便于调试和优化
    print(f"\n[Ops Knowledge Search] Query: '{query}'")
    print(f"[Ops Knowledge Search] Top-K: {top_k}")
    
    try:
        results = ops_vector_store.similarity_search_with_score(query, k=top_k)
        
        # 格式化返回结果
        formatted_results = []
        for doc, score in results:
            formatted_results.append({
                "id": doc.metadata.get("doc_id", "unknown"),
                "title": doc.metadata.get("title", "unknown"),
                "type": doc.metadata.get("type", "unknown"),
                "category": doc.metadata.get("category", "unknown"),
                "similarity_score": float(score),
                "content_preview": doc.page_content[:200],
                "metadata": doc.metadata
            })
        
        print(f"\n[Ops Knowledge Search] ===== 检索结果 =====")
        print(f"Query: '{query}'")
        print(f"Top-K: {top_k}")
        print(f"Found {len(formatted_results)} results:\n")
        
        for i, result in enumerate(formatted_results, 1):
            score = result['similarity_score']
            # ChromaDB 返回的是距离值（cosine distance，越小越相似）
            # 转换为相似度分数（0-1，越大越相似）
            similarity = 1 - score if score <= 1 else score
            
            print(f"  [{i}] {result['title']}")
            print(f"      ID: {result['id']}")
            print(f"      类型: {result['type']}")
            print(f"      分类: {result['category']}")
            print(f"      距离分数: {score:.4f} (越小越相似)")
            print(f"      相似度: {similarity:.4f} (越大越相似)")
            print(f"      内容预览: {result['content_preview'][:100]}...")
            print()
        
        return {
            "status": "success",
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results)
        }
    
    except Exception as e:
        print(f"[Ops Knowledge Search] Error: {str(e)}")
        return {
            "status": "error",
            "query": query,
            "message": str(e)
        }

@mcp.tool()
def fetch_docker_logs(
    container_name: str,
    lines: int = None,
    since_time: Optional[str] = None,
    until_time: Optional[str] = None
) -> dict:
    """
    获取指定时间范围的 Docker 容器日志（避免全量读取大日志文件）
    
    Args:
        container_name: 容器名称（必填）
        lines: 最大返回行数（默认使用 OPS_LOG_DEFAULT_LINES）
        since_time: 起始时间（ISO 8601 格式如 "2024-01-15T10:30:00" 或相对时间如 "10m"、"1h"）
        until_time: 结束时间（ISO 8601 格式，默认为当前时间）
    
    Returns:
        包含日志内容和元数据的字典
    """
    if lines is None:
        lines = LOG_DEFAULT_LINES
    
    # 构建 docker logs 命令（使用时间过滤参数）
    cmd_parts = [f"docker logs {container_name}"]
    
    if since_time:
        cmd_parts.append(f"--since '{since_time}'")
    
    if until_time:
        cmd_parts.append(f"--until '{until_time}'")
    
    cmd_parts.append(f"--tail {lines}")
    cmd_parts.append("2>&1")
    
    cmd = " ".join(cmd_parts)
    
    print(f"\n[Fetch Logs] Executing: {cmd}")
    
    # 通过 SSH 执行命令
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command(cmd)
        logs = stdout.read().decode('utf-8')
        error_output = stderr.read().decode('utf-8')
        
        ssh.close()
        
        if error_output and "error" in error_output.lower():
            return {
                "status": "error",
                "message": f"SSH 命令执行失败: {error_output}"
            }
        
        return {
            "status": "success",
            "container": container_name,
            "time_range": {"since": since_time, "until": until_time},
            "line_count": len(logs.splitlines()),
            "logs": logs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def check_memory_usage() -> dict:
    """检查服务器内存使用情况"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command("free -h")
        memory_info = stdout.read().decode('utf-8')
        
        ssh.close()
        
        return {
            "status": "success",
            "memory_info": memory_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def check_cpu_usage() -> dict:
    """检查服务器 CPU 使用情况"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        key_path = ssh_config["key_file"]
        ssh.connect(
            hostname=ssh_config["host"],
            port=ssh_config["port"],
            username=ssh_config["username"],
            key_filename=key_path,
            timeout=30
        )
        
        stdin, stdout, stderr = ssh.exec_command("top -bn1 | head -20")
        cpu_info = stdout.read().decode('utf-8')
        
        ssh.close()
        
        return {
            "status": "success",
            "cpu_info": cpu_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def load_ops_knowledge_entries() -> dict:
    """手动触发运维知识条目的加载和索引"""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from Server.init_ops_knowledge import initialize_ops_knowledge
        
        print("开始加载运维知识条目...")
        result = initialize_ops_knowledge()
        
        return {
            "status": "success",
            "message": "知识条目加载完成",
            "details": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"知识条目加载失败: {str(e)}"
        }

if __name__ == "__main__":
    print("Ops Diagnosis Server starting...")
    mcp.run(transport="stdio")
