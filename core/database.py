"""
Centralized Database Access Layer (SQLite)
Handles all structured data: notes, reminders, workflows, websites, emails, content clients.
Chat history is NOT stored here — it's in ChromaDB (see core/memory.py).
"""
import sqlite3
import logging
import time
from datetime import datetime
import json

DB_FILE = 'monitor.db'

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # --- Notes ---
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        tags TEXT DEFAULT '',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- Reminders ---
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        content TEXT NOT NULL,
        remind_at TIMESTAMP NOT NULL,
        status TEXT DEFAULT 'pending',
        interval_seconds INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- Websites ---
    c.execute('''CREATE TABLE IF NOT EXISTS websites (
        url TEXT PRIMARY KEY,
        content_hash TEXT,
        last_checked TIMESTAMP,
        last_content TEXT,
        last_error TEXT,
        status_code INTEGER,
        last_summary TEXT
    )''')
    
    # --- Email History ---
    c.execute('''CREATE TABLE IF NOT EXISTS email_history (
        message_id TEXT UNIQUE NOT NULL,
        account TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- Content Clients ---
    c.execute('''CREATE TABLE IF NOT EXISTS content_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        niche TEXT NOT NULL,
        frequency TEXT DEFAULT 'daily',
        extra_notes TEXT,
        last_post_date TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- Content Posts ---
    c.execute('''CREATE TABLE IF NOT EXISTS content_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_id) REFERENCES content_clients(id)
    )''')
    
    # --- Workflows ---
    c.execute('''CREATE TABLE IF NOT EXISTS workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        params TEXT DEFAULT '{}',
        interval_seconds INTEGER DEFAULT 0,
        next_run_time TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- Job Run Tracking ---
    c.execute('''CREATE TABLE IF NOT EXISTS job_runs (
        job_name TEXT PRIMARY KEY,
        last_run TIMESTAMP
    )''')
    
    # Migration: add status column if missing
    try:
        c.execute("ALTER TABLE workflows ADD COLUMN status TEXT DEFAULT 'active'")
        logging.info("Migration: added 'status' column to workflows table.")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    conn.commit()
    conn.close()
    logging.info("Database initialized.")


# --- Job Run Tracking Functions ---
def record_job_run(job_name):
    """Record that a job just ran. Creates or updates the timestamp."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("""INSERT INTO job_runs (job_name, last_run) VALUES (?, ?)
                 ON CONFLICT(job_name) DO UPDATE SET last_run = ?""",
              (job_name, now, now))
    conn.commit()
    conn.close()

def get_last_job_run(job_name):
    """Returns seconds since the job last ran, or None if never ran."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT last_run FROM job_runs WHERE job_name = ?", (job_name,))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        last_dt = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        elapsed = (datetime.now() - last_dt).total_seconds()
        return max(0, elapsed)
    except Exception:
        return None


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
    c.execute("SELECT id, content, timestamp FROM notes ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


# --- Reminder Functions ---
def add_reminder(chat_id, content, remind_at, interval_seconds=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO reminders (chat_id, content, remind_at, interval_seconds, status) VALUES (?, ?, ?, ?, 'pending')",
              (chat_id, content, remind_at, interval_seconds))
    conn.commit()
    conn.close()

def get_pending_reminders():
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("SELECT id, chat_id, content, interval_seconds FROM reminders WHERE status = 'pending' AND remind_at <= ?", (now,))
    rows = c.fetchall()
    conn.close()
    return rows

def reschedule_reminder(reminder_id, new_time):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE reminders SET remind_at = ? WHERE id = ?", (new_time, reminder_id))
    conn.commit()
    conn.close()

def mark_reminder_sent(reminder_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

def delete_reminder(reminder_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

def delete_all_pending_reminders(chat_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE chat_id = ? AND status = 'pending'", (chat_id,))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

def search_reminders(chat_id, query_text=None, start_time=None, end_time=None):
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT id, content, remind_at, interval_seconds FROM reminders WHERE chat_id = ? AND status = 'pending'"
    params = [chat_id]
    if query_text:
        query += " AND content LIKE ?"
        params.append(f"%{query_text}%")
    if start_time:
        query += " AND remind_at >= ?"
        params.append(str(start_time))
    if end_time:
        query += " AND remind_at <= ?"
        params.append(str(end_time))
    query += " ORDER BY remind_at ASC"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows


# --- Email History Functions ---
def is_email_processed(message_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM email_history WHERE message_id = ?", (message_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_email_processed(message_id, account):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO email_history (message_id, account) VALUES (?, ?)", (message_id, account))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already processed
    conn.close()


# --- Content Research Functions ---
def add_client(name, niche, frequency='daily', extra_notes=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO content_clients (name, niche, frequency, extra_notes) VALUES (?, ?, ?, ?)",
              (name, niche, frequency, extra_notes))
    conn.commit()
    conn.close()

def get_clients():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, niche, frequency, extra_notes, last_post_date, status FROM content_clients")
    rows = c.fetchall()
    conn.close()
    return rows

def get_client_by_name(name):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, niche, frequency, extra_notes, last_post_date, status FROM content_clients WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return row

def find_clients_like(name_pattern):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, niche, frequency, extra_notes, last_post_date, status FROM content_clients WHERE name LIKE ?", (f"%{name_pattern}%",))
    rows = c.fetchall()
    conn.close()
    return rows

def update_client(client_id, name=None, niche=None, frequency=None, extra_notes=None):
    conn = get_connection()
    c = conn.cursor()
    updates = []
    params = []
    if name:
        updates.append("name = ?")
        params.append(name)
    if niche:
        updates.append("niche = ?")
        params.append(niche)
    if frequency:
        updates.append("frequency = ?")
        params.append(frequency)
    if extra_notes is not None:
        updates.append("extra_notes = ?")
        params.append(extra_notes)
    if updates:
        params.append(client_id)
        c.execute(f"UPDATE content_clients SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()

def delete_client(client_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM content_posts WHERE client_id = ?", (client_id,))
    c.execute("DELETE FROM content_clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()

def add_post(client_id, content, status='pending'):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO content_posts (client_id, content, status) VALUES (?, ?, ?)", (client_id, content, status))
    conn.commit()
    conn.close()

def get_pending_posts():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT p.id, c.name, p.content, p.created_at 
        FROM content_posts p 
        JOIN content_clients c ON p.client_id = c.id 
        WHERE p.status = 'pending' 
        ORDER BY p.created_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def update_post_status(post_id, status):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE content_posts SET status = ? WHERE id = ?", (status, post_id))
    conn.commit()
    conn.close()

def update_client_last_post_date(client_id):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d')
    c.execute("UPDATE content_clients SET last_post_date = ? WHERE id = ?", (now, client_id))
    conn.commit()
    conn.close()

def update_client_status(client_id, status):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE content_clients SET status = ? WHERE id = ?", (status, client_id))
    conn.commit()
    conn.close()


# --- Workflow Functions ---
def add_workflow(type, params, interval_seconds, next_run_time=None):
    conn = get_connection()
    c = conn.cursor()
    if next_run_time is None:
        next_run_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(params, dict):
        params = json.dumps(params)
    c.execute("INSERT INTO workflows (type, params, interval_seconds, next_run_time) VALUES (?, ?, ?, ?)",
              (type, params, interval_seconds, next_run_time))
    conn.commit()
    wf_id = c.lastrowid
    conn.close()
    return wf_id

def get_active_workflows():
    conn = get_connection()
    c = conn.cursor()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("""
        SELECT id, type, params, interval_seconds, next_run_time 
        FROM workflows 
        WHERE status = 'active' AND next_run_time <= ?
    """, (now,))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        params = r[2]
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        result.append({
            'id': r[0],
            'type': r[1],
            'params': params,
            'interval_seconds': r[3],
            'next_run_time': r[4]
        })
    return result

def get_all_workflows():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, type, params, interval_seconds, next_run_time, status FROM workflows WHERE status = 'active'")
    rows = c.fetchall()
    conn.close()
    return rows

def update_workflow_next_run(w_id, next_time):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE workflows SET next_run_time = ? WHERE id = ?", (next_time, w_id))
    conn.commit()
    conn.close()

def delete_workflow(w_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE workflows SET status = 'cancelled' WHERE id = ?", (w_id,))
    conn.commit()
    conn.close()


# --- Website Functions ---
def get_website(url):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT url, content_hash, last_content, last_checked, last_error FROM websites WHERE url = ?", (url,))
    row = c.fetchone()
    conn.close()
    return row

def upsert_website(url, content_hash, content, status_code=200, last_error=None, last_summary=None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("""INSERT INTO websites (url, content_hash, last_content, last_checked, status_code, last_error, last_summary) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(url) DO UPDATE SET 
                    content_hash = ?, last_content = ?, last_checked = ?, status_code = ?, last_error = ?, last_summary = ?""",
              (url, content_hash, content, now, status_code, last_error, last_summary,
               content_hash, content, now, status_code, last_error, last_summary))
    conn.commit()
    conn.close()

def get_website_changes(url_query):
    """Find a website by partial URL match and return its last change info."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT url, last_checked, last_error, status_code, last_summary FROM websites WHERE url LIKE ?",
        (f"%{url_query}%",)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_websites():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT url, last_checked, last_error, status_code, last_summary FROM websites")
    rows = c.fetchall()
    conn.close()
    return rows


# --- Generic Table Functions (for Web Dashboard) ---
def get_table_schema(table_name):
    """Returns list of column names for a table."""
    conn = get_connection()
    c = conn.cursor()
    # Whitelist tables
    allowed_tables = ['notes', 'reminders', 'websites', 'email_history', 
                      'content_clients', 'content_posts', 'workflows']
    if table_name not in allowed_tables:
        conn.close()
        return []
    c.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in c.fetchall()]
    conn.close()
    return columns

def get_table_data(table_name, page=1, limit=20, sort_by=None, sort_order='DESC', search=None, filters=None):
    """Retrieves table data with search, filter, sort and pagination."""
    conn = get_connection()
    c = conn.cursor()
    
    columns = get_table_schema(table_name)
    if not columns:
        conn.close()
        return [], 0, []
    
    where_clauses = []
    params = []
    
    if search:
        search_conditions = [f"{col} LIKE ?" for col in columns]
        where_clauses.append(f"({' OR '.join(search_conditions)})")
        params.extend([f"%{search}%" for _ in columns])
    
    if filters:
        for col, val in filters.items():
            if col in columns:
                where_clauses.append(f"{col} LIKE ?")
                params.append(f"%{val}%")
    
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    
    # Count
    c.execute(f"SELECT COUNT(*) FROM {table_name} {where_sql}", params)
    total_count = c.fetchone()[0]
    
    # Sort
    if sort_by and sort_by in columns:
        order_sql = f"ORDER BY {sort_by} {sort_order}"
    else:
        order_sql = f"ORDER BY rowid DESC"
    
    # Paginate
    offset = (page - 1) * limit
    c.execute(f"SELECT * FROM {table_name} {where_sql} {order_sql} LIMIT ? OFFSET ?", params + [limit, offset])
    rows = c.fetchall()
    
    conn.close()
    return rows, total_count, columns
