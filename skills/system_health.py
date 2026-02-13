import paramiko
import psutil
import logging
import io
from telegram import Update
from telegram.ext import ContextTypes

import config

async def handle_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check system status from /status command."""
    conf = config.load_config()
    msg = get_system_status(conf)
    await update.message.reply_text(msg, parse_mode='Markdown')

import time
from datetime import timedelta

def check_local_health():
    """Checks the health of the local machine."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Uptime
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))

        return {
            "name": "Local System",
            "cpu_percent": cpu,
            "ram_used": round(ram.used / (1024**3), 2),
            "ram_total": round(ram.total / (1024**3), 2),
            "ram_percent": ram.percent,
            "disk_percent": disk.percent,
            "uptime": uptime_str,
            "status": "online"
        }
    except Exception as e:
        logging.error(f"Error checking local health: {e}")
        return {"name": "Local System", "status": "error", "error": str(e)}

def check_ssh_health(server_config):
    """Checks the health of a remote server via SSH."""
    hostname = server_config.get('host')
    username = server_config.get('user', 'root')
    password = server_config.get('password')
    key_path = server_config.get('key_path')
    port = server_config.get('port', 22)
    name = server_config.get('name', hostname)
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        connect_kwargs = {"hostname": hostname, "username": username, "port": port}
        if key_path:
            connect_kwargs["key_filename"] = key_path
        if password:
            connect_kwargs["password"] = password
            
        client.connect(**connect_kwargs, timeout=10)
        
        # Run commands
        # 1. CPU Usage % (read /proc/stat twice)
        # We run a compound command to get two readings with a 1s delay
        cmd = (
            "grep 'cpu ' /proc/stat; sleep 1; grep 'cpu ' /proc/stat; "
            "free -m | grep Mem | awk '{print $2, $3}'; "
            "df -h / | tail -1 | awk '{print $5}'; "
            "cat /proc/uptime"
        )
        stdin, stdout, stderr = client.exec_command(cmd)
        output = stdout.read().decode().strip().split('\n')
        
        # Parse CPU
        cpu_usage = "?"
        if len(output) >= 4:
            # CPU
            fields1 = [float(x) for x in output[0].split()[1:]]
            fields2 = [float(x) for x in output[1].split()[1:]]
            
            total1 = sum(fields1)
            idle1 = fields1[3]
            total2 = sum(fields2)
            idle2 = fields2[3]
            
            delta_total = total2 - total1
            delta_idle = idle2 - idle1
            
            if delta_total > 0:
                cpu_usage = round((1 - (delta_idle / delta_total)) * 100, 1)
            else:
                cpu_usage = 0.0
                
            # RAM
            ram_data = output[2].split()
            ram_total = int(ram_data[0])
            ram_used = int(ram_data[1])
            ram_percent = round((ram_used / ram_total) * 100, 1)
            
            # Disk
            disk_percent = int(output[3].strip().replace('%', ''))
            
            # Uptime
            uptime_seconds = float(output[4].split()[0])
            uptime_str = str(timedelta(seconds=int(uptime_seconds)))
            
        else:
             raise Exception("Unexpected output format from server")
        
        client.close()
        
        return {
            "name": name,
            "cpu_percent": cpu_usage,
            "ram_used": round(ram_used / 1024, 2), # Convert MB to GB? No, free -m is MB. 
            "ram_total": round(ram_total / 1024, 2),
            "ram_percent": ram_percent,
            "disk_percent": disk_percent,
            "uptime": uptime_str,
            "status": "online"
        }
        
    except Exception as e:
        logging.error(f"Error checking remote server {name}: {e}")
        return {"name": name, "status": "offline", "error": str(e)}

def format_health_report(health_data):
    if health_data.get('status') == 'offline':
        return f"❌ *{health_data['name']}*: OFFLINE ({health_data.get('error')})"
    
    icon = "✅"
    if health_data.get('disk_percent', 0) > 90 or health_data.get('ram_percent', 0) > 95:
        icon = "⚠️"
        
    report = f"{icon} *{health_data['name']}*\n"
    if 'cpu_percent' in health_data:
        report += f"   • CPU: {health_data['cpu_percent']}%\n"
    elif 'cpu_load' in health_data:
        report += f"   • Load: {health_data['cpu_load']}\n"
        
    report += f"   • RAM: {health_data['ram_percent']}% ({health_data['ram_used']}GB / {health_data['ram_total']}GB)\n"
    report += f"   • Disk: {health_data['disk_percent']}%\n"
    report += f"   • Uptime: {health_data.get('uptime', 'N/A')}\n"
    
    return report

from skills.registry import skill

@skill(name="SYSTEM_HEALTH", description="Check comprehensive system health (Local + SSH).")
def get_system_status(conf=None):
    if not conf:
        conf = config.load_config()
    
    # Backward compatibility for string report
    reports = get_all_system_health(conf)
    return "\n".join([format_health_report(r) for r in reports])

@skill(name="STATUS", description="Check local system health only.")
def get_local_status():
    local = check_local_health()
    return f"*🖥️ Local Status:*\n{format_health_report(local)}"

def get_all_system_health(config):
    """Returns a list of health dictionaries for all configured servers."""
    reports = []
    
    # Check configured servers
    for server in config.get('servers', []):
        if server.get('type') == 'local':
             reports.append(check_local_health())
        else:
             reports.append(check_ssh_health(server))
             
    # If no servers configured or list empty
    if not reports and not config.get('servers'):
        reports.append(check_local_health())
        
    return reports

async def check_server_health_job(context: ContextTypes.DEFAULT_TYPE, report_all=False):
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    
    if not chat_id:
        return

    full_report = "🖥️ *System Health Report*\n\n"
    has_alerts = False

    # custom check to get objects, not string report
    for server in conf.get('servers', []):
        try:
            if server.get('type') == 'local':
                data = check_local_health()
            else:
                data = check_ssh_health(server)
            
            # Check thresholds
            server_status_msg = f"*{data['name']}*: "
            
            if data.get('status') == 'offline':
                server_status_msg += f"🔴 OFFLINE ({data.get('error')})"
                has_alerts = True
                full_report += server_status_msg + "\n"
            else:
                server_status_msg += "🟢 Online\n"
                server_status_msg += f"   CPU: {data.get('cpu_percent', '?')}% | RAM: {data.get('ram_percent', '?')}% | Disk: {data.get('disk_percent', '?')}%\n"
                
                # Append to full report
                full_report += server_status_msg + "\n"

                # Check for critical alerts to send IMMEDIATELY if we aren't already reporting all
                if not report_all:
                    if data.get('disk_percent', 0) > 90 or data.get('ram_percent', 0) > 95:
                        # Send specific alert
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ *Critical Alert*\n{server_status_msg}", parse_mode='Markdown')

        except Exception as e:
            logging.error(f"Error checking server {server.get('name')}: {e}")
            full_report += f"*{server.get('name')}*: ⚠️ Check Failed ({e})\n"

    # Send full report if requested OR if there are offline servers (which we always want to know about in a summary)
    if report_all:
        try:
            await context.bot.send_message(chat_id=chat_id, text=full_report, parse_mode='Markdown')
        except Exception as e:
             logging.error(f"Error sending health report: {e}")
