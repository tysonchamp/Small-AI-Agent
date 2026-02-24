"""
AI Personal Assistant — Main Entry Point (LangChain Edition)
"""
import os
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "monitor.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=1),
        logging.StreamHandler()
    ],
    force=True
)
# Suppress noisy loggers
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def main():
    """Start the AI Assistant."""
    import config as app_config
    from core.database import init_db
    from bot.telegram_bot import setup_bot
    
    # 1. Initialize Database
    init_db()
    logging.info("✅ Database initialized.")
    
    # 2. Load Config
    conf = app_config.load_config()
    if not conf:
        logging.error("Config not found. Exiting.")
        return
    
    agent_name = conf.get('agent', {}).get('name', 'AI Assistant')
    logging.info(f"🤖 Starting {agent_name} (LangChain Edition)...")
    
    # 3. Verify LLM connectivity
    try:
        from core.llm import get_ollama_llm
        llm = get_ollama_llm()
        logging.info("✅ Ollama LLM connected.")
    except Exception as e:
        logging.error(f"⚠️ Ollama LLM connection failed: {e}")
        logging.error("Make sure Ollama is running: ollama serve")
        return
    
    # 4. Check Gemini (optional)
    try:
        from core.llm import get_gemini_llm
        gemini = get_gemini_llm()
        if gemini:
            logging.info("✅ Gemini LLM configured.")
        else:
            logging.info("ℹ️ Gemini not configured (optional).")
    except Exception:
        logging.info("ℹ️ Gemini not configured (optional).")
    
    # 5. Verify tools load
    try:
        from core.agent import get_all_tools
        tools = get_all_tools()
        logging.info(f"✅ {len(tools)} tools loaded: {[t.name for t in tools]}")
    except Exception as e:
        logging.error(f"⚠️ Tool loading failed: {e}", exc_info=True)
        return
    
    # 6. Setup and run Telegram bot
    application = setup_bot()
    if not application:
        logging.error("Failed to setup Telegram bot. Check bot_token in config.yaml.")
        return
    
    logging.info(f"🚀 {agent_name} (LangChain Edition) started! Press Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()
