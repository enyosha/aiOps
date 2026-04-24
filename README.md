# MCP (Model Context Protocol) Agent System

基于 Model Context Protocol (MCP) 构建的智能代理系统，旨在通过标准化协议连接 AI 模型与外部工具/数据源。

## 项目结构

```
├── .env                          # 环境变量配置文件
├── .gitignore                    # Git 忽略配置
├── README.md                     # 项目说明文件
├── requirements.txt              # Python 依赖包
├── aiOps.pem                     # SSL 证书文件（如有）
├── mcp.json                      # MCP 服务器配置文件
├── quickstart.py                 # 快速启动脚本
├── interactive_chat.py           # 交互式聊天界面
├── mcp_client.py                 # LangChain MCP Agent 客户端
├── mcp_client/                   # LangGraph/LangChain 客户端模块
│   ├── __init__.py
│   ├── mcp_client_langchain.py   # LangChain 客户端实现
│   └── mcp_client_langgraph.py   # LangGraph 客户端实现（主入口）
├── mcp_server/                   # MCP 服务器模块
│   ├── __init__.py
│   ├── calucate_mcp_server.py    # 计算器 MCP 服务器
│   └── logReader_mcp_server.py   # 日志读取 MCP 服务器
├── test/                         # 测试相关文件
│   ├── test_weather.py           # 天气 API 测试
│   ├── full_test.py              # 完整测试脚本
│   ├── simple_test.py            # 简单测试脚本
│   └── ...                       # 其他测试文件
├── doc/                          # 项目文档
│   ├── ARCHITECTURE.md           # 架构文档
│   ├── QUICKSTART.md             # 快速开始指南
│   └── ...                       # 其他文档
└── logs/                         # 日志目录
    └── Logs.txt                  # 日志文件（如有）
```

## 功能特性

### 1. LangGraph MCP Agent
- **动态工具加载**：通过 `langchain-mcp-adapters` 动态加载 MCP 服务器提供的工具
- **高德地图集成**：集成高德地图 MCP 服务，支持天气查询、地理编码、路径规划等功能
- **多服务器支持**：支持连接多个 MCP 服务器（计算器、日志读取、高德地图等）
- **智能路由**：根据用户输入自动选择合适的工具执行

### 2. MCP 服务器
- **计算器服务器**：提供基本数学运算功能（加减乘除）
- **日志读取服务器**：提供日志搜索和过滤功能
- **高德地图服务器**：通过 MCP 协议访问高德地图服务（天气、地理编码、路径规划等）

## 快速开始

### 1. 环境准备
```bash
# 创建并激活 Python 虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量
在 `.env` 文件中配置 API 密钥：
```
DASHSCOPE_API_KEY=your_dashscope_api_key
AMAP_API_KEY=your_amap_api_key
```

### 3. 运行 LangGraph Agent
```bash
# 运行 LangGraph 版本（推荐）
python mcp_client/mcp_client_langgraph.py

# 或运行交互式聊天
python interactive_chat.py
```

## 高德 MCP 服务集成

本项目集成了高德地图的 MCP 服务，支持以下功能：

- **天气查询**：`maps_weather` - 根据城市名称查询天气信息
- **地理编码**：`maps_geo` - 将地址转换为经纬度坐标
- **逆地理编码**：`maps_regeocode` - 将经纬度转换为地址信息
- **路径规划**：`maps_direction_driving`、`maps_direction_walking` 等 - 提供多种出行方式路线规划
- **POI 搜索**：`maps_text_search`、`maps_around_search` - 地点搜索功能
- **IP 定位**：`maps_ip_location` - 根据 IP 地址定位

## 技术栈

- **Python** >= 3.9
- **LangChain** >= 0.3.0
- **LangGraph** >= 0.2.0
- **MCP Protocol** >= 1.0.0
- **langchain-mcp-adapters** >= 0.1.0
- **FastMCP** >= 0.1.0
- **DashScope API** - 用于 LLM 服务
- **高德开放平台 API** - 用于地图服务

## 使用示例

LangGraph Agent 可以理解和处理以下类型的查询：

1. 数学计算："(6+9/8-7)/2的结果是什么"
2. 天气查询："今天北京的天气如何？"
3. 路径规划："从天安门到西单怎么走？"
4. 日志分析："日志中有多少条DEBUG信息？"

## 开发说明

项目遵循严格的模块化设计，将工具定义、状态管理、节点实现等分离到不同模块中，便于维护和扩展。主要架构分为六个模块：

1. Tools & Model (工具与模型)
2. State (状态定义)
3. Model Node (模型节点)
4. Tool Node (工具节点)
5. End Logic (结束逻辑)
6. Build & Compile (构建与编译)

## 贡献

欢迎提交 Issue 和 Pull Request 来帮助改进项目。
