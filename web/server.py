from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import logging
import database
import config
from skills import system_health, erp
from datetime import datetime
from pydantic import BaseModel
from web.chat_handler import ChatHandler

app = FastAPI()
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
    conf = config.load_config()
    
    # Fetch Data
    # 1. System Health
    servers_health = system_health.get_all_system_health(conf)
    
    # 2. Websites (from DB)
    conn = database.get_connection()
    c = conn.cursor()
    # Updated query to fetch new columns: last_error, status_code, last_summary
    # Note: Using `try-except` or checking columns isn't easy in raw SQL without schema info, 
    # but we just added them. If old DB, it might fail unless migration ran.
    # The migration logic is in init_db(), so we should be good if app restarted.
    try:
        c.execute("SELECT url, last_checked, last_error, status_code, last_summary FROM websites")
        websites = c.fetchall()
    except Exception as e:
        websites = []
        logging.error(f"Error fetching websites: {e}")

    conn.close()
    
    website_status = []
    for w in websites:
        # url, last_checked, last_error, status_code, last_summary
        status = "Active"
        status_class = "status-ok"
        
        if w[2]: # last_error is not None
            status = f"Error: {w[2]}"
            status_class = "status-err"
        elif w[3] and w[3] >= 400: # status_code >= 400
            status = f"Error (HyperText Transfer Protocol {w[3]})"
            status_class = "status-err"
            
        website_status.append({
            "url": w[0],
            "last_checked": w[1],
            "status": status,
            "status_class": status_class,
            "summary": w[4] if w[4] else "No changes detected."
        })

    # 3. Logs (Read last 50 lines)
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
async def view_table(request: Request, table_name: str, page: int = 1, limit: int = 20):
    conn = database.get_connection()
    c = conn.cursor()
    
    # Get all tables for the menu
    c.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in c.fetchall() if row[0] != 'sqlite_sequence']
    
    # Validate table name to prevent SQL injection
    if table_name not in tables:
        return HTMLResponse("Table not found", status_code=404)
        
    # Get total count
    c.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_count = c.fetchone()[0]
    total_pages = (total_count + limit - 1) // limit
    
    # Get column names
    c.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in c.fetchall()]
    
    # Get data with pagination
    offset = (page - 1) * limit
    c.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (limit, offset))
    rows = c.fetchall()
    
    conn.close()
    
    return templates.TemplateResponse("table.html", {
        "request": request,
        "table_name": table_name,
        "tables": tables,
        "columns": columns,
        "rows": rows,
        "page": page,
        "total_pages": total_pages,
        "limit": limit
    })

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/api/chat")
async def chat_api(request: ChatRequest):
    response = await chat_handler.process_message(request.message, chat_id="web-user")
    return {"response": response}

@app.get("/api/logs")
async def api_logs():
    try:
        with open("logs/monitor.log", "r") as f:
            # Return last 100 lines for realtime view
            lines = f.readlines()[-100:]
            return {"logs": "".join(lines)}
    except:
        return {"logs": "Log file not found."}
