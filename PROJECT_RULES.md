# Project Rules & Developer Guidelines

## 1. Project Overview
This project is a modular **AI Personal Assistant** built with **LangChain** and **LangGraph**. It integrates website monitoring, ERP management, system health tracking, email operations, and content research into a single, extensible platform — accessible via **Telegram** and a **Web Dashboard**.

**Core Philosophy:**
- **Modularity:** Each capability is a LangChain `@tool` in `tools/`.
- **Non-Blocking:** All background jobs use `asyncio.run_in_executor` to avoid blocking.
- **Privacy:** Data is stored locally in SQLite (`monitor.db`).
- **Extensibility:** Add new tools without modifying the core agent.

---

## 2. Directory Structure

```
project_root/
├── app.py                 # Main entry point (starts Telegram bot + web server)
├── requirements.txt       # Python dependencies
├── monitor.db             # SQLite database (git-ignored)
├── .env                   # Environment variables (git-ignored)
├── config/
│   ├── config.yaml        # Main configuration (git-ignored)
│   └── __init__.py        # Config loader (app_config.load_config())
├── core/
│   ├── agent.py           # Prompt-based agent with tool routing
│   ├── llm.py             # Ollama LLM initialization
│   ├── database.py        # Centralized Database Access Layer
│   └── memory.py          # ChromaDB chat memory (optional)
├── tools/                 # ALL AI capabilities as LangChain tools
│   ├── notes.py           # Notes management
│   ├── reminders.py       # Reminder scheduling
│   ├── web_monitor.py     # Website change detection
│   ├── web_search.py      # DuckDuckGo web search
│   ├── system_health.py   # Server health monitoring (SSH)
│   ├── system_ops.py      # Shell command execution
│   ├── erp.py             # GBYTE ERP API integration
│   ├── email_ops.py       # Email checking (IMAP)
│   ├── workflows.py       # Scheduled workflow automation
│   ├── content_researcher.py  # AI content generation
│   ├── seo_expert.py      # SEO analysis
│   ├── meta_coder.py      # Dynamic tool creation
│   └── notifications.py   # Telegram notifications
├── bot/
│   └── telegram_bot.py    # Telegram handlers & background job scheduling
├── web/
│   ├── server.py          # FastAPI web server & dashboard
│   ├── chat_handler.py    # Web chat endpoint
│   ├── static/            # CSS, JS, images
│   └── templates/         # Jinja2 HTML templates
├── service/               # Systemd service files
├── logs/                  # Runtime logs (git-ignored)
└── _legacy/               # Old code (pre-LangChain, reference only)
```

---

## 3. Coding Standards

### General Python
- **Version:** Python 3.10+
- **Style:** PEP 8 — snake_case for functions/variables, PascalCase for classes.
- **Async:** Use `asyncio` for all I/O-bound operations.
- **Logging:**
  - ❌ `print("Error")`
  - ✅ `logging.error("Error")`
  - Use the globally configured logger.

### Configuration
- **Never hardcode secrets.**
- Access config via:
  ```python
  import config as app_config
  conf = app_config.load_config()
  value = conf['section'].get('key')
  ```

### Database
- **All SQL** must go through `core/database.py` — never write raw SQL in tools.
- **Schema changes** must update `init_db()` in `core/database.py`.
- **Connections:** Use `database.get_connection()` for direct access.

---

## 4. Creating New Tools

All AI capabilities are LangChain `@tool` functions in `tools/`.

### Steps to Create a New Tool
1. Create or update a module in `tools/`.
2. Import the decorator: `from langchain_core.tools import tool`
3. Decorate your function with `@tool`.
4. Add clear docstring — this becomes the tool description for the agent.
5. Register the tool in `core/agent.py` → `get_all_tools()`.
6. Return a user-friendly string (Markdown supported).

### Example
```python
from langchain_core.tools import tool

@tool
def calculate_sum(a: float, b: float) -> str:
    """Add two numbers together. Args: a — first number, b — second number."""
    try:
        result = a + b
        return f"✅ The sum is *{result}*."
    except Exception as e:
        return f"⚠️ Error: {e}"
```

### Tool Description Best Practices
The docstring is used by the agent to decide when to invoke the tool.
- ✅ **Good:** `"Search for invoices by customer name. Args: customer_name — the name to search."`
- ❌ **Bad:** `"Search func."`

---

## 5. Background Jobs

Background jobs run via the Telegram bot's job queue (APScheduler).

### Rules
- **All I/O ops** must run inside `asyncio.get_running_loop().run_in_executor(None, func)`.
- **Never block the event loop** — HTTP requests, SSH, LLM calls, DB queries all go in executor.
- **Parallel HTTP** is fine (ThreadPoolExecutor) — it's pure network I/O, no GPU.
- **Sequential LLM** calls — avoid parallel GPU load.

### Example Pattern
```python
async def my_background_job(context):
    import asyncio
    loop = asyncio.get_running_loop()
    
    def _do_work():
        # Blocking I/O here (HTTP, SSH, DB, etc.)
        return result
    
    result = await loop.run_in_executor(None, _do_work)
    # Async bot messaging here
    await context.bot.send_message(chat_id=chat_id, text=result)
```

---

## 6. Web Interface
- Built with **FastAPI** + **Jinja2**.
- **Static files:** `web/static/`
- **Templates:** `web/templates/`
- Starts automatically with `app.py` on port **8000**.
- Dashboard shows: server health, website monitoring, and live logs.

---

## 7. ERP Integration
- API base URL set in `config.yaml` → `GBYTE_ERP_URL`.
- Auth uses `X-API-KEY` header (from `config.yaml` → `API_KEY`).
- All endpoints go through `{base_url}/api/agent/...`.
- Tool functions in `tools/erp.py`.

---

## 8. Git Rules
- **Branches:** Use feature branches (e.g., `feature/add-weather-tool`).
- **Commits:** Clear, descriptive messages.
- **Ignored:**
  - `*.log`, `*.db`, `.env`
  - `config/config.yaml` (use example template)
  - `debug/`, `__pycache__/`

---

## 9. Deployment & Troubleshooting

### Service Management
```bash
sudo systemctl start ai-assistant
sudo systemctl stop ai-assistant
sudo systemctl restart ai-assistant
systemctl status ai-assistant
```

### Development Workflow
1. Stop service: `sudo systemctl stop ai-assistant`
2. Run manually: `python3 app.py`
3. Make changes, test.
4. Restart service: `sudo systemctl restart ai-assistant`

### Logs
- Runtime: `logs/monitor.log`
- Service: `journalctl -u ai-assistant -f`

---

## ⚠️ Critical Rules

1. **The AI Assistant MUST NOT run `systemctl` commands.** These are manual user actions only.
2. **Never store secrets in code.** Always use `config.yaml` or `.env`.
3. **Never block the asyncio event loop.** All sync I/O goes in `run_in_executor`.
4. **All database access goes through `core/database.py`.** No raw SQL in tools.
5. **All new capabilities go in `tools/` as `@tool` functions.** Never modify `core/agent.py` for feature logic.
