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
import erp_client

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
    
    # Increased context limit to 30k chars to avoid truncation
    old_text = clean_html(old_content)[:30000]
    new_text = clean_html(new_content)[:30000]
    
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

        # Calculate hash on CLEARED text to avoid hidden HTML changes (nonces, etc)
        # run cpu-bound clean_html in executor
        current_cleaned_text = await loop.run_in_executor(None, clean_html, current_content)
        current_hash = get_content_hash(current_cleaned_text)
        
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


# --- Dynamic Workflow Logic ---

async def run_briefing_workflow(context: ContextTypes.DEFAULT_TYPE, params: dict):
    """Compiles and sends a morning briefing."""
    import database
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    
    if not chat_id:
        return

    # 1. Get Pending Reminders for Today
    now = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    reminders = database.search_reminders(chat_id, start_time=now, end_time=end_of_day)
    
    # 2. Get Unread Notes (Recent 5)
    notes = database.get_notes(limit=5)
    
    # 3. System Health (Simple check)
    import system_monitor
    health = system_monitor.check_local_health()
    
    # Compile Message
    msg = f"🌅 *Morning Briefing* - {now.strftime('%d %b %Y')}\n\n"
    
    if reminders:
        msg += "*📅 Today's Agenda:*\n"
        for r in reminders:
            msg += f"- {r[1]} at {r[2]}\n"
    else:
        msg += "📅 No reminders set for today.\n"
    
    msg += "\n"
    
    if notes:
        msg += "*📝 Recent Notes:*\n"
        for n in notes:
            msg += f"- {n[1]}\n"
    
    msg += "\n"
    msg += "*🖥️ System Status:*\n"
    msg += f"CPU: {health['cpu_percent']}% | RAM: {health['ram_percent']}%\n"
    
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')


async def run_system_health_workflow(context, params):
    """Aliased to existing logic but triggered via workflow."""
    # Force a report even if healthy
    await check_server_health_job(context, report_all=True)


async def check_workflows_job(context: ContextTypes.DEFAULT_TYPE):
    """Generic job to check and run dynamic workflows."""
    workflows = database.get_active_workflows()
    now = datetime.now()
    
    for w in workflows:
        try:
            next_run_str = w['next_run_time']
            # Parse next_run (handling potential format issues)
            # Default database stores as string via datetime.now() default str() or specific format
            try:
                # Try standard format first
                next_run = datetime.strptime(next_run_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                try:
                     # Fallback to dateparser
                     next_run = dateparser.parse(next_run_str)
                except:
                     next_run = None
            
            # Logging for debug
            logging.info(f"Checking Workflow {w['id']} ({w['type']}): Now={now}, Next={next_run}")

            if not next_run:
                logging.warning(f"Could not parse next_run for workflow {w['id']}: {next_run_str}")
                continue
                
            if now >= next_run:
                logging.info(f"Running workflow {w['id']} ({w['type']})")
                
                # DISPATCHER
                if w['type'] == 'BRIEFING':
                    await run_briefing_workflow(context, w['params'])
                elif w['type'] == 'SYSTEM_HEALTH':
                    await run_system_health_workflow(context, w['params'])
                
                # SCHEDULE NEXT RUN
                interval = w['interval_seconds']
                if interval > 0:
                    new_next_run = now + timedelta(seconds=interval)
                    database.update_workflow_next_run(w['id'], new_next_run)
                    logging.info(f"Rescheduled workflow {w['id']} to {new_next_run}")
                else:
                    # One-off workflow
                    database.delete_workflow(w['id'])
                    
        except Exception as e:
            logging.error(f"Error in workflow {w.get('id')}: {e}")

# --- Server Monitoring Logic ---

async def check_server_health_job(context: ContextTypes.DEFAULT_TYPE, report_all=False):
    import system_monitor
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    
    if not chat_id:
        return

    full_report = "🖥️ *System Health Report*\n\n"
    has_alerts = False

    # custom check to get objects, not string report
    for server in conf.get('servers', []):
        try:
            if server.get('type') == 'local':
                data = system_monitor.check_local_health()
            else:
                data = system_monitor.check_ssh_health(server)
            
            # Check thresholds
            server_status_msg = f"*{data['name']}*: "
            
            if data.get('status') == 'offline':
                server_status_msg += f"🔴 OFFLINE ({data.get('error')})"
                has_alerts = True
                full_report += server_status_msg + "\n"
            else:
                server_status_msg += "🟢 Online\n"
                server_status_msg += f"   CPU: {data.get('cpu_percent', '?')}% | RAM: {data.get('ram_percent', '?')}% | Disk: {data.get('disk_percent', '?')}%\n"
                
                # Append to full report
                full_report += server_status_msg + "\n"

                # Check for critical alerts to send IMMEDIATELY if we aren't already reporting all
                if not report_all:
                    if data.get('disk_percent', 0) > 90 or data.get('ram_percent', 0) > 95:
                        # Send specific alert
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *Critical Alert*\n{server_status_msg}", parse_mode='Markdown')

        except Exception as e:
            logging.error(f"Error checking server {server.get('name')}: {e}")
            full_report += f"*{server.get('name')}*: ⚠️ Check Failed ({e})\n"

    # Send full report if requested OR if there are offline servers (which we always want to know about in a summary)
    if report_all:
        try:
            await context.bot.send_message(chat_id=chat_id, text=full_report, parse_mode='Markdown')
        except Exception as e:
             logging.error(f"Error sending health report: {e}")


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

# --- Content Fetching Logic ---

def perform_web_search(query):
    from ddgs import DDGS
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."
        
        summary = ""
        for r in results:
            summary += f"- [{r['title']}]({r['href']}): {r['body']}\n"
        return summary
    except Exception as e:
        return f"Error performing search: {e}"

def get_youtube_video_id(url):
    import re
    # Patterns: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/|v\/|watch\?v=|youtu\.be\/|\/v\/)([^#\&\?]*).*'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# ... (existing content logic) ...

# --- Main Bot Logic ---

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
    
    try:
        # Use image context if available
        msg_payload = {'role': 'user', 'content': f"Message: {user_message}"}
        if images:
            msg_payload['images'] = images
            
        loop = asyncio.get_running_loop()
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
        
        if action == "WEB_SEARCH":
            query = params.get("query")
            await update.message.reply_text(f"🔍 Searching the web for: '{query}'...")
            
            search_results = await loop.run_in_executor(None, perform_web_search, query)
            
            # Synthesize answer
            synth_prompt = f"""
            You are a helpful assistant. Use the following search results to answer the user's question.
            
            Question: {user_message}
            
            Search Results:
            {search_results}
            
            Provide a concise and accurate answer with citations (URLs) where appropriate.
            """
            
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
            
            ai_response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
                {'role': 'user', 'content': synth_prompt}
            ]))
            
            response_text = ai_response['message']['content']
            
            # Chunking and Robust Sending
            chunk_size = 4000
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                try:
                    await update.message.reply_text(chunk, parse_mode='Markdown')
                except Exception:
                    await update.message.reply_text(chunk)

        elif action == "SUMMARIZE_CONTENT":
            url = params.get("url")
            instruction = params.get("instruction", "Summarize this content effectively.")
            
            await update.message.reply_text(f"🔍 Fetching and analyzing content from: {url}...")
            
            # Run fetch in executor
            content_text, error = await loop.run_in_executor(None, fetch_smart_content, url)
            
            if error:
                 await update.message.reply_text(f"⚠️ Error fetching content: {error}")
            else:
                 # Summarize with Ollama
                 summary_prompt = f"""
                 You are an expert content analyst. 
                 The following text is the content of a website or video transcript.
                 
                 Your specific task: "{instruction}"
                 
                 Guidelines:
                 - Focus ONLY on the subject matter (products, features, news, concepts).
                 - Do NOT evaluate the quality of the text/transcript.
                 - Do NOT sound like you are giving feedback to a writer.
                 - Provide a clear, bulleted summary of what the content is ABOUT.
                 
                 Content to Analyze:
                 {content_text[:20000]} 
                 """
                 # Truncate content to avoid context limits (20k chars is safe for most ~32k context models, or 8k)
                 
                 await context.bot.send_chat_action(chat_id=chat_id, action='typing')
                 
                 summary_response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
                     {'role': 'user', 'content': summary_prompt}
                 ]))
                 
                 response_text = summary_response['message']['content']
                 
                 # Split into chunks of 4000 chars (safe limit)
                 chunk_size = 4000
                 for i in range(0, len(response_text), chunk_size):
                     chunk = response_text[i:i + chunk_size]
                     try:
                         await update.message.reply_text(chunk, parse_mode='Markdown')
                     except Exception as e:
                         logging.error(f"Markdown parsing failed for chunk, sending plain text: {e}")
                         await update.message.reply_text(chunk)

        elif action == "SCHEDULE_WORKFLOW":
            w_type = params.get("type")
            w_time_str = params.get("time")
            w_interval = params.get("interval_seconds", 0)
            
            dt = dateparser.parse(w_time_str, settings={'PREFER_DATES_FROM': 'future'})
            if not dt:
                dt = datetime.now() # Default to start now if parsing fails

            database.add_workflow(w_type, {}, w_interval, dt)
            
            resp = f"✅ Scheduled *{w_type}* starting at {dt.strftime('%Y-%m-%d %H:%M:%S')}"
            if w_interval > 0:
                resp += f" (Runs every {w_interval}s)"
            await update.message.reply_text(resp, parse_mode='Markdown')

        elif action == "LIST_WORKFLOWS":
            workflows = database.get_active_workflows()
            if not workflows:
                await update.message.reply_text("📭 No active system workflows.")
            else:
                msg = "*⚙️ Active Workflows:*\n"
                for w in workflows:
                    msg += f"- *{w['type']}*: Next run {w['next_run_time']} (Interval: {w['interval_seconds']}s)\n"
                await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "ADD_REMINDER":
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

        elif action == "ERP_TASKS":
            await update.message.reply_text("📋 Fetching pending tasks...")
            msg = await loop.run_in_executor(None, erp_client.get_pending_tasks)
            await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "ERP_INVOICES":
            req_type = params.get('type', 'due')
            if req_type == 'summary':
                await update.message.reply_text("📊 Fetching invoice summary...")
                msg = await loop.run_in_executor(None, erp_client.get_invoice_summary)
            else:
                await update.message.reply_text("💰 Fetching due invoices...")
                msg = await loop.run_in_executor(None, erp_client.get_due_invoices)
            
            await update.message.reply_text(msg, parse_mode='Markdown')

        elif action == "ERP_CREDENTIALS":
            search_query = params.get('search')
            if search_query:
                await update.message.reply_text(f"🔐 Searching credentials for '{search_query}'...")
                msg = await loop.run_in_executor(None, erp_client.get_credentials, search_query)
            else:
                await update.message.reply_text("🔐 Fetching all credentials...")
                msg = await loop.run_in_executor(None, erp_client.get_credentials)
            await update.message.reply_text(msg, parse_mode='Markdown')
            
        elif action == "ERP_SEARCH_INVOICES":
             customer_name = params.get('customer_name')
             customer_id = params.get('customer_id')
             if not customer_name and not customer_id:
                 await update.message.reply_text("❓ Please specify a customer name or ID.")
             else:
                 await update.message.reply_text(f"🔎 Searching invoices...")
                 msg = await loop.run_in_executor(None, erp_client.search_invoices, customer_name, customer_id)
                 await update.message.reply_text(msg, parse_mode='Markdown')

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *AI Developer Assistant Online*\n\n"
        "**Features:**\n"
        "🔍 Website Monitoring (Background)\n"
        "🧠 Persistent Memory (I remember our chat)\n"
        "📝 Notes (Type `/note content`)\n"
        "⏰ Reminders (Type `Remind me to...`)\n"
        "📸 Image Analysis\n",
        "🌐 web search for real-time news, live prices, weather, or recent events (post-cutoff)\n",
        "workflow, system health check (external servers, internal servers)\n",
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
    
    # Workflow Job (Check every 60 seconds)
    job_queue.run_repeating(check_workflows_job, interval=60, first=5)
    
    logging.info("AI Assistant started! Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
