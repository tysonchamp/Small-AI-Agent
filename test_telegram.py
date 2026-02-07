import yaml
import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CONFIG_FILE = 'config.yaml'

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        return None

def test_telegram():
    config = load_config()
    if not config:
        return

    bot_token = config['telegram'].get('bot_token')
    chat_id = config['telegram'].get('chat_id')

    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        logging.error("Bot token not configured!")
        return
    
    if not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        logging.error("Chat ID not configured!")
        return

    # 1. Test getMe
    url_me = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        response = requests.get(url_me)
        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                logging.info(f"✅ Telegram Bot Token is valid! Bot Name: {bot_info['result']['first_name']} (@{bot_info['result']['username']})")
            else:
                logging.error(f"❌ API returned error: {bot_info}")
        else:
            logging.error(f"❌ Failed to connect to Telegram API. Status: {response.status_code}")
    except Exception as e:
        logging.error(f"❌ Connection error: {e}")
        return

    # 2. Test sendMessage
    url_send = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ Test Message: Your website monitor credentials are working correctly!"
    }
    try:
        response = requests.post(url_send, json=payload)
        if response.status_code == 200:
            logging.info(f"✅ Successfully sent a test message to Chat ID: {chat_id}")
        else:
            logging.error(f"❌ Failed to send message to Chat ID {chat_id}. Status: {response.status_code}. Response: {response.text}")
            logging.error("Make sure the user has started a chat with the bot first!")
    except Exception as e:
        logging.error(f"❌ Error sending message: {e}")

if __name__ == "__main__":
    test_telegram()
