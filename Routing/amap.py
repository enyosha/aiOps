"""
高德地图代理 - 专门处理地图和地理位置相关请求
已重构为使用 BaseAgent 基类和全局工具缓存
"""

# 从基类导入，保持向后兼容
from Routing.base_agent import AmapAgent, create_amap_agent

# 导出以保持向后兼容
__all__ = ['AmapAgent', 'create_amap_agent']
