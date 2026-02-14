
import logging
import inspect
import functools

# Global Registry
# Format: { "ACTION_NAME": { "func": function_obj, "description": "docstring", "params": ["param1"] } }
TOOLS = {}

def skill(name=None, description=None):
    """Decorator to register a function as a skill available to the AI."""
    def decorator(func):
        # Use provided name or default to function function name (upper case)
        tool_name = name if name else func.__name__.upper()
        
        # Use provided description or docstring
        tool_desc = description if description else (func.__doc__ or "No description provided.")
        tool_desc = tool_desc.strip()
        
        # Get parameters (simple introspection)
        sig = inspect.signature(func)
        param_names = [p.name for p in sig.parameters.values() if p.name not in ['self', 'cls', 'chat_id']]

        TOOLS[tool_name] = {
            "func": func,
            "description": tool_desc,
            "params": param_names
        }
        
        logging.info(f"Registered Skill: {tool_name}")
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def get_system_prompt_tools():
    """Generates the 'Possible Actions' section of the prompt dynamically."""
    prompt_text = ""
    for i, (name, metadata) in enumerate(TOOLS.items(), 1):
        prompt_text += f'{i}. "{name}": {metadata["description"]}\n'
        if metadata["params"]:
            prompt_text += f'   - params: {", ".join(metadata["params"])}\n'
        prompt_text += "\n"
    return prompt_text
