"""
RAG知识库代理 - 专门处理基于Data目录的知识问答请求
已重构为使用 BaseAgent 基类和全局工具缓存
"""

# 从基类导入，保持向后兼容
from Routing.base_agent import RAGAgent, create_rag_agent

# 导出以保持向后兼容
__all__ = ['RAGAgent', 'create_rag_agent']
