"""
System Health Tool — Monitor local and remote server health.
"""
import logging
import time
import psutil
import paramiko
from datetime import timedelta
from langchain_core.tools import tool
import config as app_config


def check_local_health():
    """Checks the health of the local machine."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        boot = psutil.boot_time()
        uptime = timedelta(seconds=int(time.time() - boot))
        
        return {
            "name": "Local System",
            "type": "local",
            "cpu": f"{cpu}%",
            "ram_used": f"{ram.percent}%",
            "ram_total": f"{ram.total / (1024**3):.1f} GB",
            "disk_used": f"{disk.percent}%",
            "disk_total": f"{disk.total / (1024**3):.1f} GB",
            "uptime": str(uptime),
            "status": "ok"
        }
    except Exception as e:
        return {"name": "Local System", "status": "error", "error": str(e)}


def check_ssh_health(server_config):
    """Checks health of a remote server via SSH."""
    name = server_config.get('name', 'Unknown')
    host = server_config.get('host')
    user = server_config.get('user', 'root')
    password = server_config.get('password')
    port = server_config.get('port', 22)
    key_path = server_config.get('key_path')
    
    if not host:
        return {"name": name, "status": "error", "error": "No host configured"}
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        connect_kwargs = {"hostname": host, "username": user, "port": port, "timeout": 10}
        if key_path:
            connect_kwargs["key_filename"] = key_path
        elif password:
            connect_kwargs["password"] = password
        
        client.connect(**connect_kwargs)
        
        commands = {
            "cpu": "top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'",
            "ram": "free -m | awk 'NR==2{printf \"%s/%s MB (%.1f%%)\", $3, $2, $3*100/$2}'",
            "disk": "df -h / | awk 'NR==2{printf \"%s/%s (%s)\", $3, $2, $5}'",
            "uptime": "uptime -p"
        }
        
        results = {"name": name, "type": "ssh", "host": host, "status": "ok"}
        
        for key, cmd in commands.items():
            try:
                _, stdout, stderr = client.exec_command(cmd, timeout=10)
                output = stdout.read().decode().strip()
                results[key] = output if output else "N/A"
            except Exception:
                results[key] = "N/A"
        
        return results
    except paramiko.AuthenticationException:
        return {"name": name, "status": "error", "error": "Authentication failed"}
    except Exception as e:
        return {"name": name, "status": "error", "error": str(e)}
    finally:
        client.close()


def format_health_report(health_data):
    """Formats health data into a readable report."""
    msg = ""
    for server in health_data:
        name = server.get("name", "Unknown")
        status = server.get("status", "unknown")
        
        if status == "error":
            msg += f"❌ *{name}*: {server.get('error', 'Unknown error')}\n"
        else:
            msg += f"✅ *{name}*\n"
            if "cpu" in server:
                msg += f"  CPU: {server['cpu']}\n"
            if "ram_used" in server:
                msg += f"  RAM: {server['ram_used']} / {server.get('ram_total', 'N/A')}\n"
            elif "ram" in server:
                msg += f"  RAM: {server['ram']}\n"
            if "disk_used" in server:
                msg += f"  Disk: {server['disk_used']} / {server.get('disk_total', 'N/A')}\n"
            elif "disk" in server:
                msg += f"  Disk: {server['disk']}\n"
            if "uptime" in server:
                msg += f"  Uptime: {server['uptime']}\n"
        msg += "\n"
    
    return msg


def get_all_system_health(conf=None):
    """Returns health data for all configured servers (checked in parallel)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if conf is None:
        conf = app_config.load_config()
    
    servers = conf.get('servers', [])
    
    if not servers:
        return [check_local_health()]
    
    health_data = []
    
    def _check(server):
        if server.get('type') == 'local':
            return check_local_health()
        else:
            return check_ssh_health(server)
    
    with ThreadPoolExecutor(max_workers=min(len(servers), 10)) as executor:
        futures = {executor.submit(_check, s): s for s in servers}
        for future in as_completed(futures):
            try:
                health_data.append(future.result())
            except Exception as e:
                server = futures[future]
                health_data.append({"name": server.get('name', 'Unknown'), "status": "error", "error": str(e)})
    
    return health_data


@tool
def get_system_status() -> str:
    """Check system health of all servers (local and remote SSH). Shows CPU, RAM, Disk usage and uptime."""
    try:
        conf = app_config.load_config()
        health_data = get_all_system_health(conf)
        report = "🖥️ *System Health Report:*\n\n" + format_health_report(health_data)
        return report
    except Exception as e:
        logging.error(f"System health error: {e}")
        return f"⚠️ Failed to check system health: {e}"


@tool
def get_local_status() -> str:
    """Check local machine health only — CPU, RAM, Disk usage and uptime."""
    try:
        health = check_local_health()
        return "🖥️ *Local System:*\n\n" + format_health_report([health])
    except Exception as e:
        logging.error(f"Local health error: {e}")
        return f"⚠️ Failed to check local health: {e}"


# --- Background Job ---
async def check_server_health_job(context):
    """Background job to check server health and alert on issues. Runs in thread to avoid blocking."""
    import asyncio
    
    try:
        conf = app_config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        if not chat_id:
            return
        
        loop = asyncio.get_running_loop()
        health_data = await loop.run_in_executor(None, lambda: get_all_system_health(conf))
        
        alerts = []
        for server in health_data:
            if server.get('status') == 'error':
                alerts.append(f"❌ *{server['name']}*: {server.get('error', 'Unknown error')}")
            else:
                try:
                    cpu_val = float(str(server.get('cpu', '0')).replace('%', ''))
                    if cpu_val > 90:
                        alerts.append(f"⚠️ *{server['name']}*: CPU at {cpu_val}%")
                except (ValueError, TypeError):
                    pass
                
                try:
                    ram_str = str(server.get('ram_used', server.get('ram', '0')))
                    ram_val = float(ram_str.replace('%', '').split('(')[-1].split(')')[0].replace('%', '') if '(' in ram_str else ram_str.replace('%', ''))
                    if ram_val > 90:
                        alerts.append(f"⚠️ *{server['name']}*: RAM at {ram_val}%")
                except (ValueError, TypeError):
                    pass
        
        if alerts:
            alert_msg = "🚨 *Server Alert!*\n\n" + "\n".join(alerts)
            try:
                await context.bot.send_message(chat_id=chat_id, text=alert_msg, parse_mode='Markdown')
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=alert_msg)
    except Exception as e:
        logging.error(f"Server health job error: {e}")
