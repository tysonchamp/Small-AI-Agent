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
            
            # Email Config
            if 'email' not in config: config['email'] = {}
            
            # Ensure 'accounts' key exists
            if 'accounts' not in config['email']:
                config['email']['accounts'] = []

            # Handle Legacy/Env Var Override for FIRST account
            email_user = os.getenv('EMAIL_USER')
            email_pass = os.getenv('EMAIL_PASSWORD')
            email_host = os.getenv('EMAIL_HOST')
            
            if email_user and email_pass:
                # Check if we have any accounts to override
                if len(config['email']['accounts']) > 0:
                     # Override the first one
                     config['email']['accounts'][0]['username'] = email_user
                     config['email']['accounts'][0]['password'] = email_pass
                     if email_host: config['email']['accounts'][0]['imap_server'] = email_host
                else:
                    # Create default account from env
                    config['email']['accounts'].append({
                        'account_name': 'Default',
                        'username': email_user,
                        'password': email_pass,
                        'imap_server': email_host or 'imap.gmail.com',
                        'ssl': True,
                        'enabled': True
                    })
            
            # Default values if missing
            
            # Default values if missing
            if 'ollama' not in config: config['ollama'] = {'model': 'llama3'}
            
            return config
    except FileNotFoundError:
        logging.error(f"Configuration file {CONFIG_FILE} not found.")
        return None
    except yaml.YAMLError as e:
        logging.error(f"Error parsing configuration file: {e}")
        return None

def get_user_chat_id(username):
    """
    Resolves a username to a chat_id from config.yaml.
    Case-insensitive match on username.
    """
    conf = load_config()
    if not conf:
        return None
    
    users = conf.get('telegram', {}).get('users', {})
    
    # Direct match
    if username in users:
        return str(users[username])
        
    # Case-insensitive match
    target = username.lower()
    for u, cid in users.items():
        if u.lower() == target:
            return str(cid)
            
    # Smart Substring Match (e.g. "suman da" -> matches "suman")
    # We look for the LONGEST configured username that appears in the requested input.
    matches = []
    for u, cid in users.items():
        u_lower = u.lower()
        if u_lower in target:
            matches.append((u, cid))
            
    if matches:
        # Sort by length of the username (descending) to get specific matches first
        # e.g. input "Alexander", matches "Alex", "Al". We want "Alex".
        matches.sort(key=lambda x: len(x[0]), reverse=True)
        return str(matches[0][1])

    return None
