"""
Memory Sync Layer
Embeds structured data (notes, reminders, website changes, emails, etc.)
into ChromaDB for semantic recall by the agent.

Uses a separate collection ('assistant_memory') from chat history ('chat_memory').
"""
import logging
import uuid
from datetime import datetime

import config as app_config


_vectorstore = None


def _get_vectorstore():
    """Returns the assistant_memory ChromaDB collection (singleton)."""
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore
    
    import os
    from langchain_chroma import Chroma
    from langchain_community.embeddings import OllamaEmbeddings
    
    conf = app_config.load_config()
    memory_conf = conf.get('memory', {})
    ollama_conf = conf.get('ollama', {})
    
    persist_dir = memory_conf.get('persist_directory', 'data/chroma_db')
    host = ollama_conf.get('host', 'http://localhost:11434')
    
    embeddings = OllamaEmbeddings(
        model="nomic-embed-text",
        base_url=host,
    )
    
    os.makedirs(persist_dir, exist_ok=True)
    
    _vectorstore = Chroma(
        collection_name="assistant_memory",
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )
    
    logging.info("Memory sync: assistant_memory collection initialized")
    return _vectorstore


def sync_to_memory(category, content, metadata=None):
    """
    Embed a piece of data into ChromaDB for semantic recall.
    
    Args:
        category: Type of data — 'note', 'reminder', 'website_change', 
                  'email', 'workflow', 'content_post', 'erp_task'
        content: The text content to embed
        metadata: Optional dict of extra metadata (url, sender, etc.)
    
    Returns:
        The document ID
    """
    try:
        store = _get_vectorstore()
        
        doc_id = f"{category}_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Build metadata
        meta = {
            "category": category,
            "timestamp": timestamp,
        }
        if metadata:
            for k, v in metadata.items():
                if v is not None:
                    meta[k] = str(v)
        
        # Prefix content with category for better retrieval
        embedded_text = f"[{category.upper()}] {content}"
        
        store.add_texts(
            texts=[embedded_text],
            metadatas=[meta],
            ids=[doc_id],
        )
        
        logging.debug(f"Memory synced: {category} -> {doc_id}")
        return doc_id
        
    except Exception as e:
        logging.error(f"Memory sync error ({category}): {e}")
        return None


def search_memory(query, category=None, k=5):
    """
    Semantic search across all stored memory.
    
    Args:
        query: Search query text
        category: Optional filter — 'note', 'reminder', 'website_change', etc.
        k: Number of results to return
    
    Returns:
        List of dicts with 'content', 'category', 'timestamp', and extra metadata
    """
    try:
        store = _get_vectorstore()
        
        # Build filter
        where_filter = None
        if category:
            where_filter = {"category": category}
        
        results = store.similarity_search_with_relevance_scores(
            query,
            k=k,
            filter=where_filter,
        )
        
        output = []
        for doc, score in results:
            entry = {
                "content": doc.page_content,
                "score": round(score, 3),
            }
            if doc.metadata:
                entry.update(doc.metadata)
            output.append(entry)
        
        return output
        
    except Exception as e:
        logging.error(f"Memory search error: {e}")
        return []


def delete_memory(doc_id):
    """Delete a specific memory document by ID."""
    try:
        store = _get_vectorstore()
        store.delete(ids=[doc_id])
        logging.debug(f"Memory deleted: {doc_id}")
        return True
    except Exception as e:
        logging.error(f"Memory delete error: {e}")
        return False


def get_memory_stats():
    """Get stats about the memory store."""
    try:
        store = _get_vectorstore()
        collection = store._collection
        count = collection.count()
        return {"total_documents": count}
    except Exception as e:
        logging.error(f"Memory stats error: {e}")
        return {"total_documents": 0, "error": str(e)}
