"""
Telegram Bot Interface
Handles all Telegram commands, messages, and background jobs.
"""
import logging
import asyncio
from functools import wraps
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, filters
)

import config as app_config
from core import database

# Cached agent singleton
_agent_instance = None

def _get_agent():
    global _agent_instance
    if _agent_instance is None:
        from core.agent import create_agent
        _agent_instance = create_agent()
    return _agent_instance


# --- Authorization Decorator ---
def authorized_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        conf = app_config.load_config()
        admin_id = str(conf['telegram'].get('chat_id', '')).strip()
        user_id = str(update.effective_chat.id).strip()
        
        if not admin_id:
            await update.message.reply_text("⛔ Configuration Error: Admin ID not set.")
            return
        
        if admin_id != user_id:
            logging.warning(f"⛔ Unauthorized access attempt from {user_id}")
            await update.message.reply_text("⛔ Unauthorized access. This is a private bot.")
            return
        
        return await func(update, context, *args, **kwargs)
    return wrapper


# --- Command Handlers ---
@authorized_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conf = app_config.load_config()
    agent_name = conf.get('agent', {}).get('name', 'AI Assistant')
    
    await update.message.reply_text(
        f"👋 *{agent_name} Online (LangChain Edition)*\n\n"
        "**Features:**\n"
        "🔍 Website Monitoring\n"
        "🧠 Vector Store Memory\n"
        "📝 Notes & Reminders\n"
        "🌐 Web Search & Summarization\n"
        "⚙️ System Health & Workflows\n"
        "💼 ERP Integration\n"
        "📧 Email Integration\n"
        "🤖 SEO Expert & Meta-Coder\n",
        parse_mode='Markdown'
    )


@authorized_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *AI Assistant Help*\n\n"
        "Just chat with me naturally! I understand natural language.\n\n"
        "*Commands:*\n"
        "/start - Restart bot\n"
        "/help - Show this message\n"
        "/note [content] - Save a quick note\n"
        "/notes - List your notes\n"
        "/reminders - List active reminders\n"
        "/status - Check system health\n"
        "/dashboard - Get Web Dashboard link\n"
        "/emails - Check unread emails\n"
        "/workflows - List active workflows",
        parse_mode='Markdown'
    )


@authorized_only
async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 *Web Dashboard*: http://localhost:8000/\n"
        "💬 *Chat Interface*: http://localhost:8000/chat\n"
        "*Note*: Use your computer's IP address for remote access.",
        parse_mode='Markdown'
    )


@authorized_only
async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /note [content]")
        return
    content = " ".join(context.args)
    database.add_note(content)
    await update.message.reply_text("✅ Note saved.")


@authorized_only
async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from tools.notes import list_notes
    result = list_notes.invoke({"limit": 10})
    await update.message.reply_text(result, parse_mode='Markdown')


@authorized_only
async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from tools.reminders import query_schedule
    result = query_schedule.invoke({"time_range": "all"})
    await update.message.reply_text(result, parse_mode='Markdown')


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from tools.system_health import get_system_status
    await update.message.reply_text("🔄 Checking system health...")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: get_system_status.invoke({}))
    try:
        await update.message.reply_text(result, parse_mode='Markdown')
    except Exception:
        await update.message.reply_text(result)


@authorized_only
async def workflows_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from tools.workflows import list_workflows
    result = list_workflows.invoke({})
    await update.message.reply_text(result, parse_mode='Markdown')


@authorized_only
async def emails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from tools.email_ops import check_emails
    await update.message.reply_text("📧 Checking emails...")
    result = check_emails.invoke({"limit": 5})
    try:
        await update.message.reply_text(result, parse_mode='Markdown')
    except Exception:
        await update.message.reply_text(result)


# --- Main Message Handler ---
@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user_message = update.message.text
    chat_id = str(update.message.chat_id)
    
    # Handle Image Analysis (use Gemini for multimodal)
    images = []
    if update.message.photo:
        try:
            import io
            import base64
            photo_file = await update.message.photo[-1].get_file()
            img_byte_arr = io.BytesIO()
            await photo_file.download_to_memory(img_byte_arr)
            images.append(base64.b64encode(img_byte_arr.getvalue()).decode('utf-8'))
            if not user_message:
                user_message = update.message.caption or "Describe this image."
        except Exception as e:
            logging.error(f"Error downloading photo: {e}")
            await update.message.reply_text("Failed to process image.")
            return
    
    if not user_message:
        return
    
    logging.info(f"Processing message from {chat_id}: {user_message}")
    
    # Handle clear memory command
    if user_message.lower().strip() in ["clear memory", "forget everything", "reset chat"]:
        from core.memory import clear_memory
        result = clear_memory()
        await update.message.reply_text(result)
        return
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    
    try:
        # Handle image messages with Gemini
        if images:
            from core.llm import get_gemini_llm
            from langchain_core.messages import HumanMessage
            
            gemini = get_gemini_llm()
            if gemini:
                message = HumanMessage(
                    content=[
                        {"type": "text", "text": user_message},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{images[0]}"}}
                    ]
                )
                response = gemini.invoke([message])
                reply = response.content
            else:
                reply = "⚠️ Image analysis requires Gemini API key. Please configure it in config.yaml."
        else:
            # Use the cached LangChain agent for text messages
            agent = _get_agent()
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: agent.invoke({"input": user_message, "chat_history": []})
            )
            reply = result.get("output", "I couldn't process that request.")
        
        # Send response (chunked if too long)
        chunk_size = 4000
        for i in range(0, len(reply), chunk_size):
            chunk = reply[i:i + chunk_size]
            try:
                await update.message.reply_text(chunk, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(chunk)
    
    except Exception as e:
        logging.error(f"Error in handle_message: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Error: {str(e)[:200]}")


def setup_bot():
    """Creates and configures the Telegram bot application."""
    conf = app_config.load_config()
    bot_token = conf['telegram'].get('bot_token')
    
    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        logging.error("Bot token not set in config.yaml")
        return None
    
    application = ApplicationBuilder().token(bot_token)\
        .connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0)\
        .post_init(post_init).build()
    
    # Command Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('note', note_command))
    application.add_handler(CommandHandler('notes', notes_command))
    application.add_handler(CommandHandler('reminders', reminders_command))
    application.add_handler(CommandHandler('status', status_command))
    application.add_handler(CommandHandler('dashboard', dashboard_command))
    application.add_handler(CommandHandler('workflows', workflows_command))
    application.add_handler(CommandHandler('check_email', emails_command))
    
    # Message Handler (text + photo)
    application.add_handler(
        MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_message)
    )
    
    # --- Job Queue Setup ---
    from tools.web_monitor import check_websites_job
    from tools.system_health import check_server_health_job
    from tools.reminders import check_reminders_job
    from tools.workflows import check_workflows_job
    from tools.email_ops import check_email_job
    from tools.content_researcher import research_content_job
    
    job_queue = application.job_queue
    
    # Website Monitoring
    interval = conf['monitoring'].get('check_interval_seconds', 3600)
    job_queue.run_repeating(check_websites_job, interval=interval, first=10)
    
    # Server Health (Every 10 mins)
    job_queue.run_repeating(check_server_health_job, interval=600, first=30)
    
    # Reminder Check (Every 30 seconds)
    job_queue.run_repeating(check_reminders_job, interval=30, first=5)
    
    # Workflow Check (Every 1 minute)
    job_queue.run_repeating(check_workflows_job, interval=60, first=5)
    
    # Email Check
    email_interval = conf.get('email', {}).get('check_interval_seconds', 1800)
    job_queue.run_repeating(check_email_job, interval=email_interval, first=20)
    
    # Content Research (Every 4 hours)
    job_queue.run_repeating(research_content_job, interval=14400, first=60)
    
    logging.info(f"Jobs scheduled: Monitor({interval}s), Health(600s), Reminders(30s), Workflows(60s), Email({email_interval}s), Content(4h)")
    
    return application


async def post_init(application):
    """Post-initialization — starts web server and sets bot commands."""
    import threading
    import uvicorn
    from web.server import app as web_app
    
    # Start web server in background thread
    def start_web():
        logging.info("Starting Web Interface on http://0.0.0.0:8000")
        uvicorn.run(web_app, host="0.0.0.0", port=8000, log_level="info", access_log=False)
    
    web_thread = threading.Thread(target=start_web, daemon=True)
    web_thread.start()
    
    # Set bot commands
    await application.bot.set_my_commands([
        ("start", "Start the bot"),
        ("help", "Show help message"),
        ("notes", "Show your notes"),
        ("reminders", "Show your reminders"),
        ("status", "Check system status"),
        ("dashboard", "Get link to Web Dashboard"),
        ("workflows", "List active system workflows"),
        ("check_email", "Force an immediate email check"),
    ])
