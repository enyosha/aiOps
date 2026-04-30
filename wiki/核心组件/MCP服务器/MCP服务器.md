# MCP服务器

<cite>
**本文档引用的文件**
- [README.md](file://README.md)
- [requirements.txt](file://requirements.txt)
- [quickstart.py](file://quickstart.py)
- [Server/calculator_server.py](file://Server/calculator_server.py)
- [Server/logReader_server.py](file://Server/logReader_server.py)
- [Routing/base_agent.py](file://Routing/base_agent.py)
- [Routing/tool_cache.py](file://Routing/tool_cache.py)
- [Routing/calculator.py](file://Routing/calculator.py)
- [Routing/log_reader.py](file://Routing/log_reader.py)
- [test_output.txt](file://test_output.txt)
</cite>

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖分析](#依赖分析)
7. [性能考虑](#性能考虑)
8. [故障排查指南](#故障排查指南)
9. [结论](#结论)
10. [附录](#附录)

## 简介
本项目基于 Model Context Protocol (MCP) 构建，提供标准化协议连接 AI 模型与外部工具/数据源。系统包含两个核心 MCP 服务器：
- 计算器 MCP 服务器：提供加减乘除等基础数学运算工具
- 日志读取 MCP 服务器：提供日志读取、搜索和统计功能

服务器通过 FastMCP 框架以 stdio 传输协议运行，配合全局工具缓存机制实现高效、稳定的工具加载与复用。

## 项目结构
项目采用模块化设计，将工具定义、状态管理、节点实现等分离到不同模块中，便于维护和扩展。主要目录结构如下：
- Server：MCP 服务器实现
- Routing：代理与工具缓存管理
- Client：客户端相关代码
- Data：数据文件
- logs：日志目录

```mermaid
graph TB
subgraph "Server"
CS["计算器服务器<br/>calculator_server.py"]
LS["日志读取服务器<br/>logReader_server.py"]
end
subgraph "Routing"
BA["基础代理<br/>base_agent.py"]
TC["工具缓存<br/>tool_cache.py"]
CA["计算器代理适配<br/>calculator.py"]
LRA["日志读取代理适配<br/>log_reader.py"]
end
subgraph "Client"
QC["快速启动脚本<br/>quickstart.py"]
end
subgraph "Data"
LOGS["日志目录<br/>logs/"]
end
QC --> BA
BA --> TC
TC --> CS
TC --> LS
CS --> LOGS
LS --> LOGS
CA --> BA
LRA --> BA
```

**图表来源**
- [Server/calculator_server.py:1-111](file://Server/calculator_server.py#L1-L111)
- [Server/logReader_server.py:1-151](file://Server/logReader_server.py#L1-L151)
- [Routing/base_agent.py:1-497](file://Routing/base_agent.py#L1-L497)
- [Routing/tool_cache.py:1-302](file://Routing/tool_cache.py#L1-L302)
- [Routing/calculator.py:1-11](file://Routing/calculator.py#L1-L11)
- [Routing/log_reader.py:1-11](file://Routing/log_reader.py#L1-L11)
- [quickstart.py:1-68](file://quickstart.py#L1-L68)

**章节来源**
- [README.md:1-125](file://README.md#L1-L125)
- [quickstart.py:1-68](file://quickstart.py#L1-L68)

## 核心组件
本节详细介绍MCP服务器的核心组件及其职责。

### 计算器 MCP 服务器
计算器服务器实现四个基本数学运算工具：
- add：加法运算
- subtract：减法运算  
- multiply：乘法运算
- divide：除法运算

每个工具都使用 @mcp.tool() 装饰器注册，并返回标准化的JSON响应格式。

### 日志读取 MCP 服务器
日志读取服务器提供三种核心功能：
- read_logs：读取最新日志条目
- search_logs：按关键词搜索日志
- get_log_stats：获取日志文件统计信息

服务器自动检测日志文件位置，支持 app.log 和 Logs.txt 两种常见命名。

### 工具缓存管理器
全局工具缓存管理器负责：
- 缓存 MCP 服务器连接和工具列表
- 支持 TTL 过期策略
- 线程安全的缓存访问
- 统一管理所有 Agent 的工具加载

**章节来源**
- [Server/calculator_server.py:16-105](file://Server/calculator_server.py#L16-L105)
- [Server/logReader_server.py:18-145](file://Server/logReader_server.py#L18-L145)
- [Routing/tool_cache.py:39-298](file://Routing/tool_cache.py#L39-L298)

## 架构总览
系统采用分层架构设计，通过工具缓存实现服务器与客户端的解耦。

```mermaid
graph TB
subgraph "客户端层"
QA["快速启动脚本<br/>quickstart.py"]
BA["基础代理<br/>base_agent.py"]
end
subgraph "工具管理层"
TC["工具缓存<br/>tool_cache.py"]
MCM["MCP客户端适配<br/>MultiServerMCPClient"]
end
subgraph "服务器层"
CS["计算器服务器<br/>calculator_server.py"]
LS["日志读取服务器<br/>logReader_server.py"]
end
subgraph "数据层"
LOGS["日志文件<br/>logs/"]
end
QA --> BA
BA --> TC
TC --> MCM
MCM --> CS
MCM --> LS
CS --> LOGS
LS --> LOGS
```

**图表来源**
- [quickstart.py:1-68](file://quickstart.py#L1-L68)
- [Routing/base_agent.py:44-66](file://Routing/base_agent.py#L44-L66)
- [Routing/tool_cache.py:118-196](file://Routing/tool_cache.py#L118-L196)
- [Server/calculator_server.py:108-111](file://Server/calculator_server.py#L108-L111)
- [Server/logReader_server.py:148-151](file://Server/logReader_server.py#L148-L151)

## 详细组件分析

### 计算器服务器组件分析

#### 类图
```mermaid
classDiagram
class FastMCP {
+tool() decorator
+run(transport) void
}
class CalculatorServer {
+add(a : float, b : float) dict
+subtract(a : float, b : float) dict
+multiply(a : float, b : float) dict
+divide(a : float, b : float) dict
}
class ToolDecorator {
+__call__(func) callable
+register_tool(name, func) void
}
FastMCP <|-- CalculatorServer
FastMCP --> ToolDecorator : "uses"
```

**图表来源**
- [Server/calculator_server.py:5-13](file://Server/calculator_server.py#L5-L13)
- [Server/calculator_server.py:16-105](file://Server/calculator_server.py#L16-L105)

#### 请求处理序列图
```mermaid
sequenceDiagram
participant Client as "客户端"
participant Server as "计算器服务器"
participant Tool as "工具函数"
participant Env as "环境变量"
Client->>Server : 调用 add(a, b)
Server->>Env : 加载环境变量
Server->>Tool : 执行 add 函数
Tool->>Tool : 打印调用日志
Tool->>Tool : 执行计算 (a + b - 100)
Tool-->>Server : 返回 {operation, a, b, result}
Server-->>Client : 返回标准化响应
Note over Client,Server : 除法运算包含错误处理逻辑
```

**图表来源**
- [Server/calculator_server.py:16-35](file://Server/calculator_server.py#L16-L35)
- [Server/calculator_server.py:95-98](file://Server/calculator_server.py#L95-L98)

#### 错误处理流程图
```mermaid
flowchart TD
Start(["除法运算入口"]) --> CheckDivisor["检查除数是否为零"]
CheckDivisor --> IsZero{"除数为零？"}
IsZero --> |是| ReturnError["返回错误信息"]
IsZero --> |否| PerformCalc["执行除法计算"]
PerformCalc --> FormatResponse["格式化响应"]
FormatResponse --> End(["返回结果"])
ReturnError --> End
```

**图表来源**
- [Server/calculator_server.py:94-105](file://Server/calculator_server.py#L94-L105)

**章节来源**
- [Server/calculator_server.py:16-105](file://Server/calculator_server.py#L16-L105)

### 日志读取服务器组件分析

#### 类图
```mermaid
classDiagram
class LogReaderServer {
+read_logs(lines : int) list
+search_logs(keyword : str) list
+get_log_stats() dict
}
class LogFileHandler {
+find_log_file() str
+read_latest_lines(file_path, lines) list
+search_keyword(file_path, keyword) list
+get_statistics(file_path) dict
}
class FileSystem {
+exists(path) bool
+listdir(path) list
+stat(path) StatResult
}
LogReaderServer --> LogFileHandler : "委托"
LogFileHandler --> FileSystem : "使用"
```

**图表来源**
- [Server/logReader_server.py:18-145](file://Server/logReader_server.py#L18-L145)

#### 日志读取序列图
```mermaid
sequenceDiagram
participant Client as "客户端"
participant Server as "日志读取服务器"
participant FS as "文件系统"
participant LogDir as "日志目录"
Client->>Server : 调用 read_logs(10)
Server->>LogDir : 查找日志文件
LogDir-->>Server : 返回文件路径
Server->>FS : 读取文件内容
FS-->>Server : 返回所有行
Server->>Server : 截取最新10行
Server->>Server : 格式化为日志条目
Server-->>Client : 返回日志列表
Note over Client,Server : 文件不存在时返回错误信息
```

**图表来源**
- [Server/logReader_server.py:19-57](file://Server/logReader_server.py#L19-L57)

#### 关键算法流程图
```mermaid
flowchart TD
Start(["搜索日志入口"]) --> FindFile["查找日志文件"]
FindFile --> FileExists{"找到文件？"}
FileExists --> |否| ReturnError["返回可用文件列表"]
FileExists --> |是| ReadFile["读取文件内容"]
ReadFile --> SearchLoop["遍历每一行"]
SearchLoop --> CheckKeyword{"包含关键词？"}
CheckKeyword --> |是| AddMatch["添加到匹配列表"]
CheckKeyword --> |否| NextLine["继续下一行"]
AddMatch --> NextLine
NextLine --> SearchLoop
SearchLoop --> DoneSearch{"搜索完成？"}
DoneSearch --> |否| SearchLoop
DoneSearch --> |是| HasMatches{"有匹配项？"}
HasMatches --> |是| FormatResults["格式化匹配结果"]
HasMatches --> |否| ReturnNoMatch["返回未找到信息"]
FormatResults --> End(["返回结果"])
ReturnNoMatch --> End
ReturnError --> End
```

**图表来源**
- [Server/logReader_server.py:61-102](file://Server/logReader_server.py#L61-L102)

**章节来源**
- [Server/logReader_server.py:18-145](file://Server/logReader_server.py#L18-L145)

### 工具缓存管理器组件分析

#### 缓存架构图
```mermaid
graph TB
subgraph "缓存层"
CE["缓存条目<br/>ToolCacheEntry"]
CACHE["缓存字典<br/>_cache: Dict"]
end
subgraph "会话管理"
SESSIONS["会话字典<br/>_sessions: Dict"]
CLIENT["MCP客户端<br/>MultiServerMCPClient"]
end
subgraph "配置管理"
CONFIG["配置文件<br/>mcp.json"]
SERVERCFG["服务器配置<br/>server_config"]
end
subgraph "传输层"
STDIO["stdio传输<br/>StdioServerParameters"]
HTTP["HTTP传输<br/>streamable_http_client"]
end
CE --> CACHE
CACHE --> SESSIONS
CONFIG --> SERVERCFG
SERVERCFG --> STDIO
SERVERCFG --> HTTP
STDIO --> CLIENT
HTTP --> CLIENT
```

**图表来源**
- [Routing/tool_cache.py:27-65](file://Routing/tool_cache.py#L27-L65)
- [Routing/tool_cache.py:85-139](file://Routing/tool_cache.py#L85-L139)
- [Routing/tool_cache.py:141-242](file://Routing/tool_cache.py#L141-L242)

#### 缓存生命周期流程图
```mermaid
flowchart TD
Request(["获取工具请求"]) --> CheckCache["检查缓存"]
CheckCache --> CacheHit{"缓存命中？"}
CacheHit --> |是| CheckTTL["检查TTL过期"]
CheckTTL --> Expired{"已过期？"}
Expired --> |是| Cleanup["清理过期缓存"]
Expired --> |否| ReturnCache["返回缓存工具"]
CacheHit --> |否| LoadTools["加载新工具"]
Cleanup --> LoadTools
LoadTools --> CreateSession["创建会话"]
CreateSession --> UpdateCache["更新缓存"]
UpdateCache --> ReturnNew["返回新工具"]
ReturnCache --> End(["结束"])
ReturnNew --> End
```

**图表来源**
- [Routing/tool_cache.py:85-116](file://Routing/tool_cache.py#L85-L116)
- [Routing/tool_cache.py:244-280](file://Routing/tool_cache.py#L244-L280)

**章节来源**
- [Routing/tool_cache.py:39-298](file://Routing/tool_cache.py#L39-L298)

### 代理基类组件分析

#### 代理工作流图
```mermaid
stateDiagram-v2
[*] --> 初始化
初始化 --> 模型节点 : "接收用户输入"
模型节点 --> 工具调用 : "生成AI消息"
模型节点 --> 结束 : "无工具调用"
工具调用 --> 工具节点 : "执行工具调用"
工具节点 --> 模型节点 : "返回工具结果"
模型节点 --> 错误处理 : "模型调用失败"
工具节点 --> 错误处理 : "工具执行失败"
错误处理 --> 结束 : "返回错误信息"
```

**图表来源**
- [Routing/base_agent.py:102-130](file://Routing/base_agent.py#L102-L130)
- [Routing/base_agent.py:131-217](file://Routing/base_agent.py#L131-L217)
- [Routing/base_agent.py:219-236](file://Routing/base_agent.py#L219-L236)

#### 工具执行流程图
```mermaid
flowchart TD
Start(["工具节点入口"]) --> CheckAIMessage["检查AI消息"]
CheckAIMessage --> HasToolCalls{"有工具调用？"}
HasToolCalls --> |否| NoTools["标记无工具"]
HasToolCalls --> |是| LoadTools["加载缓存工具"]
LoadTools --> MapTools["构建工具映射"]
MapTools --> ExecuteLoop["遍历工具调用"]
ExecuteLoop --> LookupTool["查找工具"]
LookupTool --> ToolFound{"找到工具？"}
ToolFound --> |否| ToolError["记录工具未找到错误"]
ToolFound --> |是| InvokeTool["执行工具调用"]
InvokeTool --> ExtractResult["提取result字段"]
ExtractResult --> CreateMessage["创建工具消息"]
CreateMessage --> StoreResult["存储结果"]
StoreResult --> NextCall["下一个工具调用"]
NextCall --> ExecuteLoop
ToolError --> NextCall
NoTools --> End(["结束"])
ExecuteLoop --> Done{"所有工具完成？"}
Done --> |否| ExecuteLoop
Done --> |是| End
```

**图表来源**
- [Routing/base_agent.py:131-217](file://Routing/base_agent.py#L131-L217)

**章节来源**
- [Routing/base_agent.py:29-318](file://Routing/base_agent.py#L29-L318)

## 依赖分析
系统依赖关系清晰，主要依赖包括 FastMCP、LangChain 生态系统和标准库。

```mermaid
graph TB
subgraph "核心依赖"
FMCP["fastmcp>=0.1.0"]
LANGCHAIN["langchain>=0.3.0"]
MCP["mcp>=1.0.0"]
DOTENV["python-dotenv>=1.0.0"]
end
subgraph "工具库"
HTTPX["httpx>=0.25.0"]
CHROMA["chromadb>=0.4.0"]
REDIS["redis>=4.0.0"]
MILVUS["pymilvus>=2.4.0"]
end
subgraph "项目模块"
CALC["计算器服务器"]
LOGREAD["日志读取服务器"]
BASEAGENT["基础代理"]
TOOLCACHE["工具缓存"]
end
FMCP --> CALC
FMCP --> LOGREAD
LANGCHAIN --> BASEAGENT
MCP --> TOOLCACHE
DOTENV --> CALC
DOTENV --> LOGREAD
HTTPX --> TOOLCACHE
CHROMA --> BASEAGENT
REDIS --> BASEAGENT
MILVUS --> BASEAGENT
```

**图表来源**
- [requirements.txt:1-17](file://requirements.txt#L1-L17)
- [Server/calculator_server.py:5-7](file://Server/calculator_server.py#L5-L7)
- [Server/logReader_server.py:5-7](file://Server/logReader_server.py#L5-L7)

**章节来源**
- [requirements.txt:1-17](file://requirements.txt#L1-L17)

## 性能考虑
基于代码分析，系统在性能方面具有以下特点：

### 缓存优化
- 工具缓存采用 TTL 过期策略，默认5分钟，减少重复连接开销
- 支持多服务器并发缓存管理
- 线程安全的缓存访问机制

### I/O优化
- 日志读取采用流式处理，避免大文件一次性加载
- 文件操作包含异常处理，防止I/O阻塞
- 支持多种日志文件格式自动检测

### 并发处理
- 异步工具执行避免阻塞主线程
- 多服务器连接管理
- 超时控制机制（HTTP传输10秒超时）

## 故障排查指南

### 常见问题诊断
根据测试输出显示，系统在启动过程中会打印详细的启动信息和版本信息，这为故障排查提供了重要线索。

### 环境配置检查
1. 确认 .env 文件中包含必要的 API 密钥配置
2. 验证日志目录存在且可读
3. 检查 Python 版本满足最低要求（>= 3.9）

### 服务器启动验证
通过测试输出可以看到服务器启动过程中的关键信息：
- 传输协议类型（stdio）
- 服务器版本信息
- FastMCP 框架版本

**章节来源**
- [test_output.txt:17-182](file://test_output.txt#L17-L182)

## 结论
本MCP服务器组件提供了完整的计算器和日志读取功能，具有以下优势：
- 基于标准MCP协议，具有良好扩展性
- 采用工具缓存机制，提升性能和稳定性
- 清晰的模块化设计，便于维护和扩展
- 完善的错误处理和异常恢复机制

系统为后续添加更多MCP服务器提供了良好的基础设施和最佳实践参考。

## 附录

### 快速开始指南
1. 创建并激活虚拟环境
2. 安装依赖包
3. 配置环境变量（API密钥）
4. 运行快速启动脚本进行功能验证

### 扩展新MCP服务器指南
1. 参考现有服务器的装饰器模式注册工具
2. 实现标准化的响应格式
3. 在配置文件中添加服务器配置
4. 通过工具缓存自动发现和加载

### 部署建议
- 使用 systemd 或类似进程管理器守护服务器进程
- 配置适当的日志轮转策略
- 监控服务器健康状态和响应时间
- 定期清理过期缓存和临时文件