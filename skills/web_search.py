import logging
import asyncio
import io
import re
import ollama
from telegram.ext import ContextTypes

import config

def perform_web_search(query):
    from ddgs import DDGS
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."
        
        summary = ""
        for r in results:
            summary += f"- [{r['title']}]({r['href']}): {r['body']}\n"
        return summary
    except Exception as e:
        return f"Error performing search: {e}"

def get_youtube_video_id(url):
    # Patterns: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/|v\/|watch\?v=|youtu\.be\/|\/v\/)([^#\&\?]*).*'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def fetch_smart_content(url):
    """
    Fetches content intelligently. 
    Returns (text_content, error_message).
    For YouTube, attempts transcript. For Web, fetches text.
    """
    try:
        vid_id = get_youtube_video_id(url)
        if vid_id:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                transcript = YouTubeTranscriptApi.get_transcript(vid_id)
                full_text = " ".join([entry['text'] for entry in transcript])
                return (f"YouTube Transcript for {vid_id}:\n\n{full_text}", None)
            except Exception as e:
                 return (None, f"Could not fetch YouTube transcript: {e}")
        else:
            # Web fetch
            try:
                import requests
                from bs4 import BeautifulSoup
                
                headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/1.0)'}
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                # Remove scripts and styles
                for script in soup(["script", "style"]):
                    script.extract()
                
                text = soup.get_text()
                # Clean whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = '\n'.join(chunk for chunk in chunks if chunk)
                
                return (clean_text, None)
            except Exception as e:
                return (None, f"Web fetch failed: {e}")

    except Exception as e:
        return (None, f"Error in fetch_smart_content: {e}")

async def handle_web_search(update, context, query):
    loop = asyncio.get_running_loop()
    chat_id = update.effective_chat.id
    conf = config.load_config()
    model = conf['ollama'].get('model', 'llama3')

    await update.message.reply_text(f"🔍 Searching the web for: '{query}'...")
    
    search_results = await loop.run_in_executor(None, perform_web_search, query)
    
    # Synthesize answer
    synth_prompt = f"""
    You are a helpful assistant. Use the following search results to answer the user's question.
    
    Question: {query} 
    (Note: The user likely asked a question that led to this search)
    
    Search Results:
    {search_results}
    
    Provide a concise and accurate answer with citations (URLs) where appropriate.
    """
    
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    
    ai_response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
        {'role': 'user', 'content': synth_prompt}
    ]))
    
    return ai_response['message']['content']

async def handle_summarize_content(update, context, url, instruction):
    loop = asyncio.get_running_loop()
    chat_id = update.effective_chat.id
    conf = config.load_config()
    model = conf['ollama'].get('model', 'llama3')

    await update.message.reply_text(f"🔍 Fetching and analyzing content from: {url}...")
    
    # Run fetch in executor
    content_text, error = await loop.run_in_executor(None, fetch_smart_content, url)
    
    if error:
         return f"⚠️ Error fetching content: {error}"
    else:
         # Summarize with Ollama
         summary_prompt = f"""
         You are an expert content analyst. 
         The following text is the content of a website or video transcript.
         
         Your specific task: "{instruction}"
         
         Guidelines:
         - Focus ONLY on the subject matter (products, features, news, concepts).
         - Do NOT evaluate the quality of the text/transcript.
         - Do NOT sound like you are giving feedback to a writer.
         - Provide a clear, bulleted summary of what the content is ABOUT.
         
         Content to Analyze:
         {content_text[:20000]} 
         """
         # Truncate content to avoid context limits
         
         await context.bot.send_chat_action(chat_id=chat_id, action='typing')
         
         summary_response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=[
             {'role': 'user', 'content': summary_prompt}
         ]))
         
         return summary_response['message']['content']
