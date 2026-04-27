"""
RAG知识库 MCP Server - 提供基于向量检索的知识问答服务
以 stdio 形式运行
"""
import os
import json
from typing import List, Dict, Any
from fastmcp import FastMCP
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

# 加载环境变量
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# 创建 FastMCP 实例
mcp = FastMCP("RAG Knowledge Server")

# ChromaDB持久化路径(相对于项目根目录)
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "vector_store")


def get_vector_store():
    """获取或初始化向量存储"""
    # 确保持久化目录存在
    os.makedirs(PERSIST_DIRECTORY, exist_ok=True)

    # 初始化Embedding模型（与init_rag.py保持一致）
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=DASHSCOPE_API_KEY
    )

    # 连接到ChromaDB
    vector_store = Chroma(
        persist_directory=PERSIST_DIRECTORY,
        embedding_function=embeddings,
        collection_name="knowledge_base"
    )

    return vector_store


@mcp.tool()
def search_knowledge(query: str, top_k: int = 5) -> dict:
    """
    在知识库中搜索与查询相关的文档片段

    Args:
        query: 搜索查询文本
        top_k: 返回最相关的top_k个结果(默认5)

    Returns:
        包含相关文档片段和相似度分数的字典
    """
    try:
        vector_store = get_vector_store()

        # 执行相似度搜索
        results = vector_store.similarity_search_with_score(query, k=top_k)

        if not results:
            return {
                "status": "no_results",
                "message": "未找到相关文档",
                "results": []
            }

        # 格式化结果
        formatted_results = []
        for doc, score in results:
            formatted_results.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "similarity_score": float(score)
            })

        return {
            "status": "success",
            "query": query,
            "result_count": len(formatted_results),
            "results": formatted_results
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"搜索失败: {str(e)}",
            "results": []
        }


@mcp.tool()
def load_documents() -> dict:
    """
    手动触发Data目录下文档的加载和索引

    Returns:
        包含加载状态和统计信息的字典
    """
    try:
        from init_rag import initialize_rag_index

        print("开始加载和索引Data目录下的文档...")
        result = initialize_rag_index()

        return {
            "status": "success",
            "message": "文档加载完成",
            "details": result
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"文档加载失败: {str(e)}"
        }


@mcp.tool()
def get_indexed_docs() -> dict:
    """
    获取已索引的文档列表和统计信息

    Returns:
        包含已索引文档信息的字典
    """
    try:
        vector_store = get_vector_store()

        # 获取集合信息
        collection = vector_store._collection
        count = collection.count()

        # 获取所有唯一的源文件
        results = collection.get(include=["metadatas"])
        sources = set()
        if results and results.get("metadatas"):
            for metadata in results["metadatas"]:
                if "source" in metadata:
                    sources.add(metadata["source"])

        return {
            "status": "success",
            "total_chunks": count,
            "indexed_files": list(sources),
            "file_count": len(sources)
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"获取索引信息失败: {str(e)}"
        }


if __name__ == "__main__":
    # 检查向量库是否已初始化（静默检查）
    if not os.path.exists(PERSIST_DIRECTORY):
        pass  # 向量库将在首次使用时自动创建

    # 以 stdio 模式运行
    mcp.run(transport="stdio")
