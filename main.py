import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, time as dt_time
from telegram import Update
from telegram.constants import ParseMode, ChatMemberStatus
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
import calendar

# ===== CONFIG =====
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304
LOG_CHANNEL_ID = -1003449720539
DB_FILE = "frc_bot.db"

# ===== HELPER FUNCTIONS =====
def gmt5_now():
    return datetime.utcnow() + timedelta(hours=5)

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

async def delete_after(msg, delay_s: int):
    await asyncio.sleep(delay_s)
    try:
        await msg.delete()
    except:
        pass

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
    # Staff
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT
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

def save_broken_log(reporter_id, reporter_name, broken_by, photo_id):
    now = gmt5_now()
    date = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO broken_logs (reported_by_id, reported_by_name, broken_by, photo_file_id, date, time, group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (reporter_id, reporter_name, broken_by, photo_id, date, time_str, GROUP_ID))
    conn.commit()
    conn.close()
    return date, time_str

# ===== STAFF MANAGEMENT =====
async def add_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❌ Reply to a user to add them.")
        return
    user = msg.reply_to_message.from_user
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO staff (user_id, username, full_name) VALUES (?, ?, ?)",
                (user.id, user.username, user.full_name))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ {user.full_name} added to staff.")

async def rm_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❌ Reply to a user to remove them.")
        return
    user = msg.reply_to_message.from_user
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE user_id=?", (user.id,))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ {user.full_name} removed from staff.")

async def show_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name, username, user_id FROM staff")
    rows = cur.fetchall()
    conn.close()
    reply = "*👥 Staff List:*\n"
    for full_name, username, user_id in rows:
        reply += f"• {escape_markdown_v2(full_name)} (@{username if username else 'N/A'}) — `{user_id}`\n"
    reply += f"\n*Total Staff:* {len(rows)}"
    await msg.reply_text(reply, parse_mode=ParseMode.MARKDOWN_V2)

# ===== CLOCK-IN / CLOCK-OUT =====
async def clock_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.text or "at fr" not in msg.text.lower():
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
    hour_min = now.hour + now.minute / 60
    if hour_min < 12:
        shift = "morning"
        clock_out_time = dt_time(17, 0)
    else:
        shift = "evening"
        clock_out_time = dt_time(0, 30)
    clock_in_time = now.strftime("%H:%M")
    cur.execute("""
        INSERT OR REPLACE INTO attendance (staff_id, date, clock_in, clock_out, shift)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id, date_str, clock_in_time, clock_out_time.strftime("%H:%M"), shift))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ {user.full_name} clocked in at {clock_in_time} ({shift})")
    await context.bot.send_message(LOG_CHANNEL_ID, f"🕒 {user.full_name} clocked in at {clock_in_time} ({shift})")

# ===== BROKEN GLASS =====
async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != GROUP_ID or not msg.photo:
        return
    broken_by = extract_broken_by(msg.caption or "")
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
    date, time_str = save_broken_log(reporter.id, reporter.full_name, broken_by, photo_id)
    await msg.reply_text(f"✅ Report logged for {broken_by}")
    caption = (
        f"🧹 Broken Glass Report\n"
        f"Reported by: {reporter.full_name}\n"
        f"Broken by: {broken_by}\n"
        f"Date: {date}\n"
        f"Time: {time_str}"
    )
    await context.bot.send_photo(LOG_CHANNEL_ID, photo=photo_id, caption=caption)

# ===== TOTAL & RESET =====
async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    now = gmt5_now()
    month = now.strftime("%Y-%m")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*), COUNT(DISTINCT reported_by_id)
        FROM broken_logs
        WHERE date LIKE ?
    """, (f"{month}%",))
    total_broken, reporter_count = cur.fetchone()
    conn.close()
    await msg.reply_text(f"📊 {now.strftime('%B %Y')} Summary\nTotal broken: {total_broken}\nReported by staff: {reporter_count}")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    chat_member = await context.bot.get_chat_member(GROUP_ID, user_id)
    if chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        await msg.reply_text("❌ Only admins can reset history.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM broken_logs")
    conn.commit()
    conn.close()
    await msg.reply_text("✅ Broken glass history reset successfully.")
    await context.bot.send_message(LOG_CHANNEL_ID, f"🗑️ Broken glass history was reset by {msg.from_user.full_name} (@{msg.from_user.username})")

# ===== REPORT EXCEL =====
async def report_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    broken_df = pd.read_sql_query("SELECT * FROM broken_logs", conn)
    staff_df = pd.read_sql_query("SELECT * FROM staff", conn)
    attendance_df = pd.read_sql_query("SELECT * FROM attendance", conn)
    conn.close()
    with pd.ExcelWriter("frc_report.xlsx") as writer:
        broken_df.to_excel(writer, sheet_name="BrokenGlass", index=False)
        staff_df.to_excel(writer, sheet_name="Staff", index=False)
        attendance_df.to_excel(writer, sheet_name="Attendance", index=False)
    with open("frc_report.xlsx", "rb") as f:
        await msg.reply_document(f)

# ===== SHOW STAFF DETAIL WITH ABSENT/OFF =====
async def show_staff_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = None
    # Admin check
    chat_member = await context.bot.get_chat_member(GROUP_ID, msg.from_user.id)
    if chat_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
        await msg.reply_text("❌ Only admins can use this command.")
        return
    # Identify target staff
    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
    elif context.args:
        try:
            user_id = int(context.args[0])
            user = await context.bot.get_chat(user_id)
        except:
            username = context.args[0].lstrip("@")
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM staff WHERE username=?", (username,))
            row = cur.fetchone()
            conn.close()
            if row:
                user = await context.bot.get_chat(row[0])
    if not user:
        await msg.reply_text("❌ Staff not found.")
        return

    # Current month
    now = gmt5_now()
    year, month = now.year, now.month
    total_days = calendar.monthrange(year, month)[1]
    all_dates = [f"{year}-{month:02d}-{day:02d}" for day in range(1, total_days+1)]

    # Fetch attendance
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT date, clock_in, clock_out, shift
        FROM attendance
        WHERE staff_id=?
    """, (user.id,))
    rows = cur.fetchall()
    conn.close()
    attendance_map = {r[0]: r[1:] for r in rows}

    reply = f"*📋 Attendance for {escape_markdown_v2(user.full_name)} ({now.strftime('%B %Y')}):*\n"
    for date_str in all_dates:
        if date_str in attendance_map:
            clock_in, clock_out, shift = attendance_map[date_str]
            if shift == "morning":
                shift_start = dt_time(8, 30)
            else:
                shift_start = dt_time(17, 0)
            try:
                ci_hour, ci_min = map(int, clock_in.split(":"))
                clock_in_time = dt_time(ci_hour, ci_min)
                late_min = max(0, (clock_in_time.hour*60 + clock_in_time.minute) - (shift_start.hour*60 + shift_start.minute))
            except:
                late_min = 0
            reply += f"• {date_str} | {shift.capitalize()} | In: {clock_in} | Out: {clock_out} | Late: {late_min} min\n"
        else:
            day_of_week = datetime.strptime(date_str, "%Y-%m-%d").weekday()
            status = "Off" if day_of_week >= 5 else "Absent"
            reply += f"• {date_str} | {status}\n"

    await msg.reply_text(reply, parse_mode=ParseMode.MARKDOWN_V2)

# ===== MAIN =====
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.PHOTO, report_handler))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("add", add_staff))
    app.add_handler(CommandHandler("rm", rm_staff))
    app.add_handler(CommandHandler("staff", show_staff))
    app.add_handler(CommandHandler("report", report_excel))
    app.add_handler(CommandHandler("show", show_staff_detail))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(GROUP_ID), clock_in))
    print("✅ FRC Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
