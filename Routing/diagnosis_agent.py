"""
DiagnosisAgent - 纯LLM驱动的运维诊断Agent（与OpsAgent完全隔离）

设计原则：
- 不使用知识库检索
- 不执行诊断树
- 完全依赖LLM的推理能力
- 通过MCP工具获取实时数据
- 简单的ReAct循环：观察 → 思考 → 行动 → 重复
"""
import os
import sys
import json
import re
from typing import TypedDict, List, Optional, Literal
from datetime import datetime, timedelta

from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# ===== State 定义 =====

class DiagnosisState(TypedDict):
    """诊断状态"""
    alert_event: dict                  # Grafana告警事件
    container_name: str                # 容器名称
    
    # 诊断过程
    messages: List                     # 对话历史
    current_step: str                  # 当前步骤
    iteration_count: int               # 迭代次数
    max_iterations: int                # 最大迭代次数
    actions_taken: List[str]           # 已执行的行动列表
    
    # 收集的数据
    anomaly_timestamps: List[str]      # 异常时间点列表(暂时保留)
    logs_data: Optional[str]           # 日志数据
    memory_info: Optional[str]         # 内存信息
    cpu_info: Optional[str]            # CPU信息
    service_status: Optional[str]      # 服务状态
    mysql_status: Optional[str]        # MySQL状态
    
    # 日志追溯
    log_search_range_minutes: int      # 当前日志搜索范围(分钟),初始30
    logs_collected_ranges: List[dict]  # 已收集的日志范围列表 [{"range": 30, "logs": "..."}, ...]
    
    # 诊断结果
    diagnosis_result: Optional[dict]   # 最终诊断结果
    
    # === 新增字段：多服务环境支持 ===
    config_status: str                 # "none" | "partial" | "complete"
    servers_config: dict               # 四组件配置 {frontend, backend, database, redis}
    discovered_containers: List[dict]  # Docker ps 发现的容器
    service_status_summary: str        # 服务未启动时的摘要信息
    docker_stats_info: str             # Docker stats 资源使用情况
    next_action: Optional[str]         # 下一步行动（由 analyze_node 决定）
    
    # === 新增字段：健康检查结果 ===
    health_check_results: Optional[dict]  # 健康检查结果 {service_name: {status, details}}
    port_check_results: Optional[dict]    # 端口检查结果 {service_name: {port, reachable}}
    performance_metrics: Optional[dict]   # 性能指标 {service_name: {cpu, memory, response_time}}
    health_check_summary: Optional[str]   # 健康检查摘要文本
    
    # === 内部调试字段（不用于诊断逻辑）===
    _health_check_execution_count: int    # 健康检查执行次数计数器

# ===== LLM 初始化 =====

llm = ChatOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE
)

# ===== 辅助函数 =====

def load_servers_config(env_file_path: str = ".env") -> dict:
    """从 .env 文件加载服务器配置"""
    from dotenv import dotenv_values
    import os
    
    # 强制重新加载配置（清除缓存）
    config = dotenv_values(env_file_path, encoding='utf-8')
    
    # 如果 dotenv_values 返回空，尝试使用 os.environ
    if not config or len(config) == 0:
        print(f"[WARNING] dotenv_values 返回空配置，尝试使用 os.environ")
        config = dict(os.environ)
    
    servers = {
        "frontend": {},
        "backend": {},
        "database": {},
        "redis": {}
    }
    
    # 前端配置
    if config.get("FRONTEND_SSH_HOST"):
        servers["frontend"] = {
            "ssh_host": config["FRONTEND_SSH_HOST"],
            "ssh_port": int(config.get("FRONTEND_SSH_PORT", "22")),
            "ssh_user": config.get("FRONTEND_SSH_USER", "root"),
            "ssh_key_path": config.get("FRONTEND_SSH_KEY_PATH", ""),
            "container_name": config.get("FRONTEND_CONTAINER_NAME", "")
        }
    
    # 后端配置
    if config.get("BACKEND_SSH_HOST"):
        servers["backend"] = {
            "ssh_host": config["BACKEND_SSH_HOST"],
            "ssh_port": int(config.get("BACKEND_SSH_PORT", "22")),
            "ssh_user": config.get("BACKEND_SSH_USER", "root"),
            "ssh_key_path": config.get("BACKEND_SSH_KEY_PATH", ""),
            "container_name": config.get("BACKEND_CONTAINER_NAME", "ruoyi-app")
        }
    
    # 数据库配置
    if config.get("DATABASE_HOST"):
        servers["database"] = {
            "host": config["DATABASE_HOST"],
            "port": int(config.get("DATABASE_PORT", "3306")),
            "user": config.get("DATABASE_USER", "root"),
            "password": config.get("DATABASE_PASSWORD", ""),
            "name": config.get("DATABASE_NAME", "")
        }
    
    # Redis 配置
    if config.get("REDIS_HOST"):
        servers["redis"] = {
            "host": config["REDIS_HOST"],
            "port": int(config.get("REDIS_PORT", "6379")),
            "password": config.get("REDIS_PASSWORD", "")
        }
    
    return servers

def determine_config_status(servers_config: dict) -> str:
    """判断配置状态"""
    configured_count = sum(1 for v in servers_config.values() if v)
    
    if configured_count == 0:
        return "none"
    elif configured_count < 4:
        return "partial"
    else:
        return "complete"


# ===== 健康检查辅助函数 =====

def check_http_health(host: str, port: int, path: str = "/health", timeout: int = 5) -> dict:
    """
    通过HTTP请求检查服务健康状态
    
    Args:
        host: 服务主机地址
        port: 服务端口
        path: 健康检查路径，默认/health
        timeout: 超时时间(秒)
    
    Returns:
        {
            'status': 'healthy' | 'unhealthy' | 'timeout' | 'error',
            'status_code': int or None,
            'response_time_ms': float,
            'error': str or None
        }
    """
    import requests
    from time import time
    
    try:
        url = f"http://{host}:{port}{path}"
        start_time = time()
        response = requests.get(url, timeout=timeout)
        elapsed_ms = (time() - start_time) * 1000
        
        if response.status_code == 200:
            return {
                'status': 'healthy',
                'status_code': response.status_code,
                'response_time_ms': round(elapsed_ms, 2),
                'error': None
            }
        else:
            return {
                'status': 'unhealthy',
                'status_code': response.status_code,
                'response_time_ms': round(elapsed_ms, 2),
                'error': f"HTTP {response.status_code}"
            }
    except requests.exceptions.Timeout:
        return {
            'status': 'timeout',
            'status_code': None,
            'response_time_ms': None,
            'error': f"请求超时({timeout}秒)"
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'status': 'error',
            'status_code': None,
            'response_time_ms': None,
            'error': f"连接失败: {str(e)}"
        }
    except Exception as e:
        return {
            'status': 'error',
            'status_code': None,
            'response_time_ms': None,
            'error': str(e)
        }

def get_performance_metrics(container_name: str, ssh_host: str = None) -> dict:
    """
    获取容器性能指标（CPU、内存）
    
    Args:
        container_name: 容器名称
        ssh_host: SSH主机地址（可选）
    
    Returns:
        {
            'cpu_percent': float,
            'memory_usage_mb': float,
            'memory_limit_mb': float,
            'memory_percent': float,
            'error': str or None
        }
    """
    from dotenv import dotenv_values
    import os
    import paramiko
    
    try:
        # 确定SSH配置
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        config = dotenv_values(env_file, encoding='utf-8')
        
        if ssh_host:
            # 查找对应服务器的配置
            for key in ['FRONTEND', 'BACKEND']:
                if config.get(f'{key}_SSH_HOST') == ssh_host:
                    ssh_user = config.get(f'{key}_SSH_USER', 'root')
                    ssh_port = int(config.get(f'{key}_SSH_PORT', '22'))
                    ssh_key_path = config.get(f'{key}_SSH_KEY_PATH', '')
                    break
            else:
                # 默认使用backend配置
                ssh_user = config.get('BACKEND_SSH_USER', 'root')
                ssh_port = int(config.get('BACKEND_SSH_PORT', '22'))
                ssh_key_path = config.get('BACKEND_SSH_KEY_PATH', '')
        else:
            ssh_user = config.get('BACKEND_SSH_USER', 'root')
            ssh_port = int(config.get('BACKEND_SSH_PORT', '22'))
            ssh_key_path = config.get('BACKEND_SSH_KEY_PATH', '')
        
        # 建立SSH连接
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        if ssh_key_path and os.path.exists(ssh_key_path):
            private_key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
            ssh_client.connect(hostname=ssh_host or config.get('BACKEND_SSH_HOST'), 
                             port=ssh_port, username=ssh_user, pkey=private_key)
        else:
            ssh_client.connect(hostname=ssh_host or config.get('BACKEND_SSH_HOST'),
                             port=ssh_port, username=ssh_user)
        
        # 执行docker stats命令
        cmd = f"docker stats {container_name} --no-stream --format '{{{{.CPUPerc}}}}|{{{{.MemUsage}}}}|{{{{.MemPerc}}}}'"
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        output = stdout.read().decode('utf-8').strip()
        error_output = stderr.read().decode('utf-8').strip()
        ssh_client.close()
        
        if error_output:
            return {
                'cpu_percent': 0.0,
                'memory_usage_mb': 0.0,
                'memory_limit_mb': 0.0,
                'memory_percent': 0.0,
                'error': error_output
            }
        
        # 解析输出
        parts = output.split('|')
        if len(parts) == 3:
            cpu_str = parts[0].replace('%', '').strip()
            mem_usage_str = parts[1].split('/')[0].strip()
            mem_limit_str = parts[1].split('/')[1].strip()
            mem_perc_str = parts[2].replace('%', '').strip()
            
            # 转换单位
            def parse_memory(mem_str):
                if 'GiB' in mem_str:
                    return float(mem_str.replace('GiB', '').strip()) * 1024
                elif 'MiB' in mem_str:
                    return float(mem_str.replace('MiB', '').strip())
                elif 'KiB' in mem_str:
                    return float(mem_str.replace('KiB', '').strip()) / 1024
                else:
                    return float(mem_str)
            
            return {
                'cpu_percent': float(cpu_str),
                'memory_usage_mb': parse_memory(mem_usage_str),
                'memory_limit_mb': parse_memory(mem_limit_str),
                'memory_percent': float(mem_perc_str),
                'error': None
            }
        else:
            return {
                'cpu_percent': 0.0,
                'memory_usage_mb': 0.0,
                'memory_limit_mb': 0.0,
                'memory_percent': 0.0,
                'error': f"无法解析docker stats输出: {output}"
            }
    
    except Exception as e:
        return {
            'cpu_percent': 0.0,
            'memory_usage_mb': 0.0,
            'memory_limit_mb': 0.0,
            'memory_percent': 0.0,
            'error': str(e)
        }


async def perform_health_checks(state: DiagnosisState) -> dict:
    """
    对所有发现的服务执行健康检查
    
    Returns:
        {
            'health_check_results': {...},
            'port_check_results': {...},
            'performance_metrics': {...},
            'summary': str
        }
    """
    discovered = state.get('discovered_containers', [])
    servers_config = state.get('servers_config', {})
    
    health_results = {}
    port_results = {}
    perf_metrics = {}
    
    for container in discovered:
        name = container.get('name', '')
        ctype = container.get('type', '')
        server = container.get('server', '')
        ports = container.get('ports', '')
        
        # 提取端口号
        port_num = None
        if ports and '->' in ports:
            try:
                port_str = ports.split('->')[0].split('/')[0]
                port_num = int(port_str)
            except:
                pass
        
        if not port_num:
            # 根据类型设置默认端口
            if ctype == 'frontend':
                port_num = 80
            elif ctype == 'backend':
                port_num = 8080
            elif ctype == 'database':
                port_num = 3306
            elif ctype == 'redis':
                port_num = 6379
        
        print(f"[Health Check] 检查服务: {name} ({ctype}) @ {server}:{port_num}")
        
        # HTTP健康检查（仅对前端和后端）
        if ctype in ['frontend', 'backend'] and server and port_num:
            health_path = '/health' if ctype == 'backend' else '/'
            health_result = check_http_health(server, port_num, path=health_path, timeout=5)
            health_results[name] = health_result
            
            # 构建HTTP检查输出信息
            status_code = health_result.get('status_code')
            response_time = health_result.get('response_time_ms')
            time_str = f"{response_time}ms" if response_time is not None else "N/A"
            
            if status_code:
                http_info = f"HTTP {status_code} ({health_result['status']}, 耗时: {time_str})"
            else:
                http_info = f"{health_result['status']} (耗时: {time_str})"
            
            print(f"  健康状态: {http_info}")
        
        # 性能指标获取（所有服务）
        perf_result = get_performance_metrics(name, ssh_host=server)
        perf_metrics[name] = perf_result
        if perf_result.get('error'):
            print(f"  性能指标: ❌ {perf_result['error']}")
        else:
            print(f"  性能指标: CPU={perf_result['cpu_percent']}%, MEM={perf_result['memory_percent']}%")
    
    # 生成摘要
    summary_lines = []
    unhealthy_count = 0
    
    # 只检查有HTTP健康检查结果的服务
    for name, health_result in health_results.items():
        if health_result['status'] != 'healthy':
            unhealthy_count += 1
            if health_result['status'] == 'timeout':
                summary_lines.append(f"- {name}: ⚠️ HTTP超时（服务可能卡死或过载）")
            elif health_result['status'] == 'error':
                summary_lines.append(f"- {name}: ❌ HTTP错误 ({health_result.get('error', '未知')})")
            else:
                summary_lines.append(f"- {name}: ⚠️ HTTP异常 (HTTP {health_result.get('status_code', 'N/A')})")
        else:
            summary_lines.append(f"- {name}: ✅ 正常 (HTTP {health_result['status_code']})")
    
    if unhealthy_count > 0:
        summary = f"\n【健康检查摘要】\n发现 {unhealthy_count} 个服务HTTP异常\n" + "\n".join(summary_lines)
    elif health_results:
        summary = f"\n【健康检查摘要】\n所有HTTP服务运行正常\n" + "\n".join(summary_lines)
    else:
        summary = ""
    
    return {
        'health_check_results': health_results,
        'port_check_results': port_results,
        'performance_metrics': perf_metrics,
        'summary': summary
    }


def determine_config_status(servers_config: dict) -> str:
    """判断配置状态"""
    configured_count = sum(1 for v in servers_config.values() if v)
    
    if configured_count == 0:
        return "none"
    elif configured_count < 4:
        return "partial"
    else:
        return "complete"


def get_stopped_services(state: DiagnosisState) -> List[str]:
    """获取未启动的服务列表"""
    required_types = ['frontend', 'backend', 'database', 'redis']
    discovered = state.get('discovered_containers', [])
    
    # 只统计正常运行的容器（排除有 issue 标记或 status 为 missing 的）
    found_types = {
        c['type'] for c in discovered 
        if c.get('type') and not c.get('issue') and c.get('status') != 'missing'
    }
    
    return list(set(required_types) - found_types)

def has_stopped_services(state: DiagnosisState) -> bool:
    """检查是否有服务未启动"""
    return len(get_stopped_services(state)) > 0

def check_logs_for_service_stop(state: DiagnosisState, stopped_services: List[str]) -> str:
    """检查日志中是否有服务停止的证据"""
    logs_data = state.get('logs_data', '')
    if not logs_data:
        return ""
    
    evidence_keywords = {
        'frontend': ['nginx.*stop', 'frontend.*exit', 'connection refused.*80'],
        'backend': ['java.*exit', 'spring.*shutdown', 'application.*failed', 'connection refused.*8080'],
        'database': ['mysql.*shutdown', 'mysqld.*stop', 'connection refused.*3306'],
        'redis': ['redis.*exit', 'redis-server.*stop', 'connection refused.*6379']
    }
    
    evidence_lines = []
    for service in stopped_services:
        keywords = evidence_keywords.get(service, [])
        for line in logs_data.splitlines():
            if any(re.search(kw, line, re.IGNORECASE) for kw in keywords):
                evidence_lines.append(line)
    
    return '\n'.join(evidence_lines[:20])  # 最多返回20条证据

def format_stopped_services(stopped_services: List[str], logs_evidence: str, discovered_containers: List[dict] = None) -> str:
    """格式化服务未启动的摘要信息"""
    summary = f"检测到以下服务未启动: {', '.join(stopped_services)}\n\n"
    
    # 添加深度诊断信息
    if discovered_containers:
        issues_found = [c for c in discovered_containers if c.get('issue')]
        if issues_found:
            summary += "【深度诊断结果】\n"
            for issue in issues_found:
                server = issue.get('server', 'unknown')
                issue_type = issue.get('issue', '')
                name = issue.get('name', '')
                status = issue.get('status', '')
                details = issue.get('diagnosis_details', '')
                suggestions = issue.get('suggestions', [])
                
                summary += f"- 服务 {name} (服务器 {server}):\n"
                summary += f"  问题类型: {issue_type}\n"
                if details:
                    summary += f"  详情: {details}\n"
                if suggestions:
                    summary += f"  建议操作:\n"
                    for sug in suggestions:
                        summary += f"    * `{sug}`\n"
                summary += "\n"
    
    if logs_evidence:
        summary += f"日志证据:\n{logs_evidence}"
    
    return summary

def get_container_for_service(service_name: str, state: DiagnosisState) -> Optional[str]:
    """根据服务名称从已发现的容器中查找对应的容器名"""
    discovered = state.get('discovered_containers', [])
    for container in discovered:
        name = container.get('name', '').lower()
        if service_name in name:
            return container.get('container_name') or name
    return None

def extract_service_logs(all_logs: str, service: str) -> str:
    """从合并的日志中提取特定服务的日志"""
    if not all_logs:  # 防止 None 或空字符串
        return ''
    marker = f"--- {service.upper()}"
    if marker in all_logs:
        parts = all_logs.split(marker)
        if len(parts) > 1:
            section = parts[1].split('---')[0]
            return section.strip()
    return ''

def get_redis_container_status(state: DiagnosisState) -> str:
    """从已发现的容器中获取 Redis 状态"""
    discovered = state.get('discovered_containers', [])
    for container in discovered:
        if 'redis' in container.get('name', '').lower():
            return f"发现容器: {container.get('container_name')}"
    return "未发现 Redis 容器"

def identify_container_type(name: str, ports: str) -> str:
    """根据容器名称和端口识别容器类型"""
    name_lower = name.lower()
    ports_lower = ports.lower()
    
    # 前端识别（优先级较低，避免误判）
    if '80/tcp' in ports_lower and '8080/tcp' not in ports_lower:
        return 'frontend'
    if '443/tcp' in ports_lower:
        return 'frontend'
    if any(kw in name_lower for kw in ['frontend', 'vue', 'nginx']):
        return 'frontend'
    
    # 后端识别（优先级较高）
    if '8080/tcp' in ports_lower:
        return 'backend'
    if any(kw in name_lower for kw in ['app', 'backend', 'java', 'spring']):
        return 'backend'
    
    # 数据库识别
    if any(kw in name_lower for kw in ['mysql', 'mariadb', 'postgres']):
        return 'database'
    if '3306/tcp' in ports_lower or '5432/tcp' in ports_lower:
        return 'database'
    
    # Redis 识别
    if 'redis' in name_lower or '6379/tcp' in ports_lower:
        return 'redis'
    
    return 'unknown'

async def check_missing_service_on_server(ssh_client, target_server: dict, expected_service_type: str, discovered: List[dict]) -> dict:
    """
    检查服务器上缺失的预期服务（通用函数，适用于所有服务类型）
    
    Args:
        ssh_client: SSH 客户端连接
        target_server: 服务器配置
        expected_service_type: 预期的服务类型 (frontend/backend/database/redis)
        discovered: 当前已发现的容器列表
    
    Returns:
        诊断结果字典，包含 issue_type, details, suggestions
    """
    result = {
        "issue_type": "unknown",
        "details": "",
        "suggestions": [],
        "missing_containers": []
    }
    
    # 检查该服务器上是否已有其他容器运行
    server_containers = [c for c in discovered if c.get('server') == target_server['ssh_host']]
    has_other_containers = len(server_containers) > 0
    
    if has_other_containers:
        print(f"[Discover Containers] 服务器 {target_server['ssh_host']} 上有 {len(server_containers)} 个其他容器运行，但缺少 {expected_service_type} 服务")
        
        # 1. 查找 docker-compose 文件
        stdin, stdout, stderr = ssh_client.exec_command(
            "find / -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' 2>/dev/null | head -5"
        )
        compose_files = stdout.read().decode('utf-8').strip()
        
        if compose_files:
            print(f"[Discover Containers] 发现 docker-compose 文件:")
            for f in compose_files.splitlines():
                print(f"  - {f}")
            
            # 检查第一个 docker-compose 文件中的服务定义
            first_compose = compose_files.splitlines()[0]
            compose_dir = '/'.join(first_compose.split('/')[:-1])
            
            # 获取 docker-compose 定义的所有服务
            stdin, stdout, stderr = ssh_client.exec_command(
                f"cd {compose_dir} && docker-compose config --services 2>/dev/null"
            )
            defined_services = stdout.read().decode('utf-8').strip().splitlines()
            
            if defined_services:
                print(f"[Discover Containers] docker-compose 定义的服务: {', '.join(defined_services)}")
                
                # 检查是否有与预期服务类型相关的定义
                # 使用通用的关键词匹配规则，适用于所有服务类型
                related_services = []
                for svc in defined_services:
                    svc_lower = svc.lower()
                    # 直接匹配服务类型名称
                    if expected_service_type in svc_lower:
                        related_services.append(svc)
                    else:
                        # 根据服务类型使用特定关键词匹配
                        keyword_map = {
                            'frontend': ['vue', 'nginx', 'web', 'ui'],
                            'backend': ['app', 'java', 'spring', 'api', 'server'],
                            'database': ['mysql', 'postgres', 'db', 'mariadb'],
                            'redis': ['redis', 'cache']
                        }
                        keywords = keyword_map.get(expected_service_type, [])
                        if any(kw in svc_lower for kw in keywords):
                            related_services.append(svc)
                
                if related_services:
                    print(f"[Discover Containers] 发现与 {expected_service_type} 相关的服务定义: {', '.join(related_services)}")
                    
                    # 检查这些服务的状态
                    stdin, stdout, stderr = ssh_client.exec_command(
                        f"cd {compose_dir} && docker-compose ps --format '{{{{.Name}}}}\\t{{{{.Status}}}}' 2>/dev/null"
                    )
                    compose_status = stdout.read().decode('utf-8').strip()
                    
                    stopped_related = []
                    for line in compose_status.splitlines():
                        parts = line.split('\t')
                        name = parts[0] if len(parts) > 0 else ''
                        status = parts[1] if len(parts) > 1 else ''
                        
                        # 检查是否是相关服务且已停止
                        if any(rel_svc in name for rel_svc in related_services):
                            if 'exit' in status.lower() or 'stopped' in status.lower() or not status:
                                stopped_related.append({"name": name, "status": status})
                    
                    if stopped_related:
                        result["issue_type"] = "compose_service_stopped"
                        result["details"] = f"docker-compose 中定义了 {expected_service_type} 相关服务，但已停止"
                        result["missing_containers"] = stopped_related
                        result["suggestions"] = [
                            f"查看日志: cd {compose_dir} && docker-compose logs {' '.join([s['name'] for s in stopped_related])}",
                            f"重启服务: cd {compose_dir} && docker-compose up -d {' '.join([s['name'] for s in stopped_related])}"
                        ]
                        return result
                    else:
                        result["issue_type"] = "compose_service_not_running"
                        result["details"] = f"docker-compose 中定义了 {expected_service_type} 相关服务，但未在运行容器中"
                        result["suggestions"] = [
                            f"检查服务状态: cd {compose_dir} && docker-compose ps",
                            f"启动服务: cd {compose_dir} && docker-compose up -d"
                        ]
                        return result
        
        # 2. 检查是否有已停止的相关容器
        stdin, stdout, stderr = ssh_client.exec_command(
            "docker ps -a --format '{{.Names}}\\t{{.Status}}' | grep -v 'Up'"
        )
        all_stopped = stdout.read().decode('utf-8').strip()
        
        if all_stopped:
            stopped_related = []
            for line in all_stopped.splitlines():
                parts = line.split('\t')
                name = parts[0] if len(parts) > 0 else ''
                status = parts[1] if len(parts) > 1 else ''
                
                # 检查是否与预期服务类型相关（使用通用关键词匹配）
                name_lower = name.lower()
                keyword_map = {
                    'frontend': ['frontend', 'vue', 'nginx', 'web', 'ui'],
                    'backend': ['backend', 'app', 'java', 'spring', 'api', 'server'],
                    'database': ['mysql', 'postgres', 'db', 'database', 'mariadb'],
                    'redis': ['redis', 'cache']
                }
                keywords = keyword_map.get(expected_service_type, [expected_service_type])
                is_related = any(kw in name_lower for kw in keywords)
                
                if is_related:
                    stopped_related.append({"name": name, "status": status})
            
            if stopped_related:
                result["issue_type"] = "container_stopped"
                result["details"] = f"发现已停止的 {expected_service_type} 相关容器"
                result["missing_containers"] = stopped_related
                result["suggestions"] = [
                    f"查看日志: docker logs {' '.join([s['name'] for s in stopped_related])}",
                    f"重启容器: docker start {' '.join([s['name'] for s in stopped_related])}"
                ]
                return result
        
        # 3. 未找到相关线索
        result["issue_type"] = "service_not_found"
        result["details"] = f"服务器上未发现 {expected_service_type} 相关容器或配置"
        result["suggestions"] = [
            f"检查部署脚本是否正确执行",
            f"确认 {expected_service_type} 服务是否应该在此服务器上运行"
        ]
        return result
    
    else:
        # 服务器上完全没有容器
        print(f"[Discover Containers] 服务器 {target_server['ssh_host']} 上无任何容器运行")
        
        # 检查 Docker 是否运行
        stdin, stdout, stderr = ssh_client.exec_command("systemctl is-active docker 2>/dev/null || service docker status 2>/dev/null")
        docker_status = stdout.read().decode('utf-8').strip()
        
        if 'active' not in docker_status.lower():
            result["issue_type"] = "docker_not_running"
            result["details"] = f"Docker 服务未运行: {docker_status}"
            result["suggestions"] = [
                "启动 Docker: systemctl start docker",
                "设置开机自启: systemctl enable docker"
            ]
        else:
            # Docker 正常运行，但没有任何容器 - 检查 docker-compose 文件
            print(f"[Discover Containers] Docker 正常运行，检查是否有 docker-compose 配置文件...")
            
            # 查找 docker-compose 文件
            stdin, stdout, stderr = ssh_client.exec_command(
                "find / -maxdepth 4 -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' 2>/dev/null | head -5"
            )
            compose_files = stdout.read().decode('utf-8').strip()
            
            if compose_files:
                print(f"[Discover Containers] 发现 docker-compose 文件:")
                compose_file_list = compose_files.splitlines()
                for f in compose_file_list:
                    print(f"  - {f}")
                
                # 分析第一个 docker-compose 文件中的服务定义
                first_compose = compose_file_list[0]
                compose_dir = '/'.join(first_compose.split('/')[:-1])
                
                print(f"[Discover Containers] 分析 docker-compose 文件: {first_compose}")
                
                # 获取 docker-compose 定义的所有服务
                stdin, stdout, stderr = ssh_client.exec_command(
                    f"cd {compose_dir} && docker-compose config --services 2>/dev/null"
                )
                defined_services = stdout.read().decode('utf-8').strip().splitlines()
                
                if defined_services:
                    print(f"[Discover Containers] docker-compose 定义的服务: {', '.join(defined_services)}")
                    
                    # 检查是否有与预期服务类型相关的定义
                    related_services = []
                    for svc in defined_services:
                        svc_lower = svc.lower()
                        # 直接匹配服务类型名称
                        if expected_service_type in svc_lower:
                            related_services.append(svc)
                        else:
                            # 根据服务类型使用特定关键词匹配
                            keyword_map = {
                                'frontend': ['vue', 'nginx', 'web', 'ui'],
                                'backend': ['app', 'java', 'spring', 'api', 'server'],
                                'database': ['mysql', 'postgres', 'db', 'mariadb'],
                                'redis': ['redis', 'cache']
                            }
                            keywords = keyword_map.get(expected_service_type, [])
                            if any(kw in svc_lower for kw in keywords):
                                related_services.append(svc)
                    
                    if related_services:
                        print(f"[Discover Containers] [OK] 找到与 {expected_service_type} 相关的服务定义: {', '.join(related_services)}")
                        
                        result["issue_type"] = "compose_services_not_started"
                        result["details"] = (
                            f"Docker 正常运行，{compose_dir}/docker-compose.yml 中定义了 {expected_service_type} 相关服务 "
                            f"({', '.join(related_services)})，但所有容器都已被删除或停止"
                        )
                        result["suggestions"] = [
                            f"查看 docker-compose 配置: cat {first_compose}",
                            f"启动所有服务: cd {compose_dir} && docker-compose up -d",
                            f"查看服务日志: cd {compose_dir} && docker-compose logs -f"
                        ]
                        return result
                    else:
                        print(f"[Discover Containers] [WARN] docker-compose 中未找到与 {expected_service_type} 相关的服务")
            
            # 未找到 docker-compose 或没有相关服务
            result["issue_type"] = "no_containers"
            result["details"] = "Docker 正常运行，但没有任何容器"
            result["suggestions"] = [
                "检查是否有 docker-compose 文件需要启动",
                "检查容器是否被意外删除",
                "查看系统日志确认是否有自动清理操作: journalctl -u docker.service --since '1 hour ago'"
            ]
        
        return result

# ===== 节点函数 =====

async def analyze_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点1：分析当前状态，决定下一步要做什么
    """
    print(f"\n{'='*70}")
    print(f"[Analyze] 分析当前状态 (迭代 {state['iteration_count']}/{state['max_iterations']})")
    print(f"{'='*70}")
    
    # === 强制检查最大迭代次数 ===
    if state['iteration_count'] >= state['max_iterations']:
        print(f"[Analyze] [WARN] 已达到最大迭代次数 ({state['max_iterations']}),强制生成报告")
        print(f"[Analyze] [DEBUG] 清空 next_action (原值: {state.get('next_action')})")
        return {
            **state,
            "current_step": "generate_report",
            "next_action": None,  # 清空next_action避免混淆
            "actions_taken": state.get('actions_taken', []) + ["force_stop_by_max_iterations"]
        }
    
    # === 新增：检测异常的资源使用情况（高CPU、高内存）===
    docker_stats_info = state.get('docker_stats_info', '')
    resource_anomaly_checked = state.get('resource_anomaly_checked', False)
    print(f"[Analyze] [DEBUG] docker_stats_info 长度: {len(docker_stats_info)}, resource_anomaly_checked: {resource_anomaly_checked}")
    if docker_stats_info and not resource_anomaly_checked:
        # 解析 docker stats 数据，检测异常
        high_cpu_containers = []
        high_memory_containers = []
        
        # 简单的关键词检测（实际应该解析表格数据）
        lines = docker_stats_info.split('\n')
        for line in lines:
            # 检测高 CPU（>100%）
            if '%' in line:
                try:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if '%' in part:
                            cpu_value = float(part.replace('%', '').strip())
                            if cpu_value > 100:
                                container_name = parts[i-1] if i > 0 else 'unknown'
                                high_cpu_containers.append((container_name, cpu_value))
                            break
                except:
                    pass
        
        if high_cpu_containers:
            print(f"[Analyze] [ALERT] 检测到 {len(high_cpu_containers)} 个容器 CPU 使用率异常高:")
            for name, cpu in high_cpu_containers:
                print(f"  - {name}: {cpu}%")
            
            # 【重要】高CPU是紧急问题，需要深入诊断
            # 即使有其他问题（如服务缺失），也要先处理高CPU问题
            print("[Analyze] [CRITICAL] 高CPU使用率属于紧急问题，需要深入诊断根因")
            
            # 如果还没有读取日志，触发读取
            if not state.get('logs_data'):
                print("[Analyze] 决定读取高CPU容器的详细日志、线程信息和资源使用情况")
                return {
                    **state,
                    "current_step": "collect_data",
                    "next_action": "read_logs",
                    "resource_anomaly_checked": True,
                    "actions_taken": state.get('actions_taken', []) + ["detect_high_cpu_critical"]
                }
            else:
                # 日志已读取，继续其他诊断步骤
                print("[Analyze] 日志已读取，继续其他诊断步骤")
                # 清除 next_action，避免循环
                state = {**state, "next_action": None}
    
    # === 新增:服务未启动的快速判断 ===
    if state.get('config_status') == 'complete' and has_stopped_services(state):
        stopped_services = get_stopped_services(state)
        logs_data = state.get('logs_data', '')
        discovered = state.get('discovered_containers') or []
        
        # 检查是否有服务完全缺失（容器不存在）
        missing_containers = [c for c in discovered if c.get('issue') in ['no_containers', 'service_not_found', 'compose_services_not_started']]
        
        if missing_containers:
            # 【重要优化】服务完全缺失时，不要立即生成报告
            # 应该先收集其他正常服务的日志和状态，以便全面诊断
            print(f"[Analyze] 检测到 {len(missing_containers)} 个服务完全缺失")
            for mc in missing_containers:
                print(f"  - {mc['name']} ({mc['type']}): {mc.get('diagnosis_details', '')}")
            
            # 如果还没有读取日志，先读取所有可用服务的日志
            if not state.get('logs_data'):
                print("[Analyze] 决定先读取其他服务的日志以进行全面诊断")
                return {
                    **state,
                    "current_step": "collect_data",
                    "next_action": "read_logs",
                    "actions_taken": state.get('actions_taken', []) + ["detect_missing_services"]
                }
            
            # 如果已有日志数据，再生成报告
            print(f"[Analyze] 已有日志数据，生成包含缺失服务的完整报告")
            missing_summary = format_stopped_services(stopped_services, '', discovered)
            return {
                **state,
                "current_step": "generate_report",
                "service_status_summary": missing_summary,
                "actions_taken": state.get('actions_taken', []) + ["detect_missing_services"]
            }
        
        # 如果已有日志数据,检查是否有服务停止的证据
        if logs_data:
            logs_evidence = check_logs_for_service_stop(state, stopped_services)
            
            if logs_evidence:  # 日志中有相关证据
                print(f"[Analyze] 检测到 {len(stopped_services)} 个服务未启动,直接生成报告")
                return {
                    **state,
                    "current_step": "generate_report",
                    "service_status_summary": format_stopped_services(stopped_services, logs_evidence, discovered),
                    "actions_taken": state.get('actions_taken', []) + ["detect_stopped_services"]
                }
    
    # === 新增：可疑容器检查（端口为空或状态异常）===
    discovered = state.get('discovered_containers') or []  # 防止 None 值
    suspicious_containers = [c for c in discovered if c.get('issue') == 'suspicious_container']
    
    if suspicious_containers:
        print(f"[Analyze] [WARN] 发现 {len(suspicious_containers)} 个可疑容器，需要进一步诊断")
        for c in suspicious_containers:
            print(f"  - {c['name']}: {c.get('diagnosis_details', '')}")
        
        # 如果有可疑容器但还没有读取日志，先读取日志
        if not state.get('logs_data'):
            print("[Analyze] 决定先读取日志以确认容器状态")
            return {
                **state,
                "current_step": "collect_data",
                "next_action": "read_logs",
                "actions_taken": state.get('actions_taken', []) + ["detect_suspicious_containers"]
            }
    
    # === 新增:配置不足的快速判断 ===
    if state.get('config_status') == 'none':
        print("[Analyze] 配置信息不足,返回错误")
        return {
            **state,
            "current_step": "error_no_config",
            "actions_taken": state.get('actions_taken', []) + ["check_config"]
        }
    
    # === 新增:部分配置时触发 Docker 发现 ===
    if state.get('config_status') == 'partial' and not state.get('discovered_containers'):
        print("[Analyze] 配置不完整,触发 Docker 容器发现")
        return {
            **state,
            "current_step": "discover_containers",
            "actions_taken": state.get('actions_taken', []) + ["trigger_discovery"]
        }
    
    # === 原有逻辑保持不变 ===
    # 构建分析提示
    actions_taken_str = ', '.join(state.get('actions_taken', [])) if state.get('actions_taken') else '无'
    
    alert = state.get('alert_event', {})
    alert_desc = f"{alert.get('alert_name', 'Unknown')} - {alert.get('description', '')}"
    
    prompt = f"""你是运维诊断专家。请基于当前已收集的数据决定下一步行动。

【已执行的行动】: {actions_taken_str}
【当前数据状态】:
- 内存信息: {'已收集' if state.get('memory_info') else '未收集'}
- CPU信息: {'已收集' if state.get('cpu_info') else '未收集'}
- 服务状态: {'已收集' if state.get('service_status') else '未收集'}
- MySQL状态: {'已收集' if state.get('mysql_status') else '未收集'}
- 日志数据: {'已收集' if state.get('logs_data') else '未收集'}
- 健康检查: {'已执行' if state.get('health_check_results') else '未执行'}
- 当前日志追溯范围: {state.get('log_search_range_minutes', 0)}分钟
- 已收集的日志范围: {len(state.get('logs_collected_ranges', []))}个
- Docker Stats: {'已收集（见下方容器资源使用情况）' if state.get('docker_stats_info') else '未收集'}

{state.get('docker_stats_info', '')}

请决定下一步行动（只返回一个行动名称，不要其他内容）：
1. check_memory - 检查内存使用情况
2. check_cpu - 检查CPU使用情况
3. check_service - 检查服务运行状态
4. check_mysql - 检查MySQL数据库状态
5. read_logs - 读取或扩大日志追溯范围
6. read_logs_recent - 读取相关服务的最近10分钟日志
7. perform_health_check - 执行服务健康检查（HTTP+端口+性能）
8. generate_report - 生成诊断报告

决策规则（按优先级判断）：
1. **如果检测到服务完全缺失** → 直接 generate_report
2. 如果check_memory未执行 → check_memory
3. 如果check_memory已执行但check_cpu未执行 → check_cpu
4. 如果核心资源指标已检查但未执行健康检查 → perform_health_check
5. 如果还未读取任何日志 → read_logs
6. 如果已读取后端日志但未读取相关服务日志 → read_logs_recent
7. 如果已有足够信息 → generate_report

重要：
- **健康检查应该在资源检查之后、日志分析之前执行**
- 健康检查可以帮助确认服务当前是否真正可用
- 如果健康检查发现服务不可用，需要在报告中明确指出
- **⚠️ 重要约束：perform_health_check 只能执行一次！**
  - 如果已经执行过健康检查（actions_taken 中包含 perform_health_check），不要再选择它
  - 健康检查只需要执行一次就能获取所有服务的状态
  - 重复执行健康检查是浪费资源，应该直接进行日志分析或生成报告
"""
    
    response = await llm.ainvoke(prompt)
    next_action = response.content.strip()
    
    # === 防护机制1：检测重复行动 ===
    actions_taken = state.get('actions_taken', [])
    if len(actions_taken) >= 2:
        # 检查最近3次行动是否都是同一个行动
        recent_actions = actions_taken[-3:] if len(actions_taken) >= 3 else actions_taken
        if len(set(recent_actions)) == 1 and recent_actions[0] == next_action:
            print(f"[Analyze] [WARN] 检测到行动 '{next_action}' 已连续执行 {len(recent_actions)} 次，强制切换到 generate_report")
            next_action = "generate_report"
    
    # === 防护机制2：防止重复执行健康检查 ===
    if next_action == "perform_health_check":
        health_check_count = state.get('_health_check_execution_count', 0)
        if health_check_count >= 1:
            print(f"[Analyze] [WARN] 健康检查已执行过 {health_check_count} 次，避免重复执行，切换到 read_logs")
            # 如果已经读取过日志，直接生成报告
            if state.get('logs_data'):
                next_action = "generate_report"
            else:
                next_action = "read_logs"
    
    print(f"[Analyze] 决定下一步行动: {next_action}")
    
    return {
        **state,
        "current_step": next_action,
        "next_action": next_action,  # 同时更新next_action供collect_data_node使用
        "actions_taken": state.get('actions_taken', []) + [next_action]
    }


# async def scan_anomalies_node(state: DiagnosisState) -> DiagnosisState:
#     """
#     节点2：快速扫描日志，识别异常时间点
#     """
#     print(f"\n{'='*70}")
#     print(f"[Scan Anomalies] 快速扫描异常时间点")
#     print(f"{'='*70}")
#
#     from Routing.tool_cache import tool_cache
#     tools = await tool_cache.get_tools("log-reader")
#     scan_tool = next((t for t in tools if t.name == "scan_logs_for_anomalies"), None)
#     
#     if not scan_tool:
#         print("[Scan Anomalies] 未找到scan_logs_for_anomalies工具")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }
#     
#     try:
#         result = await scan_tool.ainvoke({
#             "container_name": state['container_name'],
#             "time_range_hours": 2  # 扫描过去2小时
#         })
#         
#         # 解析MCP返回格式
#         if isinstance(result, list) and len(result) > 0:
#             first_item = result[0]
#             if isinstance(first_item, dict) and 'text' in first_item:
#                 scan_data = json.loads(first_item['text'])
#             else:
#                 scan_data = first_item
#         else:
#             scan_data = result
#         
#         if scan_data.get('status') == 'success':
#             timestamps = scan_data.get('anomaly_timestamps', [])
#             print(f"[Scan Anomalies] 找到 {len(timestamps)} 个异常时间点")
#             for ts in timestamps[:5]:
#                 print(f"  - {ts}")
#             
#             return {
#                 **state,
#                 "anomaly_timestamps": timestamps,
#                 "iteration_count": state['iteration_count'] + 1
#             }
#         else:
#             print(f"[Scan Anomalies] 扫描失败: {scan_data.get('message')}")
#             return {
#                 **state,
#                 "anomaly_timestamps": [],
#                 "iteration_count": state['iteration_count'] + 1
#             }
#     
#     except Exception as e:
#         print(f"[Scan Anomalies] 错误: {str(e)}")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }


async def discover_containers_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点:Docker 容器发现
    通过 SSH 连接到所有已配置的服务器,获取所有运行中的容器信息
    """
    print(f"\n{'='*70}")
    print(f"[Discover Containers] 开始 Docker 容器发现")
    print(f"{'='*70}")
    
    # 从已配置的服务器中遍历所有有 SSH 配置的服务器
    servers_config = state.get('servers_config', {})
    
    # 收集所有有 SSH 配置的服务器
    ssh_servers = []
    for server_type in ['frontend', 'backend']:
        server = servers_config.get(server_type)
        if server and server.get('ssh_host'):
            ssh_servers.append((server_type, server))
    
    if not ssh_servers:
        print("[Discover Containers] 没有可用的服务器配置")
        return {
            **state,
            "discovered_containers": [],
            "iteration_count": state['iteration_count'] + 1
        }
    
    all_discovered = []
    
    # 遍历所有服务器
    for server_type, target_server in ssh_servers:
        try:
            # 使用 paramiko 建立 SSH 连接
            import warnings
            warnings.filterwarnings('ignore', category=DeprecationWarning, module='paramiko')
            import paramiko
            
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 加载 SSH 密钥
            private_key = None
            key_types = [
                paramiko.RSAKey,
                paramiko.ECDSAKey,
                paramiko.Ed25519Key,
            ]
            
            key_path = target_server.get('ssh_key_path', '')
            for key_type in key_types:
                try:
                    private_key = key_type.from_private_key_file(key_path)
                    break
                except paramiko.SSHException:
                    continue
            
            if not private_key:
                print(f"[Discover Containers] 警告: 无法识别的密钥格式: {key_path}")
                continue
            
            # 建立连接
            ssh_client.connect(
                hostname=target_server['ssh_host'],
                port=target_server.get('ssh_port', 22),
                username=target_server.get('ssh_user', 'root'),
                pkey=private_key,
                timeout=30
            )
            
            print(f"[Discover Containers] SSH 连接成功: {target_server['ssh_host']}")
            
            # 执行 docker ps 命令
            stdin, stdout, stderr = ssh_client.exec_command(
                "docker ps --format '{{.Names}}\\t{{.Ports}}\\t{{.Status}}'"
            )
            
            output = stdout.read().decode('utf-8').strip()
            error_output = stderr.read().decode('utf-8').strip()
            
            if error_output:
                print(f"[Discover Containers] Docker 命令错误: {error_output}")
                ssh_client.close()
                continue
            
            # 解析输出
            discovered = []
            for line in output.splitlines():
                if not line.strip():
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 2:
                    container_name = parts[0].strip()
                    ports = parts[1].strip()
                    status = parts[2].strip() if len(parts) > 2 else "running"
                    
                    # 识别容器类型
                    container_type = identify_container_type(container_name, ports)
                    
                    container_info = {
                        "name": container_name,
                        "ports": ports,
                        "type": container_type,
                        "status": status,
                        "server": target_server['ssh_host']
                    }
                    
                    # === 新增：检测可疑容器（端口为空或状态异常）===
                    if not ports or status.lower() in ['exited', 'dead', 'created']:
                        print(f"[Discover Containers] [WARN] 发现可疑容器: {container_name} (端口: '{ports}', 状态: {status})")
                        container_info['issue'] = 'suspicious_container'
                        container_info['diagnosis_details'] = f"容器状态异常 - 端口: '{ports}', 状态: {status}"
                        container_info['suggestions'] = [
                            f"查看容器详细状态: docker inspect {container_name}",
                            f"查看容器日志: docker logs {container_name} --tail 50",
                            f"重启容器: docker restart {container_name}"
                        ]
                    
                    discovered.append(container_info)
            
            if discovered:
                print(f"[Discover Containers] 在 {target_server['ssh_host']} 上发现 {len(discovered)} 个容器:")
                for c in discovered:
                    print(f"  - {c['name']} ({c['type']}): {c['ports']}")
                all_discovered.extend(discovered)
            else:
                print(f"[Discover Containers] 在 {target_server['ssh_host']} 上未发现容器")
            
            # === 新增：检查预期服务是否缺失 ===
            # 确定该服务器预期的服务类型
            expected_types_for_server = []
            for svc_type, svc_config in servers_config.items():
                if svc_config and svc_config.get('ssh_host') == target_server['ssh_host']:
                    expected_types_for_server.append(svc_type)
            
            # 检查是否有预期服务类型未在发现的容器中出现
            found_types = {c['type'] for c in discovered if c.get('type')}
            missing_types = [t for t in expected_types_for_server if t not in found_types]
            
            if missing_types:
                print(f"[Discover Containers] [WARN] 服务器 {target_server['ssh_host']} 缺少预期服务: {', '.join(missing_types)}")
                
                # 对每个缺失的服务类型进行深度诊断
                for missing_type in missing_types:
                    print(f"[Discover Containers] 开始诊断缺失的 {missing_type} 服务...")
                    try:
                        diagnosis = await check_missing_service_on_server(ssh_client, target_server, missing_type, all_discovered)
                        
                        print(f"[Discover Containers] 诊断结果: {diagnosis['issue_type']}")
                        print(f"[Discover Containers] 详情: {diagnosis['details']}")
                        if diagnosis['suggestions']:
                            print(f"[Discover Containers] 建议操作:")
                            for sug in diagnosis['suggestions']:
                                print(f"  - {sug}")
                        
                        # 将诊断结果添加到 discovered 列表中（标记为问题容器）
                        for missing_container in diagnosis.get('missing_containers', []):
                            problem_container = {
                                "name": missing_container['name'],
                                "type": missing_type,
                                "status": missing_container.get('status', 'missing'),
                                "server": target_server['ssh_host'],
                                "ports": "",
                                "issue": diagnosis['issue_type'],
                                "diagnosis_details": diagnosis['details'],
                                "suggestions": diagnosis['suggestions']
                            }
                            all_discovered.append(problem_container)
                        
                        # 如果没有具体容器信息，创建一个占位符
                        if not diagnosis.get('missing_containers'):
                            problem_container = {
                                "name": f"{missing_type}-service",
                                "type": missing_type,
                                "status": "missing",
                                "server": target_server['ssh_host'],
                                "ports": "",
                                "issue": diagnosis['issue_type'],
                                "diagnosis_details": diagnosis['details'],
                                "suggestions": diagnosis['suggestions']
                            }
                            all_discovered.append(problem_container)
                    except Exception as e:
                        print(f"[Discover Containers] 诊断 {missing_type} 服务时出错: {e}")
            
            # 关闭 SSH 连接
            ssh_client.close()
        
        except Exception as e:
            print(f"[Discover Containers] 连接 {target_server['ssh_host']} 失败: {str(e)}")
            continue
    
    # 汇总结果
    print(f"\n[Discover Containers] Docker 容器发现结束，一共发现了 {len(all_discovered)} 个容器:")
    if all_discovered:
        for c in all_discovered:
            name = c['name']
            ctype = c['type']
            ports = c['ports']
            server = c['server']
            issue = c.get('issue', '')
            
            # 如果是占位符容器（有 issue 标记），显示特殊标识
            if issue:
                status_marker = "[MISSING]"
                print(f"  - {name} ({ctype}): {ports} [服务器: {server}] {status_marker}")
                # 显示诊断详情
                details = c.get('diagnosis_details', '')
                if details:
                    print(f"    → {details}")
            else:
                print(f"  - {name} ({ctype}): {ports} [服务器: {server}]")
    else:
        print("  (无)")
    
    # 更新 servers_config 中的容器名称
    updated_config = state.get('servers_config', {}).copy()
    for container in all_discovered:
        if container['type'] == 'frontend' and not updated_config.get('frontend', {}).get('container_name'):
            updated_config.setdefault('frontend', {})['container_name'] = container['name']
        elif container['type'] == 'backend' and not updated_config.get('backend', {}).get('container_name'):
            updated_config.setdefault('backend', {})['container_name'] = container['name']
    
    # === 新增：获取 docker stats 信息 ===
    docker_stats_info = ""
    servers_config = state.get('servers_config', {})
    
    # 按服务器分组容器
    containers_by_server = {}
    for container in all_discovered:
        server = container.get('server', 'unknown')
        if server not in containers_by_server:
            containers_by_server[server] = []
        containers_by_server[server].append(container)
    
    # 对每个服务器执行 docker stats
    import paramiko
    for server_ip, containers in containers_by_server.items():
        # 查找该服务器的 SSH 配置
        ssh_config = None
        for svc_type, svc_config in servers_config.items():
            if svc_config and svc_config.get('ssh_host') == server_ip:
                ssh_config = svc_config
                break
        
        if not ssh_config:
            print(f"[Discover Containers] [WARN] 未找到服务器 {server_ip} 的 SSH 配置")
            continue
        
        try:
            # 建立 SSH 连接
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            key_path = ssh_config.get('ssh_key_path', '')
            if key_path:
                key = paramiko.RSAKey.from_private_key_file(key_path)
                ssh_client.connect(
                    hostname=server_ip,
                    username=ssh_config.get('ssh_user', 'root'),
                    pkey=key,
                    timeout=10
                )
            else:
                ssh_client.connect(
                    hostname=server_ip,
                    username=ssh_config.get('ssh_user', 'root'),
                    password=ssh_config.get('ssh_password', ''),
                    timeout=10
                )
            
            # 执行 docker stats 命令（只取一次快照，不持续监控）
            stdin, stdout, stderr = ssh_client.exec_command(
                "docker stats --no-stream --format 'table {{.ID}}\t{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}'"
            )
            stats_output = stdout.read().decode('utf-8').strip()
            error_output = stderr.read().decode('utf-8').strip()
            
            if error_output:
                print(f"[Discover Containers] [WARN] docker stats 错误: {error_output}")
            
            if stats_output:
                docker_stats_info += f"\n服务器 {server_ip}:\n{stats_output}\n"
                print(f"[Discover Containers] 成功获取服务器 {server_ip} 的 docker stats")
            else:
                print(f"[Discover Containers] [WARN] 服务器 {server_ip} 的 docker stats 为空")
            
            ssh_client.close()
        except Exception as e:
            print(f"[Discover Containers] [WARN] 获取服务器 {server_ip} 的 docker stats 失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"[Discover Containers] [DEBUG] docker_stats_info 长度: {len(docker_stats_info)}")
    if docker_stats_info:
        print(f"[Discover Containers] [DEBUG] docker_stats_info 前100字符: {docker_stats_info[:100]}")
    
    return {
        **state,
        "discovered_containers": all_discovered,
        "servers_config": updated_config,
        "config_status": "complete",  # 发现后升级为 complete
        "docker_stats_info": docker_stats_info,  # 新增：保存 docker stats
        "iteration_count": state['iteration_count'] + 1
    }
#     
#     from Routing.tool_cache import tool_cache
#     tools = await tool_cache.get_tools("log-reader")
#     scan_tool = next((t for t in tools if t.name == "scan_logs_for_anomalies"), None)
#     
#     if not scan_tool:
#         print("[Scan Anomalies] 未找到scan_logs_for_anomalies工具")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }
#     
#     try:
#         result = await scan_tool.ainvoke({
#             "container_name": state['container_name'],
#             "time_range_hours": 2  # 扫描过去2小时
#         })
#         
#         # 解析MCP返回格式
#         if isinstance(result, list) and len(result) > 0:
#             first_item = result[0]
#             if isinstance(first_item, dict) and 'text' in first_item:
#                 scan_data = json.loads(first_item['text'])
#             else:
#                 scan_data = first_item
#         else:
#             scan_data = result
#         
#         if scan_data.get('status') == 'success':
#             timestamps = scan_data.get('anomaly_timestamps', [])
#             print(f"[Scan Anomalies] 找到 {len(timestamps)} 个异常时间点")
#             for ts in timestamps[:5]:
#                 print(f"  - {ts}")
#             
#             return {
#                 **state,
#                 "anomaly_timestamps": timestamps,
#                 "iteration_count": state['iteration_count'] + 1
#             }
#         else:
#             print(f"[Scan Anomalies] 扫描失败: {scan_data.get('message')}")
#             return {
#                 **state,
#                 "anomaly_timestamps": [],
#                 "iteration_count": state['iteration_count'] + 1
#             }
#     
#     except Exception as e:
#         print(f"[Scan Anomalies] 错误: {str(e)}")
#         return {
#             **state,
#             "anomaly_timestamps": [],
#             "iteration_count": state['iteration_count'] + 1
#         }


async def collect_data_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点3：根据当前步骤收集相应的数据
    """
    # === 修复：使用 next_action 而不是 current_step ===
    action = state.get('next_action', state['current_step'])
    
    # 追踪 perform_health_check 执行次数
    if action == "perform_health_check":
        health_check_count = state.get('_health_check_execution_count', 0) + 1
        print(f"\n{'='*70}")
        print(f"[Collect Data] ⚠️  WARNING: perform_health_check 第 {health_check_count} 次执行")
        print(f"{'='*70}")
    else:
        print(f"\n{'='*70}")
        print(f"[Collect Data] 执行行动: {action}")
        print(f"{'='*70}")
    
    from Routing.tool_cache import tool_cache
    
    if action == "read_logs":
        # 读取或扩大日志追溯范围
        log_tools = await tool_cache.get_tools("log-reader")
        read_tool = next((t for t in log_tools if t.name == "read_docker_logs"), None)
        
        if read_tool:
            # 确定本次读取的时间范围
            current_range = state.get('log_search_range_minutes', 0)
            
            # === 新增：检测是否为高CPU紧急问题 ===
            is_high_cpu_critical = "detect_high_cpu_critical" in state.get('actions_taken', [])
            
            if current_range == 0:
                # 首次读取
                if is_high_cpu_critical:
                    # 高CPU紧急问题，直接读取最近60分钟日志
                    new_range = 60
                    print(f"[Collect Data] [CRITICAL] 检测到高CPU问题，首次读取最近{new_range}分钟日志以深入诊断")
                else:
                    # 普通情况，从30分钟开始
                    new_range = 30
                    print(f"[Collect Data] 首次读取最近{new_range}分钟日志")
            elif current_range < 180:
                # 扩大追溯范围: 30 → 60 → 120 → 180
                if current_range == 30:
                    new_range = 60
                elif current_range == 60:
                    new_range = 120
                else:
                    new_range = 180
                print(f"[Collect Data] 扩大追溯范围至{new_range}分钟")
            else:
                # 已达到最大范围
                print(f"[Collect Data] 已达到最大追溯范围(180分钟)")
                return {
                    **state,
                    "iteration_count": state['iteration_count'] + 1
                }
            
            now = datetime.now()
            since = (now - timedelta(minutes=new_range)).strftime("%Y-%m-%dT%H:%M:%S")
            until = now.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[Collect Data] 读取时间范围: {since} 到 {until}")
            
            result = await read_tool.ainvoke({
                "container_name": state['container_name'],
                "since_time": since,
                "until_time": until,
                "lines": 500,  # 增加行数,获取更多日志
                "log_level": None  # 不过滤，获取所有日志
            })
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    log_data = json.loads(first_item['text'])
                else:
                    log_data = first_item
            else:
                log_data = result
            
            if log_data.get('status') == 'success':
                new_logs = log_data.get('logs', '')
                line_count = log_data.get('line_count', 0)
                print(f"[Collect Data] 读取到 {line_count} 行日志")
                
                # 打印完整日志内容
                if new_logs and line_count > 0:
                    print(f"[Collect Data] 后端日志内容 ({line_count}行):")
                    for line in new_logs.split('\n'):
                        print(f"  {line}")
                
                # === 新增：当日志为空时的处理策略 ===
                if line_count == 0:
                    print(f"[Collect Data] [WARN] 警告: 最近{new_range}分钟没有日志记录")
                    
                    # 检查是否有可疑容器
                    discovered = state.get('discovered_containers', [])
                    suspicious = [c for c in discovered if c.get('issue') == 'suspicious_container']
                    
                    if suspicious and new_range < 120:
                        # 如果有可疑容器，扩大时间范围继续尝试
                        print(f"[Collect Data] 发现可疑容器，扩大时间范围至 120 分钟重新读取")
                        return {
                            **state,
                            "log_search_range_minutes": 120,  # 直接跳到 120 分钟
                            "iteration_count": state['iteration_count'] + 1,
                            "next_action": "read_logs"  # 标记下次行动
                        }
                    elif not state.get('logs_collected_ranges'):
                        # 首次读取且无日志，尝试读取其他服务日志
                        print(f"[Collect Data] 后端无日志，尝试读取其他服务日志...")
                        services_to_read = []
                        for container in discovered:
                            if container.get('type') in ['frontend', 'redis', 'database']:
                                services_to_read.append(container)
                        
                        if services_to_read:
                            combined_logs = ""
                            existing_ranges = state.get('logs_collected_ranges', [])
                            
                            for svc_container in services_to_read:
                                svc_name = svc_container.get('name', '')
                                svc_type = svc_container.get('type', '')
                                svc_server = svc_container.get('server', '')  # 获取容器所在的服务器
                                print(f"[Collect Data] 读取 {svc_type} 服务日志 (容器: {svc_name}, 服务器: {svc_server})")
                                
                                try:
                                    # 构建调用参数
                                    invoke_params = {
                                        "container_name": svc_name,
                                        "since_time": since,
                                        "until_time": until,
                                        "lines": 200,
                                        "log_level": None
                                    }
                                    
                                    # 如果容器不在默认服务器上，指定ssh_host参数
                                    default_server = state.get('servers_config', {}).get('backend', {}).get('ssh_host', '')
                                    if svc_server and svc_server != default_server:
                                        invoke_params['ssh_host'] = svc_server
                                        print(f"[Collect Data] [INFO] 切换到服务器: {svc_server}")
                                    
                                    svc_result = await read_tool.ainvoke(invoke_params)
                                    
                                    # 解析结果
                                    if isinstance(svc_result, list) and len(svc_result) > 0:
                                        first_item = svc_result[0]
                                        if isinstance(first_item, dict) and 'text' in first_item:
                                            svc_log_data = json.loads(first_item['text'])
                                        else:
                                            svc_log_data = first_item
                                    else:
                                        svc_log_data = svc_result
                                    
                                    if svc_log_data.get('status') == 'success':
                                        svc_logs = svc_log_data.get('logs', '')
                                        svc_line_count = svc_log_data.get('line_count', 0)
                                        if svc_logs:
                                            combined_logs += f"\n\n--- {svc_type.upper()} 服务日志 ({svc_name}, 最近{new_range}分钟, {svc_line_count}行) ---\n{svc_logs}"
                                            print(f"[Collect Data] {svc_type} 服务日志: {svc_line_count} 行")
                                            # 打印完整日志内容
                                            print(f"[Collect Data] {svc_type} 日志内容 ({svc_line_count}行):")
                                            for line in svc_logs.split('\n'):
                                                print(f"  {line}")
                                except Exception as e:
                                    print(f"[Collect Data] 读取 {svc_type} 服务日志失败: {e}")
                            
                            if combined_logs:
                                existing_ranges.append({
                                    "range_minutes": new_range,
                                    "line_count": len(combined_logs.splitlines()),
                                    "timestamp": datetime.now().isoformat()
                                })
                                
                                return {
                                    **state,
                                    "logs_data": combined_logs,
                                    "log_search_range_minutes": new_range,
                                    "logs_collected_ranges": existing_ranges,
                                    "iteration_count": state['iteration_count'] + 1
                                }
                
                # 累积合并日志
                existing_ranges = state.get('logs_collected_ranges', [])
                existing_logs = state.get('logs_data', '')
                
                # 将新日志追加到现有日志
                if existing_logs:
                    combined_logs = existing_logs + "\n\n--- 扩大追溯范围至" + str(new_range) + "分钟 ---\n\n" + new_logs
                else:
                    combined_logs = new_logs
                
                # 记录已收集的范围
                existing_ranges.append({
                    "range_minutes": new_range,
                    "line_count": line_count,
                    "timestamp": datetime.now().isoformat()
                })
                
                print(f"[Collect Data] 累积日志总数: {len(combined_logs.splitlines())} 行")
                print(f"[Collect Data] 已收集范围: {[r['range_minutes'] for r in existing_ranges]}")
                
                # === 智能多服务日志收集 ===
                # === 新增：根据容器发现结果和日志内容智能决定读取哪些服务日志 ===
                services_to_check = []
                
                # 1. 检查后端日志中是否包含其他服务的错误关键词
                if any(kw in new_logs.lower() for kw in ['redis', '6379']):
                    services_to_check.append('redis')
                if any(kw in new_logs.lower() for kw in ['mysql', 'database', '3306']):
                    services_to_check.append('mysql')
                
                # 2. 检查是否有缺失的服务需要确认状态
                discovered = state.get('discovered_containers') or []
                missing_services = [c for c in discovered if c.get('issue') in ['no_containers', 'service_not_found']]
                for ms in missing_services:
                    service_type = ms.get('type', '')
                    if service_type and service_type not in services_to_check:
                        services_to_check.append(service_type)
                        print(f"[Collect Data] 检测到 {service_type} 服务缺失，需要确认状态")
                
                # 读取相关服务日志（最近10分钟）
                if services_to_check:
                    print(f"[Collect Data] 检测到后端日志中包含其他服务错误，开始读取相关服务日志...")
                    for service in services_to_check:
                        container_name = get_container_for_service(service, state)
                        if container_name:
                            print(f"[Collect Data] 读取 {service} 服务日志 (容器: {container_name})")
                            try:
                                # 读取该服务最近 10 分钟日志
                                service_since = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
                                service_result = await read_tool.ainvoke({
                                    "container_name": container_name,
                                    "since_time": service_since,
                                    "until_time": until,
                                    "lines": 200,
                                    "log_level": None
                                })
                                
                                # 解析结果
                                if isinstance(service_result, list) and len(service_result) > 0:
                                    first_item = service_result[0]
                                    if isinstance(first_item, dict) and 'text' in first_item:
                                        service_log_data = json.loads(first_item['text'])
                                    else:
                                        service_log_data = first_item
                                else:
                                    service_log_data = service_result
                                
                                if service_log_data.get('status') == 'success':
                                    service_logs = service_log_data.get('logs', '')
                                    service_line_count = service_log_data.get('line_count', 0)
                                    if service_logs:
                                        combined_logs += f"\n\n--- {service.upper()} 服务日志 (最近10分钟, {service_line_count}行) ---\n{service_logs}"
                                        print(f"[Collect Data] {service} 服务日志: {service_line_count} 行")
                                        # 打印完整日志内容
                                        print(f"[Collect Data] {service} 日志内容 ({service_line_count}行):")
                                        for line in service_logs.split('\n'):
                                            print(f"  {line}")
                            except Exception as e:
                                print(f"[Collect Data] 读取 {service} 服务日志失败: {e}")
                
                return {
                    **state,
                    "logs_data": combined_logs,
                    "log_search_range_minutes": new_range,
                    "logs_collected_ranges": existing_ranges,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "read_logs_recent":
        # 读取相关服务的最近10分钟日志用于交叉验证
        log_tools = await tool_cache.get_tools("log-reader")
        read_tool = next((t for t in log_tools if t.name == "read_docker_logs"), None)
        
        if read_tool:
            print(f"[Collect Data] 读取相关服务的最近10分钟日志进行交叉验证")
            
            # 确定需要读取的服务
            services_to_read = []
            discovered = state.get('discovered_containers', [])
            for container in discovered:
                name = container.get('name', '').lower()
                if 'redis' in name:
                    services_to_read.append({
                        'service_name': 'redis',
                        'container_name': container.get('container_name') or container.get('name'),
                        'server': container.get('server', '')
                    })
                elif 'mysql' in name:
                    services_to_read.append({
                        'service_name': 'mysql',
                        'container_name': container.get('container_name') or container.get('name'),
                        'server': container.get('server', '')
                    })
            
            now = datetime.now()
            since = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
            until = now.strftime("%Y-%m-%dT%H:%M:%S")
            
            combined_logs = state.get('logs_data', '')
            
            # 依次读取各服务日志
            for svc_info in services_to_read:
                service_name = svc_info['service_name']
                container_name = svc_info['container_name']
                svc_server = svc_info.get('server', '')
                print(f"[Collect Data] 读取 {service_name} 服务日志 (容器: {container_name}, 服务器: {svc_server})")
                try:
                    # 构建调用参数
                    invoke_params = {
                        "container_name": container_name,
                        "since_time": since,
                        "until_time": until,
                        "lines": 200,
                        "log_level": None
                    }
                    
                    # 如果容器不在默认服务器上，指定ssh_host参数
                    default_server = state.get('servers_config', {}).get('backend', {}).get('ssh_host', '')
                    if svc_server and svc_server != default_server:
                        invoke_params['ssh_host'] = svc_server
                        print(f"[Collect Data] [INFO] 切换到服务器: {svc_server}")
                    
                    result = await read_tool.ainvoke(invoke_params)
                    
                    # 解析结果
                    if isinstance(result, list) and len(result) > 0:
                        first_item = result[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            log_data = json.loads(first_item['text'])
                        else:
                            log_data = first_item
                    else:
                        log_data = result
                    
                    if log_data.get('status') == 'success':
                        service_logs = log_data.get('logs', '')
                        line_count = log_data.get('line_count', 0)
                        if service_logs:
                            combined_logs += f"\n\n--- {service_name.upper()} 服务日志 (最近10分钟, {line_count}行) ---\n{service_logs}"
                            print(f"[Collect Data] {service_name} 服务日志: {line_count} 行")
                            # 打印完整日志内容
                            print(f"[Collect Data] {service_name} 日志内容 ({line_count}行):")
                            for line in service_logs.split('\n'):
                                print(f"  {line}")
                except Exception as e:
                    print(f"[Collect Data] 读取 {service_name} 服务日志失败: {e}")
            
            return {
                **state,
                "logs_data": combined_logs,
                "iteration_count": state['iteration_count'] + 1
            }
    
    elif action == "check_memory":
        # 检查内存使用情况
        log_tools = await tool_cache.get_tools("log-reader")
        mem_tool = next((t for t in log_tools if t.name == "check_memory_usage"), None)
        
        if mem_tool:
            print(f"[Collect Data] 检查内存使用情况")
            
            result = await mem_tool.ainvoke({})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    mem_data = json.loads(first_item['text'])
                else:
                    mem_data = first_item
            else:
                mem_data = result
            
            if mem_data.get('status') == 'success':
                memory_info = mem_data.get('memory_info', '')
                print(f"[Collect Data] 内存信息:\n{memory_info}")
                
                return {
                    **state,
                    "memory_info": memory_info,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_cpu":
        # 检查CPU使用情况
        log_tools = await tool_cache.get_tools("log-reader")
        cpu_tool = next((t for t in log_tools if t.name == "check_cpu_usage"), None)
        
        if cpu_tool:
            print(f"[Collect Data] 检查CPU使用情况")
            
            result = await cpu_tool.ainvoke({})
            
            # 解析MCP返回格式
            if isinstance(result, list) and len(result) > 0:
                first_item = result[0]
                if isinstance(first_item, dict) and 'text' in first_item:
                    cpu_data = json.loads(first_item['text'])
                else:
                    cpu_data = first_item
            else:
                cpu_data = result
            
            if cpu_data.get('status') == 'success':
                cpu_info = cpu_data.get('cpu_info', '')
                print(f"[Collect Data] CPU使用情况:")
                print(f"{cpu_info}")
                
                return {
                    **state,
                    "cpu_info": cpu_info,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_service":
        # 检查服务状态
        log_tools = await tool_cache.get_tools("log-reader")
        status_tool = next((t for t in log_tools if t.name == "get_container_status"), None)
        
        if status_tool:
            print(f"[Collect Data] 检查服务状态")
            
            try:
                result = await status_tool.ainvoke({"container_name": state['container_name']})
                
                # 解析MCP返回格式
                if isinstance(result, list) and len(result) > 0:
                    first_item = result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        status_data = json.loads(first_item['text'])
                    else:
                        status_data = first_item
                else:
                    status_data = result
                
                if status_data.get('status') == 'success':
                    container_name = state['container_name']
                    service_status = f"运行中: {status_data.get('running')}, 详情: {status_data.get('status_detail')}"
                    print(f"[Collect Data] 服务状态 [{container_name}]:")
                    print(f"  {service_status}")
                    
                    return {
                        **state,
                        "service_status": service_status,
                        "iteration_count": state['iteration_count'] + 1
                    }
            except Exception as e:
                print(f"[Collect Data] 检查服务状态失败: {e}")
                # 即使失败也返回完整状态，防止丢失 discovered_containers
                return {
                    **state,
                    "service_status": f"检查失败: {str(e)}",
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "check_mysql":
        # 检查MySQL状态
        log_tools = await tool_cache.get_tools("log-reader")
        mysql_tool = next((t for t in log_tools if t.name == "check_mysql_status"), None)
        
        if mysql_tool:
            print(f"[Collect Data] 检查MySQL数据库状态")
            
            try:
                result = await mysql_tool.ainvoke({})
                
                # 解析MCP返回格式
                if isinstance(result, list) and len(result) > 0:
                    first_item = result[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        mysql_data = json.loads(first_item['text'])
                    else:
                        mysql_data = first_item
                else:
                    mysql_data = result
                
                if mysql_data.get('status') == 'success':
                    mysql_running = mysql_data.get('mysql_running', False)
                    process_info = mysql_data.get('process_info', '')
                    port_info = mysql_data.get('port_info', '')
                    docker_info = mysql_data.get('docker_info', '')
                    
                    print(f"[Collect Data] MySQL 数据库状态:")
                    print(f"  运行状态: {'[OK] 运行中' if mysql_running else '[FAIL] 未运行'}")
                    if process_info:
                        print(f"  进程信息: {process_info}")
                    if port_info:
                        print(f"  端口监听: {port_info}")
                    if docker_info:
                        print(f"  Docker 容器: {docker_info}")
                    
                    mysql_status = f"运行状态: {'运行中' if mysql_running else '未运行'}\n进程: {process_info}\n端口: {port_info}\nDocker: {docker_info}"
                    
                    return {
                        **state,
                        "mysql_status": mysql_status,
                        "iteration_count": state['iteration_count'] + 1
                    }
                else:
                    print(f"[Collect Data] MySQL检查失败: {mysql_data.get('message', 'Unknown error')}")
            except Exception as e:
                print(f"[Collect Data] MySQL检查出错: {str(e)}")
                import traceback
                traceback.print_exc()
                
                return {
                    **state,
                    "mysql_status": mysql_status,
                    "iteration_count": state['iteration_count'] + 1
                }
    
    elif action == "perform_health_check":
        # 执行健康检查
        print(f"[Collect Data] 执行服务健康检查")
        
        try:
            check_results = await perform_health_checks(state)
            
            # 更新健康检查执行计数器
            health_check_count = state.get('_health_check_execution_count', 0) + 1
            
            return {
                **state,
                "health_check_results": check_results['health_check_results'],
                "port_check_results": check_results['port_check_results'],
                "performance_metrics": check_results['performance_metrics'],
                "health_check_summary": check_results['summary'],
                "_health_check_execution_count": health_check_count,  # 记录执行次数
                "iteration_count": state['iteration_count'] + 1
            }
        except Exception as e:
            print(f"[Collect Data] 健康检查失败: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                **state,
                "health_check_summary": f"健康检查执行失败: {str(e)}",
                "iteration_count": state['iteration_count'] + 1
            }
    
    # 如果没有执行任何操作，仍然增加迭代计数
    return {
        **state,
        "iteration_count": state['iteration_count'] + 1
    }


async def generate_error_report_node(state: DiagnosisState) -> DiagnosisState:
    """生成配置不足的错误报告"""
    print(f"\n{'='*70}")
    print(f"[Error Report] 生成配置错误报告")
    print(f"{'='*70}")
    
    error_content = """## 错误:配置信息不足

请至少提供一个服务器的 SSH 配置信息(前端、后端、数据库或 Redis)。

### 配置说明:

请在 `.env` 文件中添加以下配置项(根据实际情况填写):

```bash
# 后端服务配置(推荐至少配置此项)
BACKEND_SSH_HOST=<你的服务器IP>
BACKEND_SSH_PORT=22
BACKEND_SSH_USER=<SSH用户名>
BACKEND_SSH_KEY_PATH=<SSH密钥文件路径>
BACKEND_CONTAINER_NAME=<后端容器名称>

# 前端服务配置(可选,系统会自动发现)
FRONTEND_SSH_HOST=<前端服务器IP>
FRONTEND_SSH_PORT=22
FRONTEND_SSH_USER=<SSH用户名>
FRONTEND_SSH_KEY_PATH=<SSH密钥文件路径>
FRONTEND_CONTAINER_NAME=<前端容器名称>

# 数据库配置(可选)
DATABASE_HOST=<数据库主机地址>
DATABASE_PORT=3306
DATABASE_USER=<数据库用户名>
DATABASE_PASSWORD=<数据库密码>

# Redis 配置(可选)
REDIS_HOST=<Redis主机地址>
REDIS_PORT=6379
REDIS_PASSWORD=<Redis密码>
```

### 说明:
- 至少配置一个服务器的 SSH 信息即可, 并保证前后端、数据库和 Redis 的配置正确, 以便系统自动发现
- 系统会通过 Docker 自动发现其他相关服务
- 确保 SSH 密钥文件路径正确且有读取权限
- 请参考当前 `.env` 文件中已有的配置格式
"""
    
    return {
        **state,
        "diagnosis_result": {
            "content": error_content,
            "confidence": "low",
            "error_type": "missing_config"
        },
        "current_step": "complete"
    }


async def generate_report_node(state: DiagnosisState) -> DiagnosisState:
    """
    节点4：基于收集的所有数据生成诊断报告
    """
    print(f"\n{'='*70}")
    print(f"[Generate Report] 生成最终诊断报告")
    print(f"{'='*70}")
    
    # === 调试：打印状态信息 ===
    print(f"[Generate Report] state keys: {list(state.keys())}")
    print(f"[Generate Report] discovered_containers type: {type(state.get('discovered_containers'))}")
    print(f"[Generate Report] discovered_containers value: {state.get('discovered_containers')}")
    
    # === 新增：构建检测到的异常情况列表（必须在快速报告检查之前）===
    discovered = state.get('discovered_containers') or []
    detected_anomalies = "\n\n【检测到的异常情况】\n"
    
    # 1. 检测高CPU容器
    docker_stats_info_for_check = state.get('docker_stats_info', '')
    high_cpu_list = []
    if docker_stats_info_for_check:
        for line in docker_stats_info_for_check.split('\n'):
            if '%' in line:
                try:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if '%' in part and i > 0:
                            cpu_value = float(part.replace('%', '').strip())
                            if cpu_value > 100:
                                container_name = parts[i-1]
                                high_cpu_list.append(f"{container_name} ({cpu_value}%)")
                            break
                except:
                    pass
    
    if high_cpu_list:
        detected_anomalies += f"- **高CPU容器**: {', '.join(high_cpu_list)} ⚠️ 紧急问题\n"
    else:
        detected_anomalies += "- **高CPU容器**: 无\n"
    
    # 2. 检测缺失服务
    missing_services = [c['name'] for c in discovered if c.get('issue') in ['no_containers', 'service_not_found']]
    if missing_services:
        detected_anomalies += f"- **缺失服务**: {', '.join(missing_services)} ❌\n"
    else:
        detected_anomalies += "- **缺失服务**: 无\n"
    
    # 3. 检测可疑容器
    suspicious = [c['name'] for c in discovered if c.get('issue') == 'suspicious_container']
    if suspicious:
        detected_anomalies += f"- **可疑容器**: {', '.join(suspicious)} ⚠️\n"
    else:
        detected_anomalies += "- **可疑容器**: 无\n"
    
    # 4. MySQL状态
    mysql_ok = state.get('mysql_status') and ('运行中' in state.get('mysql_status', '') or '[OK]' in state.get('mysql_status', ''))
    detected_anomalies += f"- **MySQL状态**: {'✓ 正常' if mysql_ok else '✗ 未检查'}\n"
    
    # === 新增：获取 docker stats 信息（必须在快速报告检查之前）===
    docker_stats_info = state.get('docker_stats_info', '')
    
    # === 临时禁用：服务未启动的快速报告（所有问题走完整诊断流程）===
    # service_status_summary = state.get('service_status_summary', '')
    # if service_status_summary:
    #     print("[Generate Report] 生成服务未启动的快速报告")
    #     
    #     # === 修复：在快速报告中也包含所有检测到的异常 ===
    #     prompt = f"""你是运维诊断专家。检测到以下服务未启动：

# {service_status_summary}

# {detected_anomalies}

# {docker_stats_info}

# 请基于以上信息生成诊断报告：
# 1. **明确指出所有检测到的问题**（包括服务缺失、高CPU、可疑容器等）
# 2. 分析可能的原因（基于日志证据）
# 3. 给出恢复步骤

# 【重要要求】
# - 必须在"问题根因"中列出**所有**检测到的问题，不要遗漏任何一个
# - 如果检测到高CPU（>100%），必须在报告中明确指出并标记为紧急问题
# - 如果有多个问题，按严重程度排序：高CPU > 服务缺失 > 可疑容器

# 【输出格式要求】
# ```markdown
# ## 问题根因
# （精炼描述所有问题的原因，引用日志证据）
# - 问题1: ...
# - 问题2: ...
# ...

# ## 立即执行
# 1. `命令1` - 作用说明
# 2. `命令2` - 作用说明
# ...

# ## 长期优化
# 1. 建议1
# 2. 建议2
# ...
# ```

# **注意：只输出上述格式的内容，不要有任何其他文字！**
# """
    #     response = await llm.ainvoke(prompt)
    #     
    #     stopped_services = get_stopped_services(state)
    #     
    #     return {
    #         **state,
    #         "diagnosis_result": {
    #             "content": response.content,
    #             "confidence": "high",
    #             "data_sources": {
    #                 "service_status": True,
    #                 "logs": bool(state.get('logs_data'))
    #             },
    #             "stopped_services": stopped_services
    #         },
    #         "current_step": "complete"
    #     }
    
    # === 原有逻辑:正常诊断流程的报告生成 ===
    alert = state.get('alert_event', {})
    
    # 构建简洁的数据摘要
    memory_available = 'N/A'
    if state.get('memory_info'):
        try:
            # free -h 输出格式: total used free shared buff/cache available
            mem_line = state['memory_info'].splitlines()[1].split()
            memory_available = mem_line[6] if len(mem_line) > 6 else 'N/A'
        except:
            memory_available = 'N/A'
    
    # 日志追溯信息
    log_ranges = state.get('logs_collected_ranges', [])
    log_trace_info = ""
    logs_content = ""
    if log_ranges:
        ranges_str = ", ".join([f"{r['range_minutes']}min({r['line_count']}行)" for r in log_ranges])
        total_lines = sum(r['line_count'] for r in log_ranges)
        log_trace_info = f"\n日志追溯: 共{len(log_ranges)}次读取, 范围[{ranges_str}], 总计{total_lines}行"
        
        # 添加日志内容给LLM分析
        logs_data = state.get('logs_data') or ''  # 防止 None 值
        if logs_data:
            log_lines = logs_data.splitlines()
            if len(log_lines) <= 500:
                # 日志较少,直接包含全部内容
                logs_content = f"\n\n【日志内容】(共{len(log_lines)}行):\n{logs_data}"
            else:
                # 日志较多,提取关键错误和警告行
                error_keywords = ['error', 'exception', 'fatal', 'outofmemory', 'heap space', 
                                 'gc overhead', 'timeout', 'critical', 'warn', 'failed']
                key_lines = []
                for line in log_lines:
                    if any(keyword in line.lower() for keyword in error_keywords):
                        key_lines.append(line)
                
                # 如果找到关键行,取最多200行;否则取最后200行
                if key_lines:
                    selected_lines = key_lines[:200]
                    logs_content = f"\n\n【日志中的关键错误/警告】(共{len(key_lines)}条异常,显示前200条):\n" + "\n".join(selected_lines)
                else:
                    selected_lines = log_lines[-200:]
                    logs_content = f"\n\n【日志最后200行】:\n" + "\n".join(selected_lines)
    
    data_summary = f"""告警信息：
- 名称：{alert.get('alert_name', 'N/A')}
- 类型：{alert.get('alert_type', 'N/A')}
- 时间：{alert.get('alert_time', 'N/A')}
- 描述：{alert.get('description', 'N/A')}

容器：{state['container_name']}

关键指标：
- 内存可用：{memory_available}
- CPU状态：{'正常' if state.get('cpu_info') else '未收集'}
- MySQL状态：{'运行中' if state.get('mysql_status') and ('运行中' in state.get('mysql_status', '') or '[OK]' in state.get('mysql_status', '')) else '未检查或异常'}
- 服务状态：{state.get('service_status', '未收集')}{log_trace_info}{logs_content}
"""
    
    # === 新增：从合并的日志中提取各服务日志 ===
    logs_data = state.get('logs_data', '')
    backend_logs = extract_service_logs(logs_data, 'backend')
    redis_logs = extract_service_logs(logs_data, 'redis')
    mysql_logs = extract_service_logs(logs_data, 'mysql')
    frontend_logs = extract_service_logs(logs_data, 'frontend')
    
    # === 新增：日志统计分析（帮助LLM更好地理解日志）===
    def analyze_log_patterns(logs: str, service_name: str) -> str:
        """分析日志模式，提供统计信息"""
        if not logs:
            return f"- {service_name}: 无日志\n"
        
        lines = logs.splitlines()
        total_lines = len(lines)
        
        # 统计HTTP状态码
        status_codes = {}
        error_count = 0
        warn_count = 0
        timeout_count = 0
        connection_refused = 0
        upstream_error = 0
        
        # 提取客户端IP和请求路径
        client_ips = {}
        request_paths = {}
        
        for line in lines:
            # 提取HTTP状态码
            import re
            status_match = re.search(r'" (\d{3}) ', line)
            if status_match:
                code = status_match.group(1)
                status_codes[code] = status_codes.get(code, 0) + 1
            
            # 提取客户端IP（Nginx日志格式）
            ip_match = re.match(r'(\d+\.\d+\.\d+\.\d+)', line)
            if ip_match:
                ip = ip_match.group(1)
                client_ips[ip] = client_ips.get(ip, 0) + 1
            
            # 提取请求路径
            path_match = re.search(r'"(GET|POST|PUT|DELETE|PATCH) ([^ ]+)', line)
            if path_match:
                path = path_match.group(2)
                request_paths[path] = request_paths.get(path, 0) + 1
            
            # 统计错误类型
            line_lower = line.lower()
            if 'error' in line_lower or 'exception' in line_lower:
                error_count += 1
            if 'warn' in line_lower:
                warn_count += 1
            if 'timeout' in line_lower or 'timed out' in line_lower:
                timeout_count += 1
            if 'connection refused' in line_lower:
                connection_refused += 1
            if 'upstream' in line_lower and ('error' in line_lower or 'timed out' in line_lower):
                upstream_error += 1
        
        # 构建统计信息
        stats = f"- {service_name}: {total_lines}行日志\n"
        if status_codes:
            stats += f"  HTTP状态码分布: {', '.join([f'{code}({count}次)' for code, count in sorted(status_codes.items())])}\n"
        if client_ips:
            top_ips = sorted(client_ips.items(), key=lambda x: x[1], reverse=True)[:5]
            stats += f"  主要客户端IP: {', '.join([f'{ip}({count}次)' for ip, count in top_ips])}\n"
        if request_paths:
            top_paths = sorted(request_paths.items(), key=lambda x: x[1], reverse=True)[:5]
            stats += f"  高频请求路径: {', '.join([f'{path}({count}次)' for path, count in top_paths])}\n"
        if error_count > 0:
            stats += f"  错误/异常: {error_count}条\n"
        if warn_count > 0:
            stats += f"  警告: {warn_count}条\n"
        if timeout_count > 0:
            stats += f"  超时: {timeout_count}条\n"
        if connection_refused > 0:
            stats += f"  连接拒绝: {connection_refused}条\n"
        if upstream_error > 0:
            stats += f"  上游服务错误: {upstream_error}条\n"
        
        return stats
    
    log_statistics = "\n【日志统计分析】\n"
    log_statistics += analyze_log_patterns(frontend_logs, '前端')
    log_statistics += analyze_log_patterns(backend_logs, '后端')
    log_statistics += analyze_log_patterns(redis_logs, 'Redis')
    log_statistics += analyze_log_patterns(mysql_logs, 'MySQL')
    
    # === 新增：整合健康检查结果到当前状态验证 ===
    health_summary = state.get('health_check_summary', '')
    health_results = state.get('health_check_results', {})
    port_results = state.get('port_check_results', {})
    perf_metrics = state.get('performance_metrics', {})
    
    if health_summary:
        # 如果有健康检查结果，将其添加到当前状态报告中
        current_status_report = health_summary
        
        # 添加详细的性能指标
        if perf_metrics:
            current_status_report += "\n\n【性能指标详情】\n"
            for service_name, metrics in perf_metrics.items():
                if not metrics.get('error'):
                    current_status_report += f"- {service_name}: CPU={metrics['cpu_percent']}%, 内存={metrics['memory_percent']}% ({metrics['memory_usage_mb']:.1f}MB/{metrics['memory_limit_mb']:.1f}MB)\n"
                else:
                    current_status_report += f"- {service_name}: ❌ 无法获取性能指标 ({metrics['error']})\n"
    else:
        # 如果没有健康检查结果，使用原有的日志分析方式
        # === 新增：当前状态验证（检查问题是否仍然存在）===
        def check_current_status(logs: str, service_name: str) -> dict:
            """
            检查当前服务状态（基于最近5分钟的日志）
            返回：是否有活跃问题、问题类型、证据
            """
            if not logs:
                return {
                    'has_active_issue': False,
                    'issue_type': None,
                    'evidence': '无日志数据'
                }
            
            lines = logs.splitlines()
            if not lines:
                return {
                    'has_active_issue': False,
                    'issue_type': None,
                    'evidence': '日志为空'
                }
            
            # 提取时间戳（假设格式为 [19/May/2026:12:40:01 +0800] 或 2026-05-19 12:40:01）
            import re
            from datetime import datetime, timedelta
            
            current_time = datetime.now()
            five_minutes_ago = current_time - timedelta(minutes=5)
            
            recent_lines = []
            error_in_recent = []
            timeout_in_recent = []
            
            for line in lines:
                # 尝试提取时间戳
                time_match = re.search(r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})', line)
                if not time_match:
                    time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                
                if time_match:
                    try:
                        # 解析时间
                        time_str = time_match.group(1)
                        if '/' in time_str:
                            log_time = datetime.strptime(time_str, '%d/%b/%Y:%H:%M:%S')
                        else:
                            log_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                        
                        # 检查是否在最近5分钟内
                        # 注意：这里简化处理，实际应该考虑时区
                        recent_lines.append(line)
                        
                        line_lower = line.lower()
                        if 'error' in line_lower or 'exception' in line_lower:
                            error_in_recent.append(line)
                        if 'timeout' in line_lower or 'timed out' in line_lower:
                            timeout_in_recent.append(line)
                    except:
                        # 时间解析失败，仍然计入
                        recent_lines.append(line)
                else:
                    # 没有时间戳的行，也计入
                    recent_lines.append(line)
            
            # 判断是否有活跃问题
            has_active_issue = len(error_in_recent) > 0 or len(timeout_in_recent) > 0
            
            if has_active_issue:
                issue_types = []
                evidence = []
                
                if timeout_in_recent:
                    issue_types.append('超时错误')
                    evidence.extend(timeout_in_recent[:3])  # 最多取3条证据
                
                if error_in_recent:
                    issue_types.append('异常错误')
                    evidence.extend([e for e in error_in_recent[:3] if e not in timeout_in_recent])
                
                return {
                    'has_active_issue': True,
                    'issue_type': ', '.join(issue_types),
                    'evidence': '\n'.join(evidence[:5])  # 最多5条证据
                }
            else:
                return {
                    'has_active_issue': False,
                    'issue_type': None,
                    'evidence': f'最近日志中未发现活跃问题（共{len(recent_lines)}行）'
                }
        
        # 执行当前状态验证
        frontend_status = check_current_status(frontend_logs, '前端')
        backend_status = check_current_status(backend_logs, '后端')
        redis_status = check_current_status(redis_logs, 'Redis')
        mysql_status = check_current_status(mysql_logs, 'MySQL')
        
        # 构建当前状态报告
        current_status_report = "\n\n【当前状态验证（最近5分钟）】\n"
        current_status_report += f"- 前端服务: {'❌ 存在活跃问题 (' + frontend_status['issue_type'] + ')' if frontend_status['has_active_issue'] else '✅ 正常运行'}\n"
        if frontend_status['has_active_issue']:
            current_status_report += f"  证据: {frontend_status['evidence'][:200]}...\n" if len(frontend_status['evidence']) > 200 else f"  证据: {frontend_status['evidence']}\n"
        
        current_status_report += f"- 后端服务: {'❌ 存在活跃问题 (' + backend_status['issue_type'] + ')' if backend_status['has_active_issue'] else '✅ 正常运行'}\n"
        if backend_status['has_active_issue']:
            current_status_report += f"  证据: {backend_status['evidence'][:200]}...\n" if len(backend_status['evidence']) > 200 else f"  证据: {backend_status['evidence']}\n"
        
        current_status_report += f"- Redis服务: {'❌ 存在活跃问题 (' + redis_status['issue_type'] + ')' if redis_status['has_active_issue'] else '✅ 正常运行'}\n"
        current_status_report += f"- MySQL服务: {'❌ 存在活跃问题 (' + mysql_status['issue_type'] + ')' if mysql_status['has_active_issue'] else '✅ 正常运行'}\n"
        
        # 总体状态
        any_active_issue = any([
            frontend_status['has_active_issue'],
            backend_status['has_active_issue'],
            redis_status['has_active_issue'],
            mysql_status['has_active_issue']
        ])
        
        current_status_report += f"\n**总体状态**: {'⚠️ 发现活跃问题，需要立即处理' if any_active_issue else '✅ 所有服务当前运行正常'}\n"
    
    # === 新增：检查可疑容器和日志空值情况 ===
    discovered = state.get('discovered_containers') or []  # 防止 None 值
    suspicious_containers = [c for c in discovered if c.get('issue') == 'suspicious_container']
    log_line_count = len(logs_data.splitlines()) if logs_data else 0
    
    # === 新增：构建容器状态表格 ===
    container_status_table = "\n\n【容器发现状态】\n"
    container_status_table += "| 容器名称 | 类型 | 端口 | 状态 |\n"
    container_status_table += "|---------|------|------|------|\n"
    try:
        for c in discovered:
            name = c.get('name', 'N/A')
            ctype = c.get('type', 'unknown')
            ports = c.get('ports', 'N/A') or 'N/A'
            status = c.get('status', 'running')
            has_issue = '[ABNORMAL]' if c.get('issue') else '[OK]'
            container_status_table += f"| {name} | {ctype} | {ports} | {has_issue} |\n"
    except Exception as e:
        print(f"[Generate Report] [WARN] 构建容器状态表格失败: {e}")
        import traceback
        traceback.print_exc()
    
    # === 新增：日志收集状态 ===
    log_collection_status = "\n\n【日志收集状态】\n"
    log_collection_status += f"- 后端日志: {len(backend_logs.splitlines()) if backend_logs else 0} 行\n"
    log_collection_status += f"- 前端日志: {len(frontend_logs.splitlines()) if frontend_logs else 0} 行\n"
    log_collection_status += f"- Redis日志: {len(redis_logs.splitlines()) if redis_logs else 0} 行\n"
    log_collection_status += f"- MySQL日志: {len(mysql_logs.splitlines()) if mysql_logs else 0} 行\n"
    
    # 重要提示：如果成功读取到某服务的日志，说明该服务容器一定存在且可访问
    running_services_evidence = "\n[OK] **关键证据 - 运行中的服务**:\n"
    evidence_count = 0
    if frontend_logs:
        running_services_evidence += f"- ruoyi-frontend: 成功读取 {len(frontend_logs.splitlines())} 行日志 → **容器正在运行且可访问**\n"
        evidence_count += 1
    if redis_logs:
        running_services_evidence += f"- redis: 成功读取 {len(redis_logs.splitlines())} 行日志 → **容器正在运行**\n"
        evidence_count += 1
    if mysql_logs:
        running_services_evidence += f"- mysql: 成功读取 {len(mysql_logs.splitlines())} 行日志 → **容器正在运行**\n"
        evidence_count += 1
    if backend_logs:
        running_services_evidence += f"- ruoyi-app: 成功读取 {len(backend_logs.splitlines())} 行日志 → **容器正在运行**\n"
        evidence_count += 1
    
    if evidence_count > 0:
        log_collection_status += running_services_evidence
        log_collection_status += "\n[IMPORTANT] 上述服务已通过日志读取验证为正常运行状态，诊断时应排除这些服务的'容器不存在'问题\n"
    
    container_status_info = ""
    
    # === 新增：处理缺失的服务容器 ===
    missing_containers = [c for c in discovered if c.get('issue') in ['no_containers', 'service_not_found']]
    if missing_containers:
        container_status_info += "\n\n【缺失的服务】\n"
        for c in missing_containers:
            container_status_info += f"- {c['name']} ({c.get('type', 'unknown')}): {c.get('diagnosis_details', '')}\n"
            if c.get('suggestions'):
                container_status_info += "  建议操作:\n"
                for sug in c['suggestions']:
                    container_status_info += f"    * `{sug}`\n"
    
    # 处理可疑容器
    suspicious_containers = [c for c in discovered if c.get('issue') == 'suspicious_container']
    if suspicious_containers:
        container_status_info += "\n\n【可疑容器状态】\n"
        for c in suspicious_containers:
            container_status_info += f"- {c['name']} ({c.get('type', 'unknown')}): {c.get('diagnosis_details', '')}\n"
            if c.get('suggestions'):
                container_status_info += "  建议操作:\n"
                for sug in c['suggestions']:
                    container_status_info += f"    * `{sug}`\n"
    
    log_empty_warning = ""
    if log_line_count == 0:
        log_empty_warning = "\n\n[WARN] **重要提示**: 所有服务的日志均为空，这可能表明：\n"
        log_empty_warning += "1. 服务正常运行但没有产生错误日志\n"
        log_empty_warning += "2. 日志级别设置过高，错误未被记录\n"
        log_empty_warning += "3. 服务可能已停止或无法访问\n"
        log_empty_warning += "4. 需要检查容器状态和日志配置"
    
    # === 新增：构建服务状态明确摘要（避免LLM误判）===
    service_health_summary = "\n\n【服务健康状态摘要】\n"
    service_health_summary += f"- MySQL: {'✓ 正常运行' if state.get('mysql_status') and ('运行中' in state.get('mysql_status', '') or '[OK]' in state.get('mysql_status', '')) else '✗ 未检查或异常'}\n"
    
    # === 新增：构建详细的服务状态信息 ===
    discovered = state.get('discovered_containers') or []
    service_status_detail = "\n\n【各服务运行状态】\n"
    
    # === 注意：docker_stats_info 已经在前面从 state 中获取了 ===
    
    # 按服务类型分组
    services_by_type = {}
    for container in discovered:
        ctype = container.get('type', 'unknown')
        if ctype not in services_by_type:
            services_by_type[ctype] = []
        services_by_type[ctype].append(container)
    
    # 前端服务
    if 'frontend' in services_by_type:
        frontend_containers = services_by_type['frontend']
        status_list = [f"{c['name']} ({c.get('status', 'unknown')})" for c in frontend_containers]
        service_status_detail += f"- 前端: {', '.join(status_list)}\n"
    else:
        service_status_detail += "- 前端: 未发现容器\n"
    
    # 后端服务
    if 'backend' in services_by_type:
        backend_containers = services_by_type['backend']
        status_list = [f"{c['name']} ({c.get('status', 'unknown')})" for c in backend_containers]
        service_status_detail += f"- 后端: {', '.join(status_list)}\n"
    else:
        service_status_detail += "- 后端: 未发现容器\n"
    
    # 数据库服务（显示具体数据库类型）
    if 'database' in services_by_type:
        db_containers = services_by_type['database']
        db_info_list = []
        for c in db_containers:
            name = c['name'].lower()
            # 识别数据库类型
            if 'mysql' in name or 'mariadb' in name:
                db_type = 'MySQL'
            elif 'postgres' in name or 'pgsql' in name:
                db_type = 'PostgreSQL'
            elif 'mongo' in name:
                db_type = 'MongoDB'
            else:
                db_type = 'Database'
            db_info_list.append(f"[{db_type}] {c['name']} ({c.get('status', 'unknown')})")
        service_status_detail += f"- 数据库: {', '.join(db_info_list)}\n"
    else:
        service_status_detail += "- 数据库: 未发现容器\n"
    
    # Redis/缓存服务
    if 'redis' in services_by_type:
        redis_containers = services_by_type['redis']
        redis_info_list = []
        for c in redis_containers:
            name = c['name'].lower()
            # 识别缓存类型
            if 'redis' in name:
                cache_type = 'Redis'
            elif 'memcached' in name:
                cache_type = 'Memcached'
            else:
                cache_type = 'Cache'
            redis_info_list.append(f"[{cache_type}] {c['name']} ({c.get('status', 'unknown')})")
        service_status_detail += f"- 缓存: {', '.join(redis_info_list)}\n"
    else:
        service_status_detail += "- 缓存: 未发现容器\n"
    
    prompt = f"""你是运维诊断专家。请基于以下实时数据分析问题根因并给出解决方案。

{data_summary}

{service_health_summary}

{container_status_table}

{log_collection_status}

{log_statistics}

{current_status_report}

{service_status_detail}

{docker_stats_info}

【检测到的异常情况】
{detected_anomalies}

【多服务日志摘要】
- 后端日志行数: {len(backend_logs.splitlines()) if backend_logs else 0}
- 前端日志行数: {len(frontend_logs.splitlines()) if frontend_logs else 0}
- Redis日志行数: {len(redis_logs.splitlines()) if redis_logs else 0}
- MySQL日志行数: {len(mysql_logs.splitlines()) if mysql_logs else 0}{log_statistics}{container_status_info}{log_empty_warning}

【应用启动状态分析】
- 后端容器状态: {next((c.get('status', 'unknown') for c in discovered if c.get('type') == 'backend'), '未找到')}
- 是否包含启动成功标志: {'是' if backend_logs and ('启动成功' in backend_logs or 'Started' in backend_logs or '若依启动成功' in backend_logs) else '否'}
- 是否有正常业务日志: {'是' if backend_logs and ('登录成功' in backend_logs or 'Success' in backend_logs or 'exec-' in backend_logs) else '否'}

**重要提示**：
- 如果"是否包含启动成功标志"为"是"，且"是否有正常业务日志"为"是"，说明应用已经成功启动并正常运行
- 在这种情况下，即使日志中有历史错误（如启动时的 "Too many connections"），也应该标记为"已恢复的历史问题"，而不是"当前活跃问题"

**健康检查数据使用说明**：
- 【健康检查摘要】提供了所有服务的实时健康状态（HTTP响应、端口连通性）
- 【性能指标详情】提供了各服务的CPU和内存使用情况
- **如果健康检查发现某个服务HTTP异常或超时，这通常是当前活跃问题的强证据**
- **判断问题类型的关键**：
  - 如果健康检查显示服务异常（timeout/error/unreachable）→ 很可能是"当前活跃问题"
  - 如果健康检查显示服务正常，但历史日志有错误 → 可能是"已恢复的历史问题"
  - 结合日志时间戳：最近5分钟内的错误 + 健康检查异常 = 当前活跃问题

【交叉验证指南】
请对每个潜在问题进行多维度验证（至少2个证据源一致才确认为当前问题）：

**重要：日志深度分析要求**
在分析日志时，必须执行以下步骤：
1. **时间线分析**: 按时间顺序梳理事件，识别问题发生的时间点
2. **模式识别**: 找出异常模式（如：特定IP的请求失败、特定时间段集中出错）
3. **对比分析**: 对比成功请求和失败请求的差异（客户端IP、请求路径、时间等）
4. **根因推断**: 基于以上分析，推断可能的根本原因
5. **交叉验证**: 结合其他服务的日志确认推断
6. **统计分析利用**: 充分利用上面提供的【日志统计分析】数据，特别关注：
   - HTTP状态码分布中是否有大量5xx错误
   - 主要客户端IP是否与错误请求的IP一致
   - 高频请求路径是否是出问题的接口
   - 超时/上游错误的数量是否显著

**示例分析流程**:
```
前端日志分析:
- 12:15:08 - 正常访问 (200) ← 来自扫描器
- 12:39:45 - 正常访问 (304) ← 来自 220.154.1.3
- 12:40:01 - ❌ 超时 (504) ← 来自 220.154.1.3, 请求 /prod-api/getInfo
- 12:40:11 - ❌ 超时 (504) ← 来自 220.154.1.3, 请求 /prod-api/logout

发现:
- 只有 220.154.1.3 的 /prod-api/* 请求超时
- 其他IP的请求都成功
- 2个超时发生在10秒内

推断:
- 可能是后端服务在 12:40 左右处理 /prod-api 请求时出现问题
- 需要检查后端日志中 12:39-12:41 期间的记录

交叉验证:
- 查看后端日志中 12:40 左右的记录
- 检查MySQL/Redis在该时间段是否有异常
- 确认是否为网络问题还是应用逻辑问题
```

1. **前端服务问题验证**:
   - 证据1: 容器发现状态 → {('ruoyi-frontend' in container_status_table and '✓ 正常' in container_status_table) if 'ruoyi-frontend' in container_status_table else '未找到'}
   - 证据2: 前端日志是否成功读取 → {'是，{len(frontend_logs.splitlines())}行' if frontend_logs else '否'}
   - 证据3: 前端端口是否正常映射 → {any(c.get('ports') and '80' in c.get('ports', '') for c in discovered if c.get('type') == 'frontend')}
   - 判定: 如果容器存在且日志可读取 → 前端服务正常运行；如果容器不存在或无法读取日志 → 确认为问题

2. **MySQL 问题验证**:
   - 证据1: check_mysql 状态 → {'✓ 正常运行' if state.get('mysql_status') and ('运行中' in state.get('mysql_status', '') or '[OK]' in state.get('mysql_status', '')) else '✗ 未检查或异常'}
   - 证据2: MySQL 日志 → {'有错误' if mysql_logs and any(kw in mysql_logs.lower() for kw in ['error', 'failed']) else '无明显错误'}
   - 证据3: 后端日志中的 MySQL 错误 → {'有连接错误' if backend_logs and 'mysql' in backend_logs.lower() else '无'}
   - 判定: 如果 2/3 证据显示异常 → 确认为当前问题；如果只有后端日志有历史错误但 MySQL 状态正常 → 标记为“已恢复的历史问题”

3. **Redis 问题验证**:
   - 证据1: Discover Container 状态 → {get_redis_container_status(state)}
   - 证据2: Redis 日志 → {'有错误' if redis_logs and any(kw in redis_logs.lower() for kw in ['error', 'failed']) else '无明显错误'}
   - 证据3: 后端日志中的 Redis 错误 → {'有连接错误' if backend_logs and 'redis' in backend_logs.lower() else '无'}
   - 判定: 同上

4. **内存/CPU 问题验证**:
   - 证据1: check_memory/check_cpu 状态
   - 证据2: 应用日志中的 OOM/性能错误
   - 证据3: docker stats 显示的 CPU/内存使用率
   - 证据4: 【性能指标详情】中的实时指标
   - 判定: 如果 docker stats 显示 CPU > 100%，必须检查应用日志中是否有相关错误（如线程阻塞、死循环、频繁GC等）
   - **重要**: 在报告中描述高CPU问题时，必须引用日志证据，例如：“通过查询容器 ruoyi-app 的日志发现 XXX 错误，导致 CPU 使用率达到 180%”

5. **健康检查数据验证（新增）**:
   - 证据1: 【健康检查摘要】中的HTTP状态和端口连通性
   - 证据2: 【性能指标详情】中的CPU和内存使用率
   - 证据3: 历史日志中的错误信息
   - **判定规则**:
     - 如果健康检查显示 HTTP timeout/error → 确认为“当前活跃问题”，必须在报告中明确指出
     - 如果健康检查显示所有服务正常，但历史日志有错误 → 标记为“已恢复的历史问题”
     - 如果某个服务的性能指标异常（CPU>90%或MEM>90%），结合日志确认是否为当前问题

【时间维度判断】
- **优先关注最近10分钟内的日志**：这些反映当前问题
- **10-30分钟的日志**：可能是问题的起因或早期迹象
- **30分钟以上的日志**：很可能是已解决的历史问题

**关键判断规则**：
1. 如果错误发生在应用启动阶段，但应用最终启动成功 → 标记为“已恢复的历史问题”
2. 如果服务当前状态正常（容器运行中、端口可访问）→ 即使有历史错误，也标记为“已恢复”
3. 如果最近10分钟内没有相同错误，且服务正常运行 → 标记为“已恢复的历史问题”
4. **只有当错误持续出现且健康检查显示服务异常时，才标记为“当前活跃问题”**
5. **健康检查是判断当前状态的权威依据**：
   - HTTP timeout/error → 当前活跃问题
   - 端口不可达 → 当前活跃问题
   - HTTP healthy + 历史日志错误 → 已恢复的历史问题

**示例**：
- 场景1: 启动时出现 "Too many connections"，但应用最终启动成功且有正常业务日志 → 已恢复的历史问题
- 场景2: 最近10分钟内持续出现 "Too many connections"，且应用无法响应 → 当前活跃问题
- 场景3: MySQL 容器状态为 healthy，后端日志中有历史连接错误但最近无错误 → 已恢复的历史问题
- **场景4（新增）**: 健康检查显示 ruoyi-app HTTP timeout，前端日志有504错误 → **当前活跃问题**，根因是后端服务超时
- **场景5（新增）**: 健康检查显示所有服务HTTP healthy，但历史日志有timeout错误 → **已恢复的历史问题**，服务已自动恢复

【重要要求】
1. 严格基于上述真实数据，不要编造信息
2. **综合分析所有收集的日志**,检查是否存在异常模式:
   - 错误信息(Exception, Error, Fatal, OutOfMemoryError等)
   - 警告信息(Warning, Timeout, Slow query等)
   - 异常重启或服务崩溃迹象
   - 性能退化(响应时间增加、资源使用率飙升等)
   - 任何与正常行为不符的模式
3. **结合内存、CPU、服务状态等资源指标进行综合判断**
4. 如果发现任何问题,必须在"问题根因"中明确指出
5. **引用日志证据**: 在描述每个问题时，必须引用具体的日志证据，例如：
   - "通过查询容器 ruoyi-app 的日志发现 XXX 错误，导致 CPU 使用率达到 180%"
   - "从后端日志中发现 MySQL 连接超时错误（最近10分钟内出现3次）"
   - "前端日志显示服务启动失败，错误信息: XXX"
   - "前端日志统计分析显示，主要客户端IP为 220.154.1.3，该IP的请求全部返回504错误"
   - "高频请求路径 /prod-api/* 出现超时，需要检查该接口的性能"
6. **只输出Markdown格式的诊断报告，不要添加任何额外的解释、总结或说明文字**
7. **不要在```markdown代码块之外添加任何内容**
8. 输出必须简洁明了，避免重复
9. **关键证据优先级规则**:
   - 如果【关键证据 - 运行中的服务】显示某服务成功读取了日志 → 该服务容器一定存在且可访问
   - 即使在其他地方看到"No such container"等错误信息，也应优先相信日志读取成功的证据
   - 例如：如果前端日志成功读取了1行，就绝对不能说"ruoyi-frontend 容器不存在"
10. **交叉验证原则**: 当不同证据源矛盾时，按以下优先级判断:
   - 最高优先级: 实际日志读取结果（能读到日志 = 容器存在）
   - 次高优先级: 容器发现阶段的 docker ps 结果
   - 较低优先级: 工具调用过程中的临时错误信息
11. **充分利用日志统计分析**: 在分析问题时，必须参考上面提供的【日志统计分析】数据:
   - 如果HTTP状态码中有大量5xx错误 → 说明服务端存在问题
   - 如果某个IP的请求全部失败而其他IP正常 → 可能是特定客户端或网络问题
   - 如果特定路径的请求频繁超时 → 该接口可能存在性能瓶颈或逻辑错误
   - 如果上游错误数量较多 → 需要检查后端服务的健康状态
12. **明确区分历史问题和当前活跃问题**:
   - **关键步骤**: 必须参考【当前状态验证（最近5分钟）】的结果
   - 如果当前状态验证显示“✅ 正常运行” → 将问题归类为“已恢复的历史问题”
   - 如果当前状态验证显示“❌ 存在活跃问题” → 将问题归类为“当前活跃问题”，并在“问题根因”中明确指出
   - **示例**:
     ```
     场景1: 历史日志有超时错误，但当前状态验证显示“✅ 所有服务当前运行正常”
     → 报告: “系统未发现当前错误。从历史日志来看曾发生 XXX 错误，但应用已重启成功...”
     
     场景2: 历史日志有超时错误，且当前状态验证显示“❌ 前端服务: 存在活跃问题 (超时错误)”
     → 报告: “当前仍存在超时问题。前端服务在最近5分钟内出现 X 次超时错误...”
     ```

【输出格式要求】
请严格按照以下 Markdown 格式输出诊断报告，不要添加任何额外说明或示例文字：

```markdown
## 问题根因
（如果系统正常，写：“系统未发现当前错误。从历史日志来看曾发生 XXX 错误，但应用已重启成功，各项配置均正常运行。证据：XXX”）
（如果有当前活跃问题，列出具体问题，并引用【当前状态验证】中的证据）

**重要**: 必须明确说明问题是“当前活跃”还是“已恢复的历史问题”

## 已恢复的历史问题
（列出历史问题，如果没有则省略此节）

## 立即执行
1. `命令1` - 作用说明
2. `命令2` - 作用说明
...

## 长期优化
1. 建议1
2. 建议2
3. 建议3
...

## 服务状态
前端: [容器名称] (状态)
后端: [容器名称] (状态)
数据库: [中间件类型] [容器名称] (状态)
缓存: [中间件类型] [容器名称] (状态)
```

**重要提示**：
- **每个章节只能出现一次**，不要重复输出相同的章节标题
- 在"服务状态"章节中，必须完整展示下面提供的【容器资源使用情况】数据
- 将 docker stats 表格直接放在服务状态后面，不要添加任何说明文字

**重要：只输出上述 Markdown 内容，不要输出任何其他文字、说明或示例！**
"""
    
    response = await llm.ainvoke(prompt)
    
    print(f"[Generate Report] 诊断完成")
    
    return {
        **state,
        "diagnosis_result": {
            "content": response.content,
            "confidence": "high" if state.get('logs_data') and state.get('memory_info') else "medium",
            "data_sources": {
                "logs": bool(state.get('logs_data')),
                "memory": bool(state.get('memory_info')),
                "cpu": bool(state.get('cpu_info')),
                "service_status": bool(state.get('service_status'))
            }
        },
        "current_step": "complete"
    }


# ===== 路由逻辑 =====

def route_after_analyze(state: DiagnosisState) -> str:
    """根据分析结果路由到相应节点"""
    action = state['current_step']
    next_action = state.get('next_action', '')
    
    # current_step 实际上是 analyze_node 决定的"下一步行动"
    print(f"[Route] [DEBUG] next_action: {next_action}")
    
    # === 新增:配置错误和服务未启动的快速路由 ===
    if action == "error_no_config":
        return "generate_error_report"
    
    if action == "discover_containers":
        return "discover_containers"
    
    # 如果 analyze_node 已经决定生成报告(服务未启动场景),直接路由
    if action == "generate_report":
        return "generate_report"
    
    # === 修复：检查 next_action 而不是 current_step ===
    if next_action in ["read_logs", "check_memory", "check_cpu", "check_service", "check_mysql", "perform_health_check"]:
        return "collect_data"
    
    # 兼容旧逻辑：如果 current_step 是行动名称
    if action in ["read_logs", "check_memory", "check_cpu", "check_service", "check_mysql", "perform_health_check"]:
        return "collect_data"
    
    # 默认生成报告
    return "generate_report"


def route_after_collect(state: DiagnosisState) -> str:
    """数据收集后回到分析节点"""
    if state['iteration_count'] >= state['max_iterations']:
        print(f"[Route] 达到最大迭代次数，生成报告")
        # 注意：这里只返回路由目标，不清空state
        # analyze_node会在达到最大迭代次数时清空next_action
        return "generate_report"
    return "analyze"


# ===== 构建工作流 =====

def build_diagnosis_workflow():
    """构建诊断工作流"""
    builder = StateGraph(DiagnosisState)
    
    # 原有节点
    builder.add_node("analyze", analyze_node)
    builder.add_node("collect_data", collect_data_node)
    builder.add_node("generate_report", generate_report_node)
    
    # 新增节点
    builder.add_node("discover_containers", discover_containers_node)
    builder.add_node("generate_error_report", generate_error_report_node)
    
    # 路由边
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges("analyze", route_after_analyze)
    builder.add_edge("discover_containers", "analyze")  # 发现后回到分析
    builder.add_edge("collect_data", "analyze")
    builder.add_edge("generate_report", END)
    builder.add_edge("generate_error_report", END)  # 新增
    
    return builder.compile()


# 创建工作流实例
diagnosis_workflow = build_diagnosis_workflow()


# ===== 对外接口 =====

async def run_diagnosis(
    alert_event: dict, 
    container_name: str = "ruoyi-app",  # 保持原有默认值
    env_file_path: str = ".env"
) -> dict:
    """
    运行诊断工作流（由Grafana告警自动触发）
    
    Args:
        alert_event: Grafana告警事件，包含以下字段：
            - alert_name: 告警名称
            - alert_type: 告警类型（container_restart, memory_high, cpu_high等）
            - alert_time: 告警时间
            - description: 告警描述
        container_name: 容器名称
        env_file_path: 配置文件路径
    
    Returns:
        诊断结果
    """
    # 1. 加载并验证配置
    servers_config = load_servers_config(env_file_path)
    config_status = determine_config_status(servers_config)
    
    # 2. 如果未指定容器名，尝试从配置推断
    if container_name == "ruoyi-app" and config_status != "none":
        # 根据告警类型推断目标容器
        alert_type = alert_event.get('alert_type', '')
        if 'frontend' in alert_type:
            container_name = servers_config.get('frontend', {}).get('container_name', container_name)
        elif 'backend' in alert_type or 'app' in alert_type:
            container_name = servers_config.get('backend', {}).get('container_name', container_name)
    
    initial_state: DiagnosisState = {
        "alert_event": alert_event,
        "container_name": container_name,
        "messages": [],
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 8,  # 最多8次迭代
        "actions_taken": [],  # 已执行的行动列表
        "anomaly_timestamps": [],
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
        "service_status": None,
        "mysql_status": None,
        "log_search_range_minutes": 0,  # 初始为0,首次读取时设为30
        "logs_collected_ranges": [],  # 已收集的日志范围列表
        "diagnosis_result": None,
        # 新增字段
        "config_status": config_status,
        "servers_config": servers_config,
        "discovered_containers": [],
        "service_status_summary": "",
        # 内部调试字段
        "_health_check_execution_count": 0  # 健康检查执行次数计数器
    }
    
    try:
        final_state = await diagnosis_workflow.ainvoke(initial_state)
        
        return {
            "status": "success",
            "diagnosis": final_state.get("diagnosis_result"),
            "iteration_count": final_state.get("iteration_count"),
            "data_collected": {
                "logs": bool(final_state.get('logs_data')),
                "memory": bool(final_state.get('memory_info')),
                "cpu": bool(final_state.get('cpu_info')),
                "service_status": bool(final_state.get('service_status'))
            }
        }
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"\n{'='*70}")
        print(f"[ERROR] 诊断失败 - 详细错误信息:")
        print(f"{'='*70}")
        print(error_traceback)
        return {
            "status": "error",
            "message": str(e),
            "traceback": error_traceback
        }
