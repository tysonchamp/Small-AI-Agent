import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from skills.registry import skill
import config
import ollama

def fetch_page_metadata(url: str):
    try:
        if not url.startswith('http'):
            url = f"https://{url}"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = str(soup.title.string) if soup.title else "No title"
        desc = soup.find('meta', attrs={'name': 'description'})
        description = desc['content'] if desc else "No description"
        
        h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all('h1')]
        h2_tags = [h2.get_text(strip=True) for h2 in soup.find_all('h2')][:5]
        
        text_content = soup.get_text(separator=' ', strip=True)
        words = text_content.lower().split()
        word_count = len(words)
        
        return {
            "url": url,
            "title": title,
            "description": description,
            "h1_tags": h1_tags,
            "h2_tags": h2_tags,
            "word_count": word_count
        }
    except Exception as e:
         logging.error(f"Error fetching SEO data for {url}: {e}")
         return {"error": str(e), "url": url}

async def run_seo_agent(url: str, chat_id: str, context, original_request: str = ""):
    """The actual async sub-agent loop that runs in the background"""
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"🔍 *SEO Expert Agent*: Beginning analysis of `{url}`...", parse_mode='Markdown')
        
        loop = asyncio.get_running_loop()
        
        # 1. Fetch metadata synchronously in executor
        metadata = await loop.run_in_executor(None, fetch_page_metadata, url)
        
        if "error" in metadata:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *SEO Expert Agent*: Failed to fetch `{url}`.\nError: {metadata['error']}", parse_mode='Markdown')
            return
            
        # 2. Prepare specialized LLM prompt
        conf = config.load_config()
        model = conf['ollama'].get('model', 'gemma3:latest')
        
        prompt = f"""You are an elite SEO Expert Sub-Agent. 
Your objective is to analyze the following website metadata and provide a comprehensive, actionable SEO report.

URL: {metadata['url']}
Title: {metadata['title']}
Description: {metadata['description']}
H1 Tags: {metadata.get('h1_tags', [])}
Top H2 Tags: {metadata.get('h2_tags', [])}
Approximate Word Count: {metadata.get('word_count', 0)}

User's specific context/request: {original_request}

Based on this, please provide:
1. An evaluation of the Title and Meta Description length and quality.
2. A review of the heading structure (H1, H2s).
3. Suggestions for target keywords based on the current tags.
4. Recommendations for improvement on the website.

Format the response using Markdown. Keep it professional and concise. Start the message with your persona, e.g. "🤖 **SEO Expert Sub-Agent Report**".
"""
        
        response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
            {'role': 'system', 'content': 'You are a specialized SEO Expert AI sub-agent.'},
            {'role': 'user', 'content': prompt}
        ]))
        
        report = response['message']['content']
        
        # Chunking if the report is too long
        chunk_size = 4000
        for i in range(0, len(report), chunk_size):
            chunk = report[i:i + chunk_size]
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=chunk)
            
    except Exception as e:
        logging.error(f"SEO Agent error: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *SEO Expert Agent*: An error occurred during analysis.\n`{str(e)}`", parse_mode='Markdown')

@skill(name="SEO_EXPERT_AGENT", description="Delegates a task to the specialized SEO Expert Sub-Agent. Use this when the user asks for SEO analysis, website auditing, keyword research, or meta tag review for a specific website URL. Params: url, specific_request")
async def delegate_seo_agent(url: str, specific_request: str = "", chat_id: str = None, context = None):
    """
    Spawns the SEO Expert sub-agent in the background.
    """
    if not url:
         return "⚠️ Please provide a valid URL for the SEO Expert to analyze."
    
    if not chat_id or not context:
        return "⚠️ Setup Error: The SEO Agent requires Telegram context to run asynchronously."

    # Spawn the background task
    asyncio.create_task(run_seo_agent(url, chat_id, context, specific_request))
    
    return f"🕵️‍♂️ **Delegating to SEO Expert Sub-Agent**...\nI've initiated a background process to analyze `{url}`. The sub-agent will reply to you directly when the report is ready."
