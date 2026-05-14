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
        return {
            **state,
            "current_step": "generate_report",
            "actions_taken": state.get('actions_taken', []) + ["force_stop_by_max_iterations"]
        }
    
    # === 新增:服务未启动的快速判断 ===
    if state.get('config_status') == 'complete' and has_stopped_services(state):
        stopped_services = get_stopped_services(state)
        logs_data = state.get('logs_data', '')
        discovered = state.get('discovered_containers') or []
        
        # 检查是否有服务完全缺失（容器不存在）
        missing_containers = [c for c in discovered if c.get('issue') in ['no_containers', 'service_not_found', 'compose_services_not_started']]
        
        if missing_containers:
            # 服务完全缺失，直接生成报告
            print(f"[Analyze] 检测到 {len(missing_containers)} 个服务完全缺失，直接生成报告")
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
- 当前日志追溯范围: {state.get('log_search_range_minutes', 0)}分钟
- 已收集的日志范围: {len(state.get('logs_collected_ranges', []))}个

请决定下一步行动（只返回一个行动名称，不要其他内容）：
1. check_memory - 检查内存使用情况（如果还没有执行过）
2. check_cpu - 检查CPU使用情况（如果还没有执行过）
3. check_service - 检查服务运行状态（如果还没有执行过）
4. check_mysql - 检查MySQL数据库状态（如果还没有执行过）
5. read_logs - 读取或扩大日志追溯范围
6. read_logs_recent - 读取相关服务的最近10分钟日志（用于交叉验证）
7. generate_report - 生成诊断报告

决策规则（按优先级判断）：
1. **如果检测到服务完全缺失**（discovered_containers 中有 issue='no_containers' 或 'service_not_found' 的容器）→ **直接 generate_report**
2. 如果check_memory未执行 → check_memory
3. 如果check_memory已执行但check_cpu未执行 → check_cpu
4. 如果内存和CPU都已检查，但check_service未执行 → check_service
5. 如果核心资源指标已检查：
   a. 如果还未读取任何日志 → read_logs (首次读取30分钟)
   b. 如果已读取后端日志但未读取相关服务日志 → read_logs_recent (读取Redis/MySQL等服务的最近10分钟日志)
   c. 如果已读取日志但范围 < 180分钟，且你认为需要更多信息 → read_logs (扩大范围)
   d. 如果已有足够信息或达到最大迭代次数 → generate_report
6. 如果达到最大迭代次数 → generate_report

重要判断逻辑：
- **先通过内存/CPU/服务状态进行初步判断**
- 如果资源状态异常(内存紧张/CPU高/服务异常) → 必须读取日志确认根因
- 如果后端日志显示其他服务错误 → 使用 read_logs_recent 读取相关服务日志进行交叉验证
- **日志是诊断的核心依据,不可跳过**
- **优先关注最近10分钟内的日志，历史日志可能是已解决的问题**
- **如果服务已被确认缺失（容器不存在），不要再尝试检查该服务，直接生成报告**

重要：
- **严禁重复执行已执行过的行动**
- 从“已执行的行动”列表中排除已经做过的
- **如果某个行动已经连续执行超过2次且没有收集到新信息，立即切换到其他行动或生成报告**
"""
    
    response = await llm.ainvoke(prompt)
    next_action = response.content.strip()
    
    # === 防护机制：检测重复行动 ===
    actions_taken = state.get('actions_taken', [])
    if len(actions_taken) >= 2:
        # 检查最近3次行动是否都是同一个行动
        recent_actions = actions_taken[-3:] if len(actions_taken) >= 3 else actions_taken
        if len(set(recent_actions)) == 1 and recent_actions[0] == next_action:
            print(f"[Analyze] [WARN] 检测到行动 '{next_action}' 已连续执行 {len(recent_actions)} 次，强制切换到 generate_report")
            next_action = "generate_report"
    
    print(f"[Analyze] 决定下一步行动: {next_action}")
    
    return {
        **state,
        "current_step": next_action,
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
    
    return {
        **state,
        "discovered_containers": all_discovered,
        "servers_config": updated_config,
        "config_status": "complete",  # 发现后升级为 complete
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
    action = state['current_step']
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
            
            if current_range == 0:
                # 首次读取,从30分钟开始
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
                                print(f"[Collect Data] 读取 {svc_type} 服务日志 (容器: {svc_name})")
                                
                                try:
                                    svc_result = await read_tool.ainvoke({
                                        "container_name": svc_name,
                                        "since_time": since,
                                        "until_time": until,
                                        "lines": 200,
                                        "log_level": None
                                    })
                                    
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
                # 检查后端日志中是否包含其他服务的错误关键词
                services_to_check = []
                if any(kw in new_logs.lower() for kw in ['redis', '6379']):
                    services_to_check.append('redis')
                if any(kw in new_logs.lower() for kw in ['mysql', 'database', '3306']):
                    services_to_check.append('mysql')
                
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
                    services_to_read.append(('redis', container.get('container_name') or name))
                elif 'mysql' in name:
                    services_to_read.append(('mysql', container.get('container_name') or name))
            
            now = datetime.now()
            since = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
            until = now.strftime("%Y-%m-%dT%H:%M:%S")
            
            combined_logs = state.get('logs_data', '')
            
            # 依次读取各服务日志
            for service_name, container_name in services_to_read:
                print(f"[Collect Data] 读取 {service_name} 服务日志 (容器: {container_name})")
                try:
                    result = await read_tool.ainvoke({
                        "container_name": container_name,
                        "since_time": since,
                        "until_time": until,
                        "lines": 200,
                        "log_level": None
                    })
                    
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
    
    # === 新增:服务未启动的快速报告 ===
    service_status_summary = state.get('service_status_summary', '')
    if service_status_summary:
        print("[Generate Report] 生成服务未启动的快速报告")
        
        prompt = f"""你是运维诊断专家。检测到以下服务未启动：

{service_status_summary}

请基于以上信息生成诊断报告：
1. 明确指出哪些服务未启动
2. 分析可能的原因（基于日志证据）
3. 给出恢复步骤

【输出格式要求】
```markdown
## 问题根因
（精炼描述服务未启动的原因，引用日志证据）

## 立即执行
1. `docker start <container_name>` - 启动未运行的服务
2. `docker logs <container_name> --tail 50` - 查看启动日志确认正常
3. （根据实际情况补充其他步骤）...

## 长期优化
1. 配置容器自动重启策略：docker update --restart=unless-stopped <container>
2. 添加健康检查和监控告警
3. ...
```

**注意：只输出上述格式的内容，不要有任何其他文字！**
"""
        response = await llm.ainvoke(prompt)
        
        stopped_services = get_stopped_services(state)
        
        return {
            **state,
            "diagnosis_result": {
                "content": response.content,
                "confidence": "high",
                "data_sources": {
                    "service_status": True,
                    "logs": bool(state.get('logs_data'))
                },
                "stopped_services": stopped_services
            },
            "current_step": "complete"
        }
    
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
    if suspicious_containers:
        container_status_info = "\n\n【可疑容器状态】\n"
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

{service_status_detail}

【多服务日志摘要】
- 后端日志行数: {len(backend_logs.splitlines()) if backend_logs else 0}
- 前端日志行数: {len(frontend_logs.splitlines()) if frontend_logs else 0}
- Redis日志行数: {len(redis_logs.splitlines()) if redis_logs else 0}
- MySQL日志行数: {len(mysql_logs.splitlines()) if mysql_logs else 0}{container_status_info}{log_empty_warning}

【应用启动状态分析】
- 后端容器状态: {next((c.get('status', 'unknown') for c in discovered if c.get('type') == 'backend'), '未找到')}
- 是否包含启动成功标志: {'是' if backend_logs and ('启动成功' in backend_logs or 'Started' in backend_logs or '若依启动成功' in backend_logs) else '否'}
- 是否有正常业务日志: {'是' if backend_logs and ('登录成功' in backend_logs or 'Success' in backend_logs or 'exec-' in backend_logs) else '否'}

**重要提示**：
- 如果“是否包含启动成功标志”为“是”，且“是否有正常业务日志”为“是”，说明应用已经成功启动并正常运行
- 在这种情况下，即使日志中有历史错误（如启动时的 "Too many connections"），也应该标记为“已恢复的历史问题”，而不是“当前活跃问题”

【交叉验证指南】
请对每个潜在问题进行多维度验证（至少2个证据源一致才确认为当前问题）：

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
   - 判定: 两者都异常才确认

【时间维度判断】
- **优先关注最近10分钟内的日志**：这些反映当前问题
- **10-30分钟的日志**：可能是问题的起因或早期迹象
- **30分钟以上的日志**：很可能是已解决的历史问题

**关键判断规则**：
1. 如果错误发生在应用启动阶段，但应用最终启动成功 → 标记为“已恢复的历史问题”
2. 如果服务当前状态正常（容器运行中、端口可访问）→ 即使有历史错误，也标记为“已恢复”
3. 如果最近10分钟内没有相同错误，且服务正常运行 → 标记为“已恢复的历史问题”
4. 只有当错误持续出现且服务状态异常时，才标记为“当前活跃问题”

**示例**：
- 场景1: 启动时出现 "Too many connections"，但应用最终启动成功且有正常业务日志 → 已恢复的历史问题
- 场景2: 最近10分钟内持续出现 "Too many connections"，且应用无法响应 → 当前活跃问题
- 场景3: MySQL 容器状态为 healthy，后端日志中有历史连接错误但最近无错误 → 已恢复的历史问题

【重要要求】
1. 严格基于上述真实数据，不要编造信息
2. **综合分析所有收集的日志**,检查是否存在异常模式:
   - 错误信息(Exception, Error, Fatal, OutOfMemoryError等)
   - 警告信息(Warning, Timeout, Slow query等)
   - 异常重启或服务崩溃迹象
   - 性能退化(响应时间增加、资源使用率飙升等)
   - 任何与正常行为不符的模式
3. **结合内存、CPU、服务状态等资源指标进行综合判断**
4. 如果发现任何问题,必须在“问题根因”中明确指出
5. **只输出Markdown格式的诊断报告，不要添加任何额外的解释、总结或说明文字**
6. **不要在```markdown代码块之外添加任何内容**
7. 输出必须简洁明了，避免重复
8. **关键证据优先级规则**:
   - 如果【关键证据 - 运行中的服务】显示某服务成功读取了日志 → 该服务容器一定存在且可访问
   - 即使在其他地方看到"No such container"等错误信息，也应优先相信日志读取成功的证据
   - 例如：如果前端日志成功读取了1行，就绝对不能说"ruoyi-frontend 容器不存在"
9. **交叉验证原则**: 当不同证据源矛盾时，按以下优先级判断:
   - 最高优先级: 实际日志读取结果（能读到日志 = 容器存在）
   - 次高优先级: 容器发现阶段的 docker ps 结果
   - 较低优先级: 工具调用过程中的临时错误信息

【输出格式示例】
```markdown
## 问题根因
（只列出经过交叉验证确认的当前活跃问题，语言精炼,引用具体数据和日志中的关键信息）
- 如果有可疑容器（端口为空或状态异常），必须在问题根因中明确指出
- 如果日志为空，需要分析可能的原因并给出检查建议

## 已恢复的历史问题
（列出只在历史日志中出现但当前已正常的问题，如果没有则省略此节）

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
数据库: [中间件类型] [容器名称] (状态)  # 例如: [MySQL] mysql (Up 10 minutes)
缓存: [中间件类型] [容器名称] (状态)  # 例如: [Redis] redis (Up 10 minutes)
```

**注意：只输出上述格式的内容，不要有任何其他文字！**
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
    
    # === 新增:配置错误和服务未启动的快速路由 ===
    if action == "error_no_config":
        return "generate_error_report"
    
    if action == "discover_containers":
        return "discover_containers"
    
    # 如果 analyze_node 已经决定生成报告(服务未启动场景),直接路由
    if action == "generate_report":
        return "generate_report"
    
    # === 原有路由逻辑保持不变 ===
    if action in ["read_logs", "check_memory", "check_cpu", "check_service", "check_mysql"]:
        return "collect_data"
    
    # 默认生成报告
    return "generate_report"


def route_after_collect(state: DiagnosisState) -> str:
    """数据收集后回到分析节点"""
    if state['iteration_count'] >= state['max_iterations']:
        print(f"[Route] 达到最大迭代次数，生成报告")
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
        "service_status_summary": ""
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
