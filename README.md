# 🤖 Personal AI Assistant

A powerful, self-hosted AI assistant that combines **website monitoring**, **ERP integration**, **system health checks**, **web search**, **email management**, and **personal organization** into a single platform. Accessible via **Telegram Bot** and a **Web Dashboard**. Built with **LangChain** and powered by **Ollama** for local, private intelligence.

---

## ✨ Features

### 🧠 Core Intelligence
- **Prompt-Based Tool Routing** — Works with any LLM (no native tool calling required).
- **Persistent Memory** — ChromaDB-backed conversation history.
- **Local Privacy** — Runs 100% locally using Ollama (Gemma, Qwen, Mistral, etc.).
- **Non-Blocking** — All background tasks run concurrently without freezing the bot.

### 🌐 Web Dashboard
**URL:** `http://localhost:8000/`

- **Server Health** — Real-time CPU, RAM, Disk, and Uptime for local + remote servers.
- **Website Monitor** — Status overview of all monitored websites with AI-powered change summaries.
- **Live Logs** — Streaming logs from all background processes.
- **Database Viewer** — Browse, search, filter, and sort any SQLite table.
- **Web Chat** — Full chat interface to interact with the AI from your browser.
- **Dark Theme** — Sleek, modern dark UI.

### 🛠️ Tools & Capabilities

| Tool | Description |
|:---|:---|
| 👁️ **Web Monitor** | Tracks changes on websites and sends AI-powered change summaries |
| 💼 **ERP Integration** | Manage Tasks, Invoices, Credentials via natural language |
| 🌐 **Web Search** | Real-time DuckDuckGo search and content summarization |
| 🖥️ **System Health** | Monitor local and remote (SSH) servers |
| ⏰ **Reminders** | Natural language scheduling ("Remind me in 10 mins") |
| ⚙️ **Workflows** | Automated recurring tasks (daily briefings, reports) |
| 📝 **Notes** | Quick note taking and retrieval |
| 💻 **System Ops** | Execute shell commands on the host |
| 📧 **Email** | Check and summarize emails via IMAP |
| 📢 **Notifications** | Send notifications to Telegram users |
| 📰 **Content Research** | AI-powered content generation for clients |
| 🔍 **SEO Analysis** | Website SEO auditing and recommendations |
| 🧩 **Meta Coder** | Dynamically create new tools at runtime |

---

## � Project Structure

```
├── app.py                 # Entry point (Telegram + Web Server)
├── config/config.yaml     # Configuration
├── core/
│   ├── agent.py           # Prompt-based agent with tool routing
│   ├── llm.py             # Ollama LLM setup
│   ├── database.py        # SQLite database layer
│   └── memory.py          # ChromaDB chat memory
├── tools/                 # LangChain @tool functions (13 modules)
├── bot/telegram_bot.py    # Telegram handlers & job scheduler
├── web/                   # FastAPI dashboard, chat, templates
├── service/               # Systemd service config
└── _legacy/               # Old pre-LangChain code (reference)
```

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Python 3.10+**
- **Ollama** installed and running (`ollama serve`)
- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
- **Telegram Chat ID** (from [@userinfobot](https://t.me/userinfobot))

### 2. Clone & Install
```bash
git clone https://github.com/tysonchamp/Small-AI-Agent.git
cd Small-AI-Agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
```bash
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```

**Key Settings:**

| Setting | Description |
|:---|:---|
| `telegram.bot_token` | Your Bot Token (from @BotFather) |
| `telegram.chat_id` | Your user ID (from @userinfobot) |
| `agent.name` / `agent.persona` | Bot personality |
| `monitoring.websites` | List of sites to watch |
| `servers` | SSH servers to monitor |
| `ollama.model` | Ollama model name (e.g., `gemma3:latest`) |
| `ollama.host` | Ollama server URL |
| `GBYTE_ERP_URL` | ERP API base URL |

---

## 🏃 Running

### Systemd Service (Recommended)
```bash
sudo systemctl start ai-assistant      # Start
sudo systemctl stop ai-assistant       # Stop
sudo systemctl restart ai-assistant    # Restart (after code changes)
sudo systemctl status ai-assistant     # Check status
```

### Manual (Development)
```bash
sudo systemctl stop ai-assistant       # Stop service first
python3 app.py                         # Run manually
```

> ⚠️ Don't run both at the same time — it causes Telegram polling conflicts.

---

## 💬 Usage

### Telegram Commands

| Command | Description |
|:---|:---|
| `/start` | Initialize the bot |
| `/help` | Show available commands |
| `/dashboard` | Link to Web Dashboard |
| `/status` | Check system health |
| `/notes` | List saved notes |
| `/reminders` | List active reminders |
| `/workflows` | List active workflows |
| `/note [text]` | Quick save a note |
| `/emails` | Check and summarize emails |

### Natural Language Examples

| Intent | Example |
|:---|:---|
| **Chat** | "How does a binary search work?" |
| **Search** | "Search web for RTX 5090 release date" |
| **ERP** | "Show pending tasks" / "Search invoices for Acme" |
| **System** | "Check system status" |
| **Reminders** | "Remind me to backup DB in 2 hours" |
| **Notes** | "Note: Buy milk" / "Show notes" |
| **Workflows** | "Schedule a morning briefing every day at 8am" |
| **Shell** | "Execute `ls -la`" / "Check disk usage" |
| **Email** | "Check my emails" |

### Web Chat
Access at `http://localhost:8000/chat` — supports the same commands and natural language.

---

## 🔧 Troubleshooting

| Issue | Solution |
|:---|:---|
| **Runtime errors** | Check `logs/monitor.log` |
| **Service status** | `sudo systemctl status ai-assistant` |
| **Bot conflict** | Ensure only one instance is running |
| **Web not loading** | Check port 8000 and that `app.py` is running |
| **LLM errors** | Verify Ollama is running: `curl http://localhost:11434/api/tags` |

---

## 📜 License
[MIT License](LICENSE)
