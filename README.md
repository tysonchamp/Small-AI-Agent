# 🤖 Personal AI Assistant

A powerful, modular, and self-hosted AI assistant that combines **website monitoring**, **ERP integration**, **system health checks**, **web search**, and **personal organization** into a single Telegram bot and Web Interface. Powered by **Ollama** for local, private intelligence.

## ✨ Features

### 🧠 Core Intelligence
- **Persistent Memory**: Remembers context from previous conversations.
- **Natural Language Understanding**: Chat naturally to trigger complex actions.
- **Local Privacy**: Runs 100% locally using Ollama (Llama 3, Mistral, Gemma, etc.).

### 🌐 Web Interface (New!)
A rich web-based dashboard for easier management.
**URL**: `http://localhost:8000/`

- **Dashboard**: Real-time view of Server Health (CPU/RAM/Disk/Uptime) and Website Status.
- **Live Logs**: Real-time streaming logs from background processes.
- **Database Viewer**: Browse and search through your SQLite database tables (Notes, Reminders, Websites).
- **Web Chat**: A full-featured chat interface to interact with the AI from your browser.
- **Dark Mode**: Sleek dark theme for all pages.

### Skills & Modules
The bot is organized into modular `skills/`:

- **👁️ Web Monitor**: Tracks changes on specified websites and sends AI summaries (Admin only).
- **💼 ERP Integration**: Manage Tasks, Invoices, and Credentials via natural language (Admin only).
- **🌐 Web Search**: Real-time search and content summarization (Admin only).
- **🖥️ System Health**: Monitor local and remote (SSH) server resources (Admin only).
- **⏰ Reminders**: Natural language reminders ("Remind me in 10 mins") (Admin only).
- **⚙️ Workflows**: Automated recurring tasks (e.g., Daily Briefings) (Admin only).
- **📝 Notes**: Quick note taking and retrieval (Admin only).
- **💻 System Ops**: Execute shell commands on the host machine (Admin only).
- **📢 Notifications**: Send notifications to Telegram users (to Assigned Chat ID by Admin).
- **📧 Email Integration**: Check and summarize emails (Admin only).

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Python 3.10+**
- **Ollama** installed and running (`ollama serve`).
- **Telegram Bot Token** (from @BotFather).
- **Telegram Chat ID** (from @userinfobot).

### 2. Clone & Install
```bash
git clone https://github.com/tysonchamp/Small-AI-Agent.git
cd Small-AI-Agent

# Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Install Dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy the example config and edit it:
```bash
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```
**Key Settings:**
- `telegram.bot_token`: Your Bot Token. (get from @BotFather)
- `telegram.chat_id`: Your user ID (get from @userinfobot).
- `agent.name` & `agent.persona`: Customize the bot's identity.
- `monitoring.websites`: List of sites to watch.
- `servers`: List of SSH servers to monitor.
- `ollama` : Ollama server URL and model name and api key (optional). 

---

## 🏃‍♂️ Running the Bot

### ➤ Managed Service (Recommended)
This installs the bot as a systemd service (`ai-assistant`), ensuring it starts on boot and restarts on failure.

**Install:**
```bash
sudo ./install_service.sh
```

**Manage:**
```bash
sudo systemctl start ai-assistant    # Start
sudo systemctl stop ai-assistant     # Stop
sudo systemctl restart ai-assistant  # Restart (Use this after code changes)
sudo systemctl status ai-assistant   # Check status
```

> **⚠️ IMPORTANT:** Do not run `./start.sh` manually if the service is running! It will cause conflicts.

### ➤ Manual Run (Debugging)
```bash
# Stop service first
sudo systemctl stop ai-assistant

# Run manually
python3 monitor.py
```

---

## 💬 Usage Guide

### 📱 Telegram Bot Commands
| Command | Description |
| :--- | :--- |
| `/start` | Restart/Initialize the bot |
| `/help` | Show available commands |
| `/dashboard` | Get likely to Web Dashboard |
| `/status` | Check System Health |
| `/notes` | List saved notes |
| `/reminders` | List active reminders |
| `/workflows` | List active system workflows |
| `/note [text]` | Quick save a note |
| `/emails` | Check and summarize emails |

### 💻 Web Chat Commands
The Web Chat (`/chat`) supports similar commands:
- `/help`, `/status`, `/notes`, `/reminders`, `/workflows`, `/note [text]`, `/emails`
- **Note**: Reminders created in Web Chat are linked to the configured Telegram ID.

### ️ Natural Language Examples
| Feature | User Input Example |
| :--- | :--- |
| **Chat** | "How does a binary search work?" |
| **Search** | "Search web for RTX 5090 release date." |
| **Summarize** | "Summarize this video: https://youtu.be/..." |
| **ERP** | "Show pending tasks." / "Search invoices for Acme." |
| **System** | "Check system status." |
| **Reminders** | "Remind me to backup DB in 2 hours." |
| **Notes** | "Note: Buy milk." / "Show notes." |
| **Workflows** | "Schedule a morning briefing every day at 8am." |
| **System Ops** | "Execute `ls -la`" / "Check disk usage" |
| **Notifications** | "Send Pending Task notification to Tyson" |
| **Emails** | "Check and summarize emails" |

---

## 🔧 Troubleshooting

- **Logs**: Check `logs/monitor.log` for errors.
- **Service Status**: `sudo systemctl status ai-assistant`.
- **Bot Conflict**: If you see "Conflict: terminated by other getUpdates request", ensure only **one** instance is running.
- **Web Interface Not Loading**: Ensure port `8000` is open and `monitor.py` is running.
