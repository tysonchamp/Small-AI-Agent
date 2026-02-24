import requests
import logging
import config
import yaml
import os
from dateutil import parser
from skills.registry import skill

def get_base_url():
    conf = config.load_config()
    base_url = conf.get('GBYTE_ERP_URL')
    if base_url and not base_url.endswith('/api/agent'):
        return f"{base_url.rstrip('/')}/api/agent"
    return base_url

def get_headers():
    conf = config.load_config()
    api_key = conf.get('API_KEY')
    return {"X-API-KEY": api_key}

@skill(name="ERP_TASKS", description="Fetch pending tasks.")
def get_pending_tasks():
    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."
    
    url = f"{base_url}/tasks/pending"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                tasks = data.get('data', [])
                if not tasks:
                    return "✅ No pending tasks found."
                
                msg = "📋 *Scheduled Task Report*\n\n"
                
                # Group by Priority (Optional, but user asked for grouping 'sub group', 
                # but the example showed Project -> Subtasks. Let's stick to the Project list structure.)
                # actually the user said "group the task with sub group" and "bullet point 1, 2, 3"
                
                for index, task in enumerate(tasks, 1):
                    # Title line with numbering
                    priority = task.get('priority', 'Normal').capitalize()
                    msg += f"*{index}. {task['title']}* (Priority: {priority})\n"
                    
                    sub_tasks = task.get('sub_tasks', [])
                    if sub_tasks:
                        for sub in sub_tasks:
                            # Status check/mark
                            status = sub.get('status', 'todo')
                            # You can use [ ] or [x] or just bullets. 
                            # User example: * [ ] Logo Design
                            # Let's use simplified bullets for Telegram readability
                            msg += f"  • {sub['title']}\n"
                    else:
                         msg += f"  _(No pending sub-tasks)_\n"
                    
                    msg += "\n" # Blank line between projects
                
                return msg
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        elif response.status_code == 401:
            return "⚠️ Unauthorized: Invalid API Key."
        else:
            return f"⚠️ Error fetching tasks: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error fetching pending tasks: {e}")
        return f"⚠️ Connection Error: {e}"

@skill(name="ERP_INVOICES", description="Fetch due invoices. Params: type='due' (default) or 'summary'")
def get_invoices_skill(type="due"):
    if type == "summary":
        return get_invoice_summary()
    return get_due_invoices()

def get_due_invoices():
    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."

    url = f"{base_url}/invoices/due"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                invoices = data.get('data', [])
                if not invoices:
                    return "✅ No due invoices."
                
                msg = f"💰 *Due Invoices ({len(invoices)}):*\n"
                for inv in invoices:
                    # Based on Postman Collection
                    inv_no = inv.get('invoice_no', 'N/A')
                    cust_name = inv.get('customer_name', 'Unknown')
                    due = inv.get('due_amount', '0.00')
                    date = inv.get('date', 'N/A')
                    
                    msg += f"- *{inv_no}*: {cust_name} - Due: {due} (Date: {date})\n"
                return msg
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        else:
            return f"⚠️ Error fetching invoices: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error fetching due invoices: {e}")
        return f"⚠️ Connection Error: {e}"

def get_invoice_summary():
    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."

    url = f"{base_url}/invoices/summary"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                summary = data.get('summary', {})
                return (
                    f"📊 *Invoice Summary*\n"
                    f"Pending Invoices: {summary.get('pending_invoices_count', 0)}\n"
                    f"Total Pending Amount: {summary.get('total_pending_amount', 0.00)}\n"
                    f"Total Invoiced Amount: {summary.get('total_invoiced_amount', 0.00)}"
                )
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        else:
            return f"⚠️ Error fetching summary: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error fetching invoice summary: {e}")
        return f"⚠️ Connection Error: {e}"

def get_customer_invoices(customer_id):
    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."

    url = f"{base_url}/customers/{customer_id}/invoices"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                invoices = data.get('data', [])
                if not invoices:
                    return f"✅ No invoices found for customer {customer_id}."
                
                msg = f"📄 *Invoices for Customer {customer_id} ({len(invoices)}):*\n"
                for inv in invoices:
                    status_icon = "✅" if inv.get('status') == 'Paid' else "⏳"
                    msg += f"- {status_icon} *{inv['invoice_no']}*: {inv['grand_total']} ({inv['status']})\n"
                return msg
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        else:
            return f"⚠️ Error fetching customer invoices: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error fetching invoices for customer {customer_id}: {e}")
        return f"⚠️ Connection Error: {e}"

@skill(name="ERP_CREDENTIALS", description="Search/Show project credentials. Params: search (optional)")
def get_credentials(search=None):
    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."

    url = f"{base_url}/credentials"
    params = {}
    if search:
        params['search'] = search

    try:
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                creds = data.get('data', [])
                if not creds:
                    return "🔒 No credentials found."
                
                msg = f"🔐 *Project Credentials ({len(creds)}):*\n"
                for cred in creds:
                    msg += f"*{cred['project_name']}* - {cred['service_name']}\n"
                    msg += f"User: `{cred['username']}`\n"
                    # msg += f"Pass: `{cred['password']}`\n" # Security: Mask or don't show unless explicitly asked? User asked to show.
                    msg += f"Pass: `{cred['password']}`\n"
                    msg += f"Desc: {cred['description']}\n\n"
                return msg
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        elif response.status_code == 401:
            return "⚠️ Unauthorized: Invalid API Key."
        else:
            return f"⚠️ Error fetching credentials: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error fetching credentials: {e}")
        return f"⚠️ Connection Error: {e}"

@skill(name="ERP_SEARCH_INVOICES", description="Search invoices. Params: customer_name or customer_id")
def search_invoices(customer_name=None, customer_id=None):
    if not customer_name and not customer_id:
        return "❓ Please specify a customer name or ID."

    base_url = get_base_url()
    if not base_url:
        return "⚠️ ERP URL not configured."

    url = f"{base_url}/invoices"
    params = {}
    if customer_name:
        params['customer_name'] = customer_name
    if customer_id:
        params['customer_id'] = customer_id
        
    try:
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                invoices = data.get('data', [])
                if not invoices:
                    return f"✅ No invoices found matching your criteria."
                
                msg = f"🔎 *Found Invoices ({len(invoices)}):*\n"
                for inv in invoices:
                    status_icon = "✅" if inv.get('status') == 'Paid' else "⏳"
                    cust = inv.get('customer_name', 'Unknown')
                    total = inv.get('grand_total', '0.00')
                    status = inv.get('status', 'Unknown')
                    msg += f"- {status_icon} *{inv['invoice_no']}*: {cust} - {total} ({status})\n"
                return msg
            else:
                return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        else:
            return f"⚠️ Error searching invoices: HTTP {response.status_code}"
    except Exception as e:
        logging.error(f"Error searching invoices: {e}")
        return f"⚠️ Connection Error: {e}"
