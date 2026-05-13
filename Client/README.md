# Client 启动说明

## 快速启动

### Windows (批处理)
```bash
run_client.bat
```

### Windows (PowerShell)
```powershell
.\run_client.ps1
```

### 直接运行
```bash
python Client_test.py
```

## 关于 CryptographyDeprecationWarning 警告

如果你看到类似以下的警告：
```
CryptographyDeprecationWarning: TripleDES has been moved to cryptography.hazmat.decrepit.ciphers.algorithms.TripleDES
```

**这是正常现象，可以安全忽略。**

### 原因
- 这是 `paramiko` 库和 `cryptography` 库之间的兼容性问题
- `paramiko` 使用了已弃用的 TripleDES 算法导入路径
- 不影响功能，只是提示信息

### 解决方案
使用提供的启动脚本会自动屏蔽这些警告：
- `run_client.bat` (Windows 批处理)
- `run_client.ps1` (PowerShell)

### 长期解决
等待 `paramiko` 库更新到修复此问题的版本。

## 功能说明

Client_test.py 提供以下功能：
- 💬 循环对话模式
- 🔍 运维诊断 (`diag <问题描述>`)
- 📊 会话管理
- 📦 工具缓存统计
- 🔄 RAG 后端切换 (ChromaDB / Milvus)

详细使用说明请参见程序内的 `help` 命令。
