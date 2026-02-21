import os
import logging
import importlib.util
from skills.registry import skill

ALLOW_LIST_DIRS = ['skills', 'agents']
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def write_new_skill_or_agent(filename: str, code: str) -> str:
    """
    Writes a new Python file and dynamically loads it into the registry.
    """
    try:
        # Prevent absolute paths or directory traversal
        if ".." in filename or filename.startswith("/"):
            return "⚠️ Security Error: filename must be a relative path within 'skills/' or 'agents/'."
        
        parts = filename.split('/')
        if len(parts) != 2 or parts[0] not in ALLOW_LIST_DIRS:
            return "⚠️ Security Error: filename must be directly inside 'skills/' or 'agents/' directories."
            
        full_path = os.path.join(PROJECT_ROOT, filename)
        
        # Auto-inject required imports if the LLM forgot them
        if "from skills.registry import skill" not in code and "import skill" not in code and "@skill" in code:
            code = "from skills.registry import skill\n" + code
            
        if "import asyncio" not in code and ("async def" in code or "asyncio." in code):
            code = "import asyncio\n" + code
            
        # Write the file
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        logging.info(f"Meta-Coder wrote new file to {full_path}")
        
        # Dynamically load the module so the @skill decorators trigger
        module_name = filename.replace('/', '.').replace('.py', '')
        
        spec = importlib.util.spec_from_file_location(module_name, full_path)
        if spec and spec.loader:
            new_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(new_module)
            return f"✅ Success: Successfully created and loaded `{filename}` into the registry. Its capabilities are now available to the system."
        else:
            return f"⚠️ Error: File `{filename}` was written, but failed to load dynamically."
            
    except Exception as e:
        logging.error(f"Error in WRITE_NEW_SKILL_OR_AGENT: {e}", exc_info=True)
        return f"⚠️ Meta-Coder Error: {str(e)}"
