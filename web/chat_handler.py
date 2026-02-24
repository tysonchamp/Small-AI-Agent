"""
Web Chat Handler
Uses the shared LangChain agent for web-based chat.
"""
import logging
import asyncio
from core.agent import create_agent
import config as app_config


class ChatHandler:
    def __init__(self):
        self._agent = None
    
    def _get_agent(self):
        if self._agent is None:
            self._agent = create_agent()
        return self._agent
    
    async def process_message(self, user_message: str) -> str:
        """Process a message from the web chat and return a response."""
        logging.info(f"WebChat processing: {user_message}")
        
        # Handle simple commands
        if user_message.startswith('/'):
            return await self._handle_command(user_message)
        
        # Handle clear memory
        if user_message.lower().strip() in ["clear memory", "forget everything", "reset chat"]:
            from core.memory import clear_memory
            return clear_memory()
        
        try:
            agent = self._get_agent()
            
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: agent.invoke({"input": user_message, "chat_history": []})
            )
            
            return result.get("output", "I couldn't process that request.")
        except Exception as e:
            logging.error(f"WebChat error: {e}", exc_info=True)
            return f"⚠️ Error: {str(e)[:200]}"
    
    async def _handle_command(self, message: str) -> str:
        """Handle legacy /command style messages."""
        cmd = message.split()[0].lower()
        
        if cmd == '/status':
            from tools.system_health import get_system_status
            return get_system_status.invoke({})
        
        elif cmd == '/notes':
            from tools.notes import list_notes
            return list_notes.invoke({"limit": 10})
        
        elif cmd == '/note':
            content = message[6:].strip()
            if content:
                from core import database
                database.add_note(content)
                return "✅ Note saved."
            return "Usage: /note [content]"
        
        elif cmd == '/reminders':
            from tools.reminders import query_schedule
            return query_schedule.invoke({"time_range": "all"})
        
        elif cmd == '/workflows':
            from tools.workflows import list_workflows
            return list_workflows.invoke({})
        
        elif cmd == '/help':
            return (
                "🤖 *Web Chat Help*\n\n"
                "Commands:\n"
                "/status - Check system health\n"
                "/notes - List your notes\n"
                "/reminders - List active reminders\n"
                "/workflows - List active workflows\n"
                "/note [content] - Add a note\n\n"
                "Or just chat with me naturally!"
            )
        
        return "Unknown command. Try asking in natural language."
