# Jiraiya Bot Monitor 🤖📊

A Discord bot plus web dashboard that automatically reads service, kit and invoice messages (including screenshots, using OCR) from a Discord server and logs them into Google Sheets, so a small team can track work, transactions and inventory without manual data entry.

## ✨ Features

- **Discord bot** (`bot.py`): watches selected channels, extracts details from messages and image attachments, and logs them to Google Sheets
- **OCR** (`ocr.py`): reads text from uploaded screenshots with Tesseract
- **Automatic backfill**: scans channel history so older messages are logged too, and skips duplicates
- **Web dashboard** (`monitor_app.py`): Flask app with login and role-based access (Admin / Manager / Employee) for viewing employees, transactions, inventory and audit logs
- **Pricing helpers** (`kit_pricing.py`, `service_pricing.py`) to calculate totals
- **One-command start** (`start_all.py`): runs the bot and dashboard together and keeps the free Render instance awake

## 🛠️ Tech Stack

Python · discord.py · Flask · gspread (Google Sheets API) · Tesseract OCR · Render

## 🚀 Run it locally

```bash
git clone https://github.com/Amulpappu/jiraiya-bot-monitor.git
cd jiraiya-bot-monitor
pip install -r requirements.txt
```

Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) on your system, then create a `.env` file:

```env
DISCORD_TOKEN=your_discord_bot_token
GOOGLE_CREDENTIALS_FILE=credentials.json
EXISTING_SPREADSHEET_ID=your_google_sheet_id
SECRET_KEY=a_long_random_string
ADMIN_PASSWORD=choose_a_strong_password
MANAGER_PASSWORD=choose_a_strong_password
EMPLOYEE_PASSWORD=choose_a_strong_password
```

Put your Google service-account key in `credentials.json` (already ignored by git), then start everything:

```bash
python start_all.py
```

> ⚠️ Never commit `.env`, `credentials.json` or your bot token. Always set the passwords and `SECRET_KEY` above as environment variables in production (for example in Render's dashboard).

## 📁 Project Structure

```
bot.py              Discord bot: reads messages and images, logs to Sheets
monitor_app.py      Flask web dashboard with role-based login
sheets.py           Google Sheets helpers
ocr.py              Screenshot text extraction
database.py         Local JSON data store for the dashboard
start_all.py        Starts bot + dashboard together (used on Render)
templates/, static/ Dashboard HTML and assets
```

## 👤 Author

**Lohith K**, B.E. CSE (Cyber Security) student · [GitHub](https://github.com/Amulpappu) · [LinkedIn](https://www.linkedin.com/in/lohith-k-b1331a3a8/)
