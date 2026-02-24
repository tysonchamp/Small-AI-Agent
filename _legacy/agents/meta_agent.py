import logging
import asyncio
import json
import ollama
from skills.registry import skill
from skills.meta_coder import write_new_skill_or_agent
import config

async def run_meta_agent(agent_description: str, chat_id: str, context):
    """The async meta-agent loop that generates Python code for new agents or skills."""
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"🏗️ *Meta-Agent*: I have started designing and coding a new capability based on: `{agent_description}`. Please wait...", parse_mode='Markdown')
        
        loop = asyncio.get_running_loop()
        
        conf = config.load_config()
        model = conf['ollama'].get('model', 'gemma3:latest')
        
        prompt = f"""You are an elite, senior AI Architect and Python Developer Meta-Agent.
Your objective is to write the Python code for a new Sub-Agent or Skill based on the following user request:

REQUEST: "{agent_description}"

CRITICAL INSTRUCTIONS:
1. You must output exactly two things in clear markdown formats:
   - The file path wrapped in `__FILENAME__` block. Example: `__FILENAME__agents/crypto_agent.py__FILENAME__`. It MUST start with "agents/" or "skills/".
   - The Python code wrapped inside a standard ```python code block.

2. Python Code Requirements:
   - It MUST import the `@skill` decorator: `from skills.registry import skill`
   - It MUST define at least one function decorated with `@skill(name="...", description="...")`.
   - IMPORTANT: DO NOT PASS ANY OTHER ARGUMENTS TO THE @skill DECORATOR EXCEPT `name` AND `description`. Do not use `args`, `return_type`, `arguments`, `params`, or anything else. The decorator automatically introspects function arguments. If you use `kwargs` in the `@skill` decorator it will instantly throw a Python TypeError and crash.
   - The `description` inside the `@skill` decorator must clearly explain to the main AI exactly *when* and *how* to use it.
   - For complex agents, include an async background execution function (like `seo_expert.py`) using `asyncio.create_task()`.
   - DO NOT include anything else in your response other than the filename block and the python code block.
"""
        
        messages = [
            {'role': 'system', 'content': 'You are a Python code generator API.'},
            {'role': 'user', 'content': prompt}
        ]
        
        max_retries = 3
        
        for attempt in range(max_retries):
            response = await loop.run_in_executor(None, lambda: ollama.chat(model=model, messages=messages))
            raw_content = response['message']['content'].strip()
            
            try:
                # Extract filename
                import re
                filename_match = re.search(r'__FILENAME__(.*?)__FILENAME__', raw_content)
                if not filename_match:
                    filename_match = re.search(r'(agents/[a-zA-Z0-9_]+\.py|skills/[a-zA-Z0-9_]+\.py)', raw_content)
                    if not filename_match:
                        raise ValueError("Could not find a valid filename in the output.")
                
                filename = filename_match.group(1).strip()
                
                # Extract code
                code_match = re.search(r'```python\n(.*?)\n```', raw_content, re.DOTALL)
                if not code_match:
                     code_match = re.search(r'```\n(.*?)\n```', raw_content, re.DOTALL)
                     if not code_match:
                         raise ValueError("Could not find the Python code block in the output.")
                         
                code = code_match.group(1).strip()
                
                # Use the meta_coder skill to write the file dynamically
                write_result = write_new_skill_or_agent(filename=filename, code=code)
                
                if "⚠️" in write_result:
                    if attempt < max_retries - 1:
                        # Append context for self-healing
                        messages.append({'role': 'assistant', 'content': raw_content})
                        fix_prompt = f"The code you generated failed to compile or load dynamically. Here is the exact error:\n\n{write_result}\n\nPlease identify the issue, fix the code, and return the complete updated file path (wrapped in __FILENAME__ blocks) and the fixed Python code block. Do NOT include any other text."
                        messages.append({'role': 'user', 'content': fix_prompt})
                        
                        await context.bot.send_message(chat_id=chat_id, text=f"🔧 *Meta-Agent Self-Healing* (Attempt {attempt+1}/{max_retries}):\nDetected code error. The agent is analyzing the traceback to fix the code...\n`{write_result.splitlines()[-1]}`", parse_mode='Markdown')
                        continue
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ *Meta-Agent Failure*:\nFailed to compile `{filename}` after {max_retries} attempts.\n\nFinal Error:\n{write_result}", parse_mode='Markdown')
                        break
                else:
                    await context.bot.send_message(chat_id=chat_id, text=f"🚀 *Meta-Agent Update*:\n`{filename}` generated efficiently.\n\nResult:\n{write_result}", parse_mode='Markdown')
                    break
                
            except ValueError as e:
                logging.error(f"Meta-Agent Parsing Error: {e}\nRaw={raw_content}")
                if attempt < max_retries - 1:
                     messages.append({'role': 'assistant', 'content': raw_content})
                     messages.append({'role': 'user', 'content': f"I could not parse your response. Make sure to use the __FILENAME__ block and the ```python code block. Error: {e}"})
                     continue
                else:
                     await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *Meta-Agent*: Failed to parse generated code after {max_retries} attempts.\nError: {e}", parse_mode='Markdown')
                     break
            except Exception as e:
                logging.error(f"Meta-Agent Generation Error: {e}")
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *Meta-Agent*: An error occurred during coding.\n`{str(e)}`", parse_mode='Markdown')
                break
            
    except Exception as e:
        logging.error(f"Meta-Agent error: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *Meta-Agent Error*: `{str(e)}`", parse_mode='Markdown')

@skill(name="CREATE_NEW_AGENT_OR_SKILL", description="Delegates a task to the Meta-Agent (the architect) to write actual Python code for a new capability, tool, or sub-agent dynamically. Use this when the user asks you to create a new agent, write a new skill, or extend your codebase. Params: instruction (String describing the required agent or skill)")
async def delegate_meta_agent(instruction: str, chat_id: str = None, context = None):
    """
    Spawns the Meta-Agent in the background to write code.
    """
    if not instruction:
         return "⚠️ Please provide instructions for the Meta-Agent."
    
    if not chat_id or not context:
        return "⚠️ Setup Error: The Meta-Agent requires Telegram context to run asynchronously."

    # Spawn the background task
    asyncio.create_task(run_meta_agent(instruction, chat_id, context))
    
    return f"👨‍💻 **Delegating to Meta-Agent**...\nI've assigned the Meta-Agent to write code for: `{instruction}`. I'll notify you when it's compiled and loaded."
