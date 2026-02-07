# 🤖 Personal Artificial Intelligence Assistant

A powerful, self-hosted AI assistant that combines **website monitoring**, **persistent memory**, **smart reminders**, and **note-taking** into a single Telegram bot. Powered by **Ollama** for local LLM inference, ensuring privacy and intelligence without subscription fees.

## ✨ Features

- **🧠 Persistent Memory**: Remembers context from previous conversations.
- **👁️ Website Monitoring**: Tracks changes on specified websites and sends AI-analyzed summaries of updates.
- **⏰ Intelligent Reminders**:
  - Natural language scheduling: *"Remind me to check server logs in 10 minutes"*
  - Recurring reminders: *"Remind me every hour to drink water"*
  - Smart management: *"Cancel all reminders"* or *"Do I have any meetings tomorrow?"*
- **📝 Smart Notes**: Save and retrieve notes effortlessly using natural language.
- **📸 Vision Capabilities**: Analyze images sent to the chat (requires a vision-capable model like `llava`).
- **🛡️ Privacy-First**: Runs locally using Ollama. Your data stays on your machine.

---

## 🚀 Prerequisites

1.  **Python 3.10+** installed.
2.  **Ollama** installed and running (`ollama serve`).
    - Recommended models: `llama3`, `mistral`, or `gemma`.
    - For image support: `llava` or `llama3.2-vision`.
3.  **Telegram Bot Token**:
    - Create a bot via [@BotFather](https://t.me/BotFather) on Telegram and get your token.
    - Get your Chat ID (you can use [@userinfobot](https://t.me/userinfobot)).

---

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/ai-assistant-bot.git
cd ai-assistant-bot
```

### 2. Set up Virtual Environment
It is recommended to use a virtual environment.

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuration
Create a `config.yaml` file in the root directory. You can copy the structure below:

```yaml
telegram:
  bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
  chat_id: "YOUR_TELEGRAM_CHAT_ID"

monitoring:
  check_interval_seconds: 300
  websites:
    - "https://example.com"
    - "https://another-site.com"

ollama:
  model: "llama3" # or 'mistral', 'gemma', etc.
```

---

## 🏃‍♂️ Usage

### Linux / macOS
Run the start script to launch the bot in the background:
```bash
./start.sh
```
To stop the bot:
```bash
./stop.sh
```

### Windows
Run the Python script directly:
```powershell
python monitor.py
```

---

## 💬 Commands & Interactions

The bot is designed to understand **natural language**, so you don't always need slash commands.

### 🗓️ Reminders
- **Set**: "Remind me to deploy the app in 20 minutes."
- **Recurring**: "Remind me every 30 seconds to take a break."
- **Query**: "What reminders do I have tomorrow?"
- **Cancel**: "Cancel all reminders" or "Cancel the reminder about milk."

### 📝 Notes
- **Add**: "Save a note: Storage server IP is 192.168.1.55"
- **List**: "Show my notes" or `/notes`
- **Slash Command**: `/note [content]` works too.

### 🧠 Chat & Vision
- Just send a message to chat! The bot remembers context.
- Send a **photo** to analyze it (e.g., "What is in this picture?").

### 🔍 Website Monitoring
- The bot checks configured websites every 5 minutes (configurable).
- You will receive a notification **only** if content changes, with a summary of what changed.

---

## 🔧 Troubleshooting

- **Bot not replying?**
  - Check if `ollama serve` is running.
  - Check `monitor.log` for errors.
- **"Connection Refused" error?**
  - Ensure Ollama is running on port 11434 (default).
- **Date parsing issues?**
  - Try to be specific, e.g., "in 10 minutes" rather than "later".

---

## 📂 Project Structure

- `monitor.py`: Core logic and AI intent classification.
- `database.py`: SQLite database management.
- `config.py`: Configuration loader.
- `monitor.db`: Stores chat history, reminders, and website hashes.
- `start.sh` / `stop.sh`: Service management scripts.

---

**Enjoy your new personal AI Assistant! 🚀**
