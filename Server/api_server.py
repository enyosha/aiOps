"""
AI运维诊断系统 REST API 服务

提供HTTP接口供外部系统（如Grafana）触发自动诊断
"""
import os
import sys
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import JSONResponse

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

# ===== 应用配置 =====

app = FastAPI(
    title="AI运维诊断系统",
    description="基于LLM的自动化运维故障诊断API",
    version="1.0.0"
)

# 诊断任务存储（内存中，生产环境应使用Redis）
diagnosis_tasks: Dict[str, Dict[str, Any]] = {}

# 诊断记录保存目录
DIAGNOSIS_RECORDS_DIR = Path(__file__).parent.parent / "diagnosis_records"
DIAGNOSIS_RECORDS_DIR.mkdir(exist_ok=True)


# ===== 数据模型 =====

class AlertEvent(BaseModel):
    """Grafana告警事件"""
    alert_name: str
    container_name: str
    alert_time: Optional[str] = None
    alert_type: Optional[str] = "container_restart"
    description: Optional[str] = ""


class DiagnosisRequest(BaseModel):
    """诊断请求"""
    alert_event: AlertEvent
    container_name: Optional[str] = None


class DiagnosisResponse(BaseModel):
    """诊断响应"""
    task_id: str
    status: str
    message: str


class DiagnosisResult(BaseModel):
    """诊断结果"""
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ===== 核心功能 =====

async def execute_diagnosis(task_id: str, alert_event: dict, container_name: str):
    """
    后台执行诊断任务
    
    Args:
        task_id: 任务ID
        alert_event: 告警事件
        container_name: 容器名称
    """
    try:
        # 更新任务状态为运行中
        diagnosis_tasks[task_id]['status'] = 'running'
        diagnosis_tasks[task_id]['started_at'] = datetime.now().isoformat()
        
        print(f"[API] 开始执行诊断任务: {task_id}")
        print(f"[API] 告警: {alert_event.get('alert_name')}")
        print(f"[API] 容器: {container_name}")
        
        # 导入DiagnosisAgent
        from Routing.diagnosis_agent import run_diagnosis
        
        # 执行诊断
        result = await run_diagnosis(
            alert_event=alert_event,
            container_name=container_name
        )
        
        # 保存诊断结果
        diagnosis_tasks[task_id]['status'] = 'completed'
        diagnosis_tasks[task_id]['result'] = result
        diagnosis_tasks[task_id]['completed_at'] = datetime.now().isoformat()
        
        # 持久化到文件
        save_diagnosis_record(task_id, alert_event, result)
        
        # 打印诊断报告摘要
        if result.get('status') == 'success' and result.get('diagnosis'):
            diagnosis_content = result['diagnosis'].get('content', '')
            print(f"\n{'='*70}")
            print(f"[API] 诊断报告摘要")
            print(f"{'='*70}")
            # 只打印前500字符作为摘要
            preview = diagnosis_content[:500] + "..." if len(diagnosis_content) > 500 else diagnosis_content
            print(preview)
            print(f"{'='*70}\n")
        
        print(f"[API] 诊断任务完成: {task_id}")
        
    except Exception as e:
        print(f"[API] 诊断任务失败: {task_id}, 错误: {str(e)}")
        diagnosis_tasks[task_id]['status'] = 'failed'
        diagnosis_tasks[task_id]['error'] = str(e)
        diagnosis_tasks[task_id]['completed_at'] = datetime.now().isoformat()


def save_diagnosis_record(task_id: str, alert_event: dict, result: dict):
    """
    保存诊断记录到JSON文件
    
    Args:
        task_id: 任务ID
        alert_event: 告警事件
        result: 诊断结果
    """
    try:
        record = {
            "task_id": task_id,
            "timestamp": datetime.now().isoformat(),
            "alert_event": alert_event,
            "diagnosis_result": result
        }
        
        # 文件名格式: task_id.json
        filename = DIAGNOSIS_RECORDS_DIR / f"{task_id}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        
        print(f"[API] 诊断记录已保存: {filename}")
        
    except Exception as e:
        print(f"[API] 保存诊断记录失败: {str(e)}")


# ===== API 端点 =====

@app.post("/api/diagnose", response_model=DiagnosisResponse)
async def trigger_diagnosis(request: DiagnosisRequest, background_tasks: BackgroundTasks):
    """
    触发诊断任务
    
    由Grafana等监控系统调用，传入告警事件信息
    """
    try:
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 确定容器名称
        container_name = request.container_name or request.alert_event.container_name
        
        # 创建任务记录
        diagnosis_tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "alert_event": request.alert_event.model_dump(),
            "container_name": container_name
        }
        
        # 在后台执行诊断
        background_tasks.add_task(
            execute_diagnosis,
            task_id,
            request.alert_event.model_dump(),
            container_name
        )
        
        return DiagnosisResponse(
            task_id=task_id,
            status="pending",
            message="诊断任务已提交，请稍后查询结果"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交诊断任务失败: {str(e)}")


@app.get("/api/diagnose/list")
async def list_diagnosis_tasks(limit: int = 10):
    """
    列出最近的诊断任务
    
    Args:
        limit: 返回数量限制
    """
    # 按创建时间排序，返回最近的任务
    sorted_tasks = sorted(
        diagnosis_tasks.values(),
        key=lambda x: x.get('created_at', ''),
        reverse=True
    )[:limit]
    
    return {
        "total": len(diagnosis_tasks),
        "tasks": sorted_tasks
    }


@app.get("/api/diagnose/{task_id}", response_model=DiagnosisResult)
async def get_diagnosis_result(task_id: str):
    """
    查询诊断任务结果
    
    Args:
        task_id: 任务ID
    """
    if task_id not in diagnosis_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = diagnosis_tasks[task_id]
    
    return DiagnosisResult(
        task_id=task_id,
        status=task['status'],
        result=task.get('result'),
        error=task.get('error')
    )


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "AI运维诊断系统",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "AI运维诊断系统 API",
        "docs": "/docs",
        "endpoints": {
            "POST /api/diagnose": "触发诊断任务",
            "GET /api/diagnose/{task_id}": "查询诊断结果",
            "GET /api/diagnose/list": "列出诊断任务",
            "GET /api/health": "健康检查"
        }
    }


# ===== 启动入口 =====

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("API_PORT", "8004"))  # 改为8004
    
    print(f"\n{'='*70}")
    print("AI运维诊断系统 REST API 服务")
    print(f"{'='*70}")
    print(f"端口: {port}")
    print(f"文档: http://localhost:{port}/docs")
    print(f"{'='*70}\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
