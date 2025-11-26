import os
import json
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMINS = {123456789, 987654321}  # Replace with your Telegram IDs

LIST_ABOUT = 1
DATA_FILE = "data/lists.json"

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------------- UTILS ----------------
def ensure_data_file():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f, indent=4)

def load_lists():
    ensure_data_file()
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_lists(data):
    ensure_data_file()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_group_key(update: Update):
    return str(update.effective_chat.id)

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to **List Creator Bot**!\n"
        "Use /newlist to create a list or /lists to see all lists.",
    )

# ---------------- NEW LIST ----------------
async def newlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /newlist <list name>")
        return ConversationHandler.END
    context.user_data["new_list_name"] = context.args[0].lower()
    await update.message.reply_text("📋 What is this list about? Reply with description.")
    return LIST_ABOUT

async def newlist_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = update.message.text
    list_name = context.user_data.get("new_list_name")
    if not list_name:
        await update.message.reply_text("❌ Something went wrong. Try /newlist again.")
        return ConversationHandler.END

    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data:
        data[group_key] = {"lists": {}, "selected": None}

    if list_name in data[group_key]["lists"]:
        await update.message.reply_text("❌ List already exists.")
        return ConversationHandler.END

    data[group_key]["lists"][list_name] = {
        "about": about_text,
        "lines": [],
        "allow_members": False,
        "max_member_lines": 1
    }
    data[group_key]["selected"] = list_name
    save_lists(data)

    await update.message.reply_text(f"✅ List '{list_name}' created and selected!")
    return ConversationHandler.END

# ---------------- SELECT / UNSELECT ----------------
async def select_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /select <list name>")
    list_name = context.args[0].lower()
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or list_name not in data[group_key]["lists"]:
        return await update.message.reply_text("❌ List not found.")
    data[group_key]["selected"] = list_name
    save_lists(data)
    await update.message.reply_text(f"✅ List '{list_name}' selected.")

async def unselect_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data:
        return await update.message.reply_text("❌ No lists found.")
    data[group_key]["selected"] = None
    save_lists(data)
    await update.message.reply_text("✅ List unselected.")

# ---------------- VIEW LISTS ----------------
async def lists_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or not data[group_key]["lists"]:
        return await update.message.reply_text("No lists created yet.")
    msg = "📃 *Lists:*\n"
    for name, info in data[group_key]["lists"].items():
        msg += f"- {name}: {info['about']}\n"
    await update.message.reply_markdown(msg)

async def view_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /list <list name>")
    list_name = context.args[0].lower()
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or list_name not in data[group_key]["lists"]:
        return await update.message.reply_text("❌ List not found.")
    lst = data[group_key]["lists"][list_name]
    msg = f"📃 *{list_name}* ({lst['about']}):\n"
    if not lst["lines"]:
        msg += "No items yet."
    else:
        for i, line in enumerate(lst["lines"], 1):
            msg += f"{i}. {line}\n"
    await update.message.reply_markdown(msg)

# ---------------- ADD / REMOVE / EDIT ----------------
async def addline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or not data[group_key]["selected"]:
        return await update.message.reply_text("❌ No list selected.")
    lst_name = data[group_key]["selected"]
    lst = data[group_key]["lists"][lst_name]
    uid = update.effective_user.id
    if not lst["allow_members"] and uid not in ADMINS:
        return await update.message.reply_text("❌ Only admins can add lines.")
    if not context.args:
        return await update.message.reply_text("Usage: /addline <line text>")
    line_text = " ".join(context.args)
    lst["lines"].append(line_text)
    save_lists(data)
    await update.message.reply_text(f"✅ Added line: {line_text}")

async def rmline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or not data[group_key]["selected"]:
        return await update.message.reply_text("❌ No list selected.")
    lst_name = data[group_key]["selected"]
    lst = data[group_key]["lists"][lst_name]
    if update.effective_user.id not in ADMINS:
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
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or not data[group_key]["selected"]:
        return await update.message.reply_text("❌ No list selected.")
    lst_name = data[group_key]["selected"]
    lst = data[group_key]["lists"][lst_name]
    if update.effective_user.id not in ADMINS:
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

# ---------------- LISTTYPE ----------------
async def listtype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /listtype on/off")
    group_key = get_group_key(update)
    data = load_lists()
    if group_key not in data or not data[group_key]["selected"]:
        return await update.message.reply_text("❌ No list selected.")
    lst_name = data[group_key]["selected"]
    lst = data[group_key]["lists"][lst_name]
    arg = context.args[0].lower()
    if arg in ["on", "yes"]:
        lst["allow_members"] = True
    elif arg in ["off", "no"]:
        lst["allow_members"] = False
    else:
        return await update.message.reply_text("Use 'on/yes' or 'off/no'")
    save_lists(data)
    await update.message.reply_text(f"✅ List '{lst_name}' type updated. Members can add: {lst['allow_members']}")

# ---------------- MAIN ----------------
def main():
    ensure_data_file()
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newlist", newlist)],
        states={LIST_ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newlist_about)]},
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("select", select_list))
    app.add_handler(CommandHandler("unselect", unselect_list))
    app.add_handler(CommandHandler("lists", lists_command))
    app.add_handler(CommandHandler(["list", "l"], view_list))
    app.add_handler(CommandHandler(["addline", "alist"], addline))
    app.add_handler(CommandHandler("rmline", rmline))
    app.add_handler(CommandHandler(["editline", "eline"], editline))
    app.add_handler(CommandHandler("listtype", listtype))

    print("✅ List Creator Bot running…")
    app.run_polling()

if __name__ == "__main__":
    main()
