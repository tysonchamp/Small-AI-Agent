from monitor import fetch_smart_content

url = "https://byrappasilks.in"
print(f"Fetching {url}...")
try:
    content, error = fetch_smart_content(url)
    if error:
        print(f"Error: {error}")
    else:
        print("Success!")
        print(f"Content length: {len(content)}")
        print("Preview:")
        print(content[:500])
except Exception as e:
    print(f"Exception: {e}")
