import time
import logging
import asyncio
import ollama
import io
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

import config
import database

# Import Skills
from skills import web_monitor, reminders, workflows, notes, web_search, system_health, erp

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
    ]
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
    
    Possible Actions:
    1. "ADD_REMINDER": User wants to set a reminder (simple text alert).
       - content: what to remind
       - time: natural language time
       - interval_seconds: 0 for one-time, >0 for recurring
    
    2. "SCHEDULE_WORKFLOW": User wants to schedule a SYSTEM TASK.
       - type: "BRIEFING" (morning/daily briefing) or "SYSTEM_HEALTH" (server check)
       - time: when to start (e.g. "at 8am", "now")
       - interval_seconds: frequency (e.g. "every 24h" = 86400, "every 1h" = 3600). 0 if one-off.
    
    3. "LIST_WORKFLOWS": User wants to see active scheduled system tasks.
    
    4. "CANCEL_REMINDER": User wants to cancel reminders.
       - target: "all" or specific keywords
    
    5. "QUERY_SCHEDULE": User asks about their schedule/reminders.
       - time_range: "today", "tomorrow", "all"
    
    6. "NOTE_ADD": User wants to save a note.
       - content: note content
    
    7. "NOTE_LIST": User wants to see notes.
    
    8. "SUMMARIZE_CONTENT": User wants a summary of a Link (YouTube, GitHub, Web).
       - url: the link to summarize
       - instruction: specific question about the content (optional)

    9. "WEB_SEARCH": Use ONLY for Real-Time News, Live Prices, Weather, or Recent Events (post-cutoff). DO NOT use for history, general facts, or cultural holidays.
       - query: the search query
    
    10. "CHAT": General knowledge, history, cultural facts (e.g. "What is Valentine's Day?"), coding help, or image analysis.
    
    11. "CLEAR_MEMORY": User wants to clear chat history/memory.

    12. "SYSTEM_STATUS": User asks about server/system health NOW.

    13. "ERP_TASKS": User wants to see pending tasks from the ERP.
    
    14. "ERP_INVOICES": User wants to see due invoices or a summary.
        - type: "due" or "summary"
    
    15. "ERP_CREDENTIALS": User wants to see project credentials.
        - search: optional keyword (e.g. "vps", "aws")
    
    16. "ERP_SEARCH_INVOICES": User wants to search invoices by customer name OR ID.
        - customer_name: name to search
        - customer_id: precise ID

    Output Format:
    {{
      "action": "ACTION_NAME",
      "params": {{ ... }}
    }}
    
    Examples:
    "Who won the Super Bowl?" -> {{"action": "WEB_SEARCH", "params": {{"query": "Super Bowl winner 2025"}}}}
    "Price of Bitcoin" -> {{"action": "WEB_SEARCH", "params": {{"query": "current price of bitcoin"}}}}
    "Summarize this video: https://youtu.be/xyz" -> {{"action": "SUMMARIZE_CONTENT", "params": {{"url": "https://youtu.be/xyz"}}}}
    "Show me pending tasks" -> {{"action": "ERP_TASKS", "params": {{}}}}
    "What are the due invoices?" -> {{"action": "ERP_INVOICES", "params": {{"type": "due"}}}}
    "Give me an invoice summary" -> {{"action": "ERP_INVOICES", "params": {{"type": "summary"}}}}
    "Get credentials for AWS" -> {{"action": "ERP_CREDENTIALS", "params": {{"search": "AWS"}}}}
    "Show Bennett credential" -> {{"action": "ERP_CREDENTIALS", "params": {{"search": "Bennett"}}}}
    "Search invoices for John" -> {{"action": "ERP_SEARCH_INVOICES", "params": {{"customer_name": "John"}}}}
    "Invoices for customer 123" -> {{"action": "ERP_SEARCH_INVOICES", "params": {{"customer_id": "123"}}}}
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
        raw_json = raw_json.replace("```json", "").replace("```", "").strip()
        intent = json.loads(raw_json)
        
        logging.info(f"Intent detected: {intent}")
        
        action = intent.get("action")
        params = intent.get("params", {})
        
        # --- EXECUTE ACTION ---
        response_text = ""
        
        if action == "WEB_SEARCH":
            query = params.get("query")
            response_text = await web_search.handle_web_search(update, context, query)

        elif action == "SUMMARIZE_CONTENT":
            url = params.get("url")
            instruction = params.get("instruction", "Summarize this content effectively.")
            response_text = await web_search.handle_summarize_content(update, context, url, instruction)

        elif action == "SCHEDULE_WORKFLOW":
            response_text = await workflows.handle_schedule_workflow(
                params.get("type"), 
                params.get("time"), 
                params.get("interval_seconds", 0)
            )
            await update.message.reply_text(response_text, parse_mode='Markdown')

        elif action == "LIST_WORKFLOWS":
            response_text = workflows.handle_list_workflows()
            await update.message.reply_text(response_text, parse_mode='Markdown')

        elif action == "ADD_REMINDER":
            response_text = await reminders.handle_add_reminder(
                chat_id, 
                params.get("content"), 
                params.get("time"), 
                params.get("interval_seconds", 0)
            )
            await update.message.reply_text(response_text)

        elif action == "CANCEL_REMINDER":
            response_text = await reminders.handle_cancel_reminder(chat_id, params.get("target"))
            await update.message.reply_text(response_text)

        elif action == "QUERY_SCHEDULE":
            response_text = await reminders.handle_query_schedule(chat_id, params.get("time_range"))
            await update.message.reply_text(response_text, parse_mode='Markdown')

        elif action == "NOTE_ADD":
            response_text = notes.handle_add_note(params.get("content"))
            await update.message.reply_text(response_text)

        elif action == "NOTE_LIST":
            response_text = notes.handle_list_notes()
            await update.message.reply_text(response_text, parse_mode='Markdown')

        elif action == "CLEAR_MEMORY":
            database.clear_chat_history()
            await update.message.reply_text("🧹 Memory cleared! I have forgotten our previous conversation.")

        elif action == "SYSTEM_STATUS":
             await update.message.reply_text("🔍 Checking system status...")
             # Re-import to allow hot-reloading if we edit system_health (though less likely with skills split)
             import importlib
             importlib.reload(system_health)
             
             report = system_health.get_system_status(conf)
             await update.message.reply_text(report, parse_mode='Markdown')

        elif action == "ERP_TASKS":
            await update.message.reply_text("📋 Fetching pending tasks...")
            msg = await loop.run_in_executor(None, erp.get_pending_tasks)
            await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "ERP_INVOICES":
            req_type = params.get('type', 'due')
            if req_type == 'summary':
                await update.message.reply_text("📊 Fetching invoice summary...")
                msg = await loop.run_in_executor(None, erp.get_invoice_summary)
            else:
                await update.message.reply_text("💰 Fetching due invoices...")
                msg = await loop.run_in_executor(None, erp.get_due_invoices)
            
            await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "ERP_CREDENTIALS":
            search_query = params.get('search')
            if search_query:
                await update.message.reply_text(f"🔐 Searching credentials for '{search_query}'...")
                msg = await loop.run_in_executor(None, erp.get_credentials, search_query)
            else:
                await update.message.reply_text("🔐 Fetching all credentials...")
                msg = await loop.run_in_executor(None, erp.get_credentials)
            await update.message.reply_text(msg, parse_mode='Markdown')
            
        elif action == "ERP_SEARCH_INVOICES":
             customer_name = params.get('customer_name')
             customer_id = params.get('customer_id')
             if not customer_name and not customer_id:
                 await update.message.reply_text("❓ Please specify a customer name or ID.")
             else:
                 await update.message.reply_text(f"🔎 Searching invoices...")
                 msg = await loop.run_in_executor(None, erp.search_invoices, customer_name, customer_id)
                 await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "WEB_SEARCH" or action == "SUMMARIZE_CONTENT":
             # Already handled above and populated response_text.
             # Need to chunk and send.
             if response_text:
                 chunk_size = 4000
                 for i in range(0, len(response_text), chunk_size):
                     chunk = response_text[i:i + chunk_size]
                     try:
                         await update.message.reply_text(chunk, parse_mode='Markdown')
                     except Exception:
                         await update.message.reply_text(chunk)

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


def main():
    database.init_db()
    
    conf = config.load_config()
    if not conf:
        logging.error("Config not found. Exiting.")
        return

    bot_token = conf['telegram'].get('bot_token')
    
    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        logging.error("Bot token not set in config.yaml")
        return

    application = ApplicationBuilder().token(bot_token).build()
    
    # Handlers
    application.add_handler(CommandHandler('start', start))
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
