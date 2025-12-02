import re
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
import io
import pandas as pd
from PIL import Image

from telegram import Update, InputFile
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304
LOG_CHANNEL_ID = -1003449720539
DB_FILE = "frc_bot.db"

# Telegram IDs of bot admins (for private chat access)
BOT_ADMINS = [123456789, 987654321]  # replace with actual admin IDs

# ---------------- UTILITIES ----------------
def gmt5_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5)

def escape_markdown(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

async def delete_after(msg, delay_s: int):
    await asyncio.sleep(delay_s)
    try:
        await msg.delete()
    except:
        pass

async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        mem = await context.bot.get_chat_member(GROUP_ID, user_id)
        return mem.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except:
        return False

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT,
            date TEXT,
            clock_in TEXT,
            clock_out TEXT,
            status TEXT,
            late_minutes INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS glass_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reported_by_id INTEGER,
            reported_by_name TEXT,
            broken_by TEXT,
            photo_file_id TEXT,
            date TEXT,
            time TEXT,
            group_id INTEGER,
            message_link TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date)")
    conn.commit()
    conn.close()

# ---------------- SHIFT & LATE ----------------
def determine_shift_from_time(dt: datetime):
    if 6 <= dt.hour < 11:
        return "Morning"
    elif 15 <= dt.hour < 21:
        return "Evening"
    else:
        return None

def clock_out_for_shift(shift: str):
    return "17:00" if shift == "Morning" else "00:30"

def compute_late_minutes(dt: datetime, shift: str) -> int:
    ref = dt.replace(hour=8, minute=30) if shift=="Morning" else dt.replace(hour=17, minute=0)
    delta = dt - ref
    return max(0, int(delta.total_seconds() // 60))

# ---------------- STAFF MANAGEMENT ----------------
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    if not await is_user_admin(context, user_id):
        await msg.reply_text("❌ Only group admins can add staff.")
        return
    if msg.reply_to_message:
        target_id = msg.reply_to_message.from_user.id
        name = " ".join(context.args) if context.args else (msg.reply_to_message.from_user.full_name or str(target_id))
    else:
        if not context.args or len(context.args)<2:
            await msg.reply_text("Usage: /add <id> <Full Name> or reply to user with /add <Full Name>")
            return
        try:
            target_id = int(context.args[0])
        except:
            await msg.reply_text("Invalid user ID.")
            return
        name = " ".join(context.args[1:])
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO staff (user_id, full_name) VALUES (?, ?)", (target_id, name))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ Staff added: *{escape_markdown(name)}*", parse_mode=ParseMode.MARKDOWN)

async def cmd_rm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    if not await is_user_admin(context, user_id):
        await msg.reply_text("❌ Only group admins can remove staff.")
        return
    if msg.reply_to_message:
        target_id = msg.reply_to_message.from_user.id
    elif context.args:
        try:
            target_id = int(context.args[0])
        except:
            await msg.reply_text("Invalid user ID.")
            return
    else:
        await msg.reply_text("Reply or provide ID.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    await msg.reply_text("✅ Staff removed.")

async def cmd_staff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id, full_name FROM staff ORDER BY full_name COLLATE NOCASE")
    rows = cur.fetchall()
    conn.close()
    lines = [f"• **[{escape_markdown(r[1])}](tg://user?id={r[0]})**" for r in rows]
    text = f"*Staff list ({len(rows)} total):*\n" + ("\n".join(lines) if lines else "No staff yet.")
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ---------------- CLOCK ----------------
async def handle_clock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if not (msg.text.strip().lower()=="at fr" or msg.text.strip().startswith("/clock")):
        return
    user = msg.from_user
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM staff WHERE user_id=?", (user.id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    full_name = row[0]
    today = gmt5_now().strftime("%Y-%m-%d")
    cur.execute("SELECT id FROM attendance WHERE user_id=? AND date=? AND status='Clocked In'", (user.id, today))
    if cur.fetchone():
        conn.close()
        await msg.reply_text("❌ Already clocked in today.")
        return
    now = gmt5_now()
    shift = determine_shift_from_time(now)
    if not shift:
        await msg.reply_text("❌ Cannot clock in at this time.")
        conn.close()
        return
    late_minutes = compute_late_minutes(now, shift)
    clock_in_str = now.strftime("%H:%M")
    clock_out_str = clock_out_for_shift(shift)
    cur.execute("""
        INSERT INTO attendance (user_id, full_name, date, clock_in, clock_out, status, late_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user.id, full_name, today, clock_in_str, clock_out_str, "Clocked In", late_minutes))
    conn.commit()
    conn.close()
    link = getattr(msg, "link", None)
    if not link:
        try:
            link = f"https://t.me/c/{str(GROUP_ID)[4:]}/{msg.message_id}"
        except:
            link = "N/A"
    caption = (
        "#clock\n"
        f"• Staff Name: [{escape_markdown(full_name)}](tg://user?id={user.id})\n"
        f"• Date: {today}\n"
        f"• Time: {clock_in_str}\n"
        f"• Message link: [Go to message]({link})"
    )
    await context.bot.send_message(LOG_CHANNEL_ID, caption, parse_mode=ParseMode.MARKDOWN)
    await msg.reply_text(f"✅ {full_name} clocked in at {clock_in_str} ({shift})")

# ---------------- SICK / OFF ----------------
async def cmd_sick_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    cmd = msg.text.split()[0].lstrip("/").lower()
    status = "Sick" if cmd=="sick" else "Off" if cmd=="off" else None
    if not status:
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM staff WHERE user_id=?", (user.id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await msg.reply_text("❌ Not in staff list.")
        return
    full_name = row[0]
    today = gmt5_now().strftime("%Y-%m-%d")
    cur.execute("""
        INSERT INTO attendance (user_id, full_name, date, clock_in, clock_out, status, late_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user.id, full_name, today, None, None, status, 0))
    conn.commit()
    conn.close()
    await msg.reply_text(f"✅ Marked {status} for {full_name} on {today}")

# ---------------- SHOW ----------------
async def cmd_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caller = msg.from_user
    if not await is_user_admin(context, caller.id):
        await msg.reply_text("❌ Only group admins can use /show.")
        return
    if msg.reply_to_message:
        staff_id = msg.reply_to_message.from_user.id
    elif context.args:
        try:
            staff_id = int(context.args[0])
        except:
            await msg.reply_text("Provide valid ID or reply.")
            return
    else:
        await msg.reply_text("Reply or use `/show <id>`.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM staff WHERE user_id=?", (staff_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        await msg.reply_text("Staff not found.")
        return
    full_name = row[0]
    month_prefix = gmt5_now().strftime("%Y-%m")
    cur.execute("""
        SELECT status, COUNT(*) FROM attendance
        WHERE user_id=? AND date LIKE ?
        GROUP BY status
    """, (staff_id, f"{month_prefix}%"))
    data = cur.fetchall()
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(late_minutes),0) FROM attendance
        WHERE user_id=? AND date LIKE ? AND late_minutes>0
    """, (staff_id, f"{month_prefix}%"))
    late_days_count, late_minutes_sum = cur.fetchone() or (0,0)
    late_hours = round(late_minutes_sum / 60, 2)
    conn.close()
    total_clocked = absent = sick = off = 0
    for status,count in data:
        if status=="Clocked In": total_clocked=count
        elif status=="Absent": absent=count
        elif status=="Sick": sick=count
        elif status=="Off": off=count
    text = (
        f"*Attendance Summary for {escape_markdown(full_name)}*\n"
        f"• Total Days Clocked: {total_clocked}\n"
        f"• Absent Days: {absent}\n"
        f"• Late Days: {late_days_count} (Total Late Hours: {late_hours})\n"
        f"• Sick Days: {sick}\n"
        f"• Off Days: {off}"
    )
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ---------------- STATUS ----------------
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    today = gmt5_now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT full_name, clock_in, status FROM attendance
        WHERE date=? AND status IN ('Clocked In','Sick','Off')
        ORDER BY clock_in
    """, (today,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await msg.reply_text("No one has clocked in today.")
        return
    lines = []
    for full_name, clock_in, status in rows:
        if status=="Clocked In":
            lines.append(f"• **{escape_markdown(full_name)}** - `{clock_in}`")
        else:
            lines.append(f"• **{escape_markdown(full_name)}** - {status}")
    text = f"*Today's Clock-ins ({today}):*\n" + "\n".join(lines)
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ---------------- GLASS REPORT ----------------
def extract_broken_by_from_text(text:str):
    if not text: return None
    match = re.search(r"broken\s*by\s*[:\-–=•]*\s*([^\n]+)", text, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        return re.sub(r"[\*\_\-\.\,\|\•]+$", "", name).strip()[:80]
    return None

async def handle_glass_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != GROUP_ID or not msg.photo: return
    broken_by = extract_broken_by_from_text(msg.caption or "")
    if not broken_by: return
    reporter = msg.from_user
    photo_file_id = msg.photo[-1].file_id
    try:
        file = await context.bot.get_file(photo_file_id)
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        Image.open(bio).verify()
    except: return
    now = gmt5_now()
    date,time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    link = getattr(msg, "link", None) or f"https://t.me/c/{str(GROUP_ID)[4:]}/{msg.message_id}"
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO glass_logs (reported_by_id, reported_by_name, broken_by, photo_file_id, date, time, group_id, message_link)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,(reporter.id, reporter.full_name, broken_by, photo_file_id, date, time, GROUP_ID, link))
    conn.commit()
    conn.close()
    conf = await msg.reply_text(f"Report logged for *{escape_markdown(broken_by)}*", parse_mode=ParseMode.MARKDOWN)
    asyncio.create_task(delete_after(conf,5))
    caption = (
        "#update\n"
        f"• Reported by: [{escape_markdown(reporter.full_name)}](tg://user?id={reporter.id})\n"
        f"• Broken by: `{escape_markdown(broken_by)}`\n"
        f"• Date: {date}\n"
        f"• Time: {time}\n"
        f"• Message link: [Go to message]({link})"
    )
    await context.bot.send_photo(LOG_CHANNEL_ID, photo=photo_file_id, caption=caption, parse_mode=ParseMode.MARKDOWN)

# ---------------- TOTAL ----------------
async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    month_prefix = gmt5_now().strftime("%Y-%m")
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*), COUNT(DISTINCT reported_by_id)
        FROM glass_logs
        WHERE date LIKE ? AND group_id=?
    """,(f"{month_prefix}%",GROUP_ID))
    total_broken, reporter_count = cur.fetchone()
    cur.execute("""
        SELECT reported_by_name, COUNT(*) FROM glass_logs
        WHERE date LIKE ? AND group_id=?
        GROUP BY reported_by_id,reported_by_name ORDER BY COUNT(*) DESC
    """,(f"{month_prefix}%",GROUP_ID))
    rows = cur.fetchall()
    conn.close()
    breakdown = "\n".join([f"• {escape_markdown(r[0])}: {r[1]} report{'s' if r[1]>1 else ''}" for r in rows])
    text = (
        f"*📊 Glass Break Summary - {gmt5_now().strftime('%B %Y')}*\n"
        f"• Total broken: {total_broken}\n"
        f"• Reported by staff: {reporter_count}\n\n"
        f"*Reporter Breakdown:*\n{breakdown if breakdown else 'No reports this month.'}"
    )
    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ---------------- REPORT ATTENDANCE ----------------
async def cmd_report_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("""
        SELECT a.date,a.full_name,a.status,a.clock_in,a.clock_out,a.late_minutes,a.user_id
        FROM attendance a LEFT JOIN staff s ON a.user_id=s.user_id
    """,conn)
    conn.close()
    if df.empty:
        await msg.reply_text("No attendance data.")
        return
    bio = io.BytesIO()
    bio.name = f"Attendance_{gmt5_now().strftime('%Y-%m')}.xlsx"
    df.to_excel(bio,index=False)
    bio.seek(0)
    await msg.reply_document(document=InputFile(bio),filename=bio.name)

# ---------------- RESET ----------------
async def cmd_reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await is_user_admin(context, msg.from_user.id):
        await msg.reply_text("❌ Only group admins can reset history.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    cur.execute("DELETE FROM glass_logs")
    conn.commit()
    conn.close()
    await msg.reply_text("✅ All attendance and glass logs reset.")

async def cmd_reset_clock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await is_user_admin(context, msg.from_user.id):
        await msg.reply_text("❌ Only group admins can reset clock-in data.")
        return
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance WHERE status='Clocked In'")
    conn.commit()
    conn.close()
    await msg.reply_text("✅ Clock-in data reset.")

# ---------------- BACKUP ----------------
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not await is_user_admin(context, msg.from_user.id):
        await msg.reply_text("❌ Only admins can backup data.")
        return
    conn = sqlite3.connect(DB_FILE)
    attendance_df = pd.read_sql_query("SELECT * FROM attendance",conn)
    glass_df = pd.read_sql_query("SELECT * FROM glass_logs",conn)
    conn.close()
    bio = io.BytesIO()
    bio.name = f"FRC_Backup_{gmt5_now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
    with pd.ExcelWriter(bio, engine='xlsxwriter') as writer:
        attendance_df.to_excel(writer,sheet_name='Attendance',index=False)
        glass_df.to_excel(writer,sheet_name='GlassLogs',index=False)
    bio.seek(0)
    await context.bot.send_document(LOG_CHANNEL_ID, document=InputFile(bio), filename=bio.name)
    await msg.reply_text("✅ Backup sent to log channel.")

# ---------------- PRIVATE CHAT RESTRICTION ----------------
async def private_message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.chat.type=='private' and msg.from_user.id not in BOT_ADMINS:
        return

# ---------------- BOOT ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # Staff
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("rm", cmd_rm))
    app.add_handler(CommandHandler("staff", cmd_staff))
    # Clock
    app.add_handler(CommandHandler("clock", handle_clock))
    app.add_handler(MessageHandler(filters.Regex(re.compile(r"^at fr$",re.IGNORECASE)) & filters.Chat(GROUP_ID), handle_clock))
    # Sick/Off
    app.add_handler(CommandHandler("sick", cmd_sick_off))
    app.add_handler(CommandHandler("off", cmd_sick_off))
    # Show / Status
    app.add_handler(CommandHandler("show", cmd_show))
    app.add_handler(CommandHandler("status", cmd_status))
    # Glass reporting
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.PHOTO, handle_glass_report))
    app.add_handler(CommandHandler("total", cmd_total))
    # Attendance report
    app.add_handler(CommandHandler("report", cmd_report_attendance))
    # Reset
    app.add_handler(CommandHandler("reset", cmd_reset_all))
    app.add_handler(CommandHandler("reset_clock", cmd_reset_clock))
    # Backup
    app.add_handler(CommandHandler("backup", cmd_backup))
    # Private chat restriction
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE, private_message_filter))
    print("✅ FRC Bot running (full final version).")
    app.run_polling()

if __name__=="__main__":
    main()
