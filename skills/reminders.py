import logging
import dateparser
import pytz
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ApplicationBuilder

import database
import config

async def handle_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List reminders from /reminders command."""
    chat_id = str(update.effective_chat.id)
    msg = await query_schedule(chat_id, "all") # Reuse logic
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    # Database now expects and returns everything in UTC logic
    reminders = database.get_pending_reminders() # Returns (id, chat_id, content, interval_seconds)
    
    for r in reminders:
        r_id, chat_id, content, interval = r
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ *REMINDER*\n\n{content}", parse_mode='Markdown')
            
            if interval > 0:
                # Reschedule - Calculate next run in UTC
                next_time = datetime.utcnow() + timedelta(seconds=interval)
                database.reschedule_reminder(r_id, next_time)
                logging.info(f"Rescheduled reminder {r_id} to {next_time} UTC")
            else:
                database.mark_reminder_sent(r_id)
                logging.info(f"Sent reminder {r_id} to {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send reminder {r_id}: {e}")

from skills.registry import skill

@skill(name="ADD_REMINDER", description="Set a reminder. Params: content, time. interval_seconds (OPTIONAL). target_user (OPTIONAL): Username to remind instead of self.")
async def add_reminder(chat_id, content, time, interval_seconds=0, target_user=None):
    if target_user:
        resolved_id = config.get_user_chat_id(target_user)
        if resolved_id:
            chat_id = resolved_id
        else:
            return f"❌ User '{target_user}' not found in configuration."

    conf = config.load_config()
    tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
    user_tz = pytz.timezone(tz_str)
    
    # "now" in user's timezone for relative parsing
    now_user = datetime.now(user_tz)
    
    settings = {
        'PREFER_DATES_FROM': 'future',
        'RELATIVE_BASE': now_user.replace(tzinfo=None), # dateparser prefers naive base? or aware?
        'TIMEZONE': tz_str,
        'RETURN_AS_TIMEZONE_AWARE': True 
    }
    
    # Dateparser sometimes struggles with aware relative base if not configured perfectly
    # Let's try parsing.
    dt = dateparser.parse(time, settings=settings)
    
    if not dt and interval_seconds > 0:
         dt = now_user + timedelta(seconds=interval_seconds)

    if dt:
        # If dt is naive, assume it's in user_tz
        if not dt.tzinfo:
            dt = user_tz.localize(dt)
        
        # Convert to UTC for storage
        dt_utc = dt.astimezone(pytz.utc)
        
        # Create a naive UTC object for DB (sqlite usually prefers matching string format)
        dt_db = dt_utc.replace(tzinfo=None) # 2026-02-13 12:00:00 (UTC value) via naive
        
        database.add_reminder(chat_id, content, dt_db, interval_seconds)
        
        # Format for reply in User TZ
        reply_dt = dt_utc.astimezone(user_tz)
        formatted_time = reply_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        
        resp = f"✅ Reminder set: '{content}' at {formatted_time}"
        if target_user:
            resp += f" for {target_user}"
        if interval_seconds > 0:
            resp += f" (Every {interval_seconds}s)"
        return resp
    else:
        return f"❓ Couldn't parse time for reminder: '{content}'"

@skill(name="CANCEL_REMINDER", description="Cancel reminders. Params: target ('all' or search text)")
async def cancel_reminder(chat_id, target):
    if target == "all":
        count = database.delete_all_pending_reminders(chat_id)
        return f"🗑️ Cancelled {count} pending reminders."
    else:
        # Find matching reminders
        reminders = database.search_reminders(chat_id, query_text=target)
        if not reminders:
                return f"No reminders found matching '{target}'."
        else:
            for r in reminders:
                database.delete_reminder(r[0])
            return f"🗑️ Cancelled {len(reminders)} reminders matching '{target}'."

@skill(name="QUERY_SCHEDULE", description="Check upcoming reminders. Params: time_range ('all', 'today', 'tomorrow')")
async def query_schedule(chat_id, time_range="all"):
    conf = config.load_config()
    tz_str = conf['telegram'].get('timezone', 'Asia/Kolkata')
    user_tz = pytz.timezone(tz_str)
    
    # Determine start/end time in UTC based on User TZ range
    # But wait, search_reminders does string comparison.
    # If we store UTC, we must convert our query range to UTC.
    
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
        return "📅 You have no upcoming reminders found."
    else:
        msg = "*📅 Upcoming Schedule:*\n"
        for r in reminders:
            # r = (id, content, remind_at_str, interval)
            try:
                # Parse DB string (UTC) -> Aware UTC
                db_dt = datetime.fromisoformat(str(r[2]))
                db_dt = pytz.utc.localize(db_dt)
                
                # Convert to User TZ
                local_dt = db_dt.astimezone(user_tz)
                time_str = local_dt.strftime('%d %b %H:%M')
            except Exception:
                time_str = str(r[2]) + " (UTC)"

            msg += f"- *{r[1]}* at {time_str}"
            if r[3] > 0:
                    msg += f" (Runs every {r[3]}s)"
            msg += "\n"
        return msg
