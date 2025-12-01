import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)
from PIL import Image
import io
import pandas as pd

# ===== CONFIGURATION =====
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304   # Group where reports happen
LOG_CHANNEL_ID = -1003449720539   # Channel where logs go
DB_FILE = "frc_bot.db"

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
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
    # Staff table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT
        )
    """)
    # Attendance table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            staff_id INTEGER,
            date TEXT,
            clock_in TEXT,
            clock_out TEXT,
            shift TEXT
        )
    """)
    conn.commit()
    conn.close()

# ===== TIME HELPERS =====
def gmt5_now():
    return datetime.now(timezone.utc) + timedelta(hours=5)

# ===== HELPER FUNCTIONS =====
def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

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

def save_broken_log(reporter_id, reporter_name, broken_by, photo_id, group_id):
    now = gmt5_now()
    date = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO broken_logs (
            reported_by_id, reported_by_name, broken_by,
            photo_file_id, date, time, group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (reporter_id, reporter_name, broken_by, photo_id, date, time_str, group_id))
    conn.commit()
    conn.close()
    return date, time_str

# ===== HANDLERS =====
async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != GROUP_ID or not msg.photo:
        return
    text = msg.caption or ""
    broken_by = extract_broken_by(text)
    if not broken_by:
        return
    reporter = msg.from_user
    photo_id = msg.photo[-1].file_id
    # Validate photo
    try:
        file = await context.bot.get_file(photo_id)
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        img = Image.open(bio)
        img.verify()
    except:
        return
    date, time_str = save_broken_log(reporter.id, reporter.full_name, broken_by, photo_id, GROUP_ID)
    confirm = await msg.reply_text(f"✅ Report logged for {broken_by}")
    asyncio.create_task(delete_after(confirm, 5))
    caption = (
        f"🧹 Broken Glass Report\n"
        f"Reported by: {reporter.full_name}\n"
        f"Broken by: {broken_by}\n"
        f"Date: {date}\n"
        f"Time: {time_str}"
    )
    await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=photo_id, caption=caption)

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.chat_id != GROUP_ID:
        return
    now = gmt5_now()
    month = now.strftime("%Y-%m")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*), COUNT(DISTINCT reported_by_id)
        FROM broken_logs
        WHERE date LIKE ? AND group_id = ?
    """, (f"{month}%", GROUP_ID))
    total_broken, reporter_count = cur.fetchone()
    conn.close()
    await msg.reply_text(
        f"{now.strftime('%B %Y')} Summary\n"
        f"Total broken: {total_broken}\n"
        f"Reported by staff: {reporter_count}"
    )

# ===== STAFF MANAGEMENT =====
async def add_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message and not context.args:
        await msg.reply_text("Reply to user or provide ID to add staff.")
        return
    user_id = context.args[0] if context.args else msg.reply_to_message.from_user.id
    full_name = msg.reply_to_message.from_user.full_name if msg.reply_to_message else "Unknown"
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO staff(user_id, full_name) VALUES (?, ?)", (int(user_id), full_name))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ Staff {full_name} added.")

async def remove_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message and not context.args:
        await msg.reply_text("Reply to user or provide ID to remove staff.")
        return
    user_id = context.args[0] if context.args else msg.reply_to_message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE user_id=?", (int(user_id),))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ Staff removed.")

async def list_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name, user_id FROM staff")
    rows = cur.fetchall()
    conn.close()
    text = "\n".join([f"{r[0]} ({r[1]})" for r in rows])
    await msg.reply_text(f"Staff list ({len(rows)} total):\n{text}")

# ===== CLOCK-IN / CLOCK-OUT =====
async def clock_in_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text.lower() if msg.text else ""
    if text != "at fr" and not msg.text.startswith("/clock"):
        return
    user = msg.from_user
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM staff WHERE user_id=?", (user.id,))
    if not cur.fetchone():
        conn.close()
        return
    now = gmt5_now()
    date_str = now.strftime("%Y-%m-%d")
    cur.execute("SELECT * FROM attendance WHERE staff_id=? AND date=?", (user.id, date_str))
    if cur.fetchone():
        conn.close()
        await msg.reply_text(f"❌ {user.full_name}, you have already clocked in today.")
        return
    hour_min = now.hour + now.minute / 60
    if hour_min < 12:
        shift = "morning"
        clock_out_time = dt_time(17, 0)
    else:
        shift = "evening"
        clock_out_time = dt_time(0, 30)
    clock_in_time = now.strftime("%H:%M")
    cur.execute("""
        INSERT INTO attendance (staff_id, date, clock_in, clock_out, shift)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id, date_str, clock_in_time, clock_out_time.strftime("%H:%M"), shift))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ {user.full_name} clocked in at {clock_in_time} ({shift})")
    await context.bot.send_message(LOG_CHANNEL_ID, f"{user.full_name} clocked in at {clock_in_time} ({shift})")

async def show_staff_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args and not msg.reply_to_message:
        await msg.reply_text("Provide staff ID or reply to their message.")
        return
    staff_id = int(context.args[0]) if context.args else msg.reply_to_message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM staff WHERE user_id=?", (staff_id,))
    staff = cur.fetchone()
    if not staff:
        conn.close()
        await msg.reply_text("Staff not found.")
        return
    cur.execute("SELECT date, clock_in, clock_out, shift FROM attendance WHERE staff_id=?", (staff_id,))
    rows = cur.fetchall()
    conn.close()
    text = f"Attendance for {staff[0]}:\n" + "\n".join([f"{r[0]} | {r[1]} - {r[2]} ({r[3]})" for r in rows])
    await msg.reply_text(text)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_member = await context.bot.get_chat_member(GROUP_ID, msg.from_user.id)
    if chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await msg.reply_text("❌ Only admins can reset.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM broken_logs")
    cur.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    await msg.reply_text("✅ All history reset.")
    await context.bot.send_message(LOG_CHANNEL_ID, f"⚠️ {msg.from_user.full_name} reset all history.")

async def report_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM broken_logs", conn)
    conn.close()
    file_name = "broken_logs.xlsx"
    df.to_excel(file_name, index=False)
    with open(file_name, "rb") as f:
        await context.bot.send_document(chat_id=msg.chat_id, document=f, filename=file_name)

# ===== MAIN =====
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Broken glass
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.PHOTO, report_handler))
    app.add_handler(CommandHandler("total", total))

    # Staff management
    app.add_handler(CommandHandler("add", add_staff))
    app.add_handler(CommandHandler("rm", remove_staff))
    app.add_handler(CommandHandler("staff", list_staff))
    app.add_handler(CommandHandler("show", show_staff_detail))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("report", report_excel))

    # Clock in
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, clock_in_user))
    app.add_handler(CommandHandler("clock", clock_in_user))

    print("✅ FRC Bot running on PTB v21+")
    app.run_polling()

if __name__ == "__main__":
    main()
