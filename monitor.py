import time
import logging
import asyncio
import ollama
import io
from datetime import datetime
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

import config
import database

# Import Skills
from skills import web_monitor, reminders, workflows, notes, web_search, system_health, erp, registry

import os
from logging.handlers import RotatingFileHandler

# Configure logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "monitor.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=1), # 5MB, 1 backup
        logging.StreamHandler()
    ],
    force=True
)

# --- Main Assistant Logic ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *AI Developer Assistant Online*\n\n"
        "**Features:**\n"
        "🔍 Website Monitoring (Background)\n"
        "🧠 Persistent Memory (I remember our chat)\n"
        "📝 Notes (Type `/note content`)\n"
        "⏰ Reminders (Type `Remind me to...`)\n"
        "📸 Image Analysis\n"
        "🌐 Web Search & Summarization\n"
        "⚙️ System Workflows & Health Monitoring\n"
        "💼 ERP Integration (Tasks, Invoices, Credentials)\n",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *AI Assistant Help*\n\n"
        "Just chat with me normally! I understand natural language.\n\n"
        "*Commands:*\n"
        "/start - Restart bot\n"
        "/help - Show this message\n"
        "/note [content] - Save a quick note\n"
        "/notes - List your notes\n"
        "/reminders - List active reminders\n"
        "/status - Check system health\n"
        "/dashboard - Get Web Dashboard link\n"
        "/workflows - List active system workflows",
        parse_mode='Markdown'
    )

async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 *Web Dashboard*: http://<YOUR_IP>:8000/dashboard\n"
        "💬 *Chat Interface*: http://<YOUR_IP>:8000/chat",
        parse_mode='Markdown'
    )

async def workflows_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = workflows.handle_list_workflows()
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Debug log for ANY update
    logging.info(f"Update received: {update}")
    
    if not update.message:
        return

    user_message = update.message.text
    chat_id = str(update.message.chat_id)
    
    # Handle Image Analysis
    images = []
    if update.message.photo:
        # Get largest photo
        try:
             photo_file = await update.message.photo[-1].get_file()
             import io
             img_byte_arr = io.BytesIO()
             await photo_file.download_to_memory(img_byte_arr)
             images.append(img_byte_arr.getvalue())
             # If no caption, treat as "Describe this"
             if not user_message:
                 user_message = update.message.caption or "Describe this image."
        except Exception as e:
             logging.error(f"Error downloading photo: {e}")
             await update.message.reply_text("Failed to process image.")
             return

    logging.info(f"Processing message from {chat_id}: {user_message}")
    
    conf = config.load_config()
    model = conf['ollama'].get('model', 'gemma3:latest')

    # --- Intelligent Intent Classification ---
    import json
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    system_prompt = f"""
    You are an intelligent assistant. 
    Current Time: {current_time}
    
    Analyze the user's message and determine the optimal action.
    Return ONLY a JSON object.
    
    1. "CHAT": General knowledge, history, cultural facts, or coding help.
    
    --- AVAILABLE SKILLS ---
{registry.get_system_prompt_tools()}
    ------------------------

    Output Format:
    {{
      "action": "ACTION_NAME",
      "params": {{ ... }}
    }}
    
    Examples:
    "Who won the Super Bowl?" -> {{"action": "WEB_SEARCH", "params": {{"query": "Super Bowl winner 2025"}}}}
    "Price of Bitcoin" -> {{"action": "WEB_SEARCH", "params": {{"query": "current price of bitcoin"}}}}
    "Summarize this video: https://youtu.be/xyz" -> {{"action": "SUMMARIZE_CONTENT", "params": {{"url": "https://youtu.be/xyz"}}}}
    "Summarize this video: https://youtu.be/xyz" -> {{"action": "SUMMARIZE_CONTENT", "params": {{"url": "https://youtu.be/xyz"}}}}
    "Show me pending tasks" -> {{"action": "ERP_TASKS", "params": {{}}}}
    "Setup a workflow to check pending tasks every hour" -> {{"action": "SCHEDULE_WORKFLOW", "params": {{"type": "ERP_TASKS", "time": "now", "interval_seconds": 3600}}}}
    "Schedule invoice check daily at 9am" -> {{"action": "SCHEDULE_WORKFLOW", "params": {{"type": "ERP_INVOICES", "time": "9am", "interval_seconds": 86400}}}}
    "What are the due invoices?" -> {{"action": "ERP_INVOICES", "params": {{"type": "due"}}}}
    "Give me an invoice summary" -> {{"action": "ERP_INVOICES", "params": {{"type": "summary"}}}}
    "Get credentials for AWS" -> {{"action": "ERP_CREDENTIALS", "params": {{"search": "AWS"}}}}
    "Show Bennett credential" -> {{"action": "ERP_CREDENTIALS", "params": {{"search": "Bennett"}}}}
    "Search invoices for John" -> {{"action": "ERP_SEARCH_INVOICES", "params": {{"customer_name": "John"}}}}
    "Invoices for customer 123" -> {{"action": "ERP_SEARCH_INVOICES", "params": {{"customer_id": "123"}}}}
    "Cancel BRIEFING workflows" -> {{"action": "CANCEL_WORKFLOW", "params": {{"workflow_type": "BRIEFING"}}}}
    "Remove workflow 5" -> {{"action": "CANCEL_WORKFLOW", "params": {{"workflow_id": 5}}}}
    "Stop checking system health" -> {{"action": "CANCEL_WORKFLOW", "params": {{"workflow_type": "SYSTEM_HEALTH"}}}}
    """
    
    loop = asyncio.get_running_loop()
    
    try:
        # Use image context if available
        msg_payload = {'role': 'user', 'content': f"Message: {user_message}"}
        if images:
            msg_payload['images'] = images
            
        classification_response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
            {'role': 'system', 'content': system_prompt},
            msg_payload
        ]))
        
        raw_json = classification_response['message']['content'].strip()
        
        # Robust JSON extraction
        try:
            # Find first { and last }
            start_idx = raw_json.find('{')
            end_idx = raw_json.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                raw_json = raw_json[start_idx:end_idx+1]
            else:
                logging.warning(f"No JSON object found in response: {raw_json}")
                # Fallback: try cleaning markdown code blocks if the simple find failed (unlikely if valid json)
                raw_json = raw_json.replace("```json", "").replace("```", "").strip()
                
            intent = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logging.error(f"JSON Parse Error: {e}")
            logging.error(f"Raw Response: {classification_response['message']['content']}")
            await update.message.reply_text("⚠️ Brain freeze! I couldn't parse my own thoughts. Please try again.")
            return
        
        logging.info(f"Intent detected: {intent}")
        
        action = intent.get("action")
        params = intent.get("params", {})
        
        # --- EXECUTE ACTION ---
        response_text = ""
        
        if action == "CLEAR_MEMORY":
            database.clear_chat_history()
            await update.message.reply_text("🧹 Memory cleared! I have forgotten our previous conversation.")

        elif action == "DASHBOARD":
            await update.message.reply_text("🌐 *Web Dashboard*: http://<YOUR_IP>:8000/dashboard", parse_mode='Markdown')

        elif action in registry.TOOLS:
            tool_def = registry.TOOLS[action]
            func = tool_def["func"]
            
            # Introspection
            import inspect
            import functools
            sig = inspect.signature(func)
            call_kwargs = {}
            for param_name in sig.parameters:
                if param_name in params:
                    call_kwargs[param_name] = params[param_name]
                elif param_name == "chat_id":
                    call_kwargs["chat_id"] = chat_id
                elif param_name == "update":
                    call_kwargs["update"] = update
                elif param_name == "context":
                    call_kwargs["context"] = context

            logging.info(f"Executing Skill: {action}")
            await update.message.reply_text(f"⚡ Executing {action}...", disable_notification=True)

            try:
                if inspect.iscoroutinefunction(func):
                    response_text = await func(**call_kwargs)
                else:
                    response_text = await loop.run_in_executor(None, functools.partial(func, **call_kwargs))
                
                # Chunking
                response_text = str(response_text)
                if response_text:
                    chunk_size = 4000
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i:i + chunk_size]
                        try:
                            await update.message.reply_text(chunk, parse_mode='Markdown')
                        except Exception:
                            await update.message.reply_text(chunk)
            except Exception as e:
                logging.error(f"Skill execution failed: {e}", exc_info=True)
                await update.message.reply_text(f"⚠️ Skill Error: {e}")

        else: # CHAT or fallback
            # Normal chat logic with memory
             # Save User Context
            database.add_chat_message('user', user_message)
            
            # Fetch history
            history = database.get_recent_chat_history(limit=10)
            messages_payload = []
            messages_payload.append({
                'role': 'system', 
                'content': f"You are a helpful assistant. Current time: {current_time}"
            })
            for role, content in history:
                messages_payload.append({'role': role, 'content': content})
            
            # Current message
            curr_payload = {'role': 'user', 'content': user_message}
            if images:
                curr_payload['images'] = images
            messages_payload.append(curr_payload)
            
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
            
            response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=messages_payload))
            bot_reply = response['message']['content']
            
            try:
                await update.message.reply_text(bot_reply, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(bot_reply)
                
            database.add_chat_message('assistant', bot_reply)

    except Exception as e:
        logging.error(f"Error in handle_message: {e}")
        await update.message.reply_text(f"⚠️ Error processing request: {e}")


import threading
import uvicorn
from web.server import app as web_app

def start_web_server():
    """Starts the FastAPI web server."""
    logging.info("Starting Web Interface on http://0.0.0.0:8000")
    uvicorn.run(web_app, host="0.0.0.0", port=8000, log_level="info", access_log=False)

async def post_init(application: Application):
    """
    Post-initialization hook.
    Using this to start the web server thread.
    """
    # Start Web Server in a separate thread
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    
    # Set bot commands
    await application.bot.set_my_commands([
        ("start", "Start the bot"),
        ("help", "Show help message"),
        ("notes", "Show your notes"),
        ("reminders", "Show your reminders"),
        ("status", "Check system status"),
        ("dashboard", "Get link to Web Dashboard"),
        ("workflows", "List active system workflows")
    ])

def main():
    """Start the bot."""
    database.init_db()
    
    conf = config.load_config()
    if not conf:
        logging.error("Config not found. Exiting.")
        return

    bot_token = conf['telegram'].get('bot_token')
    
    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        logging.error("Bot token not set in config.yaml")
        return

    application = ApplicationBuilder().token(bot_token).post_init(post_init).build()
    
    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('note', notes.handle_note_command))
    application.add_handler(CommandHandler('notes', notes.handle_notes_command))
    application.add_handler(CommandHandler('reminders', reminders.handle_reminders_command))
    application.add_handler(CommandHandler('status', system_health.handle_status_command))
    application.add_handler(CommandHandler('dashboard', dashboard_command))
    application.add_handler(CommandHandler('workflows', workflows_command))
    
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_message))
    
    # Job Queue
    job_queue = application.job_queue
    
    # Monitoring Job
    monitor_interval = conf['monitoring'].get('check_interval_seconds', 300)
    job_queue.run_repeating(web_monitor.check_websites_job, interval=monitor_interval, first=10)
    
    # Reminder Job (Check every 30 seconds)
    job_queue.run_repeating(reminders.check_reminders_job, interval=30, first=5)
    
    # Server Health Job (Check every 10 minutes)
    job_queue.run_repeating(system_health.check_server_health_job, interval=600, first=15)
    
    # Workflow Job (Check every 60 seconds)
    job_queue.run_repeating(workflows.check_workflows_job, interval=60, first=5)
    
    logging.info("AI Assistant (Modularized) started! Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
