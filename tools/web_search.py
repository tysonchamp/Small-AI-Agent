"""
Web Search Tool — Search the web and summarize content.
"""
import logging
import re
from langchain_core.tools import tool
import config as app_config


def perform_web_search(query):
    """Performs a DuckDuckGo search."""
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
    """Extracts YouTube video ID from URL."""
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
    """Fetches content intelligently. YouTube → transcript. Web → text."""
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
            import requests
            from bs4 import BeautifulSoup
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; AIWebsiteMonitor/2.0)'}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = '\n'.join(chunk for chunk in chunks if chunk)
            return (clean_text, None)
    except Exception as e:
        return (None, f"Error fetching content: {e}")


@tool
def web_search(query: str) -> str:
    """Search the web for real-time information. Use this when the user asks for current events, facts, or anything that needs up-to-date information. Args: query — the search query."""
    try:
        from core.llm import get_ollama_llm
        
        search_results = perform_web_search(query)
        
        synth_prompt = f"""Use the following search results to answer the user's question.

Question: {query}

Search Results:
{search_results}

Provide a concise and accurate answer with citations (URLs) where appropriate."""
        
        llm = get_ollama_llm()
        response = llm.invoke(synth_prompt)
        return response.content
    except Exception as e:
        logging.error(f"Web search error: {e}")
        return f"⚠️ Search failed: {e}"


@tool
def summarize_content(url: str, instruction: str = "Summarize this content effectively.") -> str:
    """Summarize a URL (webpage or YouTube video). Args: url — the URL to summarize, instruction — optional custom instruction."""
    try:
        from core.llm import get_ollama_llm
        
        content_text, error = fetch_smart_content(url)
        
        if error:
            return f"⚠️ Error fetching content: {error}"
        
        summary_prompt = f"""You are an expert content analyst.
The following text is the content of a website or video transcript.

Your specific task: "{instruction}"

Guidelines:
- Focus ONLY on the subject matter.
- Do NOT evaluate the quality.
- Provide a clear, bulleted summary.

Content to Analyze:
{content_text[:20000]}"""
        
        llm = get_ollama_llm()
        response = llm.invoke(summary_prompt)
        return response.content
    except Exception as e:
        logging.error(f"Summarize error: {e}")
        return f"⚠️ Summarization failed: {e}"
