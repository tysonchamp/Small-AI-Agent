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
    
    # Website Monitoring Table
    c.execute('''CREATE TABLE IF NOT EXISTS websites
                 (url TEXT PRIMARY KEY, content_hash TEXT, last_checked TIMESTAMP, last_content TEXT,
                  last_error TEXT, status_code INTEGER, last_summary TEXT)''')
    try:
        c.execute("ALTER TABLE websites ADD COLUMN last_content TEXT")
    except sqlite3.OperationalError:
        pass 
    try:
        c.execute("ALTER TABLE websites ADD COLUMN last_error TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE websites ADD COLUMN status_code INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE websites ADD COLUMN last_summary TEXT")
    except sqlite3.OperationalError:
        pass 

    # Workflows Table (Dynamic Scheduling)
    c.execute('''CREATE TABLE IF NOT EXISTS workflows
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  type TEXT NOT NULL, 
                  params TEXT, 
                  interval_seconds INTEGER,
                  next_run_time TEXT,
                  created_at TEXT)''')

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

def clear_chat_history():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()

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

# --- Workflow Functions ---

def add_workflow(type, params, interval_seconds, next_run_time=None):
    if not next_run_time:
        next_run_time = datetime.now()
        
    conn = get_connection()
    c = conn.cursor()
    # Ensure params is a dict before dumping? 
    # The caller passes a dict usually.
    c.execute("INSERT INTO workflows (type, params, interval_seconds, next_run_time, created_at) VALUES (?, ?, ?, ?, ?)",
              (type, json.dumps(params), interval_seconds, next_run_time, datetime.now()))
    conn.commit()
    w_id = c.lastrowid
    conn.close()
    return w_id

def get_active_workflows():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, type, params, interval_seconds, next_run_time FROM workflows")
    rows = c.fetchall()
    conn.close()
    
    import json
    workflows = []
    for r in rows:
        # id, type, params_json, interval, next_run
        workflows.append({
            'id': r[0],
            'type': r[1],
            'params': json.loads(r[2]) if r[2] else {},
            'interval_seconds': r[3],
            'next_run_time': r[4]
        })
    return workflows

def update_workflow_next_run(w_id, next_time):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE workflows SET next_run_time=? WHERE id=?", (next_time, w_id))
    conn.commit()
    conn.close()

def delete_workflow(w_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM workflows WHERE id=?", (w_id,))
    conn.commit()
    conn.close()
# --- Generic Table Functions (Advanced Viewer) ---
def get_table_schema(table_name):
    """Returns list of column names for a table."""
    conn = get_connection()
    c = conn.cursor()
    try:
        # Validate existence first to be safe, though PRAGMA is generally safe with param
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not c.fetchone():
            return []
        
        c.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in c.fetchall()]
    except Exception as e:
        logging.error(f"Error getting schema for {table_name}: {e}")
        return []
    finally:
        conn.close()

def get_table_data(table_name, page=1, limit=20, sort_by=None, sort_order='DESC', search=None, filters=None):
    """
    Retrieves table data with search, filter, sort and pagination.
    Returns: (rows, total_count, columns)
    """
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # 1. Validate table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not c.fetchone():
            raise ValueError(f"Table {table_name} does not exist")

        # 2. Get columns
        c.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in c.fetchall()]
        
        # 3. Build Query
        query = f"SELECT * FROM {table_name}"
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        conditions = []
        params = []

        # Global Search
        if search:
            search_conditions = []
            for col in columns:
                search_conditions.append(f"{col} LIKE ?")
                params.append(f"%{search}%")
            if search_conditions:
                conditions.append(f"({' OR '.join(search_conditions)})")

        # Column Filters
        if filters:
            for col, val in filters.items():
                if col in columns and val:
                    conditions.append(f"{col} LIKE ?")
                    params.append(f"%{val}%")

        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
            query += where_clause
            count_query += where_clause
        
        # Sort
        if sort_by and sort_by in columns:
            order = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'
            query += f" ORDER BY {sort_by} {order}"
        else:
            # Default sort
            if 'id' in columns:
                query += " ORDER BY id DESC"
            elif 'timestamp' in columns: # Common in our tables
                query += " ORDER BY timestamp DESC"
            else:
                query += " ORDER BY ROWID DESC"

        # Pagination
        offset = (page - 1) * limit
        query += " LIMIT ? OFFSET ?"
        
        # Execute Count (using params ONLY for WHERE clause)
        c.execute(count_query, params)
        total_count = c.fetchone()[0]

        # Execute Data (params + limit + offset)
        data_params = list(params)
        data_params.append(limit)
        data_params.append(offset)
        
        c.execute(query, data_params)
        rows = c.fetchall()
        
        return rows, total_count, columns

    except Exception as e:
        logging.error(f"Error fetching table data for {table_name}: {e}")
        raise e
    finally:
        conn.close()
