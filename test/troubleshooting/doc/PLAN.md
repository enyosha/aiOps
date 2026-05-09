# AI运维日志分析测试场景设计

## 目标
为当前系统(Docker + ruoyi-app + MySQL)生成至少5种故障场景,覆盖前端、后端、数据库三层架构,测试AI运维诊断Agent的通用性。

## 系统现状分析
基于代码审查:
- **宿主机**: 8.130.131.36 (SSH访问)
- **Docker容器**: ruoyi-app (默认监控容器)
- **可用工具**: 
  - `check_memory_usage` - 检查内存 (`free -h`)
  - `check_cpu_usage` - 检查CPU (`top -bn1`)
  - `read_docker_logs` - 读取容器日志
  - `get_container_status` - 检查容器状态
  - `fetch_docker_logs` - 按时间范围获取日志
  - `search_ops_knowledge` - 知识库检索
- **现有知识条目**: OOM Killer诊断、HTTP 502诊断

## 文件组织结构

所有生成的脚本和测试文件将存放在 `test/troubleshooting/` 目录下,按以下结构组织:

```
test/troubleshooting/
├── generateCase.py             # 统一构建所有故障环境(支持选择case编号)
├── resumeCase.py               # 统一恢复所有故障环境(支持选择case编号)
├── logs/                       # 测试结果日志目录
│   ├── case01_20260508_143022.txt
│   ├── case02_20260508_150530.txt
│   └── ...
├── run_test.py                 # 统一测试脚本,通过问答形式运行指定case
└── PLAN.md                     # 本计划文档
```

**Case分布**:
- **前端/接入层 (2个)**: Case01(Tomcat线程池), Case02(静态资源404)
- **后端/数据层 (3个)**: Case03(MySQL连接池), Case04(JVM OOM), Case05(MySQL慢查询)

测试结果输出:
- **Console**: 实时打印诊断过程和结果
- **文件**: `test/troubleshooting/logs/casexx_YYYYMMDD_HHMMSS.txt` (例如: `test/troubleshooting/logs/case01_20260508_143022.txt`)

---

## 设计的5种故障场景

### 前端/接入层 (2个Case)

---

### Case01: Tomcat线程池耗尽导致请求超时
**故障类型**: 并发处理能力不足  
**影响层级**: 前端 → 应用  
**症状表现**:
- 前端请求响应时间显著增加(>10秒)
- 高并发时部分请求返回504 Gateway Timeout
- Tomcat日志显示 "Maximum number of threads exceeded"
- 应用仍在运行,但无法及时处理新请求

**generate_case01.py功能**:
1. 通过SSH连接到宿主机
2. 修改application.yml中的Tomcat线程池配置
3. 将`server.tomcat.threads.max`从800改为5
4. 重启容器使配置生效
5. 发送大量并发请求触发线程池耗尽
6. 验证请求超时现象

**resume_case01.py功能**:
1. 恢复Tomcat线程池配置到正常值(max=800)
2. 重启容器
3. 验证服务恢复正常响应速度

**诊断关键点**:
- 检查应用日志中的线程池相关警告
- 监控Tomcat线程使用情况
- 分析并发请求数量和响应时间
- 区分是线程池问题还是数据库连接池问题

**预期诊断路径**:
1. LLM识别到"请求超时"和"高并发"关键词
2. 调用 `read_docker_logs` 查看应用日志
3. 发现Tomcat线程池耗尽警告
4. 检查当前Tomcat配置
5. 建议调整线程池大小或优化请求处理逻辑

---

### Case02: 静态资源加载失败(404/403错误)
**故障类型**: 资源配置或权限问题  
**影响层级**: 前端展示层  
**症状表现**:
- 前端页面样式丢失(CSS加载失败)
- JavaScript文件无法加载,交互功能失效
- 浏览器控制台显示404 Not Found或403 Forbidden
- 页面布局错乱或部分功能不可用

**generate_case02.py功能**:
1. 通过SSH连接到宿主机
2. 修改静态资源配置或删除关键静态文件
3. 例如: 删除 `/app/static/css/` 目录或修改ResourcesConfig
4. 重启容器或直接验证效果
5. 访问前端页面验证资源加载失败

**resume_case02.py功能**:
1. 恢复被删除的静态文件或配置
2. 重启容器(如果需要)
3. 验证前端页面正常加载所有资源

**诊断关键点**:
- 检查浏览器控制台的404/403错误
- 查看Spring Boot静态资源配置
- 确认文件路径和权限是否正确
- 区分是文件缺失还是权限问题

**预期诊断路径**:
1. LLM识别到"404"、"静态资源"、"CSS/JS加载失败"
2. 建议检查浏览器控制台错误信息
3. 验证静态文件是否存在于正确路径
4. 检查Spring Boot资源配置类(ResourcesConfig)
5. 建议恢复文件或修正配置

---

### 后端/数据层 (3个Case)

---

### Case03: MySQL连接池耗尽导致后端服务不可用
**故障类型**: 数据库连接问题  
**影响层级**: 后端 → 前端  
**症状表现**:
- 前端请求超时或返回500错误
- 后端日志出现 `Cannot get connection from pool` 或 `Connection pool exhausted`
- MySQL进程正常但连接数达到上限
- 应用响应时间显著增加

**generate_case01.py功能**:
1. 通过SSH连接到宿主机
2. 修改ruoyi-app容器的数据库连接池配置,将最大连接数设置为极小值(如2)
3. 或者模拟高并发请求,快速耗尽连接池
4. 验证故障现象:应用日志出现连接池错误

**resume_case01.py功能**:
1. 恢复连接池配置到正常值
2. 重启ruoyi-app容器
3. 验证服务恢复正常

**诊断关键点**:
- 检查ruoyi-app容器日志中的数据库连接异常
- 检查MySQL容器的连接数 (`SHOW PROCESSLIST`)
- 验证是否是连接泄漏还是并发过高
- 检查是否有慢查询占用连接

**预期诊断路径**:
1. LLM识别到"连接池"相关关键词
2. 调用 `read_docker_logs` 查看应用日志
3. 发现连接池耗尽错误
4. 建议重启应用或优化连接池配置

---

### Case05: MySQL慢查询导致CPU飙升和应用超时
**故障类型**: 性能问题  
**影响层级**: MySQL → 后端 → 前端  
**症状表现**:
- 前端页面加载缓慢或超时(>10秒)
- 后端接口响应时间长,部分请求失败
- MySQL CPU使用率持续>90%
- 慢查询日志中出现执行时间>5秒的SQL

**generate_case05.py功能**:
1. 通过SSH连接到MySQL容器
2. 创建一个大表(10万+行)且无索引
3. 执行一个复杂的慢查询SQL(如全表扫描+多表JOIN)
4. 持续运行该查询以占用CPU资源
5. 验证CPU使用率>90%和查询响应时间

**resume_case05.py功能**:
1. 终止慢查询进程
2. 删除测试表或添加适当索引
3. 验证CPU使用率恢复正常
4. 清理测试数据

**诊断关键点**:
- 通过 `check_cpu_usage` 发现CPU异常
- 识别出是mysqld进程占用CPU
- 检查MySQL慢查询日志 (`/var/log/mysql/slow.log`)
- 分析具体慢查询SQL语句和执行计划(EXPLAIN)
- 确认是否缺少索引或查询条件不当

**预期诊断路径**:
1. LLM检测到CPU高负载
2. 调用 `check_cpu_usage` 确认CPU使用情况
3. 识别出是MySQL进程占用CPU
4. 建议查看慢查询日志并优化SQL
5. 给出添加索引或重写SQL的建议

---

### Case04: Docker容器内存泄漏导致频繁OOM重启
**故障类型**: 资源耗尽  
**影响层级**: 容器 → 应用 → 前端  
**症状表现**:
- ruoyi-app容器频繁重启(RestartCount持续增长)
- 前端间歇性返回502 Bad Gateway
- dmesg日志显示 `Out of memory: Killed process java`
- 容器启动后内存持续增长直至被杀死

**generate_case03.py功能**:
1. 通过SSH执行命令,限制ruoyi-app容器的内存上限(如--memory=256m)
2. 或者注入内存泄漏代码,使容器内存持续增长
3. 触发OOM Killer杀死进程
4. 验证容器频繁重启

**resume_case03.py功能**:
1. 移除内存限制或修复内存泄漏
2. 重启容器并设置合理的内存限制
3. 验证容器稳定运行

**诊断关键点**:
- 通过 `get_container_status` 检查重启次数
- 调用 `check_memory_usage` 查看系统内存
- 读取dmesg日志确认OOM Killer触发
- 分析应用是否存在内存泄漏(如未关闭的资源)

**预期诊断路径**:
1. LLM识别到"频繁重启"和"502"
2. 调用 `get_container_status` 确认重启情况
3. 调用 `check_memory_usage` 检查内存
4. 匹配现有知识条目 `oom_001`
5. 给出立即释放内存和长期优化建议

---

### Case04: JVM堆内存溢出导致应用崩溃
**故障类型**: 内存问题(JVM层面)  
**影响层级**: 应用 → 前端  
**症状表现**:
- 应用突然崩溃,容器仍在运行但无法提供服务
- 前端请求返回502 Bad Gateway或连接超时
- 应用日志出现 `java.lang.OutOfMemoryError: Java heap space`
- JVM Heap Dump文件生成(如果配置了-XX:+HeapDumpOnOutOfMemoryError)
- 与Case03的区别: Case03是Linux内核OOM Killer杀死整个容器,Case04是JVM内部堆内存溢出

**generate_case04.py功能**:
1. 通过SSH连接到宿主机
2. 修改Dockerfile或docker-compose中的JVM参数,将堆内存限制为极小值(如-Xms64m -Xmx64m)
3. 重启容器使新JVM参数生效
4. 触发大对象创建或大量数据查询以快速耗尽堆内存
5. 验证应用抛出OutOfMemoryError并崩溃

**resume_case04.py功能**:
1. 恢复JVM参数到正常值(-Xms256m -Xmx512m)
2. 重启容器
3. 清理可能生成的Heap Dump文件
4. 验证应用恢复正常

**诊断关键点**:
- 检查容器状态: `docker ps` (容器应该还在运行)
- 检查应用日志: `docker logs ruoyi-app --tail 100`
- 查找OutOfMemoryError关键词
- 检查是否生成了Heap Dump文件
- 区分JVM OOM和Linux OOM Killer

**预期诊断路径**:
1. LLM识别到"OutOfMemoryError"或"Java heap space"
2. 调用 `read_docker_logs` 查看应用日志
3. 发现JVM堆内存溢出错误
4. 检查当前JVM配置和容器资源限制
5. 建议调整JVM堆内存参数或优化代码

---

### Case05: MySQL主从复制延迟导致数据不一致
**故障类型**: 数据同步问题  
**影响层级**: MySQL → 后端 → 前端  
**症状表现**:
- 前端显示的数据与实际操作不一致
- 写入操作成功但读取不到最新数据
- MySQL从库Seconds_Behind_Master值持续增长
- 后端日志出现数据校验失败或业务逻辑异常

**generate_case05.py功能**:
1. 在主库执行大批量INSERT/UPDATE操作
2. 或者在从库故意制造锁表,阻塞复制线程
3. 验证Seconds_Behind_Master值持续增长
4. 验证读写分离场景下数据不一致

**resume_case05.py功能**:
1. 停止大批量写入或解除从库锁表
2. 等待主从同步完成
3. 验证Seconds_Behind_Master回归0

**诊断关键点**:
- 检查MySQL主从状态 (`SHOW SLAVE STATUS`)
- 查看Seconds_Behind_Master的值
- 分析主库是否有大批量写入操作
- 检查从库是否有锁表或慢查询阻塞复制

**预期诊断路径**:
1. LLM识别到"数据不一致"或"读写分离"问题
2. 建议检查MySQL主从复制状态
3. 发现复制延迟过大
4. 分析延迟原因(网络、锁、慢查询等)
5. 给出优化复制或临时切换到主库读取的建议

---

## 实施步骤

### 第一步: 创建 generateCase.py 和 resumeCase.py

这两个文件将包含所有5个case的构建和恢复逻辑,通过参数选择执行哪个case。

#### generateCase.py 功能设计

**使用方式**:
```bash
# 构建 Case01 故障环境
python test/troubleshooting/generateCase.py --case 1

# 构建 Case02 故障环境
python test/troubleshooting/generateCase.py --case 2

# 或者交互式选择
python test/troubleshooting/generateCase.py
```

**代码结构**:
```python
import sys
import argparse
import paramiko
import time
from Server.ops_diagnosis_server import ssh_config

def execute_ssh_command(cmd):
    """执行SSH命令"""
    # ... SSH连接和执行逻辑 ...

def generate_case01():
    """Case01: MySQL连接池耗尽"""
    print("【Case01】开始构建MySQL连接池耗尽故障...")
    # 具体实现...

def generate_case02():
    """Case02: MySQL慢查询导致CPU飙升"""
    print("【Case02】开始构建MySQL慢查询故障...")
    # 具体实现...

def generate_case03():
    """Case03: Docker容器OOM重启"""
    print("【Case03】开始构建OOM重启故障...")
    # 具体实现...

def generate_case04():
    """Case04: JVM堆内存溢出导致应用崩溃"""
    print("【Case04】开始构建JVM堆内存溢出故障...")
    # 具体实现...

def generate_case05():
    """Case05: MySQL主从复制延迟"""
    print("【Case05】开始构建主从复制延迟故障...")
    # 具体实现...

def main():
    parser = argparse.ArgumentParser(description='构建故障测试环境')
    parser.add_argument('--case', type=int, choices=[1,2,3,4,5], 
                       help='选择要构建的case编号(1-5)')
    args = parser.parse_args()
    
    if not args.case:
        # 交互式选择
        print("请选择要构建的故障场景:")
        print("1. MySQL连接池耗尽")
        print("2. MySQL慢查询导致CPU飙升")
        print("3. Docker容器OOM重启")
        print("4. Nginx配置错误导致502")
        print("5. MySQL主从复制延迟")
        args.case = int(input("请输入case编号(1-5): "))
    
    # 根据选择调用对应函数
    case_functions = {
        1: generate_case01,
        2: generate_case02,
        3: generate_case03,
        4: generate_case04,
        5: generate_case05
    }
    
    if args.case in case_functions:
        case_functions[args.case]()
    else:
        print(f"无效的case编号: {args.case}")

if __name__ == "__main__":
    main()
```

#### resumeCase.py 功能设计

**使用方式**:
```bash
# 恢复 Case01 环境
python test/troubleshooting/resumeCase.py --case 1

# 或者交互式选择
python test/troubleshooting/resumeCase.py
```

**代码结构**: 与generateCase.py类似,包含resume_case01()到resume_case05()函数

---

### 第二步: 创建统一测试脚本 run_test.py

**功能设计**:
1. **交互式选择**: 用户选择要测试的case编号(1-5)
2. **自动构建故障**: 调用对应的 `generate_casexx.py`
3. **触发诊断**: 
   - 构造Grafana告警事件(模拟真实告警)
   - 调用 `DiagnosisAgent.run_diagnosis()` 进行自动诊断
4. **收集结果**:
   - 打印诊断过程到Console
   - 保存完整日志到 `test/troubleshooting/logs/casexx_YYYYMMDD_HHMMSS.txt`
5. **自动恢复**: 调用对应的 `resume_casexx.py` 恢复环境
6. **评估报告**: 对比预期诊断路径和实际诊断结果,给出评分

**测试流程示例**:
```python
# 用户输入: 选择测试 case01
# 系统执行:
1. 运行 test/troubleshooting/generateCase.py --case 1
2. 等待30秒让故障现象稳定
3. 构造告警事件:
   alert_event = {
       "alert_name": "MySQL连接池耗尽",
       "alert_type": "database_connection_pool_exhausted",
       "alert_time": datetime.now().isoformat(),
       "description": "前端请求超时,后端日志显示Cannot get connection from pool"
   }
4. 调用 diagnosis_agent.run_diagnosis(alert_event, "ruoyi-app")
5. 记录诊断过程和结果
6. 运行 test/troubleshooting/resumeCase.py --case 1
7. 生成测试报告并保存到 test/troubleshooting/logs/case01_20260508_143022.txt
```

**输出文件格式**:
```
=== Case01 测试报告 ===
测试时间: 2026-05-08 14:30:22
故障类型: MySQL连接池耗尽

【诊断过程】
迭代1: 分析当前状态...
  → 决定行动: check_memory
迭代2: 检查内存使用情况...
  → 内存可用: 1.2Gi
迭代3: 读取容器日志...
  → 发现错误: Cannot get connection from pool
...

【诊断结果】
根因: MySQL连接池配置过小,当前最大连接数为2,无法支撑正常业务请求
建议:
1. 立即执行: 修改application.yml中的spring.datasource.hikari.maximum-pool-size为20
2. 长期优化: 监控连接池使用率,设置动态扩容策略

【评估】
准确性: ✓ 正确定位到连接池问题
完整性: ✓ 覆盖了日志检查和配置分析
可操作性: ✓ 给出了具体的配置修改命令
效率: 迭代3次,工具调用4次

总体评分: 9/10
```

---

## 技术实现要点

### SSH命令执行封装
所有generate/resume脚本需要通过SSH远程执行命令,复用现有的SSH配置:
```python
from Server.ops_diagnosis_server import ssh_config
import paramiko

def execute_ssh_command(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=ssh_config["host"],
        port=ssh_config["port"],
        username=ssh_config["username"],
        key_filename=ssh_config["key_file"],
        timeout=30
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    output = stdout.read().decode('utf-8')
    error = stderr.read().decode('utf-8')
    ssh.close()
    return output, error
```

### 日志记录和文件输出
```python
import logging
from datetime import datetime

def setup_logger(case_id):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 日志文件相对于 troubleshooting 目录
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"case{case_id}_{timestamp}.txt")
    
    logger = logging.getLogger(f"case{case_id}")
    logger.setLevel(logging.INFO)
    
    # 文件handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger, log_file
```

### 诊断Agent调用
```python
from Routing.diagnosis_agent import run_diagnosis

async def test_diagnosis(alert_event, container_name="ruoyi-app"):
    result = await run_diagnosis(alert_event, container_name)
    return result
```

---

## 注意事项

1. **安全性**: generate脚本可能影响生产环境,建议在测试环境执行
2. **幂等性**: resume脚本必须能多次执行,确保环境可恢复
3. **超时控制**: 每个步骤设置合理超时,避免脚本卡死
4. **权限验证**: 确保SSH密钥有足够权限执行Docker和MySQL命令
5. **日志清理**: 测试完成后清理临时日志和测试数据

---

## 下一步行动
1. 创建 `test/troubleshooting/logs/` 目录 ✅ 已完成
2. 实现 Case03 (MySQL连接池耗尽) - generateCase.py & resumeCase.py ✅ 已完成
3. 实现 Case04 (JVM堆内存溢出) - generateCase.py & resumeCase.py ✅ 已完成
4. 实现 Case01 (Tomcat线程池耗尽) - 前端层第1个场景
5. 实现 Case02 (静态资源404) - 前端层第2个场景
6. 实现 Case05 (MySQL慢查询CPU飙升) - 后端层第3个场景
7. 验证所有5个Cases的generate/resume流程
8. 实现 `run_test.py` 测试脚本,集成诊断Agent调用和报告生成
