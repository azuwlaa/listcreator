import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, time as dt_time, date as dt_date
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ParseMode
from PIL import Image
import io
import pandas as pd

# ===== CONFIG =====
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304       # Staff group
LOG_CHANNEL_ID = -1003449720539 # Logging channel

# ===== DATABASE INIT =====
def init_db():
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    # Broken glass logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS broken_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reported_by_id INTEGER,
            reported_by_name TEXT,
            broken_by TEXT,
            photo_file_id TEXT,
            date TEXT,
            time TEXT,
            group_id INTEGER
        )
    """)
    # Staff
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    # Attendance
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            staff_id INTEGER,
            date TEXT,
            clock_in TEXT,
            clock_out TEXT,
            shift TEXT,
            PRIMARY KEY (staff_id, date)
        )
    """)
    conn.commit()
    conn.close()

# ===== HELPER FUNCTIONS =====
def gmt5_now():
    return datetime.utcnow() + timedelta(hours=5)

def save_broken_log(reporter_id, reporter_name, broken_by, photo_id, group_id):
    now = gmt5_now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M:%S")
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO broken_logs (reported_by_id, reported_by_name, broken_by, photo_file_id, date, time, group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (reporter_id, reporter_name, broken_by, photo_id, date, time, group_id))
    conn.commit()
    conn.close()
    return date, time

def extract_broken_by(text: str):
    if not text:
        return None
    match = re.search(r"broken\s*by\s*[:\-–=•]*\s*([^\n]+)", text, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        name = re.sub(r"[\*\_\-\.\,\|\•]+$", "", name).strip()
        name = re.sub(r"[^\w\s\.\-']", "", name)
        return name[:50].strip()
    return None

async def delete_after(msg, delay_s: int):
    await asyncio.sleep(delay_s)
    try:
        await msg.delete()
    except:
        pass

def staff_is_admin(user_id, chat_id, bot: "telegram.Bot"):
    # Can be improved with bot.get_chat_member if needed
    return True  # For now, only implement via admin check in command handlers

# ===== BROKEN GLASS HANDLER =====
async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != GROUP_ID or not msg.photo:
        return

    text = msg.caption or ""
    broken_by = extract_broken_by(text)
    if not broken_by:
        return

    try:
        file = await context.bot.get_file(msg.photo[-1].file_id)
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        img = Image.open(bio)
        img.verify()
    except:
        return

    reporter = msg.from_user
    photo_id = msg.photo[-1].file_id
    date, time = save_broken_log(reporter.id, reporter.full_name, broken_by, photo_id, GROUP_ID)

    confirm = await msg.reply_text(f"✅ Report logged for {broken_by}")
    asyncio.create_task(delete_after(confirm, 5))

    caption = (
        f"🧹 Broken Glass Report\n"
        f"Reported by: {reporter.full_name}\n"
        f"Broken by: {broken_by}\n"
        f"Date: {date}\n"
        f"Time: {time}"
    )
    await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=photo_id, caption=caption)

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    now = gmt5_now()
    month = now.strftime("%Y-%m")
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT reported_by_id) FROM broken_logs WHERE date LIKE ? AND group_id=?",
                (f"{month}%", GROUP_ID))
    total_broken, reporter_count = cur.fetchone()
    conn.close()
    await msg.reply_text(f"📊 {now.strftime('%B %Y')} Summary\nTotal broken: {total_broken}\nReported by staff: {reporter_count}")

# ===== STAFF MANAGEMENT =====
async def add_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message and not context.args:
        await msg.reply_text("Reply to a user or provide Telegram ID/username.")
        return

    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
    else:
        arg = context.args[0]
        user_id = int(arg) if arg.isdigit() else None
        user = type('obj', (object,), {'id': user_id, 'username': arg})()  # dummy

    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO staff (user_id, username) VALUES (?, ?)", (user.id, getattr(user, 'username', None)))
    conn.commit()
    conn.close()
    confirm = await msg.reply_text(f"✅ Added staff: {getattr(user, 'username', user.id)}")
    asyncio.create_task(delete_after(confirm, 5))

async def rm_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message and not context.args:
        await msg.reply_text("Reply to a user or provide Telegram ID/username.")
        return
    if msg.reply_to_message:
        user_id = msg.reply_to_message.from_user.id
    else:
        arg = context.args[0]
        user_id = int(arg)
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    confirm = await msg.reply_text(f"✅ Removed staff ID {user_id}")
    asyncio.create_task(delete_after(confirm, 5))

async def list_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT username, user_id FROM staff")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No staff found.")
        return
    lines = [f"{r[0]} ({r[1]})" for r in rows]
    await update.message.reply_text("👥 Staff List:\n" + "\n".join(lines))

# ===== CLOCK-IN/OUT =====
async def clock_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text.lower()
    if "at fr" not in text:
        return

    user = msg.from_user
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM staff WHERE user_id=?", (user.id,))
    if not cur.fetchone():
        conn.close()
        return

    now = gmt5_now()
    date_str = now.strftime("%Y-%m-%d")
    hour = now.hour + now.minute/60

    # Determine shift
    shift = "morning" if hour < 12 else "evening"
    clock_out_time = dt_time(17,0) if shift=="morning" else dt_time(0,30)
    clock_in_time = now.strftime("%H:%M:%S")
    cur.execute("INSERT OR REPLACE INTO attendance (staff_id, date, clock_in, clock_out, shift) VALUES (?, ?, ?, ?, ?)",
                (user.id, date_str, clock_in_time, clock_out_time.strftime("%H:%M:%S"), shift))
    conn.commit()
    conn.close()
    confirm = await msg.reply_text(f"✅ {user.full_name} clocked in at {clock_in_time} ({shift})")
    asyncio.create_task(delete_after(confirm,5))

# ===== SHOW STAFF REPORT =====
async def show_staff_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use previous code for /show, including absent/off detection
    ...

# ===== EXPORT REPORT =====
async def export_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use previous code for /report to generate Excel
    ...

# ===== RESET HISTORY =====
async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM broken_logs")
    conn.commit()
    conn.close()
    await msg.reply_text("✅ Broken glass history reset and logged.")
    await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"🗑️ History reset by {msg.from_user.full_name}")

# ===== MAIN =====
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.PHOTO, report_handler))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(CommandHandler("add", add_staff))
    app.add_handler(CommandHandler("rm", rm_staff))
    app.add_handler(CommandHandler("staff", list_staff))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(GROUP_ID), clock_in))
    app.add_handler(CommandHandler("show", show_staff_report))
    app.add_handler(CommandHandler("report", export_report))
    app.add_handler(CommandHandler("reset", reset_history))

    print("✅ FRC Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
