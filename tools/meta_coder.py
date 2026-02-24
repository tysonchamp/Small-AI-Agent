"""
Meta Coder Tool — Dynamically generate and load new Python tools/agents.
"""
import os
import re
import logging
import importlib.util
from langchain_core.tools import tool
import config as app_config


ALLOW_LIST_DIRS = ['tools', 'agents']
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_and_load_module(filename: str, code: str) -> str:
    """Writes a Python file and dynamically loads it."""
    try:
        if ".." in filename or filename.startswith("/"):
            return "⚠️ Security Error: filename must be a relative path within 'tools/' or 'agents/'."
        
        parts = filename.split('/')
        if len(parts) != 2 or parts[0] not in ALLOW_LIST_DIRS:
            return "⚠️ Security Error: filename must be directly inside 'tools/' or 'agents/' directories."
        
        full_path = os.path.join(PROJECT_ROOT, filename)
        
        # Auto-inject required imports if missing
        if "from langchain_core.tools import tool" not in code and "@tool" in code:
            code = "from langchain_core.tools import tool\n" + code
        
        if "import asyncio" not in code and ("async def" in code or "asyncio." in code):
            code = "import asyncio\n" + code
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(code)
        
        logging.info(f"Meta-Coder wrote new file to {full_path}")
        
        # Dynamically load the module
        module_name = filename.replace('/', '.').replace('.py', '')
        spec = importlib.util.spec_from_file_location(module_name, full_path)
        if spec and spec.loader:
            new_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(new_module)
            return f"✅ Successfully created and loaded `{filename}`."
        else:
            return f"⚠️ File `{filename}` was written, but failed to load dynamically."
    except Exception as e:
        logging.error(f"Meta-Coder write error: {e}", exc_info=True)
        return f"⚠️ Meta-Coder Error: {str(e)}"


@tool
def create_new_tool(instruction: str) -> str:
    """Generate a new Python tool or agent from a natural language description. Uses AI to write the code and dynamically loads it.
    Args:
        instruction: A detailed description of what the new tool/agent should do."""
    try:
        from core.llm import get_llm
        
        llm = get_llm(task_type="complex")  # Use Gemini for code generation
        
        prompt = f"""You are an elite Python Developer. Write Python code for a new tool based on this request:

REQUEST: "{instruction}"

CRITICAL INSTRUCTIONS:
1. Output exactly two things:
   - File path wrapped in __FILENAME__ block. Example: __FILENAME__tools/weather.py__FILENAME__. Must start with "tools/" or "agents/".
   - Python code in a ```python block.

2. Code Requirements:
   - Import the decorator: `from langchain_core.tools import tool`
   - Define at least one function decorated with `@tool`
   - The function MUST have a descriptive docstring (this becomes the tool description)
   - Use type hints for all parameters
   - Return a string result
   - Handle errors gracefully

3. Do NOT include anything else in your response.

Example:
__FILENAME__tools/example.py__FILENAME__
```python
from langchain_core.tools import tool

@tool
def example_function(param: str) -> str:
    \"\"\"Description of what this tool does. Args: param — what this parameter is for.\"\"\"
    return f"Result: {{param}}"
```"""
        
        response = llm.invoke(prompt)
        raw_content = response.content.strip()
        
        # Extract filename
        filename_match = re.search(r'__FILENAME__(.*?)__FILENAME__', raw_content)
        if not filename_match:
            filename_match = re.search(r'(tools/[a-zA-Z0-9_]+\.py|agents/[a-zA-Z0-9_]+\.py)', raw_content)
            if not filename_match:
                return "⚠️ Could not determine filename from generated code."
        
        filename = filename_match.group(1).strip()
        
        # Extract code
        code_match = re.search(r'```python\n(.*?)\n```', raw_content, re.DOTALL)
        if not code_match:
            code_match = re.search(r'```\n(.*?)\n```', raw_content, re.DOTALL)
            if not code_match:
                return "⚠️ Could not extract Python code from generated output."
        
        code = code_match.group(1).strip()
        
        result = write_and_load_module(filename, code)
        return f"👨‍💻 **Meta-Coder Result:**\nFile: `{filename}`\n{result}"
    except Exception as e:
        logging.error(f"Meta-Coder error: {e}", exc_info=True)
        return f"⚠️ Meta-Coder Error: {str(e)}"
