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
from PIL import Image
import io

# ===== CONFIGURATION =====
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -1001956620304   # Group where reports happen
LOG_CHANNEL_ID = -1003449720539   # Channel where logs go

# ===== DATABASE =====
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

def save_log(reporter_id, reporter_name, broken_by, photo_id, group_id):
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
    """, (reporter_id, reporter_name, broken_by, photo_id, date, time, group_id))
    conn.commit()
    conn.close()
    return date, time

# ===== HELPER FUNCTIONS =====
def extract_broken_by(text: str):
    """Extract 'broken by' name from text, robustly"""
    if not text:
        return None
    text = text.lower().replace("\n", " ").strip()
    match = re.search(r"broken\s*by\s*[:\-–=•]*\s*([^\n]+)", text, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        name = re.sub(r"[\*\_\-\.\,\|\•]+$", "", name).strip()
        name = re.sub(r"[^\w\s\.\-']", "", name)
        return name[:50].strip()
    return None

def escape_markdown_v2(text: str) -> str:
    """Fully escape Telegram MarkdownV2 special characters"""
    if not text:
        return ""
    # Escape backslash first
    text = text.replace("\\", "\\\\")
    # Escape all other MarkdownV2 special characters
    return re.sub(r'([_\*\[\]\(\)\~\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

async def delete_after(msg, delay_s: int):
    await asyncio.sleep(delay_s)
    try:
        await msg.delete()
    except:
        pass

# ===== HANDLERS =====
async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or message.chat_id != GROUP_ID or not message.photo:
        return

    text = message.caption or ""
    broken_by = extract_broken_by(text)
    if not broken_by:
        return

    # Validate photo using Pillow
    try:
        file = await context.bot.get_file(message.photo[-1].file_id)
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)
        img = Image.open(bio)
        img.verify()
    except Exception as e:
        print(f"Invalid image: {e}")
        return

    reporter = message.from_user
    photo_id = message.photo[-1].file_id
    date, time = save_log(reporter.id, reporter.full_name, broken_by, photo_id, GROUP_ID)

    # Confirmation message (auto-delete)
    confirm = await message.reply_text(
        f"✅ Report logged for *{escape_markdown_v2(broken_by)}*",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    asyncio.create_task(delete_after(confirm, 5))

    # Send log to channel
    caption = (
        f"*🧹 Broken Glass Report*\n"
        f"• *Reported by:* [{escape_markdown_v2(reporter.full_name)}](tg://user?id={reporter.id})\n"
        f"• *Broken by:* `{escape_markdown_v2(broken_by)}`\n"
        f"• *Date:* {date}\n"
        f"• *Time:* {time}"
    )
    await context.bot.send_photo(
        chat_id=LOG_CHANNEL_ID,
        photo=photo_id,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN_V2
    )

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
    await message.reply_text(
        f"*📊 {now.strftime('%B %Y')} Summary*\n"
        f"• *Total broken:* `{total_broken}`\n"
        f"• *Reported by staff:* `{reporter_count}`",
        parse_mode=ParseMode.MARKDOWN_V2
    )

# ===== MAIN =====
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Report handler
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.PHOTO, report_handler))
    app.add_handler(CommandHandler("total", total))

    print("✅ FRC Bot running on PTB v21+")
    app.run_polling()

if __name__ == "__main__":
    main()
