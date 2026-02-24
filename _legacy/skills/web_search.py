import logging
import asyncio
import io
import re
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

from skills.registry import skill

@skill(name="WEB_SEARCH", description="Find real-time information or specific data points from the internet. Params: query")
async def web_search(query):
    # loop = asyncio.get_running_loop() # Not needed if we await run_in_executor here or let dispatcher handle it.
    # Actually, we can just use the sync perform_web_search in executor if we want, or make this sync.
    # But perform_web_search is sync blocking.
    import asyncio
    import ai_client # Lazy import to avoid circular dependency if any (though unlikely here)
    loop = asyncio.get_running_loop()
    
    conf = config.load_config()
    model = conf['ollama'].get('model', 'llama3')

    # We cannot send "Searching..." message here effectively if we return string. 
    # The dispatcher should handle "Processing..." or user won't know? 
    # For now, we return the result.
    
    search_results = await loop.run_in_executor(None, perform_web_search, query)
    
    synth_prompt = f"""
    You are a helpful assistant. Use the following search results to answer the user's question.
    
    Question: {query} 
    
    Search Results:
    {search_results}
    
    Provide a concise and accurate answer with citations (URLs) where appropriate.
    """
    
    client = ai_client.get_client()
    ai_response = await loop.run_in_executor(None, lambda: client.chat(model=model, messages=[
        {'role': 'user', 'content': synth_prompt}
    ]))
    
    return ai_response['message']['content']

@skill(name="SUMMARIZE_CONTENT", description="Summarize a URL (video/page). Params: url, instruction (optional)")
async def summarize_content(url, instruction="Summarize this content effectively."):
    import asyncio
    import ai_client
    loop = asyncio.get_running_loop()
    
    conf = config.load_config()
    model = conf['ollama'].get('model', 'llama3')
    
    content_text, error = await loop.run_in_executor(None, fetch_smart_content, url)
    
    if error:
         return f"⚠️ Error fetching content: {error}"
    else:
         summary_prompt = f"""
         You are an expert content analyst. 
         The following text is the content of a website or video transcript.
         
         Your specific task: "{instruction}"
         
         Guidelines:
         - Focus ONLY on the subject matter.
         - Do NOT evaluate the quality.
         - Provide a clear, bulleted summary.
         
         Content to Analyze:
         {content_text[:20000]} 
         """
         
         client = ai_client.get_client()
         summary_response = await loop.run_in_executor(None, lambda: client.chat(model=model, messages=[
             {'role': 'user', 'content': summary_prompt}
         ]))
         
         return summary_response['message']['content']
