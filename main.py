import os
import json
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# ------------------ CONFIG ------------------
BOT_TOKEN = "5217317508:AAEBtf71up5-fssiHWOwamZakB7_OveI3Os"
ADMINS = {624102836, 8394010826, 548916625}

LISTS_FILE = "data/lists.json"

# ------------------ LOGGING ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ------------------ LISTS DATABASE ------------------
LIST_ABOUT = range(1)

def ensure_data_file():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(LISTS_FILE):
        with open(LISTS_FILE, "w") as f:
            json.dump({"lists": {}, "selected_list": None}, f, indent=4)

def load_lists():
    ensure_data_file()
    with open(LISTS_FILE, "r") as f:
        return json.load(f)

def save_lists(data):
    ensure_data_file()
    with open(LISTS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ------------------ LISTS COMMANDS ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /newlist to create a new list or /lists to see all lists.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong!")

# Create new list
async def newlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /newlist <list name>")
    list_name = context.args[0].lower()
    data = load_lists()
    if list_name in data["lists"]:
        return await update.message.reply_text("❌ List already exists.")
    context.user_data["new_list_name"] = list_name
    await update.message.reply_text("What is this list about?")
    return LIST_ABOUT

async def newlist_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = update.message.text
    list_name = context.user_data["new_list_name"]
    data = load_lists()
    data["lists"][list_name] = {
        "about": about_text,
        "lines": [],
        "allow_members": False,
        "max_member_lines": 1
    }
    data["selected_list"] = list_name
    save_lists(data)
    await update.message.reply_text(f"✅ List '{list_name}' created and selected!")
    return ConversationHandler.END

# Select / Unselect list
async def select_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /select <list name>")
    list_name = context.args[0].lower()
    data = load_lists()
    if list_name not in data["lists"]:
        return await update.message.reply_text("❌ List not found.")
    data["selected_list"] = list_name
    save_lists(data)
    await update.message.reply_text(f"✅ List '{list_name}' selected.")

async def unselect_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    data["selected_list"] = None
    save_lists(data)
    await update.message.reply_text("✅ List unselected.")

# Show all lists
async def lists_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    if not data["lists"]:
        return await update.message.reply_text("No lists created yet.")
    msg = "📃 *Lists:*\n"
    for name, info in data["lists"].items():
        msg += f"- {name}: {info['about']}\n"
    await update.message.reply_markdown(msg)

# Show single list
async def view_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /list <listname>")
    list_name = context.args[0].lower()
    data = load_lists()
    if list_name not in data["lists"]:
        return await update.message.reply_text("❌ List not found.")
    lst = data["lists"][list_name]
    msg = f"📃 *{list_name}* ({lst['about']}):\n"
    if not lst["lines"]:
        msg += "No items yet."
    else:
        for i, line in enumerate(lst["lines"], 1):
            msg += f"{i}. {line}\n"
    await update.message.reply_markdown(msg)

# Add / Remove / Edit lines
async def addline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    selected = data["selected_list"]
    if not selected:
        return await update.message.reply_text("❌ No list selected.")
    lst = data["lists"][selected]
    uid = update.effective_user.id
    if not lst["allow_members"] and uid not in ADMINS:
        return await update.message.reply_text("❌ Only admins can add to this list.")
    if not context.args:
        return await update.message.reply_text("Usage: /addline <line text>")
    line_text = " ".join(context.args)
    lst["lines"].append(line_text)
    save_lists(data)
    await update.message.reply_text(f"✅ Added line: {line_text}")

async def rmline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    selected = data["selected_list"]
    if not selected:
        return await update.message.reply_text("❌ No list selected.")
    lst = data["lists"][selected]
    uid = update.effective_user.id
    if uid not in ADMINS:
        return await update.message.reply_text("❌ Only admins can remove lines.")
    if not context.args:
        return await update.message.reply_text("Usage: /rmline <line#>")
    try:
        idx = int(context.args[0]) - 1
        removed = lst["lines"].pop(idx)
        save_lists(data)
        await update.message.reply_text(f"✅ Removed line: {removed}")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid line number.")

async def editline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    selected = data["selected_list"]
    if not selected:
        return await update.message.reply_text("❌ No list selected.")
    lst = data["lists"][selected]
    uid = update.effective_user.id
    if uid not in ADMINS:
        return await update.message.reply_text("❌ Only admins can edit lines.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /editline <line#> <text>")
    try:
        idx = int(context.args[0]) - 1
        new_text = " ".join(context.args[1:])
        old = lst["lines"][idx]
        lst["lines"][idx] = new_text
        save_lists(data)
        await update.message.reply_text(f"✅ Replaced '{old}' with '{new_text}'")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid line number.")

# Set list type for member contributions
async def listtype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_lists()
    selected = data["selected_list"]
    if not selected:
        return await update.message.reply_text("❌ No list selected.")
    if not context.args:
        return await update.message.reply_text("Usage: /listtype on/off")
    arg = context.args[0].lower()
    if arg in ["on", "yes"]:
        data["lists"][selected]["allow_members"] = True
    elif arg in ["off", "no"]:
        data["lists"][selected]["allow_members"] = False
    else:
        return await update.message.reply_text("Use 'on/yes' or 'off/no'")
    save_lists(data)
    await update.message.reply_text(f"✅ List '{selected}' type updated. Members can add: {data['lists'][selected]['allow_members']}")

# ------------------ MAIN ------------------
def main():
    ensure_data_file()

    app = Application.builder().token(BOT_TOKEN).build()

    # Lists conversation handler
    list_conv = ConversationHandler(
        entry_points=[CommandHandler("newlist", newlist)],
        states={LIST_ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newlist_about)]},
        fallbacks=[]
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(list_conv)
    app.add_handler(CommandHandler("select", select_list))
    app.add_handler(CommandHandler("unselect", unselect_list))
    app.add_handler(CommandHandler("lists", lists_command))
    app.add_handler(CommandHandler(["list", "l"], view_list))
    app.add_handler(CommandHandler(["addline", "alist"], addline))
    app.add_handler(CommandHandler("rmline", rmline))
    app.add_handler(CommandHandler(["editline", "eline"], editline))
    app.add_handler(CommandHandler("listtype", listtype))

    print("Bot running…")
    app.run_polling()

if __name__ == "__main__":
    main()
