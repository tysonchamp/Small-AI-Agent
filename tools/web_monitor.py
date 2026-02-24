"""
Web Monitor Tool — Monitor websites for changes.
"""
import hashlib
import logging
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from core import database
import config as app_config
import yaml


def get_website_content(url):
    """Fetches and returns cleaned text content from a URL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/2.0)'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text, response.status_code, None
    except requests.exceptions.Timeout:
        return None, 0, "Read timed out"
    except requests.exceptions.RequestException as e:
        return None, 0, str(e)


def get_content_hash(content):
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def clean_html(html_content):
    """Removes scripts, styles, and extracts meaningful text."""
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
        tag.decompose()
    text = soup.get_text(separator='\n', strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return '\n'.join(lines)


def analyze_changes_with_llm(old_content, new_content):
    """Uses LLM to analyze and summarize website changes."""
    from core.llm import get_ollama_llm
    
    llm = get_ollama_llm()
    
    old_clean = clean_html(old_content)[:5000] if old_content else "(No previous content)"
    new_clean = clean_html(new_content)[:5000]
    
    prompt = f"""Analyze the changes between the old and new content of a website.
Focus on MEANINGFUL changes only (text, products, prices, announcements).
Ignore timestamps, session IDs, or random dynamic content.

OLD CONTENT (truncated):
{old_clean}

NEW CONTENT (truncated):
{new_clean}

If the changes are trivial (only timestamps, etc), say "No significant changes."
Otherwise, provide a brief summary of what changed."""
    
    try:
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        logging.error(f"LLM analysis failed: {e}")
        return "Could not analyze changes (LLM error)."


@tool
def list_websites() -> str:
    """List all websites currently being monitored. Shows URL, last check time, and status."""
    try:
        conf = app_config.load_config()
        sites = conf.get('monitoring', {}).get('websites', [])
        
        if not sites:
            return "No websites configured for monitoring."
        
        websites = database.get_all_websites()
        db_map = {w[0]: w for w in websites}
        
        msg = f"*🌐 Monitored Websites ({len(sites)}):*\n\n"
        for url in sites:
            w = db_map.get(url)
            if w:
                status = "✅ Active" if not w[2] else f"❌ {w[2]}"
                last = w[1] or "Never"
                msg += f"• `{url}`\n  Status: {status} | Last: {last}\n"
            else:
                msg += f"• `{url}` — _Not checked yet_\n"
        
        return msg
    except Exception as e:
        logging.error(f"Error listing websites: {e}")
        return f"⚠️ Failed to list websites: {e}"


@tool
def add_website(url: str) -> str:
    """Add a new website to monitoring. Args: url — the website URL to monitor."""
    try:
        conf = app_config.load_config()
        sites = conf.get('monitoring', {}).get('websites', [])
        
        if url in sites:
            return f"⚠️ `{url}` is already being monitored."
        
        sites.append(url)
        
        # Update config file
        config_path = 'config/config.yaml'
        with open(config_path, 'r') as f:
            full_config = yaml.safe_load(f)
        
        full_config['monitoring']['websites'] = sites
        
        with open(config_path, 'w') as f:
            yaml.dump(full_config, f, default_flow_style=False)
        
        return f"✅ Added `{url}` to monitoring list."
    except Exception as e:
        logging.error(f"Error adding website: {e}")
        return f"⚠️ Failed to add website: {e}"


# --- Background Job ---
async def check_websites_job(context):
    """Background job to check all websites for changes.
    
    Two-phase approach for speed without GPU pressure:
    Phase 1: Fetch ALL sites in parallel (pure network I/O, no GPU)
    Phase 2: Run LLM analysis only on changed sites (sequential, rare)
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    conf = app_config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    sites = conf.get('monitoring', {}).get('websites', [])
    
    if not sites or not chat_id:
        return
    
    logging.info(f"Website check starting for {len(sites)} sites")
    
    loop = asyncio.get_running_loop()
    
    def _fetch_all_sites():
        """Phase 1: Fetch all sites in parallel (network I/O only, no GPU)."""
        results = {}  # url -> (html_content, status_code, error)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(get_website_content, url): url for url in sites}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    results[url] = (None, 0, str(e))
        
        return results
    
    def _process_results(fetch_results):
        """Phase 2: Compare hashes and run LLM only on changed sites (sequential)."""
        changes = []
        
        for url, (html_content, status_code, error) in fetch_results.items():
            try:
                if error:
                    database.upsert_website(url, None, None, status_code=0, last_error=error)
                    continue
                
                if status_code >= 400:
                    database.upsert_website(url, None, None, status_code=status_code, last_error=f"HTTP {status_code}")
                    continue
                
                content_hash = get_content_hash(html_content)
                existing = database.get_website(url)
                
                if existing and existing[1] == content_hash:
                    # No change — quick update, no GPU needed
                    database.upsert_website(url, content_hash, html_content, status_code=status_code)
                    continue
                
                old_content = existing[2] if existing else None
                
                if old_content:
                    # Content changed — THIS is the only step that uses GPU (rare)
                    logging.info(f"Content changed for {url}, running LLM analysis...")
                    summary = analyze_changes_with_llm(old_content, html_content)
                    
                    if summary and "no significant changes" not in summary.lower():
                        database.upsert_website(url, content_hash, html_content,
                                               status_code=status_code, last_summary=summary)
                        changes.append((url, summary))
                    else:
                        database.upsert_website(url, content_hash, html_content, status_code=status_code)
                else:
                    # First check — just store, no GPU needed
                    database.upsert_website(url, content_hash, html_content, status_code=status_code)
                    logging.info(f"First check stored for {url}")
            
            except Exception as e:
                logging.error(f"Error processing {url}: {e}")
                try:
                    database.upsert_website(url, None, None, status_code=0, last_error=str(e))
                except Exception:
                    pass
        
        return changes
    
    def _run_full_check():
        """Run both phases in a background thread."""
        fetch_results = _fetch_all_sites()
        logging.info(f"Phase 1 complete: fetched {len(fetch_results)} sites")
        changes = _process_results(fetch_results)
        return changes
    
    # Run in thread so it doesn't block the event loop
    changes = await loop.run_in_executor(None, _run_full_check)
    
    # Send notifications (async, in event loop)
    for url, summary in changes:
        notification = f"🔔 *Website Changed!*\n\n🌐 `{url}`\n\n{summary}"
        try:
            await context.bot.send_message(chat_id=chat_id, text=notification, parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=notification)
    
    logging.info("Website check complete.")
