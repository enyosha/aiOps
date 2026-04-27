"""
计算器代理 - 专门处理数学计算请求
已重构为使用 BaseAgent 基类和全局工具缓存
"""

# 从基类导入，保持向后兼容
from Routing.base_agent import CalculatorAgent, create_calculator_agent

# 导出以保持向后兼容
__all__ = ['CalculatorAgent', 'create_calculator_agent']
