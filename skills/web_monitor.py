import time
import logging
import asyncio
import ollama
from telegram.ext import ContextTypes

import config
import database
import yaml

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
        
        # Initialize variables
        current_content = None
        status_code = 0
        error_msg = None
        
        try:
            # Run blocking request in a separate thread
            # Modified get_website_content to return status code as well, or we handle it here
            import requests
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/1.0)'}
            response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=30))
            status_code = response.status_code
            response.raise_for_status()
            current_content = response.text
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error checking {url}: {e}")
            
            # Update DB with error
            c.execute("UPDATE websites SET last_checked=?, last_error=?, status_code=? WHERE url=?",
                      (time.strftime('%Y-%m-%d %H:%M:%S'), error_msg, status_code, url))
            conn.commit()
            
            # Notify if critical? Maybe just log for now to avoid spam, dashboard will show red.
            continue
        
        if not current_content:
            continue

        # success path
        # Calculate hash on CLEARED text to avoid hidden HTML changes (nonces, etc)
        # run cpu-bound clean_html in executor
        current_cleaned_text = await loop.run_in_executor(None, clean_html, current_content)
        current_hash = get_content_hash(current_cleaned_text)
        
        c.execute("SELECT content_hash, last_content FROM websites WHERE url=?", (url,))
        row = c.fetchone()
        
        if row is None:
            c.execute("INSERT INTO websites (url, content_hash, last_checked, last_content, status_code, last_error) VALUES (?, ?, ?, ?, ?, ?)",
                      (url, current_hash, time.strftime('%Y-%m-%d %H:%M:%S'), current_content, status_code, None))
            conn.commit()
            logging.info(f"Initial check for {url}. Content stored.")
            
        elif row[0] != current_hash:
            logging.info(f"Change detected for {url}!")
            old_content = row[1]
            
            analysis = await loop.run_in_executor(None, analyze_changes_with_ollama, old_content, current_content, model)
            
            summary_text = None
            if analysis:
                summary_text = analysis
                msg = f"📢 *Website Change Detected!* \n\nURL: {url}\n\nAI Analysis:\n{analysis}"
                if chat_id:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                    except Exception as send_e:
                         logging.error(f"Failed to send change notification: {send_e}")
            else:
                logging.info(f"No meaningful changes for {url}. Notification suppressed.")

            c.execute("UPDATE websites SET content_hash=?, last_checked=?, last_content=?, status_code=?, last_error=?, last_summary=? WHERE url=?",
                      (current_hash, time.strftime('%Y-%m-%d %H:%M:%S'), current_content, status_code, None, summary_text, url))
            conn.commit()
        else:
            # Update last_checked even if no change, clear error
            c.execute("UPDATE websites SET last_checked=?, status_code=?, last_error=? WHERE url=?", 
                      (time.strftime('%Y-%m-%d %H:%M:%S'), status_code, None, url))
            conn.commit()
            logging.info(f"No changes for {url}.")
            
    conn.close()

from skills.registry import skill

@skill(name="LIST_WEBSITES", description="List monitored websites.")
def list_websites():
    conf = config.load_config()
    sites = conf['monitoring'].get('websites', [])
    if not sites:
        return "📭 No websites are being monitored."
    
    msg = "*🌐 Monitored Websites:*\n"
    
    # Enrich with status from DB
    conn = database.get_connection()
    c = conn.cursor()
    for url in sites:
        c.execute("SELECT status_code, last_checked, last_error FROM websites WHERE url=?", (url,))
        row = c.fetchone()
        status = "Unknown"
        if row:
            if row[2]: # last_error
                status = f"❌ Error: {row[2]}"
            elif row[0]: # status_code
                status = f"✅ {row[0]}"
            msg += f"- {url} ({status})\n"
        else:
             msg += f"- {url} (Pending check)\n"
    conn.close()
    return msg

@skill(name="ADD_WEBSITE", description="Add a website to monitor. Params: url")
def add_website(url: str):
    # This involves updating config.yaml which might be complex if it's not designed for programmatic edits.
    # But we can try loading, appending, and saving.
    try:
        with open('config/config.yaml', 'r') as f:
            raw_conf = yaml.safe_load(f)
        
        if 'monitoring' not in raw_conf:
            raw_conf['monitoring'] = {'websites': []}
            
        if url not in raw_conf['monitoring']['websites']:
            raw_conf['monitoring']['websites'].append(url)
            
            with open('config/config.yaml', 'w') as f:
                yaml.dump(raw_conf, f)
            return f"✅ Added {url} to monitoring list."
        else:
            return f"⚠️ {url} is already being monitored."
            
    except Exception as e:
        return f"⚠️ Failed to update config: {e}"
