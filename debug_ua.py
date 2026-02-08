from monitor import fetch_smart_content, get_website_content
import requests

# Override get_website_content temporarily to test UA
def get_website_content_chrome(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        raise e

url = "https://byrappasilks.in"
print(f"Fetching {url} with Chrome UA...")
try:
    content = get_website_content_chrome(url)
    print("Success!")
    print(f"Content length: {len(content)}")
except Exception as e:
    print(f"Exception: {e}")
