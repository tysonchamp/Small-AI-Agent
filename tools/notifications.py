"""
Notifications Tool — Send messages to Telegram users.
"""
import logging
import asyncio
from langchain_core.tools import tool
import config as app_config


@tool
def notify_user(target_user: str, message: str) -> str:
    """Send a message to a specific Telegram user. Use this when the user wants to send a notification or message to someone.
    Args:
        target_user: The username (from config) or chat ID of the recipient.
        message: The message text to send."""
    try:
        conf = app_config.load_config()
        users = conf.get('telegram', {}).get('users', {})
        bot_token = conf['telegram'].get('bot_token')
        
        if not bot_token:
            return "⚠️ Bot token not configured."
        
        # Resolve user
        chat_id = users.get(target_user)
        if not chat_id:
            if target_user.isdigit() or (target_user.startswith('-') and target_user[1:].isdigit()):
                chat_id = target_user
            else:
                return f"⚠️ User '{target_user}' not found in configuration."
        
        # Send via Telegram Bot API
        from telegram import Bot
        
        async def _send():
            bot = Bot(token=bot_token)
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            asyncio.run(_send())
        
        return f"✅ Message sent to *{target_user}*."
    except Exception as e:
        logging.error(f"Notification error: {e}")
        return f"⚠️ Failed to send message: {e}"
