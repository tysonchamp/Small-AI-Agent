"""
SEO Expert Tool — Analyze websites for SEO best practices.
"""
import logging
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool
import config as app_config


def fetch_page_metadata(url: str):
    """Fetches SEO metadata from a URL."""
    try:
        if not url.startswith('http'):
            url = f"https://{url}"
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = str(soup.title.string) if soup.title else "No title"
        desc = soup.find('meta', attrs={'name': 'description'})
        description = desc['content'] if desc else "No description"
        
        h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all('h1')]
        h2_tags = [h2.get_text(strip=True) for h2 in soup.find_all('h2')][:5]
        
        text_content = soup.get_text(separator=' ', strip=True)
        word_count = len(text_content.lower().split())
        
        return {
            "url": url,
            "title": title,
            "description": description,
            "h1_tags": h1_tags,
            "h2_tags": h2_tags,
            "word_count": word_count,
        }
    except Exception as e:
        logging.error(f"Error fetching SEO data for {url}: {e}")
        return {"error": str(e), "url": url}


@tool
def seo_analysis(url: str, specific_request: str = "") -> str:
    """Perform a comprehensive SEO analysis of a website. Use this when the user asks for SEO audit, keyword research, or meta tag review.
    Args:
        url: The website URL to analyze.
        specific_request: Optional specific aspect to focus on (e.g., 'check meta tags', 'keyword suggestions')."""
    try:
        metadata = fetch_page_metadata(url)
        
        if "error" in metadata:
            return f"⚠️ Failed to fetch `{url}`: {metadata['error']}"
        
        # Use Gemini for more detailed analysis (falls back to Ollama)
        from core.llm import get_llm
        llm = get_llm(task_type="complex")
        
        prompt = f"""You are an elite SEO Expert. Analyze the following website metadata and provide a comprehensive, actionable SEO report.

URL: {metadata['url']}
Title: {metadata['title']}
Description: {metadata['description']}
H1 Tags: {metadata.get('h1_tags', [])}
Top H2 Tags: {metadata.get('h2_tags', [])}
Approximate Word Count: {metadata.get('word_count', 0)}

{f"User's specific request: {specific_request}" if specific_request else ""}

Provide:
1. Evaluation of Title and Meta Description (length and quality)
2. Review of heading structure (H1, H2s)
3. Target keyword suggestions based on current content
4. Specific recommendations for improvement

Format with Markdown. Start with "🤖 **SEO Expert Report**"."""
        
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        logging.error(f"SEO analysis error: {e}")
        return f"⚠️ SEO analysis failed: {e}"
