"""
Notes Tool — Save and list notes.
"""
import logging
from langchain_core.tools import tool
from core import database


@tool
def add_note(content: str) -> str:
    """Save a note to the database. Use this when the user wants to write down or save something. Args: content — the note text."""
    try:
        database.add_note(content)
        
        # Sync to semantic memory
        try:
            from core.memory_sync import sync_to_memory
            sync_to_memory("note", content)
        except Exception as e:
            logging.warning(f"Memory sync failed for note: {e}")
        
        return "✅ Note saved."
    except Exception as e:
        logging.error(f"Error adding note: {e}")
        return f"⚠️ Failed to save note: {e}"


@tool
def list_notes(limit: int = 10) -> str:
    """List recent saved notes. Use this when the user wants to see their notes. Args: limit — number of notes to show (default 10)."""
    try:
        notes = database.get_notes(limit=limit)
        if not notes:
            return "📝 No notes found."
        
        msg = "*📝 Recent Notes:*\n"
        for n in notes:
            msg += f"- {n[1]}\n"
        return msg
    except Exception as e:
        logging.error(f"Error listing notes: {e}")
        return f"⚠️ Failed to list notes: {e}"
