# 调试工具集

本目录包含用于开发和调试故障测试脚本的辅助工具。

## 🛠️ 可用工具

### debug_container_paths.py - 容器路径诊断工具

**用途**: 快速探查容器内部的文件路径结构,帮助定位配置文件、日志文件、静态资源等关键路径。

**使用场景**:
- 编写 `generateCase.py` / `resumeCase.py` 时确认文件路径
- 故障构建失败时排查路径问题
- 验证容器内目录结构是否符合预期

**使用方法**:

```bash
# 检查默认容器 ruoyi-app (全部检查)
python test/troubleshooting/tools/debug_container_paths.py

# 检查指定容器
python test/troubleshooting/tools/debug_container_paths.py --container mysql

# 仅检查配置文件
python test/troubleshooting/tools/debug_container_paths.py -c ruoyi-app --section config

# 仅检查日志文件
python test/troubleshooting/tools/debug_container_paths.py -s logs

# 查看帮助
python test/troubleshooting/tools/debug_container_paths.py --help
```

**检查模块**:
- `config` - 检查配置文件 (application.yml 等)
- `directory` - 检查目录结构 (/app, /app/ruoyi-admin 等)
- `logs` - 检查日志文件和目录
- `static` - 检查静态资源 (CSS/JS 文件)
- `all` - 检查所有模块 (默认)

**输出示例**:
```
================================================================================
【检查配置文件】
================================================================================

1️⃣  查找 application.yml 文件:
   📄 /app/config/application.yml
   📄 /app/ruoyi-admin/src/main/resources/application.yml

2️⃣  查找所有 application*.yml 文件:
   📄 /app/config/application.yml
   📄 /app/config/application-druid.yml
```

## 💡 最佳实践

1. **开发新 Case 时**: 先用此工具探查容器结构,再编写 generate/resume 脚本
2. **路径不确定时**: 优先使用此工具确认,避免硬编码错误路径
3. **多容器环境**: 通过 `--container` 参数切换不同容器进行检查

## 🔧 扩展工具

如需添加新的调试工具,请遵循以下规范:
- 文件名以 `debug_` 开头
- 支持命令行参数配置
- 采用模块化设计,功能拆分为独立函数
- 在本文档中添加使用说明
