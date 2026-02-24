"""
System Ops Tool — Execute shell commands on the host machine.
"""
import logging
import subprocess
from langchain_core.tools import tool


@tool
def execute_shell_command(command: str, timeout: int = 60) -> str:
    """Execute a shell command on the host system. CAUTION: Use with care.
    Args:
        command: The shell command to execute.
        timeout: Max execution time in seconds (default 60)."""
    logging.info(f"Executing system command: {command}")
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        
        if not output:
            output = "Command executed successfully (no output)."
        
        return f"💻 **Command Output:**\n```bash\n{output}\n```"
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {timeout} seconds."
    except Exception as e:
        logging.error(f"Command execution failed: {e}")
        return f"❌ Execution failed: {str(e)}"
