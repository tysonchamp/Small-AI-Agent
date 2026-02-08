# 🤖 Personal AI Assistant

A powerful, modular, and self-hosted AI assistant that combines **website monitoring**, **ERP integration**, **system health checks**, **web search**, and **personal organization** into a single Telegram bot. Powered by **Ollama** for local, private intelligence.

## ✨ Features

### 🧠 Core Intelligence
- **Persistent Memory**: Remembers context from previous conversations.
- **Natural Language Understanding**: Chat naturally to trigger complex actions.
- **Local Privacy**: Runs 100% locally using Ollama (Llama 3, Mistral, Gemma, etc.).

### �️ Skills & Modules
The bot is organized into modular `skills/`:

- **👁️ Web Monitor** (`skills/web_monitor.py`): 
  - Tracks changes on specified websites (background job).
  - Sends AI-analyzed summaries of updates.

- **💼 ERP Integration** (`skills/erp.py`):
  - **Tasks**: "Show my pending tasks."
  - **Invoices**: "What invoices are due?" or "Search invoices for Client X."
  - **Credentials**: "Get credentials for AWS." (Secure retrieval).

- **🌐 Web Search** (`skills/web_search.py`):
  - **Real-time Search**: "Search the web for the latest crypto prices."
  - **Summarization**: "Summarize this article: [URL]" or "Summarize this YouTube video: [URL]".

- **🖥️ System Health** (`skills/system_health.py`):
  - **Status Checks**: "Check system status."
  - **Remote Monitoring**: Monitors CPU/RAM/Disk of configured VPS/Servers via SSH.
  - **Alerts**: Auto-alerts on high resource usage.

- **⏰ Reminders & Schedule** (`skills/reminders.py`):
  - **Natural Language**: "Remind me to check logs in 10 minutes."
  - **Recurring**: "Remind me every hour to stretch."
  - **Management**: "Cancel all reminders" or "What is my schedule?"

- **⚙️ Workflows** (`skills/workflows.py`):
  - **Automated Tasks**: Create custom recurring workflows (e.g., Daily Briefings).
  - **Morning Briefing**: Aggregates calendar, reminders, and system status.

- **� Notes** (`skills/notes.py`):
  - **Capture**: "Save a note: Server IP is 10.0.0.1"
  - **Retrieve**: "Show my notes."

---

## � Project Structure

```
├── config/             # Configuration files
│   ├── config.yaml     # Main configuration (API keys, settings)
│   └── __init__.py     # Config loader
├── debug/              # Debugging & Test scripts
│   ├── mock_erp.py     # Mock ERP server for testing
│   └── test_erp.py     # Integration tests
├── logs/               # Log files (Auto-rotated)
│   └── monitor.log     # Main application log
├── skills/             # Modular skill logic
│   ├── erp.py          # ERP Client
│   ├── web_monitor.py  # Website Change Detection
│   ├── system_health.py# Server Monitoring
│   ├── web_search.py   # Search & Summarization
│   └── ...             # Other skills
├── monitor.py          # Main entry point & Orchestrator
├── database.py         # SQLite database management
├── ai-assistant.service# Systemd service file
└── requirements.txt    # Python dependencies
```

---

## � Installation & Setup

### 1. Prerequisites
- **Python 3.10+**
- **Ollama** installed and running (`ollama serve`).
- **Telegram Bot Token** (from @BotFather).

### 2. Clone & Install
```bash
git clone https://github.com/yourusername/ai-assistant-bot.git
cd ai-assistant-bot

# Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Install Dependencies
pip install -r requirements.txt
```

### 3. Configuration
Move the example config and edit it:
```bash
cp config/config.yaml.example config/config.yaml
nano config/config.yaml
```
Key settings:
- `telegram.bot_token`: Your Bot Token.
- `telegram.chat_id`: Your user ID (get from @userinfobot).
- `monitoring.websites`: List of sites to watch.
- `servers`: List of SSH servers to monitor.

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
If you need to debug or run without the service:
```bash
# Stop service first
sudo systemctl stop ai-assistant

# Run manually
python3 monitor.py
```

---

## 💬 Usage Examples

| Feature | Command / Interaction |
| :--- | :--- |
| **Chat** | "How does a binary search work?" |
| **Search** | "Search web for RTX 5090 release date." |
| **Summarize** | "Summarize this video: https://youtu.be/..." |
| **ERP** | "Show pending tasks." / "Search invoices for Acme." |
| **System** | "System status." |
| **Reminders** | "Remind me to backup DB in 2 hours." |
| **Notes** | "Note: Buy milk." / "Show notes." |

---

## 🔧 Troubleshooting

- **Logs**: Check `logs/monitor.log` for errors.
- **Service Status**: `sudo systemctl status ai-assistant`.
- **Bot Conflict**: If you see "Conflict: terminated by other getUpdates request", ensure only **one** instance is running (check `ps aux | grep monitor.py`).
