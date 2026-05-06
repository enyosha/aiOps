"""
运维知识库初始化脚本
读取 KnowledgeBase/knowledge_entries/*.json 并导入到 ops_vector_store
"""
import sys
import os
import json

# 添加项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_chroma import Chroma

# 配置
OPS_PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "vector_store", "ops_vector_store")
OPS_COLLECTION_NAME = "ops_knowledge"
KNOWLEDGE_ENTRIES_DIR = os.path.join(os.path.dirname(__file__), "..", "ops_knowledge_entries")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def initialize_ops_knowledge():
    """初始化运维知识库"""
    print("=" * 70)
    print("运维知识库初始化")
    print("=" * 70)
    
    # 初始化向量库
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=DASHSCOPE_API_KEY
    )
    
    os.makedirs(OPS_PERSIST_DIRECTORY, exist_ok=True)
    vector_store = Chroma(
        persist_directory=OPS_PERSIST_DIRECTORY,
        embedding_function=embeddings,
        collection_name=OPS_COLLECTION_NAME
    )
    
    # 读取知识条目
    if not os.path.exists(KNOWLEDGE_ENTRIES_DIR):
        print(f"ERROR: 知识条目目录不存在: {KNOWLEDGE_ENTRIES_DIR}")
        return {"status": "error", "message": "Directory not found"}
    
    loaded_count = 0
    for filename in os.listdir(KNOWLEDGE_ENTRIES_DIR):
        if not filename.endswith('.json'):
            continue
        
        filepath = os.path.join(KNOWLEDGE_ENTRIES_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                entry = json.load(f)
            
            # 构建文档内容
            if 'solution' in entry:
                content = f"""
                标题: {entry['title']}
                分类: {entry['category']}
                症状: {', '.join(entry['symptoms'])}
                根本原因: {entry['root_cause']}
                解决方案: {entry['solution']['immediate']}
                关键词: {', '.join(entry['log_keywords'])}
                标签: {', '.join(entry['tags'])}
                """
                doc_id = entry['id']
                
                metadata = {
                    "doc_id": doc_id,
                    "title": entry['title'],
                    "category": entry['category'],
                    "severity": entry['severity'],
                    "type": "solution",
                    "tags": json.dumps(entry['tags'])
                }
                
            elif 'diagnosis_tree' in entry:
                diagnosis_steps = []
                for step_key, step_data in entry['diagnosis_tree'].items():
                    diagnosis_steps.append(step_data['description'])
                
                content = f"""
                标题: {entry['title']}
                分类: {entry['category']}
                症状: {', '.join(entry['symptoms'])}
                根本原因: {entry['root_cause']}
                诊断步骤: {'; '.join(diagnosis_steps)}
                关键词: {', '.join(entry['log_keywords'])}
                标签: {', '.join(entry['tags'])}
                """
                doc_id = entry['id']
                
                metadata = {
                    "doc_id": doc_id,
                    "title": entry['title'],
                    "category": entry['category'],
                    "severity": entry['severity'],
                    "type": "diagnosis_flow",
                    "tags": json.dumps(entry['tags']),
                    "diagnosis_tree": json.dumps(entry['diagnosis_tree'])
                }
            else:
                continue
            
            # 添加到向量库
            vector_store.add_texts(
                texts=[content],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            loaded_count += 1
            print(f"✓ 已加载: {entry['title']}")
        
        except Exception as e:
            print(f"✗ 加载失败 {filename}: {str(e)}")
    
    print(f"\n总共加载 {loaded_count} 条知识条目")
    print("=" * 70)
    
    return {
        "status": "success",
        "loaded_count": loaded_count
    }

if __name__ == "__main__":
    initialize_ops_knowledge()
