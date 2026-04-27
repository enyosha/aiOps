"""
日志读取代理 - 专门处理日志分析请求
已重构为使用 BaseAgent 基类和全局工具缓存
"""

# 从基类导入，保持向后兼容
from Routing.base_agent import LogReaderAgent, create_log_reader_agent

# 导出以保持向后兼容
__all__ = ['LogReaderAgent', 'create_log_reader_agent']
