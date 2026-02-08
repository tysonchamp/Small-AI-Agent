import database

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
