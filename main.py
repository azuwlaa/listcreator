import re
import sqlite3
import asyncio
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -100111222333       # Group where staff reports broken glass
LOG_CHANNEL_ID = -100444555666 # Channel where logs are sent


# =====================================
# DATABASE SETUP
# =====================================
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
    conn.commit()
    conn.close()


def save_log(reported_by_id, reported_by_name, broken_by, photo_id, group_id):
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M:%S")

    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO broken_logs (
            reported_by_id, reported_by_name, broken_by,
            photo_file_id, date, time, group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        reported_by_id, reported_by_name, broken_by,
        photo_id, date, time, group_id
    ))
    conn.commit()
    conn.close()

    return date, time


# =====================================
# NAME EXTRACTION
# =====================================
def extract_broken_by(text: str):
    patterns = [
        r"broken\s*by\s*[:\-–=•]*\s*(.+)",
        r"broken[-\s]*by\s*(.+)",
    ]

    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name = re.sub(r"[\*\_\-\.\,\|\•]+$", "", name).strip()
            name = re.sub(r"[^\w\s\.\-']", "", name)
            return name[:40].strip()

    return None


# =====================================
# DELETE AFTER DELAY
# =====================================
async def delete_after_delay(msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass


# =====================================
# REPORT HANDLER
# =====================================
async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if not message or message.chat_id != GROUP_ID:
        return

    if not message.photo:
        return

    text = message.caption or ""
    broken_by = extract_broken_by(text)

    if not broken_by:
        return

    reporter = message.from_user
    photo_id = message.photo[-1].file_id

    date, time = save_log(
        reporter.id,
        reporter.full_name,
        broken_by,
        photo_id,
        GROUP_ID
    )

    confirm_msg = await message.reply_text(
        f"✅ Report logged for *{broken_by}*",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    asyncio.create_task(delete_after_delay(confirm_msg, 5))

    caption = (
        f"*🧹 Broken Glass Report*\n"
        f"• *Reported by:* [{reporter.full_name}](tg://user?id={reporter.id})\n"
        f"• *Broken by:* `{broken_by}`\n"
        f"• *Date:* {date}\n"
        f"• *Time:* {time}"
    )

    await context.bot.send_photo(
        chat_id=LOG_CHANNEL_ID,
        photo=photo_id,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN_V2
    )


# =====================================
# COMMAND /total
# =====================================
async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if message.chat_id != GROUP_ID:
        return

    now = datetime.now()
    month = now.strftime("%Y-%m")

    conn = sqlite3.connect("frc_bot.db")
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*), COUNT(DISTINCT reported_by_id)
        FROM broken_logs
        WHERE date LIKE ? AND group_id = ?
    """, (f"{month}%", GROUP_ID))

    total_broken, reporter_count = cur.fetchone()
    conn.close()

    reply = (
        f"*📊 {now.strftime('%B %Y')} Summary*\n"
        f"• *Total broken:* `{total_broken}`\n"
        f"• *Reported by staff:* `{reporter_count}`"
    )

    await message.reply_text(reply, parse_mode=ParseMode.MARKDOWN_V2)


# =====================================
# MAIN
# =====================================
def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.Chat(GROUP_ID) & filters.PHOTO,
            report_handler
        )
    )

    app.add_handler(CommandHandler("total", total))

    print("FRC Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
