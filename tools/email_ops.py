"""
Email Operations Tool — Check and summarize emails via IMAP.
"""
import logging
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from core import database
import config as app_config


def clean_text(text):
    """Cleans/decodes email subject headers."""
    if not text:
        return ""
    if isinstance(text, bytes):
        try:
            text = text.decode('utf-8')
        except UnicodeDecodeError:
            text = text.decode('latin-1')
    
    decoded_parts = decode_header(text)
    result = ""
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(charset or 'utf-8', errors='replace')
        else:
            result += part
    return result


def get_email_body(msg):
    """Extracts plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition:
                continue
            
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='replace')
                    break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    html = payload.decode(charset, errors='replace')
                    soup = BeautifulSoup(html, 'html.parser')
                    body = soup.get_text(separator='\n', strip=True)
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            content_type = msg.get_content_type()
            
            if content_type == "text/html":
                html = payload.decode(charset, errors='replace')
                soup = BeautifulSoup(html, 'html.parser')
                body = soup.get_text(separator='\n', strip=True)
            else:
                body = payload.decode(charset, errors='replace')
        except Exception:
            body = "(Could not decode body)"
    
    return body[:2000]  # Truncate


@tool
def check_emails(limit: int = 5) -> str:
    """Check and summarize unread emails from configured IMAP accounts. Args: limit — max emails per account (default 5)."""
    try:
        conf = app_config.load_config()
        email_conf = conf.get('email', {})
        accounts = email_conf.get('accounts', [])
        
        if not accounts:
            return "📧 No email accounts configured."
        
        all_summaries = ""
        total_new = 0
        
        for account in accounts:
            if not account.get('enabled', True):
                continue
            
            account_name = account.get('account_name', 'Unknown')
            imap_server = account.get('imap_server')
            imap_port = account.get('imap_port', 993)
            username = account.get('username')
            password = account.get('password')
            use_ssl = account.get('ssl', True)
            
            if not all([imap_server, username, password]):
                continue
            
            try:
                if use_ssl:
                    mail = imaplib.IMAP4_SSL(imap_server, imap_port)
                else:
                    mail = imaplib.IMAP4(imap_server, imap_port)
                
                mail.login(username, password)
                mail.select('INBOX')
                
                # Search for unseen emails from last 3 days
                since_date = (datetime.now() - timedelta(days=3)).strftime('%d-%b-%Y')
                _, messages = mail.search(None, f'(UNSEEN SINCE {since_date})')
                
                msg_ids = messages[0].split()
                
                if not msg_ids:
                    continue
                
                emails_data = []
                for msg_id in msg_ids[-limit:]:
                    _, msg_data = mail.fetch(msg_id, '(RFC822)')
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    message_id = msg.get('Message-ID', '')
                    
                    if database.is_email_processed(message_id):
                        continue
                    
                    subject = clean_text(msg.get('Subject', '(No Subject)'))
                    sender = clean_text(msg.get('From', 'Unknown'))
                    body = get_email_body(msg)
                    
                    emails_data.append({
                        "subject": subject,
                        "from": sender,
                        "body": body[:500],
                        "message_id": message_id
                    })
                    
                    database.mark_email_processed(message_id, account_name)
                
                if emails_data:
                    total_new += len(emails_data)
                    
                    # Summarize with LLM
                    from core.llm import get_ollama_llm
                    llm = get_ollama_llm()
                    
                    email_text = ""
                    for ed in emails_data:
                        email_text += f"From: {ed['from']}\nSubject: {ed['subject']}\nBody: {ed['body']}\n---\n"
                    
                    prompt = f"""Summarize these {len(emails_data)} new emails from "{account_name}" concisely.
For each email, provide: sender, subject summary, and key action needed (if any).
Format as a bulleted list.

Emails:
{email_text}"""
                    
                    response = llm.invoke(prompt)
                    all_summaries += f"\n📧 *{account_name}* ({len(emails_data)} new):\n{response.content}\n"
                    
                    # Sync each email to semantic memory
                    try:
                        from core.memory_sync import sync_to_memory
                        for ed in emails_data:
                            sync_to_memory("email", f"Email from {ed['from']}: {ed['subject']} — {ed['body'][:200]}", {
                                "subject": ed['subject'],
                                "sender": ed['from'],
                                "account": account_name,
                            })
                    except Exception:
                        pass
                
                mail.logout()
            except Exception as e:
                logging.error(f"Email check error for {account_name}: {e}")
                all_summaries += f"\n⚠️ *{account_name}*: Error — {str(e)[:100]}\n"
        
        if total_new == 0:
            return "📭 No new emails."
        
        return f"📧 *Email Summary ({total_new} new):*\n{all_summaries}"
    except Exception as e:
        logging.error(f"Email check error: {e}")
        return f"⚠️ Email check failed: {e}"


# --- Background Job ---
async def check_email_job(context):
    """Background job to check unread emails. Runs in thread to avoid blocking."""
    import asyncio
    
    try:
        conf = app_config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        if not chat_id:
            return
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: check_emails.invoke({"limit": 5}))
        
        if "📭" in result:
            logging.info(f"Email Job: {result}")
        elif "⚠️" in result:
            logging.warning(f"Email check issue: {result}")
        else:
            await context.bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Error in check_email_job: {e}")
