import logging
import json
import ollama
from datetime import datetime
import config
import database
from skills import notes, reminders, system_health

class ChatHandler:
    def __init__(self):
        self.conf = config.load_config()
        self.model = self.conf['ollama'].get('model', 'gemma3:latest')

    async def process_message(self, user_message, chat_id="web-user"):
        """
        Process a message from a user (Web or Telegram) and return a response.
        """
        logging.info(f"ChatHandler processing message from {chat_id}: {user_message}")
        
        # 1. Check for simple commands (Legacy support for /command style)
        if user_message.startswith('/'):
            return await self.handle_legacy_command(user_message, chat_id)

        # 2. Intent Classification via LLM
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        system_prompt = f"""
        You are an intelligent assistant. 
        Current Time: {current_time}
        
        Analyze the user's message and determine the optimal action.
        Return ONLY a JSON object.
        
        Possible Actions:
        1. "ADD_REMINDER": User wants to set a reminder.
           - content: what to remind
           - time: natural language time
        
        2. "NOTE_ADD": User wants to save a note.
           - content: note content
        
        3. "NOTE_LIST": User wants to see notes.
        
        4. "SYSTEM_STATUS": User asks about server/system health.
        
        5. "CHAT": General conversation, knowledge, or if no other action fits.
        
        JSON Format: {{ "action": "ACTION_NAME", "params": {{ ... }} }}
        """

        try:
            response = ollama.chat(model=self.model, messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_message}
            ])
            intent_str = response['message']['content'].strip()
            
            # Extract JSON
            import re
            match = re.search(r'\{.*\}', intent_str, re.DOTALL)
            if match:
                intent_data = json.loads(match.group(0))
            else:
                intent_data = {"action": "CHAT"}

            return await self.execute_action(intent_data, user_message, chat_id)

        except Exception as e:
            logging.error(f"Error in ChatHandler: {e}")
            return f"Error processing request: {str(e)}"

    async def execute_action(self, intent, original_message, chat_id):
        action = intent.get('action')
        params = intent.get('params', {})
        
        if action == 'NOTE_ADD':
            content = params.get('content')
            if content:
                notes.handle_add_note(content)
                return "✅ Note saved."
            return "What should I write in the note?"
            
        elif action == 'NOTE_LIST':
            return notes.handle_list_notes()
            
        elif action == 'SYSTEM_STATUS':
            return system_health.get_system_status(self.conf)
            
        elif action == 'ADD_REMINDER':
            return "Reminders via Web are partially supported (saved to DB, but no push notification yet unless Telegram ID matches)."
            
        elif action == 'CHAT':
            # Perform actual chat response
            chat_response = ollama.chat(model=self.model, messages=[
                {'role': 'system', 'content': "You are a helpful AI assistant. Answer concisely."},
                {'role': 'user', 'content': original_message}
            ])
            return chat_response['message']['content']
            
        return "I understood the intent but don't have a handler for it yet."

    async def handle_legacy_command(self, message, chat_id):
        cmd = message.split()[0].lower()
        if cmd == '/status':
             return system_health.get_system_status(self.conf)
        elif cmd == '/notes':
             return notes.handle_list_notes()
        elif cmd == '/note':
             content = message[6:].strip()
             notes.handle_add_note(content)
             return "✅ Note saved."
        return "Unknown command. Try asking in natural language."
