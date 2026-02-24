"""
Workflows Tool — Schedule, list, and cancel automated workflows.
"""
import logging
import json
import dateparser
import pytz
from datetime import datetime, timedelta
from langchain_core.tools import tool
from core import database
import config as app_config


# Workflow type descriptions
WORKFLOW_TYPES = {
    "BRIEFING": "Morning briefing with system health and pending tasks",
    "SYSTEM_HEALTH_REPORT": "System health status report",
    "ERP_TASKS_REPORT": "Pending ERP tasks report",
    "ERP_INVOICES_REPORT": "Due invoices report",
    "NOTIFY_USER": "Send skill output to a specific user",
    "COMPOSITE_REPORT": "Run multiple skills and send consolidated report",
}


@tool
def schedule_workflow(type: str, params: str = "{}", time: str = "now", interval_seconds: int = 0) -> str:
    """Schedule an automated workflow. Use this when the user wants to set up recurring or scheduled tasks.
    Args:
        type: Workflow type — BRIEFING, SYSTEM_HEALTH_REPORT, ERP_TASKS_REPORT, ERP_INVOICES_REPORT, NOTIFY_USER, COMPOSITE_REPORT.
        params: JSON string of workflow parameters. For NOTIFY_USER: {"target_user": "name", "skill_name": "SKILL"}. For COMPOSITE_REPORT: {"target_user": "name", "steps": [{"skill": "SKILL_NAME"}]}.
        time: When to run — 'now', or natural language like 'tomorrow at 9am', 'every day at 8am'.
        interval_seconds: Repeat interval. 0 = run once. 3600 = every hour. 86400 = every day."""
    try:
        conf = app_config.load_config()
        tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
        user_tz = pytz.timezone(tz_str)
        
        if type not in WORKFLOW_TYPES:
            available = ", ".join(WORKFLOW_TYPES.keys())
            return f"⚠️ Unknown workflow type '{type}'. Available: {available}"
        
        # Parse params
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                params_dict = {}
        else:
            params_dict = params if isinstance(params, dict) else {}
        
        # Parse time
        now_user = datetime.now(user_tz)
        
        if time.lower() == "now":
            dt_utc = datetime.utcnow()
        else:
            settings = {
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': now_user.replace(tzinfo=None),
                'TIMEZONE': tz_str,
                'RETURN_AS_TIMEZONE_AWARE': True
            }
            dt = dateparser.parse(time, settings=settings)
            if dt:
                if not dt.tzinfo:
                    dt = user_tz.localize(dt)
                dt_utc = dt.astimezone(pytz.utc).replace(tzinfo=None)
            else:
                dt_utc = datetime.utcnow()
        
        next_run = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
        
        wf_id = database.add_workflow(type, json.dumps(params_dict), interval_seconds, next_run)
        
        reply_dt = pytz.utc.localize(dt_utc).astimezone(user_tz)
        formatted_time = reply_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        
        msg = f"✅ Workflow scheduled!\n• Type: *{type}*\n• First run: {formatted_time}"
        if interval_seconds > 0:
            msg += f"\n• Repeats every {interval_seconds}s"
        msg += f"\n• ID: #{wf_id}"
        
        return msg
    except Exception as e:
        logging.error(f"Schedule workflow error: {e}")
        return f"⚠️ Failed to schedule workflow: {e}"


@tool
def list_workflows() -> str:
    """List all active scheduled workflows."""
    try:
        workflows = database.get_all_workflows()
        
        if not workflows:
            return "📋 No active workflows."
        
        conf = app_config.load_config()
        tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
        user_tz = pytz.timezone(tz_str)
        
        msg = "*📋 Active Workflows:*\n\n"
        for w in workflows:
            w_id, w_type, params, interval, next_run, status = w
            
            # Convert next_run to user TZ
            try:
                dt = datetime.fromisoformat(str(next_run))
                dt = pytz.utc.localize(dt)
                local_dt = dt.astimezone(user_tz)
                time_str = local_dt.strftime('%d %b %H:%M')
            except Exception:
                time_str = str(next_run)
            
            msg += f"#{w_id} *{w_type}*\n"
            msg += f"  Next: {time_str}"
            if interval > 0:
                msg += f" | Every {interval}s"
            msg += "\n"
        
        return msg
    except Exception as e:
        logging.error(f"List workflows error: {e}")
        return f"⚠️ Failed to list workflows: {e}"


@tool
def cancel_workflow(workflow_id: str = "", workflow_type: str = "") -> str:
    """Cancel a workflow by ID or type.
    Args:
        workflow_id: The workflow ID to cancel (e.g., '1').
        workflow_type: Cancel all workflows of this type (e.g., 'BRIEFING')."""
    try:
        if workflow_id:
            database.delete_workflow(int(workflow_id))
            return f"🗑️ Cancelled workflow #{workflow_id}."
        elif workflow_type:
            workflows = database.get_all_workflows()
            count = 0
            for w in workflows:
                if w[1].upper() == workflow_type.upper():
                    database.delete_workflow(w[0])
                    count += 1
            return f"🗑️ Cancelled {count} workflow(s) of type '{workflow_type}'."
        else:
            return "⚠️ Please specify a workflow_id or workflow_type to cancel."
    except Exception as e:
        logging.error(f"Cancel workflow error: {e}")
        return f"⚠️ Failed to cancel workflow: {e}"


# --- Background Job ---
async def check_workflows_job(context):
    """Background job to execute due workflows. Runs in thread to avoid blocking."""
    import asyncio
    
    try:
        active_workflows = database.get_active_workflows()
        
        if not active_workflows:
            return
        
        conf = app_config.load_config()
        chat_id = conf['telegram'].get('chat_id')
        if not chat_id:
            return
        
        loop = asyncio.get_running_loop()
        
        for wf in active_workflows:
            wf_id = wf['id']
            wf_type = wf['type']
            wf_params = wf['params']
            wf_interval = wf['interval_seconds']
            
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda wt=wf_type, wp=wf_params, c=conf: _execute_workflow_sync(wt, wp, c)
                )
                
                if result:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=result, parse_mode='Markdown')
                    except Exception:
                        await context.bot.send_message(chat_id=chat_id, text=result)
                
                if wf_interval > 0:
                    next_run = datetime.utcnow() + timedelta(seconds=wf_interval)
                    database.update_workflow_next_run(wf_id, next_run.strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    database.delete_workflow(wf_id)
                    
            except Exception as e:
                logging.error(f"Workflow {wf_id} ({wf_type}) execution error: {e}")
    except Exception as e:
        logging.error(f"Workflow check job error: {e}")


def _execute_workflow_sync(wf_type, params, conf):
    """Executes a specific workflow type synchronously (runs in thread). Returns result text."""
    from tools.system_health import get_system_status, get_all_system_health, format_health_report
    from tools.erp import get_pending_tasks, get_invoices
    
    if wf_type == "BRIEFING":
        health_data = get_all_system_health(conf)
        health_report = format_health_report(health_data)
        tasks = get_pending_tasks.invoke({})
        return f"☀️ *Morning Briefing*\n\n🖥️ *System Health:*\n{health_report}\n{tasks}"
    
    elif wf_type == "SYSTEM_HEALTH_REPORT":
        return get_system_status.invoke({})
    
    elif wf_type == "ERP_TASKS_REPORT":
        return get_pending_tasks.invoke({})
    
    elif wf_type == "ERP_INVOICES_REPORT":
        return get_invoices.invoke({"type": "due"})
    
    elif wf_type == "NOTIFY_USER":
        target = params.get('target_user', '')
        skill_name = params.get('skill_name', '')
        if target and skill_name:
            # Execute the skill and send to user
            from tools.notifications import notify_user
            skill_result = _invoke_skill_by_name(skill_name, params.get('skill_params', {}))
            return notify_user.invoke({"target_user": target, "message": skill_result})
        return None
    
    elif wf_type == "COMPOSITE_REPORT":
        steps = params.get('steps', [])
        intro = params.get('intro_text', '📊 *Composite Report*')
        results = [intro]
        for step in steps:
            skill_name = step.get('skill', '')
            skill_params = step.get('params', {})
            result = _invoke_skill_by_name(skill_name, skill_params)
            if result:
                results.append(result)
        return "\n\n---\n\n".join(results) if len(results) > 1 else None
    
    return None


def _invoke_skill_by_name(skill_name, params=None):
    """Invokes a tool by name."""
    from tools.erp import get_pending_tasks, get_invoices, get_credentials
    from tools.system_health import get_system_status
    
    skill_map = {
        "ERP_TASKS": lambda: get_pending_tasks.invoke({}),
        "ERP_INVOICES": lambda: get_invoices.invoke({"type": "due"}),
        "SYSTEM_HEALTH": lambda: get_system_status.invoke({}),
        "GET_CREDENTIALS": lambda: get_credentials.invoke({"search": (params or {}).get("search", "")}),
    }
    
    executor = skill_map.get(skill_name.upper())
    if executor:
        return executor()
    return f"⚠️ Unknown skill: {skill_name}"
