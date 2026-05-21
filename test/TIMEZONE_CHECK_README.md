# 时区检查工具说明

## 问题描述
前端日志显示的时间是UTC时间，没有加上+8时区（北京时间）。这通常是因为服务器或Docker容器中没有正确设置时区。

**典型症状:**
```
220.154.1.3 - - [19/May/2026:03:04:16 +0000]
```
应该是:
```
220.154.1.3 - - [19/May/2026:11:04:16 +0800]
```

## 脚本说明

### 1. check_timezone.py
**用途**: 检查本地Python环境的时区设置

**使用方法**:
```bash
python test/check_timezone.py
```

**功能**:
- 显示当前UTC时间和本地时间
- 计算与UTC的时差
- 检查TZ环境变量
- 显示Python时区信息
- 提供解决方案建议

### 2. check_server_timezone.py
**用途**: 检查远程服务器或Docker容器的时区设置

**使用方法**:
```bash
python test/check_server_timezone.py
```

**功能**:
- 支持通过SSH检查远程服务器时区
- 检查本地Docker容器时区
- 检查多个相关容器（ruoyi-app, ruoyi-nginx, ruoyi-mysql, ruoyi-redis）
- 显示系统时间、时区配置、环境变量等信息

### 3. setup_frontend_timezone.py
**用途**: 自动设置前端服务器容器时区为UTC+8

**使用方法**:
```bash
python test/setup_frontend_timezone.py
```

**功能**:
- 通过SSH连接到前端服务器 (8.146.236.55)
- 自动检测并重建ruoyi-frontend容器
- 添加 TZ=Asia/Shanghai 环境变量
- 验证时区设置是否成功

### 4. quick_setup_frontend_timezone.py
**用途**: 快速设置前端容器时区（简化版）

**使用方法**:
```bash
python test/quick_setup_frontend_timezone.py
```

**功能**:
- 更简洁的交互流程
- 自动获取容器配置并重建
- 实时验证时区设置

## 常见问题解决方案

### 1. Linux服务器设置时区
```bash
sudo timedatectl set-timezone Asia/Shanghai
```

### 2. Docker容器设置时区
在docker-compose.yml或docker run命令中添加:
```yaml
environment:
  - TZ=Asia/Shanghai
```

或者在Dockerfile中:
```dockerfile
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
```

### 3. Python应用代码中设置时区
```python
import os
import time

os.environ['TZ'] = 'Asia/Shanghai'
time.tzset()  # Linux/Mac需要
```

### 4. Nginx日志时间格式
在nginx.conf中设置:
```nginx
log_format main '$time_local ...';
# 确保使用本地时间而非UTC
```

## 诊断步骤

### 快速修复前端时区问题（推荐）

1. **运行 quick_setup_frontend_timezone.py** - 自动设置前端容器时区
   ```bash
   python test/quick_setup_frontend_timezone.py
   ```
2. **在前端页面执行一些操作**
3. **验证日志时间**: `docker logs ruoyi-frontend --tail 20`
4. **确认时间显示为北京时间 (UTC+8)**

### 详细诊断流程

1. **运行check_timezone.py** - 检查本地环境
2. **运行check_server_timezone.py** - 检查服务器和容器
3. **根据输出结果** - 确定哪个环节时区设置不正确
4. **应用相应解决方案** - 修改服务器、容器或应用配置
5. **重启服务** - 使时区设置生效
6. **验证修复** - 再次运行检查脚本确认

## 注意事项

- 修改时区后需要重启相关服务才能生效
- Docker容器需要在创建时设置时区，已运行的容器需要重建
- 确保所有相关组件（服务器、容器、应用）时区设置一致
- 前端显示时间可能还需要单独处理时区转换
