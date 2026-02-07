import sqlite3
import logging
import time

DB_FILE = 'monitor.db'

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Website Monitoring Table
    c.execute('''CREATE TABLE IF NOT EXISTS websites
                 (url TEXT PRIMARY KEY, content_hash TEXT, last_checked TIMESTAMP, last_content TEXT)''')
    try:
        c.execute("ALTER TABLE websites ADD COLUMN last_content TEXT")
    except sqlite3.OperationalError:
        pass 

    # Chat Memory Table
    # role: 'user' or 'assistant'
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  role TEXT, 
                  content TEXT, 
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Notes Table
    c.execute('''CREATE TABLE IF NOT EXISTS notes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  content TEXT, 
                  tags TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Reminders Table (status: 'pending', 'sent')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  chat_id TEXT,
                  content TEXT, 
                  remind_at TIMESTAMP,
                  status TEXT DEFAULT 'pending',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  interval_seconds INTEGER DEFAULT 0)''')
    try:
        c.execute("ALTER TABLE reminders ADD COLUMN interval_seconds INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

# --- Memory Functions ---
def add_chat_message(role, content):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    conn.close()

def get_recent_chat_history(limit=10):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows[::-1] # Return in chronological order

# --- Note Functions ---
def add_note(content, tags=""):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO notes (content, tags) VALUES (?, ?)", (content, tags))
    conn.commit()
    conn.close()

def get_notes(limit=5):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, content, timestamp FROM notes ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# --- Reminder Functions ---
def add_reminder(chat_id, content, remind_at, interval_seconds=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO reminders (chat_id, content, remind_at, status, interval_seconds) VALUES (?, ?, ?, 'pending', ?)", 
              (chat_id, content, remind_at, interval_seconds))
    conn.commit()
    conn.close()

def get_pending_reminders():
    # Get reminders that are due (remind_at <= now) and pending
    conn = get_connection()
    c = conn.cursor()
    # Using datetime('now', 'localtime') might be safer depending on how we store remind_at
    # For simplicity, we assume remind_at is stored as a comparable string or timestamp
    c.execute("SELECT id, chat_id, content, interval_seconds FROM reminders WHERE status='pending' AND remind_at <= datetime('now', 'localtime')")
    rows = c.fetchall()
    conn.close()
    return rows

def reschedule_reminder(reminder_id, new_time):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE reminders SET remind_at=?, status='pending' WHERE id=?", (new_time, reminder_id))
    conn.commit()
    conn.close()

def mark_reminder_sent(reminder_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE reminders SET status='sent' WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()

def delete_reminder(reminder_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()

def delete_all_pending_reminders(chat_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE chat_id=? AND status='pending'", (chat_id,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()
    return deleted_count

def search_reminders(chat_id, query_text=None, start_time=None, end_time=None):
    conn = get_connection()
    c = conn.cursor()
    
    sql = "SELECT id, content, remind_at, interval_seconds FROM reminders WHERE chat_id=? AND status='pending'"
    params = [chat_id]
    
    if query_text:
        sql += " AND content LIKE ?"
        params.append(f"%{query_text}%")
    
    if start_time:
        sql += " AND remind_at >= ?"
        params.append(start_time)
        
    if end_time:
        sql += " AND remind_at <= ?"
        params.append(end_time)
        
    sql += " ORDER BY remind_at ASC"
    
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows
