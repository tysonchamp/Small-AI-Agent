import ollama
import config
import logging

def get_client():
    """
    Returns a configured Ollama client instance.
    Reads 'host' and 'api_key' from config.yaml.
    """
    conf = config.load_config()
    ollama_conf = conf.get('ollama', {})
    
    host = ollama_conf.get('host')
    api_key = ollama_conf.get('api_key')
    
    # If host is not set, it defaults to localhost:11434 in the library usually, 
    # but we can be explicit or let the library handle it if None.
    # The python-ollama library (v0.1.6+) supports `Client(host=...)`.
    
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        # Or "x-api-key": api_key depending on the proxy/server auth method.
        # Standard Ollama doesn't have auth, but proxies do. 
        # We will assume Bearer token if an API key is provided, or just pass it as generic header?
        # Let's use it as a custom header if needed, but usually Bearer is safe for standard auth middlewares.
        
    try:
        client = ollama.Client(host=host, headers=headers)
        return client
    except Exception as e:
        logging.error(f"Failed to initialize Ollama client: {e}")
        # Fallback to default client (localhost)
        return ollama.Client()
