"""
Memory Module
Combines short-term conversation buffer with long-term ChromaDB vector store.
"""
import os
import logging
import config as app_config


def get_vectorstore():
    """Returns a ChromaDB vector store for long-term memory."""
    from langchain_chroma import Chroma
    from langchain_community.embeddings import OllamaEmbeddings
    
    conf = app_config.load_config()
    memory_conf = conf.get('memory', {})
    ollama_conf = conf.get('ollama', {})
    
    persist_dir = memory_conf.get('persist_directory', 'data/chroma_db')
    host = ollama_conf.get('host', 'http://localhost:11434')
    
    # Use Ollama embeddings (runs locally, no API key needed)
    embeddings = OllamaEmbeddings(
        model="nomic-embed-text",
        base_url=host,
    )
    
    os.makedirs(persist_dir, exist_ok=True)
    
    vectorstore = Chroma(
        collection_name="chat_memory",
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )
    
    logging.info(f"ChromaDB vector store initialized at {persist_dir}")
    return vectorstore


def get_memory(vectorstore=None):
    """
    Returns a combined memory setup:
    - Short-term: ConversationBufferWindowMemory (last N messages)
    - Long-term: VectorStoreRetrieverMemory (semantic search)
    """
    from langchain.memory import ConversationBufferWindowMemory, CombinedMemory, VectorStoreRetrieverMemory
    
    conf = app_config.load_config()
    memory_conf = conf.get('memory', {})
    buffer_size = memory_conf.get('buffer_size', 15)
    
    # Short-term memory
    buffer_memory = ConversationBufferWindowMemory(
        memory_key="chat_history",
        k=buffer_size,
        return_messages=True,
        input_key="input",
    )
    
    # Long-term memory (vector store)
    if vectorstore is None:
        vectorstore = get_vectorstore()
    
    retriever = vectorstore.as_retriever(
        search_kwargs={"k": 5}
    )
    
    vector_memory = VectorStoreRetrieverMemory(
        retriever=retriever,
        memory_key="long_term_memory",
        input_key="input",
    )
    
    # Combine both
    combined = CombinedMemory(memories=[buffer_memory, vector_memory])
    
    logging.info(f"Memory initialized: buffer_size={buffer_size}, vector_k=5")
    return combined


def clear_memory():
    """Clears all memory (both buffer and vector store)."""
    conf = app_config.load_config()
    memory_conf = conf.get('memory', {})
    persist_dir = memory_conf.get('persist_directory', 'data/chroma_db')
    
    import shutil
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir)
        os.makedirs(persist_dir, exist_ok=True)
        logging.info("Memory cleared (ChromaDB wiped).")
    
    return "🧹 Memory cleared! I have forgotten our previous conversation."
