# LLM 模型配置指南

## 配置文件位置
所有 LLM 相关配置都在项目根目录的 `.env` 文件中管理。

## 当前配置项

```env
# API Key
DASHSCOPE_API_KEY=sk-fab6d3aab5414d60afce5e7460635095

# LLM 模型配置
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-max
LLM_TEMPERATURE=0
```

## 如何切换模型

### 1. 切换到通义千问其他版本

**qwen-plus（性价比更高）：**
```env
LLM_MODEL=qwen-plus
```

**qwen-turbo（速度最快）：**
```env
LLM_MODEL=qwen-turbo
```

### 2. 切换到 OpenAI

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7
```

然后在 `.env` 中添加：
```env
OPENAI_API_KEY=your-openai-api-key
```

并修改代码中的 `api_key` 参数使用对应的环境变量。

### 3. 切换到其他兼容 OpenAI 格式的模型

**DeepSeek：**
```env
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

**Moonshot（月之暗面）：**
```env
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
```

**本地 Ollama：**
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3
LLM_TEMPERATURE=0.5
```

## 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `LLM_BASE_URL` | LLM API 的基础 URL | 阿里云 DashScope |
| `LLM_MODEL` | 使用的模型名称 | qwen-max |
| `LLM_TEMPERATURE` | 温度参数（0-1），控制随机性 | 0（确定性输出） |

## 注意事项

1. **修改后需要重启程序**：更改 `.env` 文件后，需要重新启动 Python 进程才能生效
2. **API Key 匹配**：确保使用的 API Key 与 BASE_URL 对应
3. **Temperature 范围**：通常为 0-1，0 表示最确定性，1 表示最创造性
4. **模型可用性**：确保您有权限访问所选模型

## 快速测试

修改 `.env` 后，可以运行以下命令测试：

```bash
python test_chain_calculation.py
```

观察输出是否正常，确认新模型配置生效。
