"""
Memory Search Tool — Search the AI's unified memory.
Queries ChromaDB for semantically similar documents across all categories
(notes, reminders, website changes, emails, etc.).
"""
import logging
from langchain_core.tools import tool
from core.memory_sync import search_memory as _search, get_memory_stats


@tool
def search_memory(query: str, category: str = "") -> str:
    """Search through all stored memory (notes, reminders, website changes, emails, etc.).
    Args: query — what to search for. category — optional filter: 'note', 'reminder', 'website_change', 'email', 'workflow', 'content_post', 'erp_task'. Leave empty to search all."""
    try:
        cat = category.strip() if category else None
        results = _search(query, category=cat, k=5)
        
        if not results:
            return f"🔍 No memories found for: \"{query}\""
        
        stats = get_memory_stats()
        msg = f"🧠 *Memory Search* ({len(results)} results from {stats.get('total_documents', '?')} total)\n\n"
        
        for i, r in enumerate(results, 1):
            cat_icon = {
                'note': '📝',
                'reminder': '⏰',
                'website_change': '🌐',
                'email': '📧',
                'workflow': '⚙️',
                'content_post': '📰',
                'erp_task': '💼',
            }.get(r.get('category', ''), '📄')
            
            content = r.get('content', '')
            # Remove the [CATEGORY] prefix for display
            if content.startswith('['):
                content = content.split('] ', 1)[-1] if '] ' in content else content
            
            # Truncate long content
            if len(content) > 300:
                content = content[:300] + "..."
            
            timestamp = r.get('timestamp', '')
            score = r.get('score', 0)
            
            msg += f"{cat_icon} *{i}.* {content}\n"
            if timestamp:
                msg += f"   _({timestamp}"
                if r.get('category'):
                    msg += f" | {r['category']}"
                msg += f" | relevance: {score})_\n"
            msg += "\n"
        
        return msg
    except Exception as e:
        logging.error(f"Memory search tool error: {e}")
        return f"⚠️ Memory search failed: {e}"
