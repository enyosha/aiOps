# Redis 会话持久化测试说明

## 测试文件

本项目包含两个测试文件来验证 Redis 会话持久化功能：

### 1. test_redis_session_unit.py（单元测试）
- **特点**：使用 Mock 模拟 Redis 操作，不依赖真实 Redis 服务器
- **适用场景**：快速验证逻辑正确性，适合 CI/CD
- **执行方式**：
  ```bash
  python test/test_redis_session_unit.py
  ```

### 2. test_redis_session_integration.py（集成测试）
- **特点**：使用真实 Redis 服务器，验证完整的持久化流程
- **适用场景**：验证实际环境中的功能完整性
- **前置条件**：需要 Redis 服务器正在运行

## 运行集成测试的前置条件

### 选项 1：本地安装 Redis（推荐用于开发环境）

#### Windows 系统
1. 下载 Redis for Windows：https://github.com/microsoftarchive/redis/releases
2. 解压并运行 `redis-server.exe`
3. 确认 Redis 在 `localhost:6379` 运行

#### 使用 Docker（推荐）
```bash
docker run -d --name redis-test -p 6379:6379 redis:latest
```

#### Linux/Mac
```bash
# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis-server

# macOS (使用 Homebrew)
brew install redis
brew services start redis
```

### 选项 2：使用远程 Redis（通过 SSH 隧道）

如果 Redis 部署在远程服务器上，需要先建立 SSH 隧道：

1. 确保 `.env` 文件中配置了正确的 SSH 信息：
   ```env
   SSH_HOST=your_server_ip
   SSH_PORT=22
   SSH_USER=root
   SSH_KEY_PATH=./aiOps.pem
   SSH_REMOTE_REDIS_PORT=6379
   SSH_LOCAL_REDIS_PORT=6379
   ```

2. 手动建立 SSH 隧道：
   ```bash
   ssh -i ./aiOps.pem -L 6379:localhost:6379 root@your_server_ip
   ```

3. 或者让程序自动建立隧道（测试脚本会自动调用 `initialize_redis_and_tunnel()`）

### 注意事项

#### Paramiko DSSKey 问题
如果遇到 `module 'paramiko' has no attribute 'DSSKey'` 错误，这是因为较新版本的 paramiko 移除了 DSSKey 支持。解决方法：

1. **降级 paramiko**（临时方案）：
   ```bash
   pip install paramiko==3.4.0
   ```

2. **更新 ssh_tunnel_manager.py**（推荐方案）：
   修改 [Routing/ssh_tunnel_manager.py](file://c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/Routing/ssh_tunnel_manager.py) 中的密钥加载逻辑，移除对 DSSKey 的依赖。

## 测试覆盖范围

### 单元测试覆盖
- ✓ 启动时无历史会话的处理
- ✓ 启动时有历史会话的选择
- ✓ 创建新会话并保存到 Redis（Mock）
- ✓ 添加消息并同步到 Redis（Mock）
- ✓ 退出时资源清理

### 集成测试覆盖
- ✓ 完整会话生命周期（创建、保存、加载）
- ✓ 会话恢复功能（模拟程序重启）
- ✓ 多会话并发管理
- ✓ 会话过期清理机制

## 常见问题

### Q1: 为什么集成测试失败？
**A**: 最常见的原因是 Redis 服务器未运行。请检查：
- Redis 是否在 `localhost:6379` 运行
- 防火墙是否阻止了连接
- 如果使用远程 Redis，SSH 隧道是否建立成功

### Q2: 如何验证 Redis 是否正常运行？
**A**: 使用 redis-cli 测试：
```bash
redis-cli ping
# 应该返回 PONG
```

或者使用 Python 测试：
```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
print(r.ping())  # 应该返回 True
```

### Q3: 测试会污染我的 Redis 数据吗？
**A**: 不会。测试会在结束后清理创建的测试数据。但建议在测试环境中运行，避免与生产数据混用。

### Q4: 可以只运行部分测试吗？
**A**: 可以。编辑测试文件，注释掉不需要运行的测试函数，或者单独调用某个测试函数：
```python
if __name__ == "__main__":
    asyncio.run(test_full_lifecycle())  # 只运行这一个测试
```

## 预期输出示例

### 单元测试（成功）
```
======================================================================
✅ 所有单元测试通过！
======================================================================

验证要点：
  ✓ 启动时正确从 Redis 加载会话列表
  ✓ 用户选择会话后 session_id 正确设置
  ✓ 创建新会话时生成唯一 UUID
  ✓ 会话元数据正确保存到 Redis（Mock）
  ✓ 消息添加后实时同步到 Redis（Mock）
  ✓ 退出时资源正确清理
  ✓ Redis 连接正确关闭
  ✓ SSH 隧道正确关闭
```

### 集成测试（成功）
```
======================================================================
✅ 所有集成测试通过！
======================================================================

验证要点：
  ✓ 完整会话生命周期正常工作
  ✓ 会话元数据正确保存到 Redis
  ✓ 消息添加后实时同步到 Redis
  ✓ 消息序列化和反序列化正确
  ✓ 会话恢复功能正常工作
  ✓ 多会话并发管理正常
  ✓ 会话过期清理机制正常
  ✓ 退出时资源正确清理
  ✓ Redis 连接正确关闭
```

## 下一步

测试通过后，您可以：
1. 在实际应用中使用 Client_test.py 进行对话
2. 验证会话在程序重启后能否正确恢复
3. 监控 Redis 中的会话数据状态

如需进一步帮助，请查看：
- [Client/Client_test.py](file://c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/Client/Client_test.py) - 客户端实现
- [Routing/conversation_manager.py](file://c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/Routing/conversation_manager.py) - 会话管理器
- [Routing/redis_session_store.py](file://c:/Users/ensha/Desktop/AiOps/GitHub/Aiops/Routing/redis_session_store.py) - Redis 存储实现
