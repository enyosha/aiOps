# LangGraph 意图识别与路由模块生成提示

## 目标
请创建一个名为 [route.py](file:///c%5CUsers%5Censha%5CDesktop%5CAiOps%5Cmcp%5C03.projects%5CAiops%5Cmcp_client%5CRouting%5Croute.py) 的 Python 脚本，用于实现一个基于 LangGraph 的意图识别和路由系统。该系统应具备以下功能和结构：

## 1. 整体架构要求
- 使用 LangGraph 的 StateGraph 构建完整的工作流
- 包含 State 定义、节点函数、条件路由和工作流编译
- 实现意图识别功能，能够将用户输入路由到适当的处理模块

## 2. 状态定义
- 定义一个 State 类型，包含以下字段：
  - input: str 类型，存储用户输入
  - decision: str 类型，存储意图识别结果
  - output: str 类型，存储最终输出结果

## 3. 意图分类定义
- 定义一个 Route Pydantic 模型，使用 Literal 类型指定三个可能的意图类别：calculator、log_reader 和 amap
- 该模型应包含描述路由过程下一步的 step 字段

## 4. 节点函数
- handle_calculator_request(state: State): 异步处理计算器请求，导入并调用 create_calculator_agent 函数
- handle_log_reader_request(state: State): 异步处理日志读取请求，导入并调用 create_log_reader_agent 函数
- handle_amap_request(state: State): 异步处理高德地图请求，导入并调用 create_amap_agent 函数
- route_request(state: State): 异步路由请求，使用结构化输出进行意图识别，使用 SystemMessage 和 HumanMessage 分别传递系统指令和用户输入
- error_handler(state: State): 处理无法识别意图的情况，返回错误信息

## 5. 条件路由
- 实现 route_decision(state: State) 函数，根据 `state["decision"]` 的值返回相应的节点名称
- 当无法识别意图时，返回 error_handler 节点

## 6. 工作流构建
- 使用 StateGraph 构建工作流
- 添加所有节点
- 添加从 START 到路由节点的边
- 添加条件边，根据路由决策函数的结果连接节点
- 添加从处理节点到 END 的边
- 编译工作流并创建全局实例

## 7. 依赖导入
- 导入必要的 LangGraph 组件（StateGraph, START, END）
- 导入 LangChain 消息组件（HumanMessage, SystemMessage）
- 从对应模块导入代理创建函数（calculator, log_reader, amap）
- 导入环境变量加载功能

## 8. 环境配置
- 使用 dotenv 加载环境变量
- 获取并使用 DASHSCOPE_API_KEY

## 9. 测试功能
- 实现一个主函数，用于演示路由功能
- 包含多个测试用例，涵盖计算器、日志读取和高德地图三种场景
- 使用工作流实例处理每个测试用例并打印结果

## 10. 消息构建
- 在意图识别过程中，使用 SystemMessage 传递系统指令
- 使用 HumanMessage 传递用户输入
- 确保系统指令明确说明如何分类意图

## 11. 错误处理
- 当无法识别意图时，应返回错误信息而不是默认行为
- 不得设置默认路由到某个节点，必须明确处理无法识别的情况

## 12. 规范要求
- 代码结构清晰，注释充分
- 遵循 LangGraph 的最佳实践
- 所有节点函数应正确处理异步操作
- 返回适当的状态更新
- 严格区分 SystemMessage 和 HumanMessage
- 遵循项目架构和开发规范