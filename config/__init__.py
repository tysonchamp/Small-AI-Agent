import yaml
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Config file is now in the same directory as this __init__.py
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.yaml')

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
            # Environment variables override config file (standard practice)
            # Ensure keys exist before setting
            if 'telegram' not in config: config['telegram'] = {}
            if 'monitoring' not in config: config['monitoring'] = {}

            config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN', config['telegram'].get('bot_token'))
            config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID', config['telegram'].get('chat_id'))
            config['GBYTE_ERP_URL'] = os.getenv('GBYTE_ERP_URL', config.get('GBYTE_ERP_URL'))
            config['API_KEY'] = os.getenv('AI_AGENT_API_KEY', config.get('API_KEY'))
            
            # Default values if missing
            if 'ollama' not in config: config['ollama'] = {'model': 'llama3'}
            
            return config
    except FileNotFoundError:
        logging.error(f"Configuration file {CONFIG_FILE} not found.")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file: {e}")
        return None
