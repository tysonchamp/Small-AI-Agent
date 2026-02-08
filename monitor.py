import time
import logging
import asyncio
import ollama
import io
import dateparser
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

import config
import database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("monitor.log"),
        logging.StreamHandler()
    ]
)

# --- Website Monitoring Logic ---

def get_website_content(url):
    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/1.0; +http://github.com/user/repo)'
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        raise e

def get_content_hash(content):
    import hashlib
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def clean_html(html_content):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup(["script", "style"]):
        script.extract()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    return text

def analyze_changes_with_ollama(old_content, new_content, model):
    if not old_content:
        return "Initial content fetch. No previous content to compare."
    
    old_text = clean_html(old_content)[:4000]
    new_text = clean_html(new_content)[:4000]
    
    prompt = f"""
    You are a website monitoring assistant. Verify if there are meaningful changes between the old and new website content below.
    Ignore minor changes like timestamps, CSRF tokens, dynamic ads, or slight formatting differences.
    
    Return your analysis in STRICT JSON format with two keys:
    1. "has_meaningful_change": boolean (true if meaningful changes exist, false otherwise)
    2. "summary": string (concise summary of changes, or null if no meaningful changes)

    Do not include any conversational text outside the JSON.

    OLD CONTENT:
    {old_text}

    NEW CONTENT:
    {new_text}
    """

    try:
        response = ollama.chat(model=model, messages=[
            {'role': 'user', 'content': prompt},
        ])
        content = response['message']['content'].strip()
        
        # improved parsing logic
        import json
        import re
        
        try:
            # Try parsing directly
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from text (in case model is chatty)
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except:
                    data = None
            else:
                data = None
        
        if data:
            if not data.get("has_meaningful_change"):
                return None
            return data.get("summary")
            
        # Fallback if JSON parsing failed completely
        lower_content = content.lower()
        if "no meaningful change" in lower_content:
            return None
            
        return content

    except Exception as e:
        logging.error(f"Error querying Ollama: {e}")
        return f"Error analyzing changes with AI: {e}"

async def check_websites_job(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Starting scheduled website check...")
    conf = config.load_config()
    if not conf:
        return

    conn = database.get_connection()
    c = conn.cursor()
    
    chat_id = conf['telegram'].get('chat_id')
    model = conf['ollama'].get('model', 'llama3')
    
    # Get the running loop for executor
    loop = asyncio.get_running_loop()

    for url in conf['monitoring']['websites']:
        logging.info(f"Checking {url}...")
        
        try:
            # Run blocking request in a separate thread
            current_content = await loop.run_in_executor(None, get_website_content, url)
        except Exception as e:
            error_msg = f"⚠️ *Error Monitoring Website* \n\nURL: {url}\n\nError: `{str(e)}`"
            logging.error(f"Error checking {url}: {e}")
            if chat_id:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=error_msg, parse_mode='Markdown')
                except Exception as send_e:
                    logging.error(f"Failed to send error notification: {send_e}")
            continue
        
        if not current_content:
            continue

        current_hash = get_content_hash(current_content)
        
        c.execute("SELECT content_hash, last_content FROM websites WHERE url=?", (url,))
        row = c.fetchone()
        
        if row is None:
            c.execute("INSERT INTO websites (url, content_hash, last_checked, last_content) VALUES (?, ?, ?, ?)",
                      (url, current_hash, time.strftime('%Y-%m-%d %H:%M:%S'), current_content))
            conn.commit()
            logging.info(f"Initial check for {url}. Content stored.")
        elif row[0] != current_hash:
            logging.info(f"Change detected for {url}!")
            old_content = row[1]
            
            # analyze_changes_with_ollama involves network calls to Ollama too (requests to localhost)
            # ideally this should also be async or threaded, but it's less likely to hang for long than external sites.
            # strict correctness: threaded.
            analysis = await loop.run_in_executor(None, analyze_changes_with_ollama, old_content, current_content, model)
            
            if analysis:
                msg = f"📢 *Website Change Detected!* \n\nURL: {url}\n\nAI Analysis:\n{analysis}"
                if chat_id:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                    except Exception as send_e:
                         logging.error(f"Failed to send change notification: {send_e}")
            else:
                logging.info(f"No meaningful changes for {url}. Notification suppressed.")

            c.execute("UPDATE websites SET content_hash=?, last_checked=?, last_content=? WHERE url=?",
                      (current_hash, time.strftime('%Y-%m-%d %H:%M:%S'), current_content, url))
            conn.commit()
        else:
            logging.info(f"No changes for {url}.")
            
    conn.close()


# --- Reminder Logic ---

async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    reminders = database.get_pending_reminders() # Returns (id, chat_id, content, interval_seconds)
    
    for r in reminders:
        r_id, chat_id, content, interval = r
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ *REMINDER*\n\n{content}", parse_mode='Markdown')
            
            if interval > 0:
                # Reschedule
                next_time = datetime.now() + timedelta(seconds=interval)
                database.reschedule_reminder(r_id, next_time)
                logging.info(f"Rescheduled reminder {r_id} to {next_time}")
            else:
                database.mark_reminder_sent(r_id)
                logging.info(f"Sent reminder {r_id} to {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send reminder {r_id}: {e}")


# --- Server Monitoring Logic ---

async def check_server_health_job(context: ContextTypes.DEFAULT_TYPE):
    import system_monitor
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    
    if not chat_id:
        return

    # custom check to get objects, not string report
    for server in conf.get('servers', []):
        try:
            if server.get('type') == 'local':
                data = system_monitor.check_local_health()
            else:
                data = system_monitor.check_ssh_health(server)
            
            # Check thresholds
            alert_needed = False
            msg = f"⚠️ *Server Alert: {data['name']}*\n"
            
            if data.get('status') == 'offline':
                msg += f"🔴 Server is OFFLINE! Error: {data.get('error')}"
                alert_needed = True
            else:
                if data.get('disk_percent', 0) > 90:
                    msg += f"💿 Disk usage high: {data['disk_percent']}%\n"
                    alert_needed = True
                
                if data.get('ram_percent', 0) > 95:
                    msg += f"🧠 RAM usage critical: {data['ram_percent']}%\n"
                    alert_needed = True
            
            if alert_needed:
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                
        except Exception as e:
            logging.error(f"Error in server check job: {e}")


# --- Chat & Assistant Logic ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conf = config.load_config()
    model = conf['ollama'].get('model', 'llama3')
    chat_id = update.effective_chat.id
    
    user_message = ""
    images = []

    if update.message.text:
        user_message = update.message.text
    elif update.message.caption:
        user_message = update.message.caption

    if update.message.photo:
        photo = update.message.photo[-1]
        try:
            file = await context.bot.get_file(photo.file_id)
            f = io.BytesIO()
            await file.download_to_memory(f)
            f.seek(0)
            images.append(f.read())
            if not user_message:
                user_message = "Analyze this image."
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error downloading image: {e}")
            return

    # --- Intelligent Intent Classification ---
    import json
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    system_prompt = f"""
    You are an intelligent assistant. 
    Current Time: {current_time}
    
    Analyze the user's message and determine the optimal action.
    Return ONLY a JSON object.
    
    Possible Actions:
    1. "ADD_REMINDER": User wants to set a reminder.
       - content: what to remind
       - time: natural language time (e.g. "in 10 min", "tomorrow at 5pm")
       - interval_seconds: 0 for one-time, >0 for recurring (e.g. "every 30s" = 30)
    
    2. "CANCEL_REMINDER": User wants to cancel reminders.
       - target: "all" or specific keywords (e.g. "milk")
    
    3. "QUERY_SCHEDULE": User asks about their schedule/reminders.
       - time_range: "today", "tomorrow", "all"
    
    4. "NOTE_ADD": User wants to save a note.
       - content: note content
    
    5. "NOTE_LIST": User wants to see notes.
    
    6. "CHAT": General conversation, coding help, or image analysis.
    
    7. "CLEAR_MEMORY": User wants to clear chat history/memory.

    8. "SYSTEM_STATUS": User asks about server/system health.
    
    Output Format:
    {{
      "action": "ACTION_NAME",
      "params": {{ ... }}
    }}
    
    Examples:
    "Remind me every 30s to check logs" -> {{"action": "ADD_REMINDER", "params": {{"content": "check logs", "time": "in 0s", "interval_seconds": 30}}}}
    "Cancel all reminders" -> {{"action": "CANCEL_REMINDER", "params": {{"target": "all"}}}}
    "Do I have any meetings tomorrow?" -> {{"action": "QUERY_SCHEDULE", "params": {{"time_range": "tomorrow"}}}}
    "Save note: API key 123" -> {{"action": "NOTE_ADD", "params": {{"content": "API key 123"}}}}
    "Clear my memory" -> {{"action": "CLEAR_MEMORY", "params": {{}}}}
    "How are the servers?" -> {{"action": "SYSTEM_STATUS", "params": {{}}}}
    "Hi" -> {{"action": "CHAT", "params": {{}}}}
    """
    
    try:
        # Use image context if available
        msg_payload = {'role': 'user', 'content': f"Message: {user_message}"}
        if images:
            msg_payload['images'] = images
            
        classification_response = ollama.chat(model=model, messages=[
            {'role': 'system', 'content': system_prompt},
            msg_payload
        ])
        
        raw_json = classification_response['message']['content'].strip()
        raw_json = raw_json.replace("```json", "").replace("```", "").strip()
        intent = json.loads(raw_json)
        
        logging.info(f"Intent detected: {intent}")
        
        action = intent.get("action")
        params = intent.get("params", {})
        
        # --- EXECUTE ACTION ---
        
        if action == "ADD_REMINDER":
            r_content = params.get("content")
            r_time_str = params.get("time")
            r_interval = params.get("interval_seconds", 0)
            
            dt = dateparser.parse(r_time_str, settings={'PREFER_DATES_FROM': 'future'})
            
             # Fallback logic
            if not dt and r_time_str and ("in" in r_time_str or "every" in r_time_str):
                 # Try to force a reparsing or use interval
                  pass # dateparser usually handles "in X" well.
            
            if not dt and r_interval > 0:
                 dt = datetime.now() + timedelta(seconds=r_interval)
            
            # If still invalid, default to now + small delay? Or error?
            if not dt: 
                 # One last try: if they said "every 30s", dateparser might return None.
                 # Only if we have interval we can save it.
                 pass

            if dt:
                database.add_reminder(chat_id, r_content, dt, r_interval)
                resp = f"✅ Reminder set: '{r_content}' at {dt.strftime('%H:%M:%S')}"
                if r_interval > 0:
                    resp += f" (Every {r_interval}s)"
                await update.message.reply_text(resp)
            else:
                 await update.message.reply_text(f"❓ Couldn't parse time for reminder: '{r_content}'")

        elif action == "CANCEL_REMINDER":
            target = params.get("target")
            if target == "all":
                count = database.delete_all_pending_reminders(chat_id)
                await update.message.reply_text(f"🗑️ Cancelled {count} pending reminders.")
            else:
                # Find matching reminders
                reminders = database.search_reminders(chat_id, query_text=target)
                if not reminders:
                     await update.message.reply_text(f"No reminders found matching '{target}'.")
                else:
                    for r in reminders:
                        database.delete_reminder(r[0])
                    await update.message.reply_text(f"🗑️ Cancelled {len(reminders)} reminders matching '{target}'.")

        elif action == "QUERY_SCHEDULE":
            time_range = params.get("time_range")
            # Determine start/end time based on range
            start_t = datetime.now()
            end_t = None
            
            if time_range == "tomorrow":
                start_t = start_t + timedelta(days=1)
                end_t = start_t + timedelta(days=1) # End of tomorrow? roughly
            
            reminders = database.search_reminders(chat_id, start_time=start_t, end_time=end_t)
            
            if not reminders:
                await update.message.reply_text("📅 You have no upcoming reminders found.")
            else:
                msg = "*📅 Upcoming Schedule:*\n"
                for r in reminders:
                    # r = (id, content, remind_at, interval)
                    r_time = r[2]
                    msg += f"- *{r[1]}* at {r_time}"
                    if r[3] > 0:
                         msg += " (Recurring)"
                    msg += "\n"
                await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "NOTE_ADD":
            content = params.get("content")
            database.add_note(content)
            await update.message.reply_text(f"✅ Note saved.")

        elif action == "NOTE_LIST":
            notes = database.get_notes(limit=10)
            if not notes:
                await update.message.reply_text("No notes found.")
            else:
                msg = "*📝 Recent Notes:*\n"
                for n in notes:
                    msg += f"- {n[1]}\n"
                await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "CLEAR_MEMORY":
            database.clear_chat_history()
            await update.message.reply_text("🧹 Memory cleared! I have forgotten our previous conversation.")

        elif action == "SYSTEM_STATUS":
             import system_monitor
             await update.message.reply_text("🔍 Checking system status...")
             report = system_monitor.get_system_status(conf)
             await update.message.reply_text(report, parse_mode='Markdown')

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
            
            response = ollama.chat(model=model, messages=messages_payload)
            bot_reply = response['message']['content']
            
            await update.message.reply_text(bot_reply, parse_mode='Markdown')
            database.add_chat_message('assistant', bot_reply)

    except Exception as e:
        logging.error(f"Error in handle_message: {e}")
        await update.message.reply_text(f"⚠️ Error processing request: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *AI Developer Assistant Online*\n\n"
        "**Features:**\n"
        "🔍 Website Monitoring (Background)\n"
        "🧠 Persistent Memory (I remember our chat)\n"
        "📝 Notes (Type `/note content`)\n"
        "⏰ Reminders (Type `Remind me to...`)\n"
        "📸 Image Analysis\n",
        parse_mode='Markdown'
    )

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
    job_queue.run_repeating(check_websites_job, interval=monitor_interval, first=10)
    
    # Reminder Job (Check every 30 seconds)
    job_queue.run_repeating(check_reminders_job, interval=30, first=5)
    
    # Server Health Job (Check every 10 minutes)
    job_queue.run_repeating(check_server_health_job, interval=600, first=15)
    
    logging.info("AI Assistant started! Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
