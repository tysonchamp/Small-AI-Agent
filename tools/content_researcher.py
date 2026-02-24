"""
Content Researcher Tool — Manage content clients and generate posts.
"""
import logging
from datetime import datetime
from langchain_core.tools import tool
from core import database
import config as app_config


@tool
def add_content_client(name: str, niche: str, frequency: str = "daily", extra_notes: str = "") -> str:
    """Add a new client for content research. The system will automatically generate content ideas.
    Args:
        name: Client or brand name.
        niche: The industry/niche (e.g., 'fitness', 'technology').
        frequency: How often to generate content — 'daily', 'weekly' (default 'daily').
        extra_notes: Optional notes about the client's preferences."""
    try:
        existing = database.get_client_by_name(name)
        if existing:
            return f"⚠️ Client '{name}' already exists."
        
        database.add_client(name, niche, frequency, extra_notes or None)
        return f"✅ Content client '{name}' added. Niche: {niche}, Frequency: {frequency}"
    except Exception as e:
        logging.error(f"Error adding content client: {e}")
        return f"⚠️ Failed to add client: {e}"


@tool
def list_pending_content() -> str:
    """List all pending content posts awaiting approval."""
    try:
        posts = database.get_pending_posts()
        
        if not posts:
            return "📝 No pending content posts."
        
        msg = "*📝 Pending Content Posts:*\n\n"
        for p in posts:
            post_id, client_name, content, created = p
            preview = content[:150] + "..." if len(content) > 150 else content
            msg += f"#{post_id} — *{client_name}*\n{preview}\n\n"
        
        return msg
    except Exception as e:
        logging.error(f"Error listing pending content: {e}")
        return f"⚠️ Failed to list content: {e}"


@tool
def approve_content(post_id: int) -> str:
    """Approve a pending content post. Args: post_id — the ID of the post to approve."""
    try:
        database.update_post_status(post_id, 'approved')
        return f"✅ Post #{post_id} approved."
    except Exception as e:
        logging.error(f"Error approving content: {e}")
        return f"⚠️ Failed to approve: {e}"


# --- Background Job ---
async def research_content_job(context):
    """Background job to generate content for active clients. Runs in thread to avoid blocking."""
    import asyncio
    
    try:
        clients = database.get_clients()
        
        if not clients:
            return
        
        conf = app_config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        
        today = datetime.now().strftime('%Y-%m-%d')
        loop = asyncio.get_running_loop()
        
        for client in clients:
            client_id, name, niche, frequency, extra_notes, last_post_date, status = client
            
            if status != 'active':
                continue
            
            if last_post_date == today:
                continue
            
            if frequency == 'weekly' and last_post_date:
                try:
                    last_dt = datetime.strptime(last_post_date, '%Y-%m-%d')
                    if (datetime.now() - last_dt).days < 7:
                        continue
                except Exception:
                    pass
            
            try:
                def _generate_content():
                    from core.llm import get_ollama_llm
                    llm = get_ollama_llm()
                    
                    prompt = f"""Generate a social media content idea for a brand in the "{niche}" niche.
Brand Name: {name}
{f"Additional Notes: {extra_notes}" if extra_notes else ""}

Create ONE engaging social media post. Include:
1. A catchy headline/hook
2. The main content (2-3 paragraphs)
3. Suggested hashtags

Keep it professional, engaging, and relevant to the niche."""
                    
                    response = llm.invoke(prompt)
                    return response.content
                
                content = await loop.run_in_executor(None, _generate_content)
                
                database.add_post(client_id, content, 'pending')
                database.update_client_last_post_date(client_id)
                
                if chat_id:
                    notification = f"📝 *New Content Generated*\n\nClient: *{name}*\nNiche: {niche}\n\n{content[:500]}..."
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=notification, parse_mode='Markdown')
                    except Exception:
                        await context.bot.send_message(chat_id=chat_id, text=notification)
                
                logging.info(f"Content generated for {name}")
            except Exception as e:
                logging.error(f"Content generation error for {name}: {e}")
    except Exception as e:
        logging.error(f"Content research job error: {e}")
