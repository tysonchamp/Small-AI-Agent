import ollama
from bs4 import BeautifulSoup
import logging
import config
import imaplib
import email
from email.header import decode_header
from skills.registry import skill

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
            
            # Search for unread emails
            status, messages = mail.search(None, 'UNSEEN')
            if status != "OK":
                logging.warning(f"Failed to search emails for {account_name}")
                continue
            
            email_ids = messages[0].split()
            if not email_ids:
                continue
            
            # Get latest 'limit' emails
            latest_email_ids = email_ids[-limit:]
            latest_email_ids.reverse() # Newest first
            
            for e_id in latest_email_ids:
                email_count += 1
                # Fetch the email body (RFC822)
                res, msg_data = mail.fetch(e_id, "(RFC822)")
                for response_part in msg_data:
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
            f"You are a helpful personal assistant. The user has {email_count} unread emails. "
            "Below is the raw content of these emails. "
            "Please provide a concise and well-formatted summary of these emails. "
            "Group them by sender or topic if relevant. "
            "Highlight any important actions or deadlines. "
            "Keep it professional and easy to read on a mobile screen.\n\n"
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
