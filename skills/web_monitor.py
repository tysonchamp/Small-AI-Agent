import time
import logging
import asyncio
import ollama
from telegram.ext import ContextTypes

import config
import database

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
