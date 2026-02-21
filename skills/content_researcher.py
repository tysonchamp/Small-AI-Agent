
import logging
import asyncio
from datetime import datetime
import config
import database
import ai_client
from skills.registry import skill

@skill(name="ADD_CONTENT_CLIENT", description="Add a client for automated content research. Params: name, niche, frequency (default 'daily'), extra_notes (Must capture ALL additional context including Tone, Formatting, Constraints, etc. Pass full text.)")
def add_content_client(name, niche, frequency="daily", extra_notes=None):
    try:
        existing = database.get_client_by_name(name)
        if existing:
            return f"⚠️ Client '{name}' already exists. Use `UPDATE_CONTENT_CLIENT` to modify details."
        
        database.add_client(name, niche, frequency, extra_notes)
        return f"✅ Client '{name}' added! I will research content for the '{niche}' niche {frequency}."
    except Exception as e:
        return f"⚠️ Error adding client: {e}"

@skill(name="UPDATE_CONTENT_CLIENT", description="Update details for an existing content client. Params: client_name, niche (optional), frequency (optional), extra_notes (optional)")
def update_content_client(client_name, niche=None, frequency=None, extra_notes=None):
    client = database.get_client_by_name(client_name)
    if not client:
        # Try fuzzy search
        matches = database.find_clients_like(client_name)
        if len(matches) == 1:
            client = matches[0]
            client_name = client[1] # Update name for report
        elif len(matches) > 1:
            names = [m[1] for m in matches]
            return f"⚠️ Client '{client_name}' not found. Did you mean one of these? {', '.join(names)}"
        else:
            return f"⚠️ Client '{client_name}' not found."
    
    database.update_client(client[0], niche=niche, frequency=frequency, extra_notes=extra_notes)
    
    updates = []
    if niche: updates.append(f"Niche -> {niche}")
    if frequency: updates.append(f"Freq -> {frequency}")
    if extra_notes: updates.append("Notes Updated")
    
    return f"✅ Client '{client_name}' updated: {', '.join(updates) if updates else 'No changes provided'}"

    return f"✅ Client '{client_name}' updated: {', '.join(updates) if updates else 'No changes provided'}"

@skill(name="REMOVE_CONTENT_CLIENT", description="Permanently remove a client and their posts. Params: client_name")
def remove_content_client(client_name):
    client = database.get_client_by_name(client_name)
    if not client:
        # Try fuzzy search
        matches = database.find_clients_like(client_name)
        if len(matches) == 1:
            client = matches[0]
            client_name = client[1] # Update name for report
        elif len(matches) > 1:
            names = [m[1] for m in matches]
            return f"⚠️ Client '{client_name}' not found. Did you mean one of these? {', '.join(names)}"
        else:
            return f"⚠️ Client '{client_name}' not found."
    
    database.delete_client(client[0])
    return f"🗑️ Client '{client_name}' and their history have been permanently deleted."

@skill(name="DEACTIVATE_CONTENT_CLIENT", description="Stop research/posting for a client. Params: client_name")
def deactivate_content_client(client_name):
    client = database.get_client_by_name(client_name)
    if not client:
        # Try fuzzy search
        matches = database.find_clients_like(client_name)
        if len(matches) == 1:
            client = matches[0]
            client_name = client[1]
        elif len(matches) > 1:
            names = [m[1] for m in matches]
            return f"⚠️ Client '{client_name}' not found. Did you mean one of these? {', '.join(names)}"
        else:
            return f"⚠️ Client '{client_name}' not found."
    
    database.update_client_status(client[0], 'inactive')
    return f"🛑 Content research for '{client_name}' has been PAUSED."

@skill(name="REACTIVATE_CONTENT_CLIENT", description="Resume research/posting for a client. Params: client_name")
def reactivate_content_client(client_name):
    client = database.get_client_by_name(client_name)
    if not client:
        # Try fuzzy search
        matches = database.find_clients_like(client_name)
        if len(matches) == 1:
            client = matches[0]
            client_name = client[1]
        elif len(matches) > 1:
            names = [m[1] for m in matches]
            return f"⚠️ Client '{client_name}' not found. Did you mean one of these? {', '.join(names)}"
        else:
            return f"⚠️ Client '{client_name}' not found."
    
    database.update_client_status(client[0], 'active')
    return f"✅ Content research for '{client_name}' has been RESUMED."

@skill(name="LIST_PENDING_CONTENT", description="List social media posts waiting for review.")
def list_pending_content():
    posts = database.get_pending_posts()
    if not posts:
        return "📭 No pending content for review."
    
    msg = "*📝 Pending Content Approvals:*\n\n"
    for p in posts:
        # p = (id, client_name, content, created_at)
        msg += f"🆔 *{p[0]}* (Client: {p[1]})\n"
        msg += f"📅 {p[3]}\n"
        msg += f"----------------------------\n"
        msg += f"{p[2]}\n" # Full Content
        msg += f"----------------------------\n\n"
        
    msg += "To approve, use `APPROVE_CONTENT(post_id)`"
    return msg

@skill(name="APPROVE_CONTENT", description="Approve a generated post. Params: post_id")
def approve_content(post_id):
    try:
        database.update_post_status(post_id, 'approved')
        return f"✅ Post {post_id} approved! status: posted"
    except Exception as e:
        return f"⚠️ Error approving post: {e}"

async def research_content_job(context):
    logging.info("Starting Content Research Job...")
    try:
        conf = config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        model = conf['ollama'].get('model', 'llama3')
        
        clients = database.get_clients()
        if not clients:
            logging.info("No clients found for research.")
            return
        
        results_summary = []
        
        for client in clients:
            # client: id, name, niche, frequency, last_post_date, extra_notes, status
            c_id, name, niche, frequency, last_post_date, extra_notes, status = client
            
            if status != 'active':
                continue

            
            should_run = False
            last_dt = None
            
            if not last_post_date:
                should_run = True
            else:
                try:
                    # Handle timestamp string parsing
                    if isinstance(last_post_date, str):
                        last_dt = datetime.strptime(last_post_date, '%Y-%m-%d %H:%M:%S')
                    else:
                        last_dt = last_post_date
                        
                    now = datetime.now()
                    diff = now - last_dt
                    
                    if frequency.lower() == 'daily' and diff.days >= 1:
                        should_run = True
                    elif frequency.lower() == 'weekly' and diff.days >= 7:
                        should_run = True
                except Exception as e:
                    logging.error(f"Date parsing error for client {name}: {e}")
                    should_run = True # Fallback run if date is messed up
            
            if should_run:
                logging.info(f"Generating content for client: {name}")
                
                try:
                    prompt = f"""
                    You are a social media manager for a client named "{name}" in the "{niche}" niche.
                    
                    Extra Notes: {extra_notes or 'None'}
                    
                    Task: Write a single engaging social media post (e.g. for LinkedIn or Twitter/X).
                    The post should be professional yet conversational, relevant to the niche, and offer true value.
                    Include 3-5 relevant hashtags.
                    
                    IMPORTANT: Return ONLY the post content. Do not include introductory text.
                    """
                    
                    client_ai = ai_client.get_client()
                    
                    # Call LLM
                    # Since we are in an async job, we can blocking call in executor
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, lambda: client_ai.chat(model=model, messages=[
                        {'role': 'user', 'content': prompt}
                    ]))
                    
                    content = response['message']['content'].strip()
                    
                    # Remove surrounding quotes if model adds them
                    if content.startswith('"') and content.endswith('"'):
                         content = content[1:-1]
                    
                    database.add_post(c_id, content, 'pending')
                    
                    # Update last post date to NOW
                    database.update_client_last_post_date(c_id)
                    
                    results_summary.append(f"✅ Generated for *{name}*")
                    
                except Exception as e:
                    logging.error(f"Error generating for {name}: {e}")
                    results_summary.append(f"❌ Failed for {name}: {e}")
        
        if results_summary and chat_id:
             msg = f"🤖 *Content Research Report*\n\n" + "\n".join(results_summary)
             msg += "\n\nType `LIST_PENDING_CONTENT` to review."
             await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error in research_content_job: {e}")

@skill(name="FORCE_CONTENT_RUN", description="Manually force the content research job to run now.")
async def force_content_run(update=None, context=None):
    if context:
        await update.message.reply_text("🚀 Starting content research job manually...")
        await research_content_job(context)
        return "Job execution finished."
    return "Context required."
