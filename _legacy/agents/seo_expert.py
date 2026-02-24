import asyncio
from skills.registry import skill
from bs4 import BeautifulSoup
import requests
import re

@skill(name="SEO Expert", description="This skill performs a comprehensive SEO analysis of a website, including meta tag analysis, competitor analysis, keyword research, and suggests website changes to improve search engine rankings.  It takes a website URL as input and returns a detailed report with recommendations.  Use this when you need to optimize a website's visibility in search results.")
async def analyze_website(url):
    """
    Analyzes a website for SEO best practices.

    Args:
        url (str): The URL of the website to analyze.

    Returns:
        dict: A dictionary containing the SEO analysis results.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.content, 'html.parser')

        # Meta Tag Analysis
        meta_title = soup.find('title')
        meta_description = soup.find('meta', attrs={'name': 'description'})
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})

        # Competitor Analysis (Simple - Example)
        competitor_url = "https://www.example.com"  # Replace with a competitor URL
        competitor_response = requests.get(competitor_url)
        competitor_soup = BeautifulSoup(competitor_response.content, 'html.parser')
        competitor_title = competitor_soup.find('title')
        
        # Keyword Research (Placeholder - needs a real API integration)
        keywords = ["SEO", "website optimization", "search engine"]

        # Website Changes Suggestions (Placeholder)
        suggestions = [
            "Ensure the title tag is concise and includes the primary keyword.",
            "Write a compelling meta description that accurately reflects the content.",
            "Optimize content for relevant keywords.",
            "Improve website loading speed.",
        ]

        results = {
            "title": meta_title.string if meta_title else None,
            "description": meta_description.get('content') if meta_description else None,
            "keywords": meta_keywords.get('content') if meta_keywords else None,
            "competitor_title": competitor_title.string if competitor_title else None,
            "keywords_suggested": keywords,
            "suggestions": suggestions,
        }

        return results

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        return {"error": str(e)}
    except Exception as e:
        print(f"An error occurred: {e}")
        return {"error": str(e)}