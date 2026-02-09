import database
from telegram import Update
from telegram.ext import ContextTypes

async def handle_note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a note from /note command."""
    if not context.args:
        await update.message.reply_text("Usage: /note [content]")
        return
    
    content = " ".join(context.args)
    handle_add_note(content)
    await update.message.reply_text("✅ Note saved.")

async def handle_notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List notes from /notes command."""
    msg = handle_list_notes()
    await update.message.reply_text(msg, parse_mode='Markdown')

def handle_add_note(content):
    database.add_note(content)
    return "✅ Note saved."

def handle_list_notes(limit=10):
    notes = database.get_notes(limit=limit)
    if not notes:
        return "No notes found."
    else:
        msg = "*📝 Recent Notes:*\n"
        for n in notes:
            msg += f"- {n[1]}\n"
        return msg
