from skills.registry import skill, TOOLS
import config
from telegram import Bot
import logging
import asyncio
import inspect

@skill(name="NOTIFY_USER", description="Send the output of another skill to a specific user. Params: target_user (name/id), skill_name (e.g. ERP_TASKS), skill_params (dict, optional)")
async def notify_user(target_user: str, skill_name: str, skill_params: dict = None):
    # 1. Resolve User
    conf = config.load_config()
    users = conf.get('telegram', {}).get('users', {})
    
    chat_id = users.get(target_user)
    if not chat_id:
        # Check if it looks like a raw ID
        if target_user.isdigit() or (target_user.startswith('-') and target_user[1:].isdigit()):
            chat_id = target_user
        else:
            return f"⚠️ User '{target_user}' not found in configuration."

    # 2. Resolve Skill
    tool_def = TOOLS.get(skill_name)
    if not tool_def:
        return f"⚠️ Skill '{skill_name}' not found."
    
    func = tool_def["func"]
    
    # 3. Execute Skill
    # We need to handle parameters carefully. 
    # If skill_params is None, use empty dict
    if skill_params is None:
        skill_params = {}
        
    try:
        logging.info(f"NOTIFY_USER: Executing {skill_name} for {target_user} ({chat_id})")
        
        # Introspection to match params (similar to monitor.py)
        # But here we assume skill_params matches what the func expects or func handles defaults.
        # Most of our skills take specific named args.
        
        if inspect.iscoroutinefunction(func):
            result = await func(**skill_params)
        else:
            # Run sync function in executor? 
            # If we are in an async function (which we are), we should use loop.run_in_executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: func(**skill_params))
            
    except Exception as e:
        logging.error(f"Error executing skill {skill_name} in NOTIFY_USER: {e}")
        return f"⚠️ Error executing {skill_name}: {e}"

    if not result:
        return f"⚠️ {skill_name} returned no output."

    # 4. Send Message via Telegram
    bot_token = conf['telegram'].get('bot_token')
    if not bot_token:
        return "⚠️ Bot token not configured."
        
    try:
        bot = Bot(token=bot_token)
        # send_message is a coroutine
        await bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')
        return f"✅ Sent output of *{skill_name}* to *{target_user}*."
    except Exception as e:
        error_str = str(e)
        if "Chat not found" in error_str:
             logging.error(f"❌ FAILED to send to {target_user} ({chat_id}): Chat not found. The user likely hasn't started the bot.")
        else:
             logging.error(f"Error sending telegram message to {chat_id}: {e}")
        return f"⚠️ Failed to send message: {e}"
