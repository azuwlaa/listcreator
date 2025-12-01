import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone, time as dt_time
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
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
    return datetime.now(timezone.utc) + timedelta(hours=5)

def calculate_late(clock_in_str, shift):
    fmt = "%H:%M:%S"
    clock_in_time = datetime.strptime(clock_in_str, fmt).time()
    start_time = dt_time(8, 30) if shift == "morning" else dt_time(17, 0)
    delta_minutes = (datetime.combine(datetime.min, clock_in_time) -
                     datetime.combine(datetime.min, start_time)).total_seconds() / 60
    return max(0, int(delta_minutes))

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
        Image.open(bio).verify()
    except:
        return
    reporter = msg.from_user
    photo_id = msg.photo[-1].file_id
    now = gmt5_now()
    date, time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO broken_logs (reported_by_id, reported_by_name, broken_by, photo_file_id, date, time, group_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (reporter.id, reporter.full_name, broken_by, photo_id, date, time, GROUP_ID))
    conn.commit()
    conn.close()

    confirm = await msg.reply_text(f"✅ Report logged for {broken_by}")
    asyncio.create_task(delete_after(confirm, 5))
    caption = f"🧹 Broken Glass Report\nReported by: {reporter.full_name}\nBroken by: {broken_by}\nDate: {date}\nTime: {time}"
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
        user = type('obj', (object,), {'id': user_id, 'username': arg})()
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
        user_id = int(context.args[0])
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
    if not msg.text or "at fr" not in msg.text.lower():
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
    hour_min = now.hour + now.minute / 60
    if hour_min < 12:
        shift = "morning"
        clock_out_time = dt_time(17, 0)
    else:
        shift = "evening"
        clock_out_time = dt_time(0, 30)
    clock_in_time = now.strftime("%H:%M:%S")
    cur.execute("INSERT OR REPLACE INTO attendance (staff_id, date, clock_in, clock_out, shift) VALUES (?, ?, ?, ?, ?)",
                (user.id, date_str, clock_in_time, clock_out_time.strftime("%H:%M:%S"), shift))
    conn.commit()
    conn.close()
    confirm = await msg.reply_text(f"✅ {user.full_name} clocked in at {clock_in_time} ({shift})")
    asyncio.create_task(delete_after(confirm, 5))
    await context.bot.send_message(LOG_CHANNEL_ID, f"🕒 {user.full_name} clocked in at {clock_in_time} ({shift})")

# ===== SHOW STAFF ATTENDANCE =====
async def show_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args and not msg.reply_to_message:
        await msg.reply_text("Reply to a user or provide Telegram ID/username.")
        return
    if msg.reply_to_message:
        staff_id = msg.reply_to_message.from_user.id
    else:
        staff_id = int(context.args[0])

    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT date, clock_in, clock_out, shift FROM attendance WHERE staff_id=? ORDER BY date", (staff_id,))
    rows = cur.fetchall()

    # Absents calculation for current month
    today = gmt5_now().date()
    month_start = today.replace(day=1)
    dates_in_month = [month_start + timedelta(days=i) for i in range(today.day)]
    present_dates = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in rows]

    lines = []
    total_days = len(dates_in_month)
    present_count = 0
    for d in dates_in_month:
        if d in present_dates:
            idx = present_dates.index(d)
            clock_in, clock_out, shift = rows[idx][1], rows[idx][2], rows[idx][3]
            late = calculate_late(clock_in, shift)
            lines.append(f"{d} - In: {clock_in}, Out: {clock_out}, Shift: {shift}, Late: {late} min")
            present_count += 1
        else:
            lines.append(f"{d} - Absent")
    conn.close()

    await msg.reply_text(f"📋 Attendance for ID {staff_id} ({present_count}/{total_days} present):\n" + "\n".join(lines))

# ===== REPORT EXCEL =====
async def report_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect("frc_bot.db")
    broken_df = pd.read_sql_query("SELECT * FROM broken_logs", conn)
    staff_df = pd.read_sql_query("SELECT * FROM staff", conn)
    attendance_df = pd.read_sql_query("SELECT * FROM attendance", conn)
    conn.close()
    file_path = "/tmp/frc_report.xlsx"
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        broken_df.to_excel(writer, sheet_name="Broken Glass", index=False)
        staff_df.to_excel(writer, sheet_name="Staff List", index=False)
        attendance_df.to_excel(writer, sheet_name="Attendance", index=False)
    await msg.reply_document(document=InputFile(file_path), filename="frc_report.xlsx")

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
    app.add_handler(CommandHandler("show", show_staff))
    app.add_handler(CommandHandler("report", report_excel))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(GROUP_ID), clock_in))
    app.add_handler(CommandHandler("reset", reset_history))

    print("✅ FRC Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
