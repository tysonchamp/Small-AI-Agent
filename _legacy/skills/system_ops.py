import logging
import subprocess
from skills.registry import skill

@skill(name="EXECUTE_SHELL_COMMAND", description="Execute a shell command on the host system. CAUTION: Use with care. Params: command, timeout (default 60)")
def execute_shell_command(command, timeout=60):
    """
    Executes a shell command and returns the output.
    """
    logging.info(f"Executing system command: {command}")
    
    try:
        # Security Note: This runs with the permissions of the user running the bot.
        # The bot is already restricted to Admin-only via the @authorized_only decorator in monitor.py
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
