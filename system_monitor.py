import paramiko
import psutil
import logging
import io

def check_local_health():
    """Checks the health of the local machine."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "name": "Local System",
            "cpu": cpu,
            "ram_used": round(ram.used / (1024**3), 2),
            "ram_total": round(ram.total / (1024**3), 2),
            "ram_percent": ram.percent,
            "disk_percent": disk.percent,
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
        # 1. CPU Load (uptime)
        conn_stdin, conn_stdout, conn_stderr = client.exec_command("uptime | awk -F'load average:' '{ print $2 }'")
        load_avg = conn_stdout.read().decode().strip().split(',')[0] # 1 min load
        
        # 2. RAM (free -m)
        conn_stdin, conn_stdout, conn_stderr = client.exec_command("free -m | grep Mem | awk '{print $2, $3}'")
        ram_data = conn_stdout.read().decode().strip().split()
        ram_total = int(ram_data[0])
        ram_used = int(ram_data[1])
        ram_percent = round((ram_used / ram_total) * 100, 1)
        
        # 3. Disk (df -h /)
        conn_stdin, conn_stdout, conn_stderr = client.exec_command("df -h / | tail -1 | awk '{print $5}'")
        disk_percent = conn_stdout.read().decode().strip().replace('%', '')
        
        client.close()
        
        return {
            "name": name,
            "cpu_load": load_avg,
            "ram_used": round(ram_used / 1024, 2), # Convert MB to GB? No, free -m is MB. 
            "ram_total": round(ram_total / 1024, 2),
            "ram_percent": ram_percent,
            "disk_percent": int(disk_percent),
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
    if 'cpu' in health_data:
        report += f"   • CPU: {health_data['cpu']}%\n"
    elif 'cpu_load' in health_data:
        report += f"   • Load: {health_data['cpu_load']}\n"
        
    report += f"   • RAM: {health_data['ram_percent']}% ({health_data['ram_used']}GB / {health_data['ram_total']}GB)\n"
    report += f"   • Disk: {health_data['disk_percent']}%\n"
    
    return report

def get_system_status(config):
    reports = []
    
    # Check configured servers
    for server in config.get('servers', []):
        if server.get('type') == 'local':
             reports.append(check_local_health())
        else:
             reports.append(check_ssh_health(server))
             
    # If no servers configured, at least check local
    if not config.get('servers'):
        reports.append(check_local_health())
        
    return "\n".join([format_health_report(r) for r in reports])
