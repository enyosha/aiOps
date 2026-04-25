"""
直接测试ChromaDB向量检索功能
"""
import sys
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

print("=" * 70)
print("ChromaDB向量检索测试")
print("=" * 70)

# 初始化向量存储
print("\n1. 加载向量存储...")
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "vector_store")

embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=DASHSCOPE_API_KEY
)

vector_store = Chroma(
    persist_directory=PERSIST_DIRECTORY,
    embedding_function=embeddings,
    collection_name="knowledge_base"
)

print(f"   向量库路径: {PERSIST_DIRECTORY}")
print("   加载成功!")

# 测试查询
test_queries = [
    "2025年人工智能发展趋势",
    "大聪明牌口服液功效",
    "糖尿病的治疗方法"
]

for query in test_queries:
    print(f"\n2. 查询: {query}")
    try:
        results = vector_store.similarity_search_with_score(query, k=3)

        if not results:
            print("   未找到相关结果")
            continue

        print(f"   找到 {len(results)} 个相关文档:")
        for i, (doc, score) in enumerate(results, 1):
            print(f"\n   结果 {i} (相似度分数: {score:.4f}):")
            print(f"   来源: {doc.metadata.get('source', 'unknown')}")
            content_preview = doc.page_content[:150].replace('\n', ' ')
            print(f"   内容: {content_preview}...")
    except Exception as e:
        print(f"   错误: {str(e)}")

print("\n" + "=" * 70)
print("测试完成!")
print("=" * 70)
