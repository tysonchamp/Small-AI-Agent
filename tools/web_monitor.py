"""
Web Monitor Tool — Monitor websites for changes.
Uses Playwright for JS-rendered content and Html2Text for clean markdown conversion.
"""
import hashlib
import logging
import html2text
import requests
from langchain_core.tools import tool
from core import database
import config as app_config
import yaml


# --- Html2Text converter (reusable) ---
def _get_html2text():
    """Create a configured html2text converter."""
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0  # Don't wrap lines
    h.skip_internal_links = True
    h.inline_links = False
    h.protect_links = True
    h.ignore_tables = False
    return h


def html_to_markdown(html_content):
    """Convert HTML to clean Markdown using html2text."""
    try:
        converter = _get_html2text()
        markdown = converter.handle(html_content)
        # Clean up excessive blank lines
        lines = markdown.splitlines()
        cleaned = []
        blank_count = 0
        for line in lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 2:
                    cleaned.append('')
            else:
                blank_count = 0
                cleaned.append(line)
        return '\n'.join(cleaned).strip()
    except Exception as e:
        logging.error(f"Html2Text conversion error: {e}")
        return html_content


def get_content_hash(content):
    """Hash content for change detection."""
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# --- Playwright-based fetcher ---
def fetch_with_playwright(url, scroll=True, timeout=30000):
    """
    Fetch fully rendered HTML using Playwright headless browser.
    Handles JS-rendered content and optionally scrolls for lazy-loaded content.
    
    Returns: (html_content, status_code, error)
    """
    from playwright.sync_api import sync_playwright
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                '--disable-background-networking',
            ])
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 720},
                java_script_enabled=True,
            )
            
            page = context.new_page()
            
            try:
                response = page.goto(url, wait_until='networkidle', timeout=timeout)
                status_code = response.status if response else 0
                
                if status_code >= 400:
                    browser.close()
                    return None, status_code, f"HTTP {status_code}"
                
                # Auto-scroll for lazy-loaded content
                if scroll:
                    page.evaluate("""
                        async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 500;
                                const maxScrolls = 10;
                                let scrollCount = 0;
                                const timer = setInterval(() => {
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    scrollCount++;
                                    if (scrollCount >= maxScrolls || totalHeight >= document.body.scrollHeight) {
                                        clearInterval(timer);
                                        window.scrollTo(0, 0);
                                        resolve();
                                    }
                                }, 200);
                            });
                        }
                    """)
                    # Wait a bit for lazy content to load after scrolling
                    page.wait_for_timeout(1000)
                
                html_content = page.content()
                browser.close()
                return html_content, status_code, None
                
            except Exception as e:
                browser.close()
                raise e
                
    except Exception as e:
        error_msg = str(e)
        if 'Timeout' in error_msg:
            return None, 0, "Page load timed out"
        return None, 0, error_msg


def fetch_with_requests(url, timeout=30):
    """Fallback: Simple HTTP fetch for when Playwright isn't needed or fails."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/2.0)'}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text, response.status_code, None
    except requests.exceptions.Timeout:
        return None, 0, "Read timed out"
    except requests.exceptions.RequestException as e:
        return None, 0, str(e)


def get_website_content(url):
    """
    Fetch website content. Uses Playwright for full JS rendering.
    Falls back to requests if Playwright fails.
    """
    # Try Playwright first (handles JS-heavy sites)
    try:
        html, status, error = fetch_with_playwright(url)
        if not error:
            return html, status, None
        logging.warning(f"Playwright failed for {url}: {error}, trying requests fallback")
    except Exception as e:
        logging.warning(f"Playwright error for {url}: {e}, trying requests fallback")
    
    # Fallback to simple requests
    return fetch_with_requests(url)


def analyze_changes_with_llm(old_markdown, new_markdown):
    """Uses LLM to analyze and summarize website changes (works on Markdown)."""
    from core.llm import get_ollama_llm
    
    llm = get_ollama_llm()
    
    old_text = old_markdown[:5000] if old_markdown else "(No previous content)"
    new_text = new_markdown[:5000]
    
    prompt = f"""Analyze the changes between the old and new content of a website.
You MUST respond in English only. Keep your response concise (under 500 characters).
Focus on MEANINGFUL changes only (text, products, prices, announcements).
Ignore timestamps, session IDs, or random dynamic content.

OLD CONTENT (truncated):
{old_text}

NEW CONTENT (truncated):
{new_text}

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
    Phase 1: Fetch ALL sites via Playwright (parallel with shared browser, CPU only)
    Phase 2: Run LLM analysis only on changed sites (sequential, rare GPU usage)
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
        """Phase 1: Fetch all sites in parallel (CPU only, no GPU)."""
        results = {}
        
        # Use ThreadPoolExecutor with 5 workers (Chromium is heavier than requests)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {executor.submit(get_website_content, url): url for url in sites}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    results[url] = (None, 0, str(e))
        
        return results
    
    def _process_results(fetch_results):
        """Phase 2: Convert to markdown, compare hashes, LLM only on changed (sequential)."""
        changes = []
        
        for url, (html_content, status_code, error) in fetch_results.items():
            try:
                if error:
                    database.upsert_website(url, None, None, status_code=0, last_error=error)
                    continue
                
                if status_code >= 400:
                    database.upsert_website(url, None, None, status_code=status_code, last_error=f"HTTP {status_code}")
                    continue
                
                # Convert HTML to Markdown for cleaner comparison
                markdown_content = html_to_markdown(html_content)
                content_hash = get_content_hash(markdown_content)
                existing = database.get_website(url)
                
                if existing and existing[1] == content_hash:
                    # No change — quick update, no GPU needed
                    database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
                    continue
                
                old_content = existing[2] if existing else None
                
                if old_content:
                    # Content changed — LLM analysis (GPU, rare)
                    logging.info(f"Content changed for {url}, running LLM analysis...")
                    summary = analyze_changes_with_llm(old_content, markdown_content)
                    
                    if summary and "no significant changes" not in summary.lower():
                        database.upsert_website(url, content_hash, markdown_content,
                                               status_code=status_code, last_summary=summary)
                        changes.append((url, summary))
                    else:
                        database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
                else:
                    # First check — just store, no GPU needed
                    database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
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
        # Truncate summary to fit Telegram's 4096 char limit
        header = f"🔔 *Website Changed!*\n\n🌐 `{url}`\n\n"
        max_summary_len = 4000 - len(header)
        if len(summary) > max_summary_len:
            summary = summary[:max_summary_len] + "\n\n_(truncated)_"
        notification = header + summary
        try:
            await context.bot.send_message(chat_id=chat_id, text=notification, parse_mode='Markdown')
        except Exception:
            try:
                await context.bot.send_message(chat_id=chat_id, text=notification)
            except Exception as e:
                logging.error(f"Failed to send notification for {url}: {e}")
    
    logging.info("Website check complete.")
