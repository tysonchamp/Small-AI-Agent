"""
ERP Integration Tool — Manage tasks, invoices, and credentials via the GBYTE ERP API.
"""
import logging
import requests
from dateutil import parser
from langchain_core.tools import tool
import config as app_config


def get_base_url():
    conf = app_config.load_config()
    url = conf.get('GBYTE_ERP_URL', '')
    if not url:
        return None
    url = url.rstrip('/')
    if not url.endswith('/api/agent'):
        url = f"{url}/api/agent"
    return url


def get_headers():
    conf = app_config.load_config()
    api_key = conf.get('API_KEY', '')
    return {'X-API-KEY': api_key, 'Accept': 'application/json'}


@tool
def get_pending_tasks() -> str:
    """Get pending ERP tasks. Shows task title, assigned user, priority, and deadline."""
    try:
        base_url = get_base_url()
        if not base_url:
            return "⚠️ ERP URL not configured."
        
        response = requests.get(f"{base_url}/tasks/pending", headers=get_headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        
        tasks = data.get('data', [])
        
        if not tasks:
            return "✅ No pending tasks."
        
        msg = "📋 *Scheduled Task Report*\n\n"
        for i, task in enumerate(tasks, 1):
            priority = task.get('priority', 'Normal').capitalize()
            msg += f"*{i}. {task.get('title', 'Untitled')}* (Priority: {priority})\n"
            
            sub_tasks = task.get('sub_tasks', [])
            if sub_tasks:
                for sub in sub_tasks:
                    msg += f"  • {sub.get('title', '')}\n"
            else:
                msg += f"  _(No pending sub-tasks)_\n"
            msg += "\n"
        
        return msg
    except requests.exceptions.RequestException as e:
        logging.error(f"ERP tasks error: {e}")
        return f"⚠️ Failed to fetch tasks: {e}"


@tool
def get_invoices(type: str = "due") -> str:
    """Get ERP invoices. Args: type — 'due' for overdue invoices, 'summary' for invoice summary."""
    try:
        base_url = get_base_url()
        if not base_url:
            return "⚠️ ERP URL not configured."
        
        if type == "summary":
            response = requests.get(f"{base_url}/invoices/summary", headers=get_headers(), timeout=15)
        else:
            response = requests.get(f"{base_url}/invoices/due", headers=get_headers(), timeout=15)
        
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        
        if type == "summary":
            summary = data.get('summary', data.get('data', {}))
            return (
                f"📊 *Invoice Summary*\n"
                f"Pending Invoices: {summary.get('pending_invoices_count', 0)}\n"
                f"Total Pending Amount: {summary.get('total_pending_amount', 0.00)}\n"
                f"Total Invoiced Amount: {summary.get('total_invoiced_amount', 0.00)}"
            )
        
        invoices = data.get('data', [])
        
        if not invoices:
            return "✅ No due invoices."
        
        msg = f"💰 *Due Invoices ({len(invoices)}):*\n"
        for inv in invoices:
            inv_no = inv.get('invoice_no', 'N/A')
            customer = inv.get('customer_name', 'Unknown')
            due = inv.get('due_amount', '0.00')
            date = inv.get('date', 'N/A')
            
            msg += f"- *{inv_no}*: {customer} - Due: {due} (Date: {date})\n"
        
        return msg
    except requests.exceptions.RequestException as e:
        logging.error(f"ERP invoices error: {e}")
        return f"⚠️ Failed to fetch invoices: {e}"


@tool
def search_invoices(customer_name: str) -> str:
    """Search invoices by customer name. Args: customer_name — name of the customer to search for."""
    try:
        base_url = get_base_url()
        if not base_url:
            return "⚠️ ERP URL not configured."
        
        params = {}
        if customer_name:
            params['customer_name'] = customer_name
        
        response = requests.get(
            f"{base_url}/invoices",
            headers=get_headers(),
            params=params,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        
        invoices = data.get('data', [])
        
        if not invoices:
            return f"✅ No invoices found for '{customer_name}'."
        
        msg = f"🔎 *Found Invoices ({len(invoices)}):*\n"
        for inv in invoices:
            status_icon = "✅" if inv.get('status') == 'Paid' else "⏳"
            cust = inv.get('customer_name', 'Unknown')
            total = inv.get('grand_total', '0.00')
            status = inv.get('status', 'Unknown')
            msg += f"- {status_icon} *{inv.get('invoice_no', 'N/A')}*: {cust} - {total} ({status})\n"
        
        return msg
    except requests.exceptions.RequestException as e:
        logging.error(f"ERP search error: {e}")
        return f"⚠️ Search failed: {e}"


@tool
def get_credentials(search: str = "") -> str:
    """Get stored ERP credentials. Args: search — optional search term to filter credentials."""
    try:
        base_url = get_base_url()
        if not base_url:
            return "⚠️ ERP URL not configured."
        
        params = {}
        if search:
            params["search"] = search
        
        response = requests.get(
            f"{base_url}/credentials",
            headers=get_headers(),
            params=params,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success'):
            return f"⚠️ API Error: {data.get('message', 'Unknown error')}"
        
        creds = data.get('data', [])
        
        if not creds:
            return "🔒 No credentials found."
        
        msg = f"🔐 *Project Credentials ({len(creds)}):*\n"
        for c in creds:
            msg += f"*{c.get('project_name', 'Unknown')}* - {c.get('service_name', '')}\n"
            msg += f"User: `{c.get('username', 'N/A')}`\n"
            msg += f"Pass: `{c.get('password', 'N/A')}`\n"
            msg += f"Desc: {c.get('description', '')}\n\n"
        
        return msg
    except requests.exceptions.RequestException as e:
        logging.error(f"ERP credentials error: {e}")
        return f"⚠️ Failed to fetch credentials: {e}"
