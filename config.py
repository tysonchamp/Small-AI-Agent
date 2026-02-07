import yaml
import logging
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_FILE = 'config.yaml'

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
            config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN')
            config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID')
            return config
    except FileNotFoundError:
        logging.error(f"Configuration file {CONFIG_FILE} not found.")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file: {e}")
        return None
