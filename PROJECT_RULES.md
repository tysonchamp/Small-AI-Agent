# Project Rules & Developer Guidelines

## 1. Project Overview
This project is a modular **AI Personal Assistant** designed to run on a local machine or VPS. It integrates persistent memory, website monitoring, ERP management, and system health tracking into a single, extensible platform.

**Core Philosophy:**
- **Modularity:** Functionalities are encapsulated in `skills/`.
- **Autonomy:** The AI identifies intents dynamically using a Skill Registry.
- **Privacy:** Data is stored locally in SQLite (`monitor.db`).

---

## 2. Directory Structure
Follow this structure for all new code:

```
project_root/
├── monitor.py           # Main entry point (Telegram Bot + Dispatcher)
├── database.py          # Centralized Database Access Layer
├── config/
│   ├── config.yaml      # Main configuration (git-ignored)
│   └── __init__.py      # Config loader
├── skills/              # ALL AI capabilities go here
│   ├── registry.py      # Core skill registration logic (@skill)
│   ├── erp.py           # ERP integration
│   ├── reminders.py     # Reminder logic
│   └── ...
├── web/                 # Web Interface (FastAPI)
│   ├── server.py        # Web Server entry point
│   ├── static/          # CSS/JS
│   └── templates/       # Jinja2 HTML templates
├── logs/                # Runtime logs (git-ignored)
└── debug/               # Scratchpad scripts (git-ignored)
```

---

## 3. Coding Standards

### General Python
- **Version:** Python 3.10+
- **Style:** Follow PEP 8 (Snake case for functions/variables, Pascal case for Classes).
- **Async/Await:** Use `asyncio` for all I/O bound operations (API calls, DB queries).
- **Type Hinting:** Strongly recommended for all function arguments.
- **Logging:**
  - ❌ `print("Error")`
  - ✅ `logging.error("Error")`
  - Use the globally configured logger.

### Configuration
- **Never hardcode secrets.**
- Use `config.load_config()` to access `config.yaml`.
- Example:
  ```python
  import config
  conf = config.load_config()
  api_key = conf['section'].get('key')
  ```

### Database
- **Centralized Logic:** All SQL queries **MUST** reside in `database.py`.
- **Helpers:** Do not write raw SQL in `skills/*` or `monitor.py`; create a helper function in `database.py`.
- **Schema:** Update `init_db()` in `database.py` for any schema changes.

---

## 4. Skill Registry (Critical ⚡)
The AI's intelligence is driven by the dynamic registry in `skills/registry.py`.

### How to Create a New Skill
1. **Create/Update a module** in `skills/`.
2. **Import the decorator:** `from skills.registry import skill`
3. **Decorate your function:**
   - `name`: unique identifier (e.g., "ADD_REMINDER").
   - `description`: CLEAR, detailed instruction for the LLM on *when* and *how* to use it.
4. **Return String:** The function must return a user-friendly string (Markdown allowed).

### Example
```python
from skills.registry import skill

@skill(name="CALCULATE_SUM", description="Adds two numbers. Params: a, b")
def calculate_sum(a, b):
    try:
        result = float(a) + float(b)
        return f"✅ The sum is *{result}*."
    except ValueError:
        return "⚠️ Invalid numbers provided."
```

### Prompt Engineering
The `description` in the `@skill` decorator is injected directly into the LLM system prompt. 
- **Good:** "Search for invoices by customer name."
- **Bad:** "Search func."

---

## 5. Web Interface
- Built with **FastAPI** + **Jinja2**.
- **Static Files:** Place CSS/Images in `web/static/`.
- **Templates:** HTML files go in `web/templates/`.
- **Running:** The web server starts automatically via `monitor.py` on port `8000`.

---

## 6. Git Rules
- **Branches:** Use feature branches (e.g., `feature/add-weather-skill`) for major changes.
- **Commits:** Clear, descriptive messages.
- **Ignored Files:**
  - `secrets/*`
  - `*.log`
  - `*.db`
  - `debug/*`
  - `.env`
  - `config.yaml` (Use `config.yaml.example` for templates)

---

## 7. Troubleshooting
- **Logs:** Check `logs/monitor.log` for runtime errors.
- **Service Status:** `sudo systemctl status ai-assistant`
- **Restarting:** `sudo systemctl restart ai-assistant`
