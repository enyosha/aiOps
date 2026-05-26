"""
RAG知识库 MCP Server - 提供基于向量检索的知识问答服务
支持 ChromaDB（本地）和 Milvus（远程 SSH 隧道）
以 stdio 形式运行
"""
import os
import sys
import json
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_community.embeddings import DashScopeEmbeddings

# Milvus 相关（用于搜索）—— 可选依赖，不存在时回退到 ChromaDB
_MILVUS_AVAILABLE = False
_MilvusTunnelManager = None
_milvus_connections = None
_Collection = None

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from utils.milvus_tunnel_manager import MilvusTunnelManager as _MilvusTunnelManager
    from pymilvus import (
        connections as _milvus_connections,
        Collection as _Collection,
    )
    _MILVUS_AVAILABLE = True
except ImportError as e:
    print(f"[RAG Server] Milvus 不可用 (缺少依赖): {e}，将仅使用 ChromaDB")

# 加载环境变量
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
MILVUS_LOCAL_PORT = int(os.getenv("MILVUS_LOCAL_PORT", "19531"))
MILVUS_COLLECTION_NAME = "knowledge_base"

# 默认向量搜索后端: 0=ChromaDB, 1=Milvus
_search_backend = 0

# 创建 FastMCP 实例
mcp = FastMCP("RAG Knowledge Server")

# ChromaDB持久化路径(相对于项目根目录)
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "vector_store", "base_vector_store")


class MilvusVectorStore:
    """Milvus 向量存储封装，提供与 ChromaDB 兼容的搜索接口"""

    def __init__(self, embeddings_model):
        if not _MILVUS_AVAILABLE:
            raise RuntimeError("Milvus 不可用，请安装 pymilvus")
        self.embeddings = embeddings_model
        self._tunnel = None
        self._collection = None

    def _connect(self):
        """建立 SSH 隧道并连接 Milvus"""
        if self._collection is not None:
            return
        self._tunnel = _MilvusTunnelManager()
        self._tunnel.create_tunnel()
        _milvus_connections.connect(
            alias="rag_search",
            host="127.0.0.1",
            port=str(MILVUS_LOCAL_PORT)
        )
        self._collection = _Collection(MILVUS_COLLECTION_NAME, using="rag_search")
        self._collection.load()

    def _disconnect(self):
        """断开连接并关闭隧道"""
        try:
            _milvus_connections.disconnect("rag_search")
        except Exception:
            pass
        if self._tunnel:
            self._tunnel.close_tunnel()
            self._tunnel = None
        self._collection = None

    def similarity_search_with_score(self, query: str, k: int = 5) -> List:
        """兼容 ChromaDB 的相似度搜索接口

        Returns:
            List of (Document, score) tuples
        """
        try:
            self._connect()

            # 生成查询向量
            query_embedding = self.embeddings.embed_query(query)

            # Milvus 搜索
            search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
            results = self._collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=k,
                output_fields=["text", "source", "file_type"]
            )

            # 格式化为 (Document, score) 列表
            docs = []
            for hits in results:
                for hit in hits:
                    doc = Document(
                        page_content=hit.entity.get("text", ""),
                        metadata={
                            "source": hit.entity.get("source", "unknown"),
                            "file_type": hit.entity.get("file_type", "unknown")
                        }
                    )
                    docs.append((doc, hit.distance))

            return docs

        except Exception as e:
            print(f"[MilvusVectorStore] 搜索失败: {e}")
            raise

    def get_stats(self) -> dict:
        """获取 Milvus Collection 统计信息"""
        try:
            self._connect()
            self._collection.load()
            count = self._collection.num_entities

            # 分批查询所有源文件
            sources = set()
            offset = 0
            batch_size = 500
            while offset < count:
                results = self._collection.query(
                    expr="id >= 0",
                    output_fields=["source"],
                    limit=batch_size,
                    offset=offset
                )
                if not results:
                    break
                for r in results:
                    sources.add(r.get("source", "unknown"))
                offset += len(results)

            return {
                "total_chunks": count,
                "indexed_files": list(sources),
                "file_count": len(sources)
            }
        except Exception as e:
            print(f"[MilvusVectorStore] 获取统计失败: {e}")
            raise


def get_vector_store(backend: Optional[int] = None):
    """获取或初始化向量存储

    Args:
        backend: 0=ChromaDB (默认), 1=Milvus
                 如果为 None，使用模块级 _search_backend 变量
    """
    if backend is None:
        backend = _search_backend

    # 初始化 Embedding 模型
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=DASHSCOPE_API_KEY
    )

    if backend == 1:
        if not _MILVUS_AVAILABLE:
            print("[RAG Server] Milvus 不可用，回退到 ChromaDB")
            backend = 0  # 回退
        else:
            return MilvusVectorStore(embeddings)

    # ChromaDB 分支（含回退）
    os.makedirs(PERSIST_DIRECTORY, exist_ok=True)
    return Chroma(
        persist_directory=PERSIST_DIRECTORY,
        embedding_function=embeddings,
        collection_name="knowledge_base"
    )


@mcp.tool()
def search_knowledge(query: str, top_k: int = 5, backend: int = 0) -> dict:
    """
    在知识库中搜索与查询相关的文档片段

    Args:
        query: 搜索查询文本
        top_k: 返回最相关的top_k个结果(默认5)
        backend: 向量库后端 (0=ChromaDB默认, 1=Milvus)

    Returns:
        包含相关文档片段和相似度分数的字典
    """
    try:
        vs = get_vector_store(backend=backend)

        # 执行相似度搜索
        results = vs.similarity_search_with_score(query, k=top_k)

        backend_name = "Milvus" if (backend if backend is not None else _search_backend) == 1 else "ChromaDB"

        if not results:
            return {
                "status": "no_results",
                "message": "未找到相关文档",
                "results": [],
                "backend_used": backend_name
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
            "results": formatted_results,
            "backend_used": backend_name
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"搜索失败: {str(e)}",
            "results": []
        }


@mcp.tool()
def set_search_backend(backend: int) -> dict:
    """
    切换 RAG 搜索使用的向量库后端

    Args:
        backend: 0=ChromaDB (本地), 1=Milvus (远程 SSH 隧道)

    Returns:
        包含切换结果和当前后端的字典
    """
    global _search_backend

    if backend not in (0, 1):
        return {
            "status": "error",
            "message": f"无效的后端参数: {backend}，请使用 0 (ChromaDB) 或 1 (Milvus)"
        }

    old = "ChromaDB" if _search_backend == 0 else "Milvus"
    _search_backend = backend
    new = "ChromaDB" if _search_backend == 0 else "Milvus"

    return {
        "status": "success",
        "message": f"RAG 搜索后端已切换: {old} -> {new}",
        "previous": old,
        "current": new,
        "backend_code": _search_backend
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
def get_indexed_docs(backend: int = 0) -> dict:
    """
    获取已索引的文档列表和统计信息

    Args:
        backend: 向量库后端 (0=ChromaDB默认, 1=Milvus)

    Returns:
        包含已索引文档信息的字典
    """
    try:
        vs = get_vector_store(backend=backend)

        if hasattr(vs, 'get_stats'):
            # MilvusVectorStore
            stats = vs.get_stats()
            return {
                "status": "success",
                "total_chunks": stats["total_chunks"],
                "indexed_files": stats["indexed_files"],
                "file_count": stats["file_count"],
                "backend_used": "Milvus"
            }

        # ChromaDB
        collection = vs._collection
        count = collection.count()
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
            "file_count": len(sources),
            "backend_used": "ChromaDB"
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
