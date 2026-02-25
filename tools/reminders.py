"""
Reminders Tool — Set, cancel, and query reminders.
"""
import logging
import dateparser
import pytz
from datetime import datetime, timedelta
from langchain_core.tools import tool
from core import database
import config as app_config


@tool
def add_reminder(content: str, time: str, interval_seconds: int = 0, target_user: str = "") -> str:
    """Set a reminder. Use this when the user wants to be reminded about something at a specific time.
    Args:
        content: What to remind about.
        time: When to remind (natural language like 'in 10 minutes', 'tomorrow at 9am', 'every day at 8am').
        interval_seconds: Optional. If > 0, the reminder repeats every N seconds. 'every hour' = 3600, 'every day' = 86400.
        target_user: Optional. Username to remind instead of self."""
    try:
        conf = app_config.load_config()
        tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
        user_tz = pytz.timezone(tz_str)
        
        # Resolve target user's chat_id
        chat_id = str(conf['telegram'].get('chat_id', ''))
        if target_user:
            users = conf.get('telegram', {}).get('users', {})
            resolved_id = users.get(target_user)
            if resolved_id:
                chat_id = resolved_id
            else:
                return f"❌ User '{target_user}' not found in configuration."
        
        now_user = datetime.now(user_tz)
        
        settings = {
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': now_user.replace(tzinfo=None),
            'TIMEZONE': tz_str,
            'RETURN_AS_TIMEZONE_AWARE': True
        }
        
        dt = dateparser.parse(time, settings=settings)
        
        if not dt and interval_seconds > 0:
            dt = now_user + timedelta(seconds=interval_seconds)
        
        if dt:
            if not dt.tzinfo:
                dt = user_tz.localize(dt)
            
            dt_utc = dt.astimezone(pytz.utc)
            dt_db = dt_utc.replace(tzinfo=None)
            
            database.add_reminder(chat_id, content, dt_db, interval_seconds)
            
            reply_dt = dt_utc.astimezone(user_tz)
            formatted_time = reply_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            
            # Sync to semantic memory
            try:
                from core.memory_sync import sync_to_memory
                sync_to_memory("reminder", f"{content} — scheduled for {formatted_time}", {
                    "remind_at": formatted_time,
                })
            except Exception as e:
                logging.warning(f"Memory sync failed for reminder: {e}")
            
            resp = f"✅ Reminder set: '{content}' at {formatted_time}"
            if target_user:
                resp += f" for {target_user}"
            if interval_seconds > 0:
                resp += f" (Every {interval_seconds}s)"
            return resp
        else:
            return f"❓ Couldn't parse time for reminder: '{content}'"
    except Exception as e:
        logging.error(f"Error adding reminder: {e}")
        return f"⚠️ Failed to add reminder: {e}"


@tool
def cancel_reminder(target: str) -> str:
    """Cancel reminders. Args: target — 'all' to cancel all, or search text to match specific reminders."""
    try:
        conf = app_config.load_config()
        chat_id = str(conf['telegram'].get('chat_id', ''))
        
        if target == "all":
            count = database.delete_all_pending_reminders(chat_id)
            return f"🗑️ Cancelled {count} pending reminders."
        else:
            reminders = database.search_reminders(chat_id, query_text=target)
            if not reminders:
                return f"No reminders found matching '{target}'."
            for r in reminders:
                database.delete_reminder(r[0])
            return f"🗑️ Cancelled {len(reminders)} reminders matching '{target}'."
    except Exception as e:
        logging.error(f"Error cancelling reminder: {e}")
        return f"⚠️ Failed to cancel reminder: {e}"


@tool
def query_schedule(time_range: str = "all") -> str:
    """Check upcoming reminders. Args: time_range — 'all', 'today', or 'tomorrow'."""
    try:
        conf = app_config.load_config()
        chat_id = str(conf['telegram'].get('chat_id', ''))
        tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
        user_tz = pytz.timezone(tz_str)
        
        start_t_utc = None
        end_t_utc = None
        now_user = datetime.now(user_tz)
        
        if time_range == "today":
            user_start = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
            user_end = now_user.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_t_utc = user_start.astimezone(pytz.utc).replace(tzinfo=None)
            end_t_utc = user_end.astimezone(pytz.utc).replace(tzinfo=None)
        elif time_range == "tomorrow":
            user_start = (now_user + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            user_end = user_start.replace(hour=23, minute=59, second=59)
            start_t_utc = user_start.astimezone(pytz.utc).replace(tzinfo=None)
            end_t_utc = user_end.astimezone(pytz.utc).replace(tzinfo=None)
        
        reminders = database.search_reminders(chat_id, start_time=start_t_utc, end_time=end_t_utc)
        
        if not reminders:
            return "📅 You have no upcoming reminders."
        
        msg = "*📅 Upcoming Schedule:*\n"
        for r in reminders:
            try:
                db_dt = datetime.fromisoformat(str(r[2]))
                db_dt = pytz.utc.localize(db_dt)
                local_dt = db_dt.astimezone(user_tz)
                time_str = local_dt.strftime('%d %b %H:%M')
            except Exception:
                time_str = str(r[2]) + " (UTC)"
            
            msg += f"- *{r[1]}* at {time_str}"
            if r[3] > 0:
                msg += f" (Runs every {r[3]}s)"
            msg += "\n"
        return msg
    except Exception as e:
        logging.error(f"Error querying schedule: {e}")
        return f"⚠️ Failed to query schedule: {e}"


# --- Background Job (not a tool, called by scheduler) ---
async def check_reminders_job(context):
    """Background job to check and send due reminders."""
    reminders = database.get_pending_reminders()
    
    for r in reminders:
        r_id, chat_id, content, interval = r
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ *REMINDER*\n\n{content}",
                parse_mode='Markdown'
            )
            
            if interval > 0:
                next_time = datetime.utcnow() + timedelta(seconds=interval)
                database.reschedule_reminder(r_id, next_time)
                logging.info(f"Rescheduled reminder {r_id} to {next_time} UTC")
            else:
                database.mark_reminder_sent(r_id)
                logging.info(f"Sent reminder {r_id} to {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send reminder {r_id}: {e}")
