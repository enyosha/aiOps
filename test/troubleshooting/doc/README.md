# 运维故障测试场景

本目录包含用于测试AI运维诊断Agent的故障场景构建和恢复脚本。

## 📁 目录结构

```
troubleshooting/
├── generateCase.py              # 统一构建所有故障环境
├── resumeCase.py                # 统一恢复所有故障环境
├── run_test.py                  # 统一测试脚本(含诊断Agent调用和报告生成)
├── tools/                       # 调试工具目录
│   └── debug_container_paths.py # 容器路径诊断工具
├── logs/                        # 测试结果日志目录
├── README.md                    # 本说明文档
└── PLAN.md                      # 详细实施计划
```

## 🎯 支持的故障场景

| Case编号 | 故障类型 | 影响层级 | 状态 |
|---------|---------|---------|------|
| Case01 | Tomcat线程池耗尽 | 前端 → 应用 | ✅ 已实现 |
| Case02 | 静态资源加载失败404 | 前端展示层 | ✅ 已实现 |
| Case03 | MySQL连接池耗尽 | 后端 → 前端 | ✅ 已实现 |
| Case04 | JVM堆内存溢出 | 应用 → 前端 | ✅ 已实现 |
| Case05 | MySQL慢查询CPU飙升 | MySQL → 后端 → 前端 | ✅ 已实现 |

## 🚀 快速开始

### 方式一: 使用统一测试脚本 (推荐)

**运行完整测试流程**:
```bash
# 交互式选择Case和模式
python test/troubleshooting/run_test.py

# 命令行指定Case和模式
python test/troubleshooting/run_test.py --case 1 --mode 1  # 全流程
python test/troubleshooting/run_test.py --case 3 --mode 2  # 仅测试
python test/troubleshooting/run_test.py --case 4 --mode 3  # 仅恢复
```

**执行模式说明**:
- **模式1 (全流程)**: Generate → Test → Resume
  - 自动构建故障环境
  - 执行诊断测试
  - 自动恢复环境
  - **在Generate完成后会询问是否继续**,按y继续/n退出

- **模式2 (仅测试)**: Test only
  - 跳过Generate阶段
  - 直接执行诊断测试
  - 跳过Resume阶段
  - 适用于已手动构建故障环境的场景

- **模式3 (仅恢复)**: Resume only
  - 跳过Generate和Test阶段
  - 直接恢复环境
  - 适用于中断后需要单独恢复的场景

该脚本会自动:
1. 交互式选择要测试的Case
2. 构建故障环境
3. 调用DiagnosisAgent进行诊断
4. **实时打印诊断过程和结果到控制台和日志文件**
5. 保存完整日志到 `logs/casexx_YYYYMMDD_HHMMSS.txt`
6. 自动恢复环境
7. 生成评估报告(准确性、完整性、可操作性、效率)

**日志输出说明**:
- ✅ 控制台输出: 实时显示诊断过程,包括每个迭代步骤
- ✅ 日志文件: 完整记录所有输出,与控制台内容完全一致
- ✅ 双路输出: 使用 DualOutput 机制确保两者同步

### 方式二: 手动分步执行

### 1. 构建故障环境

**方式一: 命令行参数**
```bash
# 构建 Case01 故障环境
python test/troubleshooting/generateCase.py --case 1
```

**方式二: 交互式选择**
```bash
python test/troubleshooting/generateCase.py
# 然后根据提示选择case编号
```

### 2. 运行诊断测试

故障环境构建完成后,可以运行诊断Agent进行测试:

```python
from Routing.diagnosis_agent import run_diagnosis
import asyncio

# 构造告警事件
alert_event = {
    "alert_name": "后端服务响应超时",
    "alert_type": "service_timeout",
    "alert_time": "2026-05-08T14:30:00",
    "description": "前端请求超时,部分接口返回500错误"
}

# 运行诊断
result = asyncio.run(run_diagnosis(alert_event, "ruoyi-app"))
print(result)
```

### 3. 恢复环境

测试完成后,**务必恢复环境**:

**方式一: 命令行参数**
```bash
python test/troubleshooting/resumeCase.py --case 1
```

**方式二: 交互式选择**
```bash
python test/troubleshooting/resumeCase.py
```

## 📋 Case01 详细说明

### 故障原理

RuoYi应用使用Druid连接池管理MySQL数据库连接:
- **正常配置**: maxActive=20, minIdle=10, initialSize=5
- **故障配置**: maxActive=2, minIdle=1, initialSize=1

当并发请求数超过2时,连接池迅速耗尽,新请求无法获取数据库连接,导致:
- 应用日志出现 `GetConnectionTimeoutException`
- 前端请求超时或返回500错误
- 服务响应时间显著增加

### 构建过程

1. **备份配置**: 将原始 `application-druid.yml` 备份为 `.bak`
2. **修改配置**: 将maxActive改为2,minIdle改为1
3. **重启容器**: 使新配置生效
4. **触发故障**: 发送10个并发请求耗尽连接池
5. **验证现象**: 检查日志中是否出现连接池错误

### 恢复过程

1. **恢复配置**: 将备份的 `.bak` 文件还原
2. **重启容器**: 使正常配置生效
3. **验证恢复**: 检查HTTP状态码和连接池配置
4. **清理备份**: 删除临时备份文件

## ⚠️ 注意事项

1. **测试环境**: 建议在测试环境执行,避免影响生产服务
2. **权限要求**: 确保SSH密钥有足够权限执行Docker命令
3. **等待时间**: 容器重启需要约60秒,请耐心等待
4. **及时恢复**: 测试完成后立即恢复环境,避免影响其他用户
5. **日志查看**: 可通过 `docker logs ruoyi-app --tail 100` 查看详细日志

## 🔧 故障排查

### 问题1: SSH连接失败

**症状**: `❌ SSH命令执行失败: Connection refused`

**解决**:
- 检查 `.env` 文件中的SSH配置是否正确
- 确认SSH密钥文件路径和权限
- 测试手动SSH连接: `ssh -i aiOps.pem root@8.130.131.36`

### 问题2: 配置文件路径错误

**症状**: `⚠️ 配置文件路径可能不同,尝试查找...`

**解决**:
- 使用容器路径诊断工具快速定位:
  ```bash
  python test/troubleshooting/tools/debug_container_paths.py --section config
  ```
- 或手动进入容器确认配置文件位置:
  ```bash
  docker exec -it ruoyi-app find / -name 'application-druid.yml'
  ```
- 修改 `generateCase.py` 中的 `config_file` 变量

### 问题3: 容器启动失败

**症状**: 重启后容器无法正常启动

**解决**:
- 查看容器日志: `docker logs ruoyi-app`
- 检查配置文件语法是否正确
- 必要时手动恢复配置并重启

## 📊 评估指标

测试诊断Agent时,关注以下指标:

- **准确性**: 是否正确定位到连接池问题
- **完整性**: 是否覆盖了日志检查和配置分析
- **可操作性**: 给出的解决方案是否具体可执行
- **效率**: 诊断过程的迭代次数和工具调用次数

## 📝 下一步

- [x] 实现 Case01: Tomcat线程池耗尽
- [x] 实现 Case02: 静态资源加载失败404
- [x] 实现 Case03: MySQL连接池耗尽
- [x] 实现 Case04: JVM堆内存溢出
- [x] 实现 Case05: MySQL慢查询CPU飙升
- [x] 创建 run_test.py 统一测试脚本
- [ ] 根据测试结果优化DiagnosisAgent的诊断逻辑
- [ ] 补充缺失的知识条目(如Tomcat调优、JVM参数优化等)
- [ ] 添加更多故障场景(磁盘空间不足、SSL证书过期等)

## 📞 支持

如有问题,请查看 [PLAN.md](PLAN.md) 获取详细实施计划。
