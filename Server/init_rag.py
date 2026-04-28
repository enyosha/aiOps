"""
RAG向量索引初始化脚本
扫描Data目录,加载PDF、JSON、TXT文件并建立向量索引
支持 ChromaDB（本地）和 Milvus（远程，通过 SSH 隧道）
"""
import os
import sys
import json
from typing import List, Dict, Optional
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    JSONLoader
)
from pydantic import SecretStr

# Milvus 相关
from pymilvus import (
    connections as milvus_connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility,
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Routing.milvus_tunnel_manager import MilvusTunnelManager

# 加载环境变量
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# 路径配置
DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "Data")
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "vector_store")

# Milvus 配置
MILVUS_LOCAL_PORT = int(os.getenv("MILVUS_LOCAL_PORT", "19531"))
MILVUS_COLLECTION_NAME = "knowledge_base"
MILVUS_EMBEDDING_DIM = 1024  # DashScope text-embedding-v3 输出维度


def load_pdf_files(directory: str) -> List:
    """加载PDF文件"""
    documents = []
    pdf_files = [f for f in os.listdir(directory) if f.endswith('.pdf')]

    if not pdf_files:
        print(f"  INFO: 未找到PDF文件")
        return documents

    print(f"  发现 {len(pdf_files)} 个PDF文件")

    for pdf_file in pdf_files:
        file_path = os.path.join(directory, pdf_file)
        try:
            print(f"    - 加载: {pdf_file}")
            loader = PyPDFLoader(file_path)
            docs = loader.load()

            # 添加源文件标记
            for doc in docs:
                doc.metadata["source"] = pdf_file
                doc.metadata["file_type"] = "pdf"

            documents.extend(docs)
            print(f"      加载成功 ({len(docs)} 页)")
        except Exception as e:
            print(f"      加载失败: {str(e)}")

    return documents


def load_json_qa(directory: str) -> List:
    """加载JSON问答数据"""
    documents = []
    json_files = [f for f in os.listdir(directory) if f.endswith('.json')]

    if not json_files:
        print(f"  INFO: 未找到JSON文件")
        return documents

    print(f"  发现 {len(json_files)} 个JSON文件")

    for json_file in json_files:
        file_path = os.path.join(directory, json_file)
        try:
            print(f"    - 加载: {json_file}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 假设JSON包含问答对列表
            if isinstance(data, list):
                for i, item in enumerate(data):
                    # 支持多种格式: {"question": ..., "answer": ...} 或 {"q": ..., "a": ...} 或 {"问题": ..., "答案": ...}
                    question = (item.get('question') or item.get('q') or 
                               item.get('query') or item.get('问题'))
                    answer = (item.get('answer') or item.get('a') or 
                             item.get('response') or item.get('答案'))

                    if question and answer:
                        from langchain_core.documents import Document
                        content = f"问题: {question}\n答案: {answer}"
                        doc = Document(
                            page_content=content,
                            metadata={
                                "source": json_file,
                                "file_type": "json",
                                "index": i
                            }
                        )
                        documents.append(doc)

                count = len([d for d in documents if d.metadata['source'] == json_file])
                print(f"      加载成功 ({count} 条问答)")
            else:
                print(f"      WARNING: JSON格式不支持(期望数组格式)")

        except Exception as e:
            print(f"      加载失败: {str(e)}")

    return documents


def load_txt_files(directory: str) -> List:
    """加载TXT文本文件"""
    documents = []
    txt_files = [f for f in os.listdir(directory) if f.endswith('.txt')]

    if not txt_files:
        print(f"  INFO: 未找到TXT文件")
        return documents

    print(f"  发现 {len(txt_files)} 个TXT文件")

    for txt_file in txt_files:
        file_path = os.path.join(directory, txt_file)
        try:
            print(f"    - 加载: {txt_file}")
            loader = TextLoader(file_path, encoding='utf-8')
            docs = loader.load()

            # 添加源文件标记
            for doc in docs:
                doc.metadata["source"] = txt_file
                doc.metadata["file_type"] = "txt"

            documents.extend(docs)
            print(f"      加载成功 ({len(docs)} 个文档块)")
        except Exception as e:
            print(f"      加载失败: {str(e)}")

    return documents


def init_milvus_collection() -> Optional[Collection]:
    """初始化 Milvus Collection（创建或获取）"""
    try:
        # 连接到 Milvus（本地隧道端口）
        milvus_connections.connect(
            alias="default",
            host="127.0.0.1",
            port=str(MILVUS_LOCAL_PORT)
        )

        # 检查 Collection 是否已存在
        if utility.has_collection(MILVUS_COLLECTION_NAME):
            print(f"  Milvus Collection '{MILVUS_COLLECTION_NAME}' 已存在，获取引用")
            collection = Collection(MILVUS_COLLECTION_NAME)
            collection.load()
            return collection

        # 定义 Schema
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=MILVUS_EMBEDDING_DIM),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="file_type", dtype=DataType.VARCHAR, max_length=10),
        ]
        schema = CollectionSchema(fields=fields, description="RAG Knowledge Base")
        collection = Collection(name=MILVUS_COLLECTION_NAME, schema=schema)

        # 创建向量索引
        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128}
        }
        collection.create_index(
            field_name="embedding",
            index_params=index_params
        )
        print(f"  Milvus Collection '{MILVUS_COLLECTION_NAME}' 创建成功")
        collection.load()
        return collection

    except Exception as e:
        print(f"  Milvus Collection 初始化失败: {e}")
        return None


def store_to_milvus(valid_docs: List, embeddings_model) -> dict:
    """将文档存储到 Milvus

    Args:
        valid_docs: 已验证的文档块列表（每个有 page_content 和 metadata）
        embeddings_model: DashScope embeddings 模型

    Returns:
        dict: 包含状态和统计信息
    """
    print("\n" + "-" * 50)
    print("Milvus 向量存储")
    print("-" * 50)

    tunnel = MilvusTunnelManager()
    tunnel_ok = tunnel.create_tunnel()
    if not tunnel_ok:
        return {"status": "error", "message": "SSH 隧道建立失败"}

    try:
        # 初始化 Collection
        print("  连接 Milvus...")
        collection = init_milvus_collection()
        if collection is None:
            return {"status": "error", "message": "Milvus Collection 初始化失败"}

        print(f"  开始向量化 {len(valid_docs)} 个文档块...")

        # 分批处理
        batch_size = 20
        total_inserted = 0

        for i in range(0, len(valid_docs), batch_size):
            batch = valid_docs[i:i + batch_size]

            texts = []
            sources = []
            file_types = []
            for doc in batch:
                text = str(doc.page_content).strip()
                texts.append(text)
                sources.append(doc.metadata.get("source", "unknown"))
                file_types.append(doc.metadata.get("file_type", "unknown"))

            # 生成 embedding
            try:
                embeddings = embeddings_model.embed_documents(texts)
            except Exception as emb_err:
                print(f"  批次 {i // batch_size + 1} Embedding 失败: {emb_err}")
                continue

            # 插入 Milvus
            try:
                insert_data = [texts, embeddings, sources, file_types]
                mr = collection.insert(insert_data)
                total_inserted += len(mr.primary_keys)
                if (i // batch_size + 1) % 5 == 0:
                    print(f"  进度: {total_inserted}/{len(valid_docs)}")
            except Exception as ins_err:
                print(f"  批次 {i // batch_size + 1} 插入失败: {ins_err}")
                continue

        # 刷新确保持久化
        collection.flush()
        print(f"  Milvus 存储完成: 已插入 {total_inserted} 条向量")

        return {
            "status": "success",
            "total_inserted": total_inserted,
            "collection": MILVUS_COLLECTION_NAME
        }

    except Exception as e:
        print(f"  Milvus 存储失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

    finally:
        try:
            milvus_connections.disconnect("default")
        except Exception:
            pass
        tunnel.close_tunnel()


def initialize_rag_index():
    """初始化RAG向量索引"""
    print("=" * 70)
    print("RAG向量索引初始化")
    print("=" * 70)

    # 检查Data目录是否存在
    if not os.path.exists(DATA_DIRECTORY):
        print(f"ERROR: Data目录不存在: {DATA_DIRECTORY}")
        return {"status": "error", "message": "Data directory not found"}

    print(f"\n扫描Data目录: {DATA_DIRECTORY}\n")

    # 1. 加载所有文档
    print("步骤 1/4: 加载文档")
    all_documents = []

    all_documents.extend(load_pdf_files(DATA_DIRECTORY))
    all_documents.extend(load_json_qa(DATA_DIRECTORY))
    all_documents.extend(load_txt_files(DATA_DIRECTORY))

    if not all_documents:
        print("\nWARNING: 未找到任何可加载的文档")
        return {"status": "warning", "message": "No documents found"}

    print(f"\n成功加载 {len(all_documents)} 个文档\n")

    # 2. 文本分块
    print("步骤 2/4: 文本分块")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len,
        separators=["\n\n", "\n", "。", "!", "?", ";", ",", " ", ""]
    )

    split_docs = text_splitter.split_documents(all_documents)
    
    # 过滤掉空内容的文档块
    split_docs = [doc for doc in split_docs if doc.page_content and len(doc.page_content.strip()) > 10]
    
    print(f"分块完成: {len(split_docs)} 个文本块\n")
    
    if not split_docs:
        print("\nWARNING: 分块后没有有效的文档内容")
        return {"status": "warning", "message": "No valid chunks after splitting"}

    # 3. 初始化向量存储
    print("步骤 3/4: 初始化向量存储")
    os.makedirs(PERSIST_DIRECTORY, exist_ok=True)

    # 使用DashScope原生SDK
    from langchain_community.embeddings import DashScopeEmbeddings
    
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=DASHSCOPE_API_KEY
    )

    vector_store = Chroma(
        persist_directory=PERSIST_DIRECTORY,
        embedding_function=embeddings,
        collection_name="knowledge_base"
    )

    # 4. 向量化并存储
    print("步骤 4/4: 生成向量并存储")
    print(f"  正在调用Embedding API...")
    
    # 数据清洗:确保所有文档内容都是有效的字符串,并移除特殊字符
    valid_docs = []
    invalid_count = 0
    for i, doc in enumerate(split_docs):
        if hasattr(doc, 'page_content') and isinstance(doc.page_content, str):
            content = doc.page_content.strip()
            
            # 移除控制字符和特殊Unicode字符(保留正常的中英文、标点、换行等)
            cleaned_content = []
            for char in content:
                code = ord(char)
                # 保留: ASCII可打印字符(32-126), 中文汉字范围, 常见标点, 换行制表符
                if (32 <= code <= 126 or  # ASCII可打印字符
                    0x4E00 <= code <= 0x9FFF or  # CJK统一汉字
                    0x3000 <= code <= 0x303F or  # CJK标点符号
                    0xFF00 <= code <= 0xFFEF or  # 全角ASCII、全角标点
                    code in (10, 13, 9)):  # \n, \r, \t
                    cleaned_content.append(char)
                # 跳过其他字符(包括Wingdings等特殊符号)
            
            content = ''.join(cleaned_content).strip()
            
            # 确保内容非空且长度合理
            if len(content) > 10:
                doc.page_content = content
                valid_docs.append(doc)
            else:
                invalid_count += 1
        else:
            invalid_count += 1
    
    if invalid_count > 0:
        print(f"  WARNING: 跳过 {invalid_count} 个无效或过短的文档块")
    
    print(f"  有效文档块: {len(valid_docs)} / {len(split_docs)}")
    
    if not valid_docs:
        print("  ERROR: 没有有效的文档内容")
        return {"status": "error", "message": "No valid document content"}

    try:
        # 批量添加文档到向量库(分批处理以避免API限制)
        batch_size = 20
        total_added = 0
        
        for i in range(0, len(valid_docs), batch_size):
            batch = valid_docs[i:i+batch_size]
            
            # 在发送前再次验证和清理文本
            texts_to_send = []
            docs_to_send = []
            for doc in batch:
                text = doc.page_content
                # 确保是纯字符串
                if isinstance(text, str):
                    # 编码为UTF-8再解码,移除无效字符
                    try:
                        text = text.encode('utf-8', errors='ignore').decode('utf-8')
                        if len(text.strip()) > 5:
                            texts_to_send.append(text)
                            docs_to_send.append(doc)
                    except:
                        pass
            
            if not docs_to_send:
                continue
            
            # 更新batch
            for idx, doc in enumerate(docs_to_send):
                doc.page_content = texts_to_send[idx]
            
            try:
                # 确保传入的文档内容是纯文本列表
                texts = [doc.page_content for doc in docs_to_send]
                metadatas = [doc.metadata for doc in docs_to_send]
                
                # 使用 Chroma 的 add_texts 方法而不是 add_documents
                vector_store.add_texts(
                    texts=texts,
                    metadatas=metadatas
                )
                total_added += len(docs_to_send)
                if (i // batch_size + 1) % 5 == 0 or total_added >= len(valid_docs) * 0.8:
                    print(f"  进度: {total_added}")
            except Exception as batch_error:
                print(f"  ERROR: 批次 {i//batch_size + 1} 失败")
                print(f"    错误详情: {str(batch_error)[:200]}")
                # 打印第一个失败的文档内容预览
                if docs_to_send:
                    preview = str(docs_to_send[0].page_content)[:200]
                    print(f"    内容预览: '{preview}'")
                    print(f"    元数据: {docs_to_send[0].metadata}")
                raise
        
        # ChromaDB会自动持久化,无需手动调用persist
        print(f"  向量存储完成")
        print(f"  总计: {total_added} 个向量")
        print(f"  存储路径: {PERSIST_DIRECTORY}")

    except Exception as e:
        print(f"  向量存储失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

    # 5. 存储到 Milvus（无需与 ChromaDB 共用 embedding，独立调用）
    milvus_result = None
    try:
        milvus_result = store_to_milvus(valid_docs, embeddings)
    except Exception as e:
        print(f"\n  WARNING: Milvus 存储失败（不影响 ChromaDB）: {e}")

    # 统计信息
    source_files = set(doc.metadata.get("source", "unknown") for doc in split_docs)
    file_types = {}
    for doc in split_docs:
        file_type = doc.metadata.get("file_type", "unknown")
        file_types[file_type] = file_types.get(file_type, 0) + 1

    print(f"\n索引统计:")
    print(f"  - 源文件数: {len(source_files)}")
    print(f"  - 文件类型分布: {file_types}")
    print(f"  - 向量总数: {len(split_docs)}")

    print("\n" + "=" * 70)
    print("RAG向量索引初始化完成!")
    print("=" * 70)

    return {
        "status": "success",
        "total_chunks": len(split_docs),
        "source_files": list(source_files),
        "file_types": file_types
    }


if __name__ == "__main__":
    result = initialize_rag_index()

    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)
