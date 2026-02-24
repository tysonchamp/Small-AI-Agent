import ollama
from bs4 import BeautifulSoup
import logging
import config
import imaplib
import email
from email.header import decode_header
from skills.registry import skill
import database
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
def clean_text(text):
    """Cleans/decodes email subject headers."""
    if not text:
        return ""
    decoded_list = decode_header(text)
    header_parts = []
    for content, encoding in decoded_list:
        if isinstance(content, bytes):
            if encoding:
                try:
                    header_parts.append(content.decode(encoding))
                except LookupError:
                    header_parts.append(content.decode('utf-8', errors='ignore'))
                except Exception:
                    header_parts.append(content.decode('utf-8', errors='ignore'))
            else:
                header_parts.append(content.decode('utf-8', errors='ignore'))
        else:
            header_parts.append(str(content))
    return "".join(header_parts)

def get_email_body(msg):
    """Extracts plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            
            if "attachment" in content_disposition:
                continue
                
            if content_type == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode()
                except:
                    pass
            elif content_type == "text/html":
                try:
                    html = part.get_payload(decode=True).decode()
                    soup = BeautifulSoup(html, "html.parser")
                    body += soup.get_text()
                except:
                    pass
    else:
        # Not multipart
        content_type = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True).decode()
            if content_type == "text/html":
                soup = BeautifulSoup(payload, "html.parser")
                body += soup.get_text()
            else:
                body += payload
        except:
            pass
            
    return body[:2000] # Limit body length per email to avoid context overflow

@skill(name="CHECK_EMAILS", description="Fetch unread emails and return a summary. Params: limit (default 5)")
def check_emails(limit=5):
    """Fetches unread emails from the configured IMAP server(s) and summarizes them using LLM."""
    conf = config.load_config()
    email_conf = conf.get('email', {})
    
    accounts = email_conf.get('accounts', [])
    model = conf.get('ollama', {}).get('model', 'gemma3:latest')
    
    if not accounts:
         return "⚠️ No email accounts configured."

    combined_email_content = ""
    accounts_checked = 0
    email_count = 0

    for idx, account in enumerate(accounts):
        if not account.get('enabled', True):
            continue
            
        account_name = account.get('account_name', f"Account {idx+1}")
        imap_server = account.get('imap_server')
        username = account.get('username')
        password = account.get('password')
        imap_port = account.get('imap_port', 993)
        
        if not imap_server or not username or not password:
            logging.warning(f"Skipping account {account_name}: Missing credentials.")
            continue
            
        accounts_checked += 1
        
        try:
            # Connect
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(username, password)
            mail.select("inbox")
            
            # Search for emails since today (IMAP granularity is day)
            # We fetch a bit more than needed (today) and filter precisely in Python
            cutoff_time = datetime.now() - timedelta(minutes=15)
            date_criterion = cutoff_time.strftime("%d-%b-%Y")
            
            status, messages = mail.search(None, f'(SINCE "{date_criterion}")')
            if status != "OK":
                logging.warning(f"Failed to search emails for {account_name}")
                continue
            
            email_ids = messages[0].split()
            logging.info(f"Account {account_name}: Found {len(email_ids)} recent emails (since {date_criterion}). Checking specifics...")

            if not email_ids:
                continue
            
            # Process from oldest to newest to maintain order, but since we want duplicates check
            # we iterate all.
            
            for e_id in email_ids:
                # Fetch headers only first to filter
                res, msg_data = mail.fetch(e_id, "(BODY.PEEK[HEADER.FIELDS (DATE MESSAGE-ID)])")
                if not msg_data or not msg_data[0]:
                    continue
                
                raw_headers = msg_data[0][1]
                msg_headers = email.message_from_bytes(raw_headers)
                
                # 1. Check Message-ID (Deduplication)
                message_id = msg_headers.get("Message-ID", "").strip()
                if not message_id:
                    # Fallback to hash if no ID? For now skip to be safe/lazy
                    continue
                    
                if database.is_email_processed(message_id):
                    logging.debug(f"Skipping duplicate email {message_id}")
                    continue
                
                # 2. Check Date (Time Window)
                email_date_str = msg_headers.get("Date")
                if email_date_str:
                    try:
                        email_dt = parsedate_to_datetime(email_date_str)
                        # Ensure cutoff is timezone aware if email_dt is
                        if email_dt.tzinfo is not None and cutoff_time.tzinfo is None:
                             cutoff_aware = cutoff_time.replace(tzinfo=email_dt.tzinfo) # Approximate
                             # Better: Convert both to UTC
                             pass 
                        
                        # Simple comparison: Convert email to naive local or make cutoff aware
                        # Let's use timestamp comparison to be safe
                        if email_dt.timestamp() < cutoff_time.timestamp():
                            logging.debug(f"Skipping old email from {email_date_str}")
                            continue
                    except Exception as e:
                        logging.warning(f"Failed to parse date {email_date_str}: {e}")
                        # If date parse fails, maybe include it? or skip? Default include to be safe?
                        # Let's skip to avoid spamming old stuff
                        continue

                # Is New! Fetch Body
                email_count += 1
                database.mark_email_processed(message_id, account_name)
                
                res, full_data = mail.fetch(e_id, "(RFC822)")
                for response_part in full_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        subject = clean_text(msg["Subject"])
                        from_ = clean_text(msg.get("From"))
                        body = get_email_body(msg)
                        
                        combined_email_content += f"--- EMAIL FROM {account_name} ---\n"
                        combined_email_content += f"From: {from_}\n"
                        combined_email_content += f"Subject: {subject}\n"
                        combined_email_content += f"Body: {body}\n"
                        combined_email_content += "----------------------------\n\n"
            
            mail.close()
            mail.logout()

        except imaplib.IMAP4.error as e:
            logging.error(f"Auth Failed for {account_name}: {e}")
            return f"⚠️ {account_name}: Auth Failed. Check config."
        except Exception as e:
            logging.error(f"Error checking emails for {account_name}: {e}")
            return f"⚠️ {account_name}: Error ({str(e)})"

    if email_count == 0:
        if accounts_checked == 0:
             return "⚠️ No valid email accounts found in config."
        return "📭 No new unread emails."
        
    # Generate Summary with LLM
    try:
        logging.info(f"Generating summary for {email_count} emails using {model}...")
        prompt = (
            f"""You are an extremely efficient executive assistant. Your task is to summarize {email_count} unread emails for a busy professional reading on a mobile device.

            Extract ONLY the critical information, facts, and required actions. Do not include any conversational filler, pleasantries, or introductory phrases like "Here is the summary."

            Format your output EXACTLY using the structure below. Group related emails by Sender or Topic.

            ### [Sender Name or Main Topic]
            * **Action Required / Deadline:** [State explicitly, or write "None" if n/a]
            * [Bullet point detailing the most important fact or request]
            * [Bullet point detailing additional specific information]

            Begin the summary now:

            RAW EMAILS:
            """
            f"{combined_email_content}"
        )
        
        response = ollama.chat(model=model, messages=[
            {'role': 'system', 'content': 'You are a helpful assistant that summarizes emails.'},
            {'role': 'user', 'content': prompt}
        ])
        
        return response['message']['content']
        
    except Exception as e:
        logging.error(f"LLM Summarization failed: {e}")
        return f"⚠️ Emails found ({email_count}), but summarization failed: {e}"
