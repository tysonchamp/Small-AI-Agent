"""
LLM Provider Factory
Provides ChatOllama (local, fast) and ChatGoogleGenerativeAI (complex tasks, images).
"""
import logging
import config as app_config

def get_ollama_llm():
    """Returns a ChatOllama instance for general tasks."""
    from langchain_ollama import ChatOllama
    
    conf = app_config.load_config()
    ollama_conf = conf.get('ollama', {})
    
    host = ollama_conf.get('host', 'http://localhost:11434')
    model = ollama_conf.get('model', 'gemma3:latest')
    api_key = ollama_conf.get('api_key', '')
    
    kwargs = {
        "model": model,
        "base_url": host,
        "temperature": 0.3,
    }
    
    # If an API key is set (for auth proxy), pass it as header
    if api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
    
    try:
        llm = ChatOllama(**kwargs)
        logging.info(f"Ollama LLM initialized: model={model}, host={host}")
        return llm
    except Exception as e:
        logging.error(f"Failed to initialize Ollama LLM: {e}")
        raise


def get_gemini_llm():
    """Returns a ChatGoogleGenerativeAI instance for complex tasks (coding, images)."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    conf = app_config.load_config()
    gemini_conf = conf.get('gemini', {})
    
    api_key = gemini_conf.get('api_key', '')
    model = gemini_conf.get('model', 'gemini-2.0-flash')
    
    if not api_key:
        logging.warning("Gemini API key not set. Gemini LLM will not be available.")
        return None
    
    try:
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.3,
            convert_system_message_to_human=True,
        )
        logging.info(f"Gemini LLM initialized: model={model}")
        return llm
    except Exception as e:
        logging.error(f"Failed to initialize Gemini LLM: {e}")
        return None


def get_llm(task_type="general"):
    """
    Router that selects the right LLM based on task type.
    
    Args:
        task_type: "general" for Ollama, "complex" for Gemini (with Ollama fallback)
    """
    if task_type == "complex":
        gemini = get_gemini_llm()
        if gemini:
            return gemini
        logging.warning("Gemini unavailable, falling back to Ollama for complex task.")
    
    return get_ollama_llm()
