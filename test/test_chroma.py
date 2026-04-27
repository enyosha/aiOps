"""测试 ChromaDB 向量库是否正常工作"""
from Server.rag_server import get_vector_store

print("=" * 70)
print("测试 ChromaDB 向量库")
print("=" * 70)

# 获取向量存储
vs = get_vector_store()

# 测试查询
query = "大聪明口服液 定价"
print(f"\n查询: {query}\n")

results = vs.similarity_search_with_score(query, k=3)

print(f"找到 {len(results)} 个结果:\n")

for i, (doc, score) in enumerate(results, 1):
    print(f"--- 结果 {i} (相似度分数: {score:.4f}) ---")
    print(f"内容预览: {doc.page_content[:200]}...")
    print(f"来源: {doc.metadata.get('source', 'unknown')}")
    print(f"文件类型: {doc.metadata.get('file_type', 'unknown')}")
    print()

print("=" * 70)
print("测试完成")
print("=" * 70)
