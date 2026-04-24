# Redis 安装设计文档

## 1. 安装方案

### 1.1 安装方式
使用 Ubuntu 的 apt 包管理器安装 Redis。

### 1.2 安装步骤
```bash
# 更新包列表
sudo apt update

# 安装 Redis
sudo apt install redis-server -y

# 启动 Redis 服务
sudo systemctl start redis-server

# 设置开机自启
sudo systemctl enable redis-server
```

### 1.3 配置调整
编辑 Redis 配置文件 `/etc/redis/redis.conf`：

```conf
# 绑定本地地址（生产环境可改为特定 IP）
bind 127.0.0.1

# 设置密码（可选，增强安全性）
# requirepass yourpassword

# 设置最大内存限制（根据服务器资源调整）
maxmemory 256mb

# 内存淘汰策略
maxmemory-policy allkeys-lru

# 启用持久化（RDB）
save 900 1
save 300 10
save 60 10000

# 日志级别
loglevel notice
```

### 1.4 验证步骤
```bash
# 检查 Redis 服务状态
sudo systemctl status redis-server

# 测试连接
redis-cli ping
# 应返回: PONG

# 测试基本操作
redis-cli
> SET test "hello"
> GET test
# 应返回: "hello"
```

## 2. 部署考虑

### 2.1 内存配置
- 建议为 Redis 分配 256MB-1GB 内存（根据应用需求调整）
- 设置适当的 maxmemory 策略防止内存溢出

### 2.2 安全建议
- 生产环境建议设置密码
- 考虑绑定到特定 IP 而非 127.0.0.1
- 确保防火墙规则正确配置

### 2.3 监控
- 监控 Redis 内存使用情况
- 监控连接数
- 设置日志轮转