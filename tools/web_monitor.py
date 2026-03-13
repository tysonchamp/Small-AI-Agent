"""
Web Monitor Tool — Monitor websites for changes.
Uses Playwright for JS-rendered content and Html2Text for clean markdown conversion.
"""
import hashlib
import logging
import html2text
import requests
import threading
from langchain_core.tools import tool
import re
from core import database
import config as app_config
import yaml


# Lock to prevent uptime and content checks from running simultaneously
_monitor_lock = threading.Lock()


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
    Fetch website content. Uses requests first (fast).
    Falls back to Playwright only if requests fails (for JS-heavy sites).
    """
    # Try requests first (fast — 2-5s per site)
    try:
        html, status, error = fetch_with_requests(url, timeout=15)
        if not error and html and len(html.strip()) > 500:
            return html, status, None
        if error:
            logging.debug(f"Requests failed for {url}: {error}, trying Playwright")
    except Exception as e:
        logging.debug(f"Requests error for {url}: {e}, trying Playwright")
    
    # Fallback to Playwright (JS-heavy sites, or requests returned minimal content)
    try:
        html, status, error = fetch_with_playwright(url, timeout=15000)
        if not error:
            return html, status, None
        logging.warning(f"Playwright also failed for {url}: {error}")
    except Exception as e:
        logging.warning(f"Playwright error for {url}: {e}")
    
    # Both failed — return the requests result (even if partial)
    return fetch_with_requests(url, timeout=15)


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
def get_website_changes(url: str) -> str:
    """Get the last detected changes for a monitored website. Use this when someone asks about recent changes, updates, or modifications to a website.
    Args: url — the website URL or domain name (e.g. 'gbyteinfotech.com' or 'gbyteinfotech')."""
    try:
        from core.memory_sync import search_memory as mem_search
        
        # Search ChromaDB for website changes related to this URL
        search_query = f"website changes {url}"
        results = mem_search(search_query, category="website_change", k=5)
        
        if not results:
            return f"🔍 No change history found in memory for `{url}`."
        
        # Filter results that actually match the requested URL
        clean_url = url.strip().replace('https://', '').replace('http://', '').rstrip('/').lower()
        matched = [r for r in results if clean_url in r.get('content', '').lower() or clean_url in r.get('url', '').lower()]
        
        if not matched:
            return f"🔍 No change history found in memory for `{url}`."
        
        msg = f"🌐 *Website Changes for `{url}`:*\n\n"
        for i, r in enumerate(matched, 1):
            content = r.get('content', '')
            # Remove the [CATEGORY] prefix for display
            if content.startswith('['):
                content = content.split('] ', 1)[-1] if '] ' in content else content
            
            timestamp = r.get('timestamp', 'Unknown')
            score = r.get('score', 0)
            
            msg += f"📝 *{i}.* {content}\n"
            msg += f"   _({timestamp} | relevance: {score})_\n\n"
        
        return msg.strip()
    except Exception as e:
        logging.error(f"Error getting website changes: {e}")
        return f"⚠️ Failed to get website changes: {e}"


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
    
    Phase 1: Sequential fetch — acquires/releases lock per site so uptime can interleave.
    Phase 2: LLM analysis + notifications — fully unlocked, no network I/O.
    """
    import asyncio
    
    conf = app_config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    sites = conf.get('monitoring', {}).get('websites', [])
    
    if not sites or not chat_id:
        return
    
    loop = asyncio.get_running_loop()
    
    # === Phase 1: Fetch all sites (lock per site, not per phase) ===
    logging.info(f"Content check Phase 1 starting: fetching {len(sites)} sites")
    
    def _fetch_all_sites():
        """Fetch all sites sequentially, locking per site."""
        fetch_results = {}
        for i, url in enumerate(sites, 1):
            try:
                _monitor_lock.acquire()
                try:
                    logging.debug(f"Content fetch [{i}/{len(sites)}]: {url}")
                    fetch_results[url] = get_website_content(url)
                finally:
                    _monitor_lock.release()
            except Exception as e:
                fetch_results[url] = (None, 0, str(e))
        return fetch_results
    
    fetch_results = await loop.run_in_executor(None, _fetch_all_sites)
    logging.info(f"Content check Phase 1 complete: fetched {len(fetch_results)} sites")
    
    # === Phase 2: Process results + LLM analysis (UNLOCKED — no network I/O) ===
    def _process_results():
        """Compare hashes, run LLM on changed sites."""
        changes = []
        for url, (html_content, status_code, error) in fetch_results.items():
            try:
                if error:
                    database.upsert_website(url, None, None, status_code=0, last_error=error)
                    continue
                if status_code >= 400:
                    database.upsert_website(url, None, None, status_code=status_code, last_error=f"HTTP {status_code}")
                    continue
                
                markdown_content = html_to_markdown(html_content)
                content_hash = get_content_hash(markdown_content)
                existing = database.get_website(url)
                
                if existing and len(existing) > 4 and existing[4]:
                    # Site is marked down (e.g. by uptime checker for parking/DNS). Preserve error and skip content check.
                    continue
                
                if existing and existing[1] == content_hash:
                    database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
                    continue
                
                old_content = existing[2] if existing else None
                
                if old_content:
                    logging.info(f"Content changed for {url}, running LLM analysis...")
                    summary = analyze_changes_with_llm(old_content, markdown_content)
                    
                    if summary and "no significant changes" not in summary.lower():
                        database.upsert_website(url, content_hash, markdown_content,
                                               status_code=status_code, last_summary=summary)
                        changes.append((url, summary))
                        try:
                            from core.memory_sync import sync_to_memory
                            sync_to_memory("website_change", f"Website {url} changed: {summary}", {"url": url})
                        except Exception:
                            pass
                    else:
                        database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
                else:
                    database.upsert_website(url, content_hash, markdown_content, status_code=status_code)
                    logging.info(f"First check stored for {url}")
            except Exception as e:
                logging.error(f"Error processing {url}: {e}")
                try:
                    database.upsert_website(url, None, None, status_code=0, last_error=str(e))
                except Exception:
                    pass
        return changes
    
    changes = await loop.run_in_executor(None, _process_results)
    
    for url, summary in changes:
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
    
    logging.info("Website content check complete.")
    database.record_job_run('content_check')


# --- Uptime Check Background Job ---
async def check_uptime_job(context):
    """Lightweight background job to check if websites are up or down.
    
    Sequential HTTP HEAD requests to avoid firewall blocks.
    Uses lock to prevent overlap with content check.
    Alerts on state changes: OK → Down, Down → Recovered.
    """
    import asyncio
    
    logging.info("Uptime check waiting for lock...")
    _monitor_lock.acquire()
    
    try:
        conf = app_config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        sites = conf.get('monitoring', {}).get('websites', [])
        
        if not sites or not chat_id:
            return
        
        logging.info(f"Uptime check starting for {len(sites)} sites")
        
        loop = asyncio.get_running_loop()
        
        import urllib.parse
        import re

        def _get_base_domain(url_str):
            try:
                netloc = urllib.parse.urlparse(url_str).netloc.lower()
                if netloc.startswith('www.'):
                    return netloc[4:]
                return netloc
            except Exception:
                return ""
        
        # Parking/expired domain detection keywords
        _PARKING_INDICATORS = [
            'parking-lander', 'LANDER_SYSTEM', '/lander',
            'sedoparking', 'domainmarket', 'domain is for sale',
            'buy this domain', 'domain expired', 'parked free',
            'godaddy.com/parking', 'afternic.com',
            'hugedomains.com', 'dan.com', '<title>redirecting...</title>',
            'prebid-wrapper'
        ]
        
        def _check_single_site(url):
            """Quick HTTP check — returns (url, is_up, status_code, error_msg)."""
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                
                if response.status_code >= 400:
                    return (url, False, response.status_code, f"HTTP {response.status_code}")
                
                orig_domain = _get_base_domain(url)
                
                # 1. Check for HTTP redirects to completely different domains (hacked or expired)
                final_domain = _get_base_domain(response.url)
                if orig_domain and final_domain and orig_domain != final_domain:
                    # Allow subdomains (e.g. site.com -> app.site.com) but block site.com -> hacker.com
                    if not final_domain.endswith(f".{orig_domain}") and not orig_domain.endswith(f".{final_domain}"):
                        return (url, False, response.status_code, f"Suspicious HTTP redirect to {final_domain}")
                
                body = response.text[:15000].lower()
                
                # 2. Check for parking/expired domain pages (these often return HTTP 200)
                if len(response.text.strip()) < 15000:
                    for indicator in _PARKING_INDICATORS:
                        if indicator.lower() in body:
                            return (url, False, response.status_code, f"Domain parked/expired (detected: {indicator})")
                
                # 3. Check for HTML JS / Meta hacks that redirect the user
                # Meta refresh (e.g. <meta http-equiv="refresh" content="0;url=http://hacker.com">)
                meta_match = re.search(r'http-equiv=["\']?refresh["\']?.*?url=([^"\'>\s]+)', body)
                if meta_match:
                    meta_url = meta_match.group(1).strip()
                    if meta_url.startswith('http'):
                        meta_domain = _get_base_domain(meta_url)
                        if meta_domain and meta_domain != orig_domain and not meta_domain.endswith(f".{orig_domain}"):
                            return (url, False, response.status_code, f"Malicious meta redirect to {meta_domain}")
                
                # JS window.location (e.g. window.location.href="http://hacker.com")
                js_match = re.search(r'window\.location(?:\.href|\.replace)?\s*=\s*["\'](http[^"\']+)["\']', body)
                if js_match:
                    js_url = js_match.group(1).strip()
                    js_domain = _get_base_domain(js_url)
                    if js_domain and js_domain != orig_domain and not js_domain.endswith(f".{orig_domain}"):
                        return (url, False, response.status_code, f"Malicious JS redirect to {js_domain}")
                
                return (url, True, response.status_code, None)
            except requests.exceptions.Timeout:
                return (url, False, 0, "Connection timed out")
            except requests.exceptions.ConnectionError as ce:
                # Check for DNS/NameResolution errors which often happen for expired domains
                err_str = str(ce)
                if "NameResolutionError" in err_str or "Failed to resolve" in err_str:
                    try:
                        import whois
                        import datetime
                        import pytz
                        import subprocess
                        domain_to_check = _get_base_domain(url)
                        if domain_to_check:
                            expired_str = None
                            if expired_str:
                                return (url, False, 0, expired_str)
                                
                            # Fallback to system whois command (handles .in TLDs better sometimes)
                            try:
                                import subprocess
                                result = subprocess.run(
                                    ['whois', domain_to_check], 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE, 
                                    text=True, 
                                    timeout=4
                                )
                                out = result.stdout.lower()
                                if 'registry expiry date:' in out or 'expiration date:' in out:
                                    # Try to find if the date is in the past
                                    match = re.search(r'(registry expiry date|expiration date):\s*([^\n]+)', out)
                                    if match:
                                        date_str = match.group(2).strip()
                                        from dateutil import parser
                                        try:
                                            parsed_date = parser.parse(date_str)
                                            if parsed_date.tzinfo is None:
                                                parsed_date = parsed_date.replace(tzinfo=pytz.UTC)
                                            if parsed_date < datetime.datetime.now(pytz.UTC):
                                                return (url, False, 0, f"Domain expired on {parsed_date.strftime('%Y-%m-%d')}")
                                        except Exception:
                                            # If we can't parse but we know it doesn't resolve, let it drop through to fallback error
                                            pass
                            except subprocess.TimeoutExpired:
                                logging.debug(f"Subprocess WHOIS timed out for {url}")
                            except Exception as e:
                                logging.debug(f"Subprocess WHOIS failed for {url}: {e}")
                    except Exception as we:
                        logging.debug(f"WHOIS lookup failed for {url}: {we}")
                
                return (url, False, 0, "Connection refused / DNS failed")
            except requests.exceptions.SSLError:
                return (url, False, 0, "SSL certificate error")
            except Exception as e:
                return (url, False, 0, str(e)[:200])
        
        def _check_all_sites_sequential():
            """Check all sites one by one."""
            results = []
            for i, url in enumerate(sites, 1):
                logging.debug(f"Uptime check [{i}/{len(sites)}]: {url}")
                results.append(_check_single_site(url))
            return results
        
        results = await loop.run_in_executor(None, _check_all_sites_sequential)
        
        # Compare with previous state and detect transitions
        down_alerts = []
        recovered_alerts = []
        
        for url, is_up, status_code, error_msg in results:
            existing = database.get_website(url)
            prev_data = database.get_website_changes(url)
            was_down = False
            if prev_data:
                was_down = bool(prev_data[0][2])  # last_error was not None/empty
            
            if is_up:
                if was_down:
                    recovered_alerts.append(f"✅ `{url}` — *Recovered* (HTTP {status_code})")
                database.upsert_website(
                    url, 
                    existing[1] if existing else None,
                    existing[2] if existing else None,
                    status_code=status_code, 
                    last_error=None
                )
            else:
                database.upsert_website(
                    url, 
                    existing[1] if existing else None,
                    existing[2] if existing else None,
                    status_code=status_code, 
                    last_error=error_msg
                )
                if not was_down:
                    down_alerts.append(f"❌ `{url}` — {error_msg}")
                else:
                    logging.debug(f"Still down: {url} — {error_msg}")
        
        # Send alerts
        if down_alerts:
            alert_msg = "🚨 *Website Down Alert!*\n\n" + "\n".join(down_alerts)
            try:
                await context.bot.send_message(chat_id=chat_id, text=alert_msg, parse_mode='Markdown')
            except Exception:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=alert_msg)
                except Exception as e:
                    logging.error(f"Failed to send downtime alert: {e}")
        
        if recovered_alerts:
            recovery_msg = "🎉 *Website Recovered!*\n\n" + "\n".join(recovered_alerts)
            try:
                await context.bot.send_message(chat_id=chat_id, text=recovery_msg, parse_mode='Markdown')
            except Exception:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=recovery_msg)
                except Exception as e:
                    logging.error(f"Failed to send recovery alert: {e}")
        
        down_count = sum(1 for _, is_up, _, _ in results if not is_up)
        logging.info(f"Uptime check complete: {len(results)} sites checked, {down_count} down")
        database.record_job_run('uptime_check')
    finally:
        _monitor_lock.release()
