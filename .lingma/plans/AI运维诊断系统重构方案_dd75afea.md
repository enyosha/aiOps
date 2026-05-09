# AI运维诊断系统重构方案

## 一、需求分析与现状评估

### 1.1 核心需求
1. **智能日志分析**：基于问题发生时间，向前追溯30分钟窗口读取日志（过滤INFO/DEBUG）
2. **SSH命令执行**：结合LLM经验执行内存、CPU等系统指标查询
3. **迭代追溯机制**：两阶段追溯 - 先快速扫描定位异常时间点，再深入分析该时段前后30分钟
4. **纯LLM驱动诊断**：完全依赖LLM的既有经验和推理能力，不使用诊断树或知识库检索
5. **REST API接口**：提供HTTP诊断接口
6. **诊断记录存储**：保存为JSON文件到diagnosis_records目录
7. **测试用例触发**：利用服务器上现有的故障场景进行测试

### 1.2 设计原则
- ⚠️ **与OpsAgent完全隔离**：不依赖`Routing/ops_agent.py`的任何逻辑
- ⚠️ **不使用诊断树**：不检索知识库，不执行预定义的诊断流程
- ✅ **纯LLM驱动**：让LLM根据日志和系统指标自主分析问题
- ✅ **工具增强**：通过MCP工具提供实时数据（日志、内存、CPU等）

### 1.3 现有基础
- ✅ Log-Reader MCP服务已存在（`Server/logReader_server.py`），但功能简单（仅读取本地日志文件）
- ✅ SSH连接管理已有基础（`Server/ops_diagnosis_server.py`中的paramiko使用）
- ✅ LangGraph工作流框架成熟（`Routing/base_agent.py`可作为参考）

### 1.4 需要实现的核心模块
- 🔧 **Log-Reader MCP服务**：从"读取本地日志文件"重构为"通过SSH读取远程Docker容器日志"
- 🔧 **日志过滤能力**：在MCP服务端实现日志级别过滤（ERROR/WARN）
- 🔧 **快速扫描工具**：识别异常时间点
- 🔧 **新建DiagnosisAgent**：独立的诊断Agent，纯LLM驱动，不使用诊断树
- 🔧 **REST API接口**：提供HTTP诊断接口
- 🔧 **诊断记录持久化**：新增JSON文件存储逻辑

---

## 二、详细实施方案

### 任务1：重构Log-Reader MCP服务（核心改造）

**目标文件**：`Server/logReader_server.py`

**改造内容**：
1. **移除本地日志文件读取逻辑**，改为通过SSH连接远程服务器
2. **新增工具函数**：
   - `read_docker_logs(container_name, lines, since_time, until_time, log_level)` - 读取指定容器的日志
   - `filter_logs_by_level(logs, levels=['ERROR', 'WARN'])` - 过滤日志级别
   - `scan_logs_for_anomalies(container_name, time_range_hours)` - 快速扫描异常时间点
   - `get_container_status(container_name)` - 获取容器运行状态

3. **实现两阶段追溯逻辑**：
   ```python
   # 第一阶段：快速扫描（过去2小时，只返回ERROR/WARN的时间戳分布）
   scan_result = await scan_logs_for_anomalies("ruoyi-app", time_range_hours=2)
   # 返回：{"anomaly_timestamps": ["2026-05-08T10:15:00", "2026-05-08T10:45:00"], ...}
   
   # 第二阶段：深入分析（针对异常时间点前后30分钟）
   for timestamp in anomaly_timestamps:
       logs = await read_docker_logs(
           container_name="ruoyi-app",
           since_time=(timestamp - 30min),
           until_time=(timestamp + 30min),
           log_level=["ERROR", "WARN"]
       )
   ```

4. **日志级别过滤实现**：
   - 在`read_docker_logs`中增加`log_level`参数（默认`["ERROR", "WARN"]`）
   - 使用正则表达式过滤：`re.match(r'.*\b(ERROR|WARN|WARNING)\b.*', line)`
   - 支持传入`None`表示不过滤（用于调试）

5. **SSH连接复用**：
   - 从`.env`读取SSH配置（已有：SSH_HOST=8.130.131.36, SSH_KEY_PATH=./aiOps.pem）
   - 使用paramiko建立SSH连接
   - 执行`docker logs`命令并解析输出

**关键代码示例**：
```python
@mcp.tool()
def read_docker_logs(
    container_name: str,
    lines: int = 100,
    since_time: Optional[str] = None,
    until_time: Optional[str] = None,
    log_level: Optional[List[str]] = ["ERROR", "WARN"]
) -> dict:
    """
    通过SSH读取远程Docker容器日志
    
    Args:
        container_name: 容器名称（必填）
        lines: 最大返回行数
        since_time: 起始时间（ISO 8601格式）
        until_time: 结束时间
        log_level: 日志级别过滤列表（默认只返回ERROR和WARN）
    
    Returns:
        包含日志内容和元数据的字典
    """
    # 构建docker logs命令
    cmd = f"docker logs {container_name}"
    if since_time:
        cmd += f" --since '{since_time}'"
    if until_time:
        cmd += f" --until '{until_time}'"
    cmd += f" --tail {lines} 2>&1"
    
    # SSH执行
    ssh_client = _get_ssh_connection()  # 从.env读取配置
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    raw_logs = stdout.read().decode('utf-8')
    
    # 过滤日志级别
    if log_level:
        filtered_logs = filter_logs_by_level(raw_logs, log_level)
    else:
        filtered_logs = raw_logs
    
    return {
        "status": "success",
        "container": container_name,
        "line_count": len(filtered_logs.splitlines()),
        "logs": filtered_logs,
        "time_range": {"since": since_time, "until": until_time}
    }
```

---

### 任务2：创建独立的DiagnosisAgent（纯LLM驱动）

**目标文件**：`Routing/diagnosis_agent.py`（新建）

**设计原则**：
- ❌ 不使用知识库检索
- ❌ 不执行诊断树
- ✅ 完全依赖LLM的推理能力
- ✅ 通过MCP工具获取实时数据
- ✅ 简单的ReAct循环：观察 → 思考 → 行动 → 重复

**State定义**：
```python
class DiagnosisState(TypedDict):
    """诊断状态"""
    user_input: str                    # 用户输入的问题描述
    container_name: str                # 容器名称
    
    # 诊断过程
    messages: List[BaseMessage]        # 对话历史
    current_step: str                  # 当前步骤
    iteration_count: int               # 迭代次数
    max_iterations: int = 5            # 最大迭代次数
    
    # 收集的数据
    anomaly_timestamps: List[str]      # 异常时间点列表
    logs_data: Optional[str]           # 日志数据
    memory_info: Optional[str]         # 内存信息
    cpu_info: Optional[str]            # CPU信息
    service_status: Optional[str]      # 服务状态
    
    # 诊断结果
    diagnosis_result: Optional[dict]   # 最终诊断结果
```

**节点设计**：

1. **analyze_node**：初步分析用户输入，决定下一步行动
   ```python
   async def analyze_node(state: DiagnosisState) -> DiagnosisState:
       """分析当前状态，决定下一步要做什么"""
       # LLM判断：是否需要扫描日志？是否需要检查资源？是否已有足够信息生成报告？
       prompt = f"""
       你是一个运维诊断专家。当前状态：
       - 用户问题：{state['user_input']}
       - 已收集的日志：{'有' if state.get('logs_data') else '无'}
       - 已检查的内存：{'有' if state.get('memory_info') else '无'}
       - 已检查的CPU：{'有' if state.get('cpu_info') else '无'}
       - 迭代次数：{state['iteration_count']}/{state['max_iterations']}
       
       请决定下一步行动（选择一个）：
       1. scan_logs - 扫描日志找异常时间点
       2. read_logs - 读取指定时间段的详细日志
       3. check_memory - 检查内存使用情况
       4. check_cpu - 检查CPU使用情况
       5. check_service - 检查服务运行状态
       6. generate_report - 生成诊断报告（当有足够数据时）
       
       只返回行动名称，不要其他内容。
       """
       
       response = await llm.ainvoke(prompt)
       next_action = response.content.strip()
       
       return {
           **state,
           "current_step": next_action
       }
   ```

2. **scan_anomalies_node**：快速扫描异常时间点
   ```python
   async def scan_anomalies_node(state: DiagnosisState) -> DiagnosisState:
       """快速扫描日志，识别异常时间点"""
       from Routing.tool_cache import tool_cache
       tools = await tool_cache.get_tools("log-reader")
       scan_tool = next((t for t in tools if t.name == "scan_logs_for_anomalies"), None)
       
       result = await scan_tool.ainvoke({
           "container_name": state['container_name'],
           "time_range_hours": 2
       })
       
       return {
           **state,
           "anomaly_timestamps": result.get("anomaly_timestamps", []),
           "iteration_count": state['iteration_count'] + 1
       }
   ```

3. **collect_data_node**：收集详细数据（日志、内存、CPU）
   ```python
   async def collect_data_node(state: DiagnosisState) -> DiagnosisState:
       """根据当前步骤收集相应的数据"""
       action = state['current_step']
       
       from Routing.tool_cache import tool_cache
       tools = await tool_cache.get_tools("log-reader")
       
       if action == "read_logs":
           # 读取异常时间点的详细日志
           read_tool = next((t for t in tools if t.name == "read_docker_logs"), None)
           if read_tool and state.get('anomaly_timestamps'):
               timestamp = state['anomaly_timestamps'][0]
               ts = datetime.fromisoformat(timestamp)
               since = (ts - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
               until = (ts + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
               
               log_result = await read_tool.ainvoke({
                   "container_name": state['container_name'],
                   "since_time": since,
                   "until_time": until,
                   "log_level": ["ERROR", "WARN"]
               })
               
               return {
                   **state,
                   "logs_data": log_result.get("logs", ""),
                   "iteration_count": state['iteration_count'] + 1
               }
       
       elif action == "check_memory":
           # 调用ops-diagnosis的check_memory_usage工具
           ops_tools = await tool_cache.get_tools("ops-diagnosis")
           mem_tool = next((t for t in ops_tools if t.name == "check_memory_usage"), None)
           if mem_tool:
               mem_result = await mem_tool.ainvoke({})
               # 解析MCP返回格式
               if isinstance(mem_result, list) and len(mem_result) > 0:
                   import json
                   first_item = mem_result[0]
                   if isinstance(first_item, dict) and 'text' in first_item:
                       mem_data = json.loads(first_item['text'])
                   else:
                       mem_data = first_item
                   
                   return {
                       **state,
                       "memory_info": mem_data.get("memory_info", ""),
                       "iteration_count": state['iteration_count'] + 1
                   }
       
       elif action == "check_cpu":
           # 类似check_memory的逻辑
           pass
       
       elif action == "check_service":
           # 检查容器状态
           pass
       
       return {
           **state,
           "iteration_count": state['iteration_count'] + 1
       }
   ```

4. **generate_report_node**：生成最终诊断报告
   ```python
   async def generate_report_node(state: DiagnosisState) -> DiagnosisState:
       """基于收集的所有数据生成诊断报告"""
       prompt = f"""
       你是一个专业的运维故障诊断专家。基于以下实时数据分析问题原因并给出解决方案。
       
       【用户问题】
       {state['user_input']}
       
       【容器名称】
       {state['container_name']}
       
       【收集的实时数据】
       
       1. 异常时间点：
       {json.dumps(state.get('anomaly_timestamps', []), indent=2)}
       
       2. 容器日志（ERROR/WARN级别）：
       {state.get('logs_data', '未收集')[:1000]}
       
       3. 内存使用情况：
       {state.get('memory_info', '未收集')}
       
       4. CPU使用情况：
       {state.get('cpu_info', '未收集')}
       
       5. 服务状态：
       {state.get('service_status', '未收集')}
       
       【要求】
       请基于以上真实数据进行分析，不要使用通用知识。
       
       输出格式：
       ```
       【问题根因】
       （详细说明导致问题的根本原因，引用具体的日志和指标数据）
       
       【立即执行】
       1. 具体命令1 # 作用说明
       2. 具体命令2 # 作用说明
       
       【长期优化】
       1. 建议1
       2. 建议2
       ```
       """
       
       response = await llm.ainvoke(prompt)
       
       return {
           **state,
           "diagnosis_result": {
               "content": response.content,
               "confidence": "high" if state.get('logs_data') and state.get('memory_info') else "medium",
               "data_sources": {
                   "logs": bool(state.get('logs_data')),
                   "memory": bool(state.get('memory_info')),
                   "cpu": bool(state.get('cpu_info'))
               }
           },
           "current_step": "complete"
       }
   ```

**路由逻辑**：
```python
def route_after_analyze(state: DiagnosisState) -> str:
    """根据分析结果路由到相应节点"""
    action = state['current_step']
    
    if action == "scan_logs":
        return "scan_anomalies"
    elif action in ["read_logs", "check_memory", "check_cpu", "check_service"]:
        return "collect_data"
    elif action == "generate_report":
        return "generate_report"
    else:
        # 默认生成报告
        return "generate_report"

def route_after_collect(state: DiagnosisState) -> str:
    """数据收集后回到分析节点"""
    if state['iteration_count'] >= state['max_iterations']:
        return "generate_report"
    return "analyze"
```

**工作流构建**：
```python
def build_diagnosis_workflow():
    """构建诊断工作流"""
    builder = StateGraph(DiagnosisState)
    
    builder.add_node("analyze", analyze_node)
    builder.add_node("scan_anomalies", scan_anomalies_node)
    builder.add_node("collect_data", collect_data_node)
    builder.add_node("generate_report", generate_report_node)
    
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges("analyze", route_after_analyze)
    builder.add_edge("scan_anomalies", "analyze")
    builder.add_edge("collect_data", "analyze")
    builder.add_edge("generate_report", END)
    
    return builder.compile()
```

**对外接口**：
```python
async def run_diagnosis(user_input: str, container_name: str = "ruoyi-app") -> dict:
    """运行诊断工作流"""
    workflow = build_diagnosis_workflow()
    
    initial_state: DiagnosisState = {
        "user_input": user_input,
        "container_name": container_name,
        "messages": [],
        "current_step": "start",
        "iteration_count": 0,
        "max_iterations": 5,
        "anomaly_timestamps": [],
        "logs_data": None,
        "memory_info": None,
        "cpu_info": None,
        "service_status": None,
        "diagnosis_result": None
    }
    
    final_state = await workflow.ainvoke(initial_state)
    
    return {
        "status": "success",
        "diagnosis": final_state.get("diagnosis_result"),
        "iteration_count": final_state.get("iteration_count"),
        "data_collected": {
            "logs": bool(final_state.get('logs_data')),
            "memory": bool(final_state.get('memory_info')),
            "cpu": bool(final_state.get('cpu_info'))
        }
    }
```

---

### 任务3：集成REST API

**目标文件**：新建 `Server/api_server.py`（独立API服务，不与现有路由耦合）

**优势**：
- ✅ 职责清晰，不影响现有代码
- ✅ 可独立部署和扩展
- ✅ 便于后续优化拆分

**实现内容**：
```python
"""
AI Ops Diagnosis API Server
独立的REST API服务，提供运维诊断接口
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
import sys
import json
from datetime import datetime

# 添加项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="AI Ops Diagnosis API", version="1.0.0")

# ===== 请求/响应模型 =====

class DiagnosisRequest(BaseModel):
    user_input: str
    container_name: Optional[str] = "ruoyi-app"

class DiagnosisResponse(BaseModel):
    status: str
    diagnosis: Optional[dict]
    iteration_count: int
    data_collected: dict
    records_saved: bool
    record_path: Optional[str] = None

# ===== 诊断记录保存 =====

def save_diagnosis_record(user_input: str, result: dict) -> str:
    """保存诊断记录为JSON文件"""
    records_dir = os.path.join(os.path.dirname(__file__), "..", "diagnosis_records")
    os.makedirs(records_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"diagnosis_{timestamp}.json"
    filepath = os.path.join(records_dir, filename)
    
    record = {
        "timestamp": datetime.now().isoformat(),
        "user_input": user_input,
        "result": result,
        "metadata": {
            "iteration_count": result.get('iteration_count'),
            "data_collected": result.get('data_collected', {})
        }
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    
    print(f"[Record] Saved to: {filepath}")
    return filepath

# ===== API路由 =====

@app.post("/api/diagnose", response_model=DiagnosisResponse)
async def api_diagnose(request: DiagnosisRequest):
    """
    运维诊断API接口
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/api/diagnose \
      -H "Content-Type: application/json" \
      -d '{"user_input": "访问8.130.131.36:8080出现502错误", "container_name": "ruoyi-app"}'
    ```
    """
    try:
        # 导入诊断Agent
        from Routing.diagnosis_agent import run_diagnosis
        
        # 调用诊断流程
        result = await run_diagnosis(
            user_input=request.user_input,
            container_name=request.container_name
        )
        
        # 保存诊断记录
        record_path = save_diagnosis_record(request.user_input, result)
        
        return DiagnosisResponse(
            status=result['status'],
            diagnosis=result.get('diagnosis'),
            iteration_count=result.get('iteration_count', 0),
            data_collected=result.get('data_collected', {}),
            records_saved=os.path.exists(record_path),
            record_path=record_path
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "service": "AI Ops Diagnosis API",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/records")
async def list_records(limit: int = 10):
    """列出最近的诊断记录"""
    records_dir = os.path.join(os.path.dirname(__file__), "..", "diagnosis_records")
    
    if not os.path.exists(records_dir):
        return {"records": []}
    
    files = sorted(
        [f for f in os.listdir(records_dir) if f.endswith('.json')],
        reverse=True
    )[:limit]
    
    records = []
    for filename in files:
        filepath = os.path.join(records_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                record = json.load(f)
                records.append({
                    "filename": filename,
                    "timestamp": record.get('timestamp'),
                    "user_input": record.get('user_input', '')[:100]
                })
        except:
            continue
    
    return {"records": records, "count": len(records)}

# ===== 启动入口 =====

if __name__ == "__main__":
    print("Starting AI Ops Diagnosis API Server...")
    print("API Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

### 任务4：创建测试用例（利用现有故障）

**目标文件**：`test/test_diagnosis_api.py`

**测试内容**：
```python
"""
测试诊断API和完整诊断流程
"""
import asyncio
import sys
import os
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

async def test_diagnosis_via_api():
    """通过REST API测试诊断功能"""
    print("\n" + "="*80)
    print("诊断API测试")
    print("="*80)
    
    # 确保API服务已启动
    api_url = "http://localhost:8000/api/diagnose"
    
    user_input = "访问 8.130.131.36:8080 时出现故障，请分析原因"
    
    print(f"\n【用户输入】")
    print(f"{user_input}")
    print(f"\n{'='*80}")
    print("开始诊断...")
    print(f"{'='*80}\n")
    
    try:
        response = requests.post(
            api_url,
            json={
                "user_input": user_input,
                "container_name": "ruoyi-app"
            },
            timeout=300  # 5分钟超时
        )
        
        if response.status_code != 200:
            print(f"❌ API请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            return False
        
        result = response.json()
        
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到API服务，请先启动: python Server/api_server.py")
        print("\n或者使用直接调用方式测试...\n")
        return await test_diagnosis_direct()
    
    print(f"\n{'='*80}")
    print("【测试结果分析】")
    print(f"{'='*80}")
    print(f"状态: {result['status']}")
    print(f"迭代次数: {result.get('iteration_count', 'N/A')}")
    print(f"数据收集情况:")
    data_collected = result.get('data_collected', {})
    print(f"  - 日志: {'✅' if data_collected.get('logs') else '❌'}")
    print(f"  - 内存: {'✅' if data_collected.get('memory') else '❌'}")
    print(f"  - CPU: {'✅' if data_collected.get('cpu') else '❌'}")
    print(f"记录保存: {'✅' if result.get('records_saved') else '❌'}")
    if result.get('record_path'):
        print(f"记录路径: {result['record_path']}")
    
    if result['status'] == 'success' and result.get('diagnosis'):
        diagnosis = result['diagnosis']
        content = diagnosis.get('content', '')
        
        # 检查点
        checks = [
            ("基于实时日志分析", "ERROR" in content or "WARN" in content or "日志" in content),
            ("执行了系统检查", any(cmd in content for cmd in ["free", "top", "docker", "memory", "CPU"])),
            ("给出了具体修复命令", any(cmd in content for cmd in ["restart", "update", "kill", "docker", "systemctl"])),
            ("分析了根本原因", "根因" in content or "原因" in content or "cause" in content.lower()),
            ("提供了优化建议", "优化" in content or "建议" in content or "长期" in content)
        ]
        
        print(f"\n{'='*80}")
        print("【检查点验证】")
        print(f"{'='*80}")
        for i, (desc, passed) in enumerate(checks, 1):
            status = "✅ 通过" if passed else "❌ 失败"
            print(f"✓ 检查点 {i} - {desc}: {status}")
        
        all_passed = all(passed for _, passed in checks)
        
        print(f"\n{'='*80}")
        print(f"总体结果: {'✅ 全部通过' if all_passed else '⚠️ 部分通过'}")
        print(f"{'='*80}")
        
        print(f"\n{'='*80}")
        print("【完整诊断报告】")
        print(f"{'='*80}")
        print(content)
        
        return all_passed
    else:
        print(f"\n❌ 诊断失败: {result.get('message', 'Unknown error')}")
        return False

async def test_diagnosis_direct():
    """直接调用DiagnosisAgent测试（备用方案）"""
    print("\n使用直接调用方式测试...\n")
    
    from Routing.diagnosis_agent import run_diagnosis
    
    user_input = "访问 8.130.131.36:8080 时出现故障，请分析原因"
    
    result = await run_diagnosis(
        user_input=user_input,
        container_name="ruoyi-app"
    )
    
    # 复用上面的检查结果展示逻辑
    # ...
    return True  # 简化示例

if __name__ == "__main__":
    try:
        success = asyncio.run(test_diagnosis_via_api())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
```

---

### 任务5：更新配置文件和环境变量

**目标文件**：`.env`

**新增配置**：
```bash
# Log Reader 配置
LOG_DEFAULT_LEVELS=ERROR,WARN
LOG_SCAN_TIME_RANGE_HOURS=2
LOG_ANALYSIS_WINDOW_MINUTES=30

# 诊断记录存储
DIAGNOSIS_RECORDS_DIR=./diagnosis_records
```

---

## 三、实施步骤与验证

### Step 1: 重构Log-Reader MCP服务
- [ ] 修改`Server/logReader_server.py`，实现SSH远程日志读取
- [ ] 添加日志级别过滤功能
- [ ] 实现`scan_logs_for_anomalies`快速扫描工具
- [ ] 测试SSH连接和日志读取

**验证方法**：
```bash
cd Server
python logReader_server.py
# 在另一个终端测试MCP工具调用
```

### Step 2: 创建DiagnosisAgent
- [ ] 新建`Routing/diagnosis_agent.py`
- [ ] 实现analyze_node、scan_anomalies_node、collect_data_node、generate_report_node
- [ ] 构建LangGraph工作流
- [ ] 实现run_diagnosis对外接口
- [ ] 测试完整的诊断流程

**验证方法**：
```bash
cd test
python test_diagnosis_api.py
```

### Step 3: 启动REST API服务
- [ ] 安装FastAPI依赖：`pip install fastapi uvicorn`
- [ ] 新建`Server/api_server.py`
- [ ] 实现诊断接口和记录保存功能
- [ ] 启动API服务并测试

**验证方法**：
```bash
cd Server
python api_server.py  # 启动API服务

# 在另一个终端测试
curl -X POST http://localhost:8000/api/diagnose \
  -H "Content-Type: application/json" \
  -d '{"user_input": "502错误", "container_name": "ruoyi-app"}'

# 查看API文档
# 浏览器访问: http://localhost:8000/docs
```

### Step 4: 创建测试用例
- [ ] 编写`test/test_diagnosis_api.py`
- [ ] 运行测试并验证输出格式
- [ ] 确保诊断记录正确保存到JSON文件
- [ ] 验证API接口的可用性

**验证方法**：
```bash
cd test
python test_diagnosis_api.py
ls ../diagnosis_records/  # 检查是否生成了JSON文件
```

### Step 5: 端到端测试
- [ ] 启动所有MCP服务
- [ ] 启动REST API
- [ ] 执行完整诊断流程
- [ ] 验证诊断记录的完整性

---

## 四、关键技术要点

### 4.1 SSH连接管理
- 使用paramiko库建立SSH连接
- 从`.env`读取配置，避免硬编码
- 实现连接池或复用机制，避免频繁建立连接

### 4.2 日志级别过滤
- 使用正则表达式匹配日志级别关键字
- 支持多种日志格式（如`[ERROR]`, `ERROR:`, `level=error`等）
- 提供灵活的过滤策略配置

### 4.3 两阶段追溯算法
```
阶段1：快速扫描（过去2小时）
  ↓ 识别异常时间点 T1, T2, T3
阶段2：深入分析（每个Ti前后30分钟）
  ↓ 读取ERROR/WARN日志
  ↓ 结合SSH指标（内存、CPU）
  ↓ LLM综合分析
```

### 4.4 诊断记录Schema
```json
{
  "timestamp": "2026-05-08T10:30:00",
  "user_input": "502 Bad Gateway错误",
  "result": {
    "status": "success",
    "diagnosis": {...},
    "iteration_count": 2,
    "retrieval_quality": "good"
  },
  "metadata": {
    "anomaly_timestamps": ["2026-05-08T10:15:00"],
    "commands_executed": ["docker ps", "free -h", "top"]
  }
}
```

---

## 五、潜在问题与解决方案

### 问题1：SSH连接超时
**症状**：paramiko连接远程服务器超时  
**解决**：
- 增加timeout参数（已有30秒）
- 检查防火墙和安全组规则
- 验证私钥权限（chmod 600 aiOps.pem）

### 问题2：日志量过大导致token超限
**症状**：LLM返回错误或截断  
**解决**：
- 严格过滤只保留ERROR/WARN
- 限制每次读取的行数（--tail 200）
- 分批次处理多个异常时间点

### 问题3：REST API与现有路由冲突
**症状**：route.py原有功能受影响  
**解决**：
- 使用独立的FastAPI实例
- 确保端口不冲突（默认8000）
- 后续优化时可拆分为独立服务

### 问题4：诊断记录文件过多
**症状**：diagnosis_records目录膨胀  
**解决**：
- 定期清理旧记录（保留最近30天）
- 按日期分目录存储
- 未来可迁移到数据库

---

## 六、后续优化方向

1. **多容器关联诊断**：同时分析多个关联容器（如nginx + app + database）
2. **历史案例匹配**：将成功的诊断案例向量化，相似问题时优先参考历史方案
3. **自动化告警联动**：与Prometheus + Grafana集成，自动触发诊断
4. **诊断报告可视化**：生成HTML格式的可视化报告
5. **知识库自动沉淀**：将高置信度的诊断案例自动转化为知识条目（可选）
6. **性能优化**：缓存SSH连接、并行执行多个检查命令

---

## 七、总结

本方案采用**纯LLM驱动**的诊断模式，与现有OpsAgent完全隔离：

### 核心特点
1. ✅ **独立架构**：新建`Routing/diagnosis_agent.py`，不依赖任何现有Agent
2. ✅ **纯LLM推理**：不使用诊断树、不检索知识库，完全依靠LLM的经验判断
3. ✅ **工具增强**：通过Log-Reader MCP和ops-diagnosis MCP获取实时数据
4. ✅ **迭代追溯**：两阶段日志分析（快速扫描 + 深入分析）
5. ✅ **REST API**：独立的FastAPI服务，便于集成和扩展
6. ✅ **记录持久化**：JSON文件存储，便于后续分析和知识库构建

### 实施顺序
Step 1（重构Log-Reader MCP）→ Step 2（创建DiagnosisAgent）→ Step 3（启动REST API）→ Step 4（测试验证）

每步完成后进行验证，确保功能正常后再进入下一步。