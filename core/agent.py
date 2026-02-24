"""
LangChain Agent Setup
Creates the central agent using prompt-based tool selection.
Works with any LLM (no native tool calling required).
"""
import logging
import json
import pytz
from datetime import datetime

import config as app_config
from core.llm import get_ollama_llm


def get_all_tools():
    """Collects and returns all LangChain tools from the tools/ package."""
    from tools.notes import add_note, list_notes
    from tools.reminders import add_reminder, cancel_reminder, query_schedule
    from tools.web_monitor import list_websites, add_website
    from tools.web_search import web_search, summarize_content
    from tools.system_health import get_system_status, get_local_status
    from tools.system_ops import execute_shell_command
    from tools.erp import get_pending_tasks, get_invoices, search_invoices, get_credentials
    from tools.email_ops import check_emails
    from tools.notifications import notify_user
    from tools.workflows import schedule_workflow, list_workflows, cancel_workflow
    from tools.content_researcher import add_content_client, list_pending_content, approve_content
    from tools.seo_expert import seo_analysis
    from tools.meta_coder import create_new_tool

    all_tools = [
        # Notes
        add_note, list_notes,
        # Reminders
        add_reminder, cancel_reminder, query_schedule,
        # Web Monitor
        list_websites, add_website,
        # Web Search
        web_search, summarize_content,
        # System
        get_system_status, get_local_status, execute_shell_command,
        # ERP
        get_pending_tasks, get_invoices, search_invoices, get_credentials,
        # Email
        check_emails,
        # Notifications
        notify_user,
        # Workflows
        schedule_workflow, list_workflows, cancel_workflow,
        # Content Research
        add_content_client, list_pending_content, approve_content,
        # SEO
        seo_analysis,
        # Meta Coder
        create_new_tool,
    ]
    
    logging.info(f"Loaded {len(all_tools)} tools: {[t.name for t in all_tools]}")
    return all_tools


def _build_tool_descriptions(tools):
    """Build a formatted string describing all available tools."""
    desc = ""
    for t in tools:
        # Get parameter info from the tool schema
        schema = t.args_schema.schema() if hasattr(t, 'args_schema') and t.args_schema else {}
        props = schema.get('properties', {})
        params = []
        for pname, pinfo in props.items():
            ptype = pinfo.get('type', 'string')
            pdesc = pinfo.get('description', '')
            default = pinfo.get('default', None)
            if default is not None:
                params.append(f'{pname} ({ptype}, default={default}): {pdesc}')
            else:
                params.append(f'{pname} ({ptype}): {pdesc}')
        
        param_str = ', '.join(params) if params else 'no parameters'
        desc += f"- {t.name}: {t.description} | Params: {param_str}\n"
    
    return desc


def create_agent(memory=None):
    """
    Creates and returns a prompt-based agent that works with any LLM.
    No native tool calling required.
    """
    conf = app_config.load_config()
    agent_name = conf.get('agent', {}).get('name', 'AI Assistant')
    persona = conf.get('agent', {}).get('persona', 'You are a helpful assistant.')
    tz_str = conf.get('telegram', {}).get('timezone', 'Asia/Kolkata')
    
    llm = get_ollama_llm()
    tools = get_all_tools()
    tool_map = {t.name: t for t in tools}
    tool_descriptions = _build_tool_descriptions(tools)
    
    logging.info(f"Agent created: {agent_name} with {len(tools)} tools")
    
    class PromptAgent:
        def __init__(self, llm, tool_map, tool_descriptions, agent_name, persona, tz_str):
            self._llm = llm
            self._tool_map = tool_map
            self._tool_descriptions = tool_descriptions
            self._agent_name = agent_name
            self._persona = persona
            self._tz_str = tz_str
        
        def _get_current_time(self):
            tz = pytz.timezone(self._tz_str)
            return datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S %Z')
        
        def _classify(self, user_input):
            """Ask LLM to decide which tool to use (or NONE for direct chat)."""
            classify_prompt = f"""You are a tool router. Given a user message, decide which tool to call.

Available tools:
{self._tool_descriptions}

User message: "{user_input}"

Respond with ONLY a valid JSON object (no markdown, no explanation):
{{"tool": "TOOL_NAME_OR_NONE", "params": {{"param1": "value1"}}}}

Rules:
- If the message is casual chat, greeting, or general knowledge question, respond: {{"tool": "NONE", "params": {{}}}}
- Pick the BEST matching tool based on the user's intent.
- Fill in tool parameters from the user's message.
- For add_note, put the note content in the "content" param.
- For add_reminder, extract "content" and "time" params.
- For web_search, put the query in the "query" param.
- ONLY output the JSON object, nothing else."""

            try:
                response = self._llm.invoke(classify_prompt)
                text = response.content.strip()
                
                # Clean up common LLM output issues
                if text.startswith('```'):
                    text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
                
                # Try to find JSON in the response
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    text = text[start:end + 1]
                
                result = json.loads(text)
                return result.get('tool', 'NONE'), result.get('params', {})
            except (json.JSONDecodeError, Exception) as e:
                logging.warning(f"Classification parse error: {e}, raw: {text[:200] if 'text' in dir() else 'N/A'}")
                return 'NONE', {}
        
        def _chat_response(self, user_input):
            """Generate a direct conversational response."""
            current_time = self._get_current_time()
            chat_prompt = f"""You are {self._agent_name}. {self._persona}
Current Time: {current_time}
Timezone: {self._tz_str}

Respond to the user naturally, concisely, and helpfully. Use Markdown formatting.

User: {user_input}"""
            
            try:
                response = self._llm.invoke(chat_prompt)
                return response.content
            except Exception as e:
                logging.error(f"Chat response error: {e}")
                return f"⚠️ Error generating response: {str(e)[:200]}"
        
        def invoke(self, inputs):
            """Process a user message — classify intent, call tool or chat."""
            user_input = inputs.get("input", "")
            
            if not user_input.strip():
                return {"output": "Please send a message."}
            
            # Step 1: Classify intent
            tool_name, params = self._classify(user_input)
            
            logging.info(f"Agent classified: tool={tool_name}, params={params}")
            
            # Step 2: If no tool needed, generate direct response
            if tool_name == "NONE" or tool_name not in self._tool_map:
                if tool_name != "NONE":
                    logging.warning(f"Unknown tool '{tool_name}', falling back to chat")
                return {"output": self._chat_response(user_input)}
            
            # Step 3: Execute tool
            try:
                tool = self._tool_map[tool_name]
                result = tool.invoke(params)
                return {"output": str(result)}
            except Exception as e:
                logging.error(f"Tool '{tool_name}' execution error: {e}", exc_info=True)
                # Fallback: try chat response about it
                return {"output": f"⚠️ Tool error ({tool_name}): {str(e)[:200]}"}
    
    return PromptAgent(llm, tool_map, tool_descriptions, agent_name, persona, tz_str)
