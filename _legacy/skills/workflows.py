import logging
import dateparser
from datetime import datetime, timedelta
from telegram.ext import ContextTypes
import pytz

import config
import database
from skills import registry

# Forward declaration or lazy import might be needed for system_health if circular
# But here we invoke it, so we can import it inside the function or at top if no cycle.
# system_health doesn't import workflows, so top level import is fine.
# But system_health is not created yet! So I will use lazy import inside function.

# --- WORKFLOW REGISTRY ---
# --- WORKFLOW REGISTRY ---
WORKFLOW_TYPES = {
    "BRIEFING": "Morning/Daily Briefing (Agenda, Notes, System Health) - Goes to Bot Owner",
    "SYSTEM_HEALTH": "System Resource Monitoring (CPU, RAM, Disk) - Goes to Bot Owner",
    "ERP_TASKS_REPORT": "Fetch Pending ERP Project Tasks - Goes to Bot Owner (Default Chat)",
    "ERP_INVOICES_REPORT": "Fetch Due ERP Invoices - Goes to Bot Owner (Default Chat)",
    "NOTIFY_USER": "Send skill output to a SPECIFIC user (Params: target_user, skill_name, skill_params)",
    "COMPOSITE_REPORT": "Run MULTIPLE skills and send consolidated report to user (Params: target_user, steps=[{skill, params}])"
}

def get_workflow_descriptions():
    """Returns a formatted string of available workflows for the System Prompt."""
    desc = ""
    for w_type, help_text in WORKFLOW_TYPES.items():
        desc += f'       - type: "{w_type}" ({help_text})\n'
    return desc.strip()

async def run_briefing_workflow(context: ContextTypes.DEFAULT_TYPE, params: dict):
    """Compiles and sends a morning briefing."""
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    
    if not chat_id:
        return

    # 1. Get Pending Reminders for Today
    now = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    reminders = database.search_reminders(chat_id, start_time=now, end_time=end_of_day)
    
    # 2. Get Unread Notes (Recent 5)
    notes = database.get_notes(limit=5)
    
    # 3. System Health (Simple check)
    # Lazy import to avoid import error during migration before system_health exists
    from skills import system_health
    health = system_health.check_local_health()
    
    # Compile Message
    msg = f"🌅 *Morning Briefing* - {now.strftime('%d %b %Y')}\n\n"
    
    if reminders:
        msg += "*📅 Today's Agenda:*\n"
        for r in reminders:
            msg += f"- {r[1]} at {r[2]}\n"
    else:
        msg += "📅 No reminders set for today.\n"
    
    msg += "\n"
    
    if notes:
        msg += "*📝 Recent Notes:*\n"
        for n in notes:
            msg += f"- {n[1]}\n"
    
    msg += "\n"
    msg += "*🖥️ System Status:*\n"
    msg += f"CPU: {health.get('cpu_percent', '?')}% | RAM: {health.get('ram_percent', '?')}%\n"
    
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')



async def run_system_health_workflow(context, params):
    """Aliased to existing logic but triggered via workflow."""
    from skills import system_health
    await system_health.check_server_health_job(context, report_all=True)

async def run_erp_tasks_workflow(context, params):
    """Fetches pending tasks and sends them."""
    from skills import erp
    # Run in executor to avoid blocking async loop
    import asyncio
    loop = asyncio.get_running_loop()
    msg = await loop.run_in_executor(None, erp.get_pending_tasks)
    
    # Send message
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

async def run_erp_invoices_workflow(context, params):
    """Fetches due invoices and sends them."""
    from skills import erp
    import asyncio
    loop = asyncio.get_running_loop()
    msg = await loop.run_in_executor(None, erp.get_due_invoices)
    
    # Send message
    conf = config.load_config()
    chat_id = conf['telegram'].get('chat_id')
    if chat_id:
        await context.bot.send_message(chat_id=chat_id, text=f"💰 *Scheduled Invoice Report:*\n{msg}", parse_mode='Markdown')

async def run_notify_user_workflow(context, params):
    """Executes the NOTIFY_USER skill."""
    from skills import notifications
    
    target_user = params.get('target_user')
    skill_name = params.get('skill_name')
    skill_params = params.get('skill_params', {})
    
    # We ignore the return value here as notify_user sends the message itself?
    # Actually notify_user implementation returns a string "Status", and sends the msg internally.
    # So we can just call it.
    
    await notifications.notify_user(target_user, skill_name, skill_params)
    await notifications.notify_user(target_user, skill_name, skill_params)

async def run_composite_report_workflow(context, params):
    """
    Executes multiple skills and sends a consolidated report to a specific user.
    Params: target_user, intro_text, steps=[{"skill": "name", "params": {}}]
    """
    target_user = params.get('target_user')
    intro_text = params.get('intro_text', "📊 *Composite Report*")
    steps = params.get('steps', [])
    
    # Resolve User
    chat_id = config.get_user_chat_id(target_user)
    if not chat_id:
        logging.error(f"Composite Workflow Failed: Target user '{target_user}' not found.")
        return

    report_msg = f"{intro_text}\n\n"
    
    for step in steps:
        skill_name = step.get('skill')
        skill_params = step.get('params', {})
        
        if skill_name in registry.TOOLS:
            tool_def = registry.TOOLS[skill_name]
            func = tool_def["func"]
            
            try:
                # Helper to call async/sync functions
                import inspect
                import asyncio
                
                # Check signature to inject dependencies if needed (though usually skills take simple params)
                # For workflows, we might need to be careful about what params we pass.
                # Simplest assumption: Skill params map 1:1 to function args.
                
                if inspect.iscoroutinefunction(func):
                    result = await func(**skill_params)
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, lambda: func(**skill_params))
                
                report_msg += f"--- {skill_name} ---\n{result}\n\n"
                
            except Exception as e:
                report_msg += f"⚠️ Error executing {skill_name}: {e}\n\n"
        else:
            report_msg += f"⚠️ Unknown Skill: {skill_name}\n\n"
            
    # Send Final Report
    await context.bot.send_message(chat_id=chat_id, text=report_msg, parse_mode='Markdown')

async def check_workflows_job(context: ContextTypes.DEFAULT_TYPE):
    """Generic job to check and run dynamic workflows."""
    workflows = database.get_active_workflows()
    now = datetime.utcnow()
    
    for w in workflows:
        try:
            next_run_str = w['next_run_time']
            try:
                # Try standard format first
                # We assume stored time is naive UTC string
                next_run = datetime.strptime(next_run_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                try:
                    # Fallback to dateparser
                    # If dateparser returns aware, convert to naive UTC
                    # If naive, assume UTC
                    next_run = dateparser.parse(next_run_str)
                    if next_run.tzinfo:
                         next_run = next_run.astimezone(pytz.utc).replace(tzinfo=None)
                except:
                        next_run = None
            
            logging.info(f"Checking Workflow {w['id']} ({w['type']}): Now(UTC)={now}, Next={next_run}")

            if not next_run:
                logging.warning(f"Could not parse next_run for workflow {w['id']}: {next_run_str}")
                continue
                
            if now >= next_run:
                logging.info(f"Running workflow {w['id']} ({w['type']})")
                
                # DISPATCHER
                if w['type'] == 'BRIEFING':
                    await run_briefing_workflow(context, w['params'])
                elif w['type'] == 'SYSTEM_HEALTH':
                     await run_system_health_workflow(context, w['params'])
                elif w['type'] == 'ERP_TASKS' or w['type'] == 'ERP_TASKS_REPORT':
                    await run_erp_tasks_workflow(context, w['params'])
                elif w['type'] == 'ERP_TASKS_REPORT,SYSTEM_STATUS': # Handle legacy/hallucinated type
                     # Split and run both? Or just ignore bad type?
                     # Let's run ERP tasks as best effort
                     await run_erp_tasks_workflow(context, w['params'])
                     await run_system_health_workflow(context, w['params'])
                elif w['type'] == 'ERP_INVOICES' or w['type'] == 'ERP_INVOICES_REPORT':
                    await run_erp_invoices_workflow(context, w['params'])
                elif w['type'] == 'NOTIFY_USER':
                    await run_notify_user_workflow(context, w['params'])
                elif w['type'] == 'COMPOSITE_REPORT':
                    await run_composite_report_workflow(context, w['params'])
                
                # SCHEDULE NEXT RUN
                interval = w['interval_seconds']
                if interval > 0:
                    new_next_run = now + timedelta(seconds=interval)
                    database.update_workflow_next_run(w['id'], new_next_run)
                    logging.info(f"Rescheduled workflow {w['id']} to {new_next_run}")
                else:
                    # One-off workflow
                    database.delete_workflow(w['id'])
                    
        except Exception as e:
            logging.error(f"Error in workflow {w.get('id')}: {e}")

from skills.registry import skill

@skill(name="SCHEDULE_WORKFLOW", description='Schedule a recurring task. Params: type, params (JSON string or dict), time (e.g. "tomorrow at 9am"), interval_seconds')
async def schedule_workflow(type: str, params = "{}", time: str = "now", interval_seconds: int = 0):
    import json
    
    params_dict = {}
    if isinstance(params, dict):
        params_dict = params
    elif isinstance(params, str):
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError:
            return "⚠️ Error: params must be a valid JSON string."
    else:
        # Fallback
        params_dict = {}

    dt = dateparser.parse(time, settings={'PREFER_DATES_FROM': 'future'})
    if not dt:
        dt = datetime.utcnow() # Default to Now UTC
    else:
        # If dt has no timezone, assume it's User Local (IST usually from config)
        # But we don't have user config here easily without loading.
        # Let's assume input text like "tomorrow 9am" implies User Local.
        # We need to convert it to UTC for DB.
        conf = config.load_config()
        tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
        local_tz = pytz.timezone(tz_str)
        
        if not dt.tzinfo:
            dt = local_tz.localize(dt)
        
        dt = dt.astimezone(pytz.utc).replace(tzinfo=None) # Convert to naive UTC

    database.add_workflow(type, params_dict, interval_seconds, dt)
    
    # Reponse in Local time
    conf = config.load_config()
    tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
    local_tz = pytz.timezone(tz_str)
    
    # dt is naive UTC now
    dt_aware = pytz.utc.localize(dt)
    dt_local = dt_aware.astimezone(local_tz)
    
    resp = f"✅ Scheduled *{type}* starting at {dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    if interval_seconds > 0:
        resp += f" (Runs every {interval_seconds}s)"
    return resp

@skill(name="LIST_WORKFLOWS", description="List active scheduled workflows.")
def list_workflows():
    workflows = database.get_active_workflows()
    if not workflows:
        return "📭 No active system workflows."
    else:
        msg = "*⚙️ Active Workflows:*\n"
        for w in workflows:
            msg += f"- *{w['id']}* [{w['type']}]: Next run {w['next_run_time']} (Interval: {w['interval_seconds']}s)\n"
            if w['params']:
                msg += f"  Params: {w['params']}\n"
        return msg


@skill(name="CANCEL_WORKFLOW", description="Cancel/Delete a scheduled workflow. Params: workflow_id (int) OR workflow_type (str). To cancel ALL, pass workflow_type='ALL'.")
def cancel_workflow(workflow_id=None, workflow_type=None):
    """Cancels a workflow by ID or Type."""
    if workflow_id:
        try:
            workflow_id = int(workflow_id)
            database.delete_workflow(workflow_id)
            return f"✅ Workflow {workflow_id} cancelled."
        except Exception as e:
             return f"⚠️ Error cancelling workflow {workflow_id}: {e}"
    
    if workflow_type:
        # Check for ALL
        if workflow_type.upper() == 'ALL':
            workflows = database.get_active_workflows()
            if not workflows:
                return "⚠️ No active workflows to cancel."
            
            for w in workflows:
                database.delete_workflow(w['id'])
            return f"✅ Cancelled ALL {len(workflows)} active workflows."

        # Find ID by type
        workflows = database.get_active_workflows()
        count = 0
        deleted_ids = []
        for w in workflows:
            if w['type'].upper() == workflow_type.upper():
                database.delete_workflow(w['id'])
                deleted_ids.append(w['id'])
                count += 1
        
        if count > 0:
            return f"✅ Cancelled {count} workflows of type '{workflow_type}' (IDs: {deleted_ids})."
        else:
            return f"⚠️ No workflows found of type '{workflow_type}'."
        
    return "⚠️ Please provide either workflow_id or workflow_type."

def handle_list_workflows():
    workflows = database.get_active_workflows()
    if not workflows:
        return "📭 No active system workflows."
    else:
        msg = "*⚙️ Active Workflows:*\n"
        for w in workflows:
            msg += f"- *{w['id']}* [{w['type']}]: Next run {w['next_run_time']} (Interval: {w['interval_seconds']}s)\n"
        return msg
