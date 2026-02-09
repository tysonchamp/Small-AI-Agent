import logging
import dateparser
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes, ApplicationBuilder

import database

async def handle_reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List reminders from /reminders command."""
    # Assuming the user wants to see their schedule
    chat_id = update.effective_chat.id
    msg = await handle_query_schedule(chat_id, "all") # Reuse logic
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    reminders = database.get_pending_reminders() # Returns (id, chat_id, content, interval_seconds)
    
    for r in reminders:
        r_id, chat_id, content, interval = r
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ *REMINDER*\n\n{content}", parse_mode='Markdown')
            
            if interval > 0:
                # Reschedule
                next_time = datetime.now() + timedelta(seconds=interval)
                database.reschedule_reminder(r_id, next_time)
                logging.info(f"Rescheduled reminder {r_id} to {next_time}")
            else:
                database.mark_reminder_sent(r_id)
                logging.info(f"Sent reminder {r_id} to {chat_id}")
        except Exception as e:
            logging.error(f"Failed to send reminder {r_id}: {e}")

from skills.registry import skill

@skill(name="ADD_REMINDER", description="Set a reminder. Params: content, time, interval_seconds")
async def add_reminder(chat_id, content, time, interval_seconds=0):
    dt = dateparser.parse(time, settings={'PREFER_DATES_FROM': 'future'})
    
    # Fallback logic
    if not dt and time and ("in" in time or "every" in time):
            pass # dateparser usually handles "in X" well.
    
    if not dt and interval_seconds > 0:
            dt = datetime.now() + timedelta(seconds=interval_seconds)
    
    if dt:
        database.add_reminder(chat_id, content, dt, interval_seconds)
        resp = f"✅ Reminder set: '{content}' at {dt.strftime('%H:%M:%S')}"
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

@skill(name="QUERY_SCHEDULE", description="Check upcoming reminders. Params: time_range ('all' or 'tomorrow')")
async def query_schedule(chat_id, time_range="all"):
    # Determine start/end time based on range
    start_t = datetime.now()
    end_t = None
    
    if time_range == "tomorrow":
        start_t = start_t + timedelta(days=1)
        end_t = start_t + timedelta(days=1) # End of tomorrow? roughly
    
    reminders = database.search_reminders(chat_id, start_time=start_t, end_time=end_t)
    
    if not reminders:
        return "📅 You have no upcoming reminders found."
    else:
        msg = "*📅 Upcoming Schedule:*\n"
        for r in reminders:
            # r = (id, content, remind_at, interval)
            r_time = r[2]
            msg += f"- *{r[1]}* at {r_time}"
            if r[3] > 0:
                    msg += " (Recurring)"
            msg += "\n"
        return msg
