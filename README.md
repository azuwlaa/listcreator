# 🧹 FRC Bot — Telegram Broken Glass Logger

A modern Telegram bot that logs broken glass reports, extracts staff names automatically, and sends logs to a separate Telegram channel.  
Built using `python-telegram-bot v20`.

---

## 🚀 Features

✔ Detects messages with photos that contain “broken by <name>”  
✔ Works ONLY in your assigned Telegram group  
✔ Sends logs to a separate logging channel  
✔ Automatically extracts staff names (any format supported)  
✔ Confirmation message shown in group (auto deletes after 5 seconds)  
✔ `/total` command shows monthly statistics  
✔ Uses SQLite for storing logs  
✔ Clean MarkdownV2 formatting  

---

## 📦 Installation

Clone the repo:

```bash
git clone https://github.com/YOUR_USERNAME/frc-bot.git
cd frc-bot

