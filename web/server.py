"""
FastAPI Web Server
Dashboard, database viewer, chat interface, and API endpoints.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import logging
from datetime import datetime
from pydantic import BaseModel

from core import database
import config as app_config
from tools.system_health import get_all_system_health
from web.chat_handler import ChatHandler

app = FastAPI(title="AI Assistant")
chat_handler = ChatHandler()


class ChatRequest(BaseModel):
    message: str


# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Templates
templates = Jinja2Templates(directory="web/templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    import asyncio
    
    conf = app_config.load_config()
    
    # 1. System Health (run in thread to avoid blocking)
    try:
        loop = asyncio.get_running_loop()
        raw_health = await loop.run_in_executor(None, lambda: get_all_system_health(conf))
        # Adapt data to match what the dashboard template expects
        servers_health = []
        for s in raw_health:
            adapted = {
                "name": s.get("name", "Unknown"),
                "status": "online" if s.get("status") == "ok" else "offline",
                "error": s.get("error", ""),
                "uptime": s.get("uptime", "N/A"),
            }
            # Parse CPU percent (comes as "5.2%" or "5.2")
            try:
                cpu_str = str(s.get("cpu", "0")).replace("%", "").strip()
                adapted["cpu_percent"] = float(cpu_str)
            except (ValueError, TypeError):
                adapted["cpu_percent"] = 0
            # Parse RAM percent
            try:
                ram_str = str(s.get("ram_used", s.get("ram", "0")))
                # Handle formats: "45.3%" or "1234/8000 MB (45.3%)"
                if "(" in ram_str:
                    ram_str = ram_str.split("(")[-1].split(")")[0]
                adapted["ram_percent"] = float(ram_str.replace("%", "").strip())
            except (ValueError, TypeError):
                adapted["ram_percent"] = 0
            # Parse Disk percent
            try:
                disk_str = str(s.get("disk_used", s.get("disk", "0")))
                if "(" in disk_str:
                    disk_str = disk_str.split("(")[-1].split(")")[0]
                adapted["disk_percent"] = float(disk_str.replace("%", "").strip())
            except (ValueError, TypeError):
                adapted["disk_percent"] = 0
            servers_health.append(adapted)
    except Exception as e:
        logging.error(f"Error fetching system health: {e}")
        servers_health = [{"name": "Error", "status": "offline", "error": str(e), "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0, "uptime": "N/A"}]
    
    # 2. Websites (from DB)
    try:
        websites_raw = database.get_all_websites()
    except Exception as e:
        websites_raw = []
        logging.error(f"Error fetching websites: {e}")
    
    website_status = []
    for w in websites_raw:
        status = "Active"
        status_class = "status-ok"
        
        if w[2]:  # last_error
            status = f"Error: {w[2]}"
            status_class = "status-err"
        elif w[3] and w[3] >= 400:  # status_code
            status = f"Error (HTTP {w[3]})"
            status_class = "status-err"
        
        website_status.append({
            "url": w[0],
            "last_checked": w[1],
            "status": status,
            "status_class": status_class,
            "summary": w[4] if w[4] else "No changes detected."
        })
    
    # 3. Logs
    logs = []
    try:
        with open("logs/monitor.log", "r") as f:
            logs = f.readlines()[-50:]
    except FileNotFoundError:
        logs = ["Log file not found."]
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "servers": servers_health,
        "websites": website_status,
        "logs": "".join(logs)
    })


@app.get("/table/{table_name}", response_class=HTMLResponse)
async def view_table(request: Request, table_name: str, page: int = 1, limit: int = 20,
                     q: str = None, sort: str = None, order: str = 'DESC'):
    
    # Extract column filters
    filters = {}
    for key, value in request.query_params.items():
        if key.startswith('f_') and value:
            col_name = key[2:]
            filters[col_name] = value
    
    # Get all tables
    import sqlite3
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in c.fetchall() if row[0] != 'sqlite_sequence']
    conn.close()
    
    if table_name not in tables:
        return HTMLResponse("Table not found", status_code=404)
    
    try:
        rows, total_count, columns = database.get_table_data(
            table_name, page, limit, sort_by=sort, sort_order=order, search=q, filters=filters
        )
        total_pages = (total_count + limit - 1) // limit
    except Exception as e:
        return HTMLResponse(f"Error loading table: {e}", status_code=500)
    
    return templates.TemplateResponse("table.html", {
        "request": request,
        "table_name": table_name,
        "tables": tables,
        "columns": columns,
        "rows": rows,
        "page": page,
        "total_pages": total_pages,
        "limit": limit,
        "q": q,
        "sort": sort,
        "order": order,
        "filters": filters
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.post("/api/chat")
async def chat_api(request: ChatRequest):
    response = await chat_handler.process_message(request.message)
    return {"response": response}


@app.get("/api/logs")
async def api_logs():
    try:
        with open("logs/monitor.log", "r") as f:
            lines = f.readlines()[-100:]
            return {"logs": "".join(lines)}
    except Exception:
        return {"logs": "Log file not found."}
