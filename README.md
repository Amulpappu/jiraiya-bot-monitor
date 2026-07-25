# CODE Jiraiya Customs and Tunerz — Invoice Logging Bot

A free Discord bot for your FiveM mechanic RP server. It reads invoice
screenshots posted in your log channels, OCRs them with Tesseract, and
logs the data into Google Sheets — with an auto-updating dashboard.

## Project structure

```
jiraiya-bot/
├── bot.py       # Discord bot — channel detection, dedupe, message flow
├── ocr.py       # Image download, Tesseract OCR, invoice field parsing
├── sheets.py    # Google Sheets read/write, dashboard calculations
├── config.py    # All settings — token, channel map, file paths
└── requirements.txt
```

## 1. Install system dependencies

**Tesseract OCR is a separate program from the Python library** — you must
install it on your machine/server first.

- **Windows:** download the installer from
  https://github.com/UB-Mannheim/tesseract/wiki and install it. Note the
  install path (usually `C:\Program Files\Tesseract-OCR\tesseract.exe`).
- **Ubuntu/Debian:** `sudo apt update && sudo apt install tesseract-ocr`
- **macOS:** `brew install tesseract`

## 2. Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Create your Discord bot

1. Go to https://discord.com/developers/applications → **New Application**.
2. Go to the **Bot** tab → **Add Bot** → copy the **Token**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
4. Go to **OAuth2 → URL Generator**, check `bot`, and permissions:
   `Read Messages/View Channels`, `Send Messages`, `Add Reactions`,
   `Read Message History`. Use the generated URL to invite the bot to
   your server.
5. In your server, create these text channels (exact names matter):
   `service-logs`, `upgrade-logs`, `repair-kit-logs`, `cleaning-kit-logs`.

## 4. Set up Google Sheets access (free)

1. Go to https://console.cloud.google.com/ → create a project.
2. Enable **Google Sheets API** and **Google Drive API** for it.
3. Go to **APIs & Services → Credentials → Create Credentials → Service Account**.
4. Open the new service account → **Keys → Add Key → Create new key (JSON)**.
   This downloads a JSON file — rename it `credentials.json` and put it in
   the `jiraiya-bot/` folder.
5. Open `credentials.json` and copy the `client_email` value
   (looks like `xxxx@xxxx.iam.gserviceaccount.com`).
6. Create a new Google Sheet named exactly
   `CODE Jiraiya Customs and Tunerz - RP Logs` (or set `SPREADSHEET_NAME`
   below to whatever name you prefer) and **share it** with that
   service account email as an **Editor**.

   > The bot will auto-create the Service/Upgrades/RepairKits/CleaningKits/
   > Dashboard sheets and all headers the first time it runs — you don't
   > need to set up columns yourself.

## 5. Configure the bot

Easiest: set environment variables before running, e.g. on Linux/Mac:

```bash
export DISCORD_TOKEN="your-bot-token-here"
export GOOGLE_CREDENTIALS_FILE="credentials.json"
export SPREADSHEET_NAME="CODE Jiraiya Customs and Tunerz - RP Logs"
```

On Windows (PowerShell):

```powershell
$env:DISCORD_TOKEN="your-bot-token-here"
```

Or just edit the default values directly in `config.py`.

If Tesseract isn't on your system PATH (common on Windows), also set
`TESSERACT_CMD` in `config.py` to the full path of `tesseract.exe`.

## 6. Run the bot

```bash
python bot.py
```

You should see `Logged in as ...` and `Google Sheets ready...` in the console.

## How it works

- Post an invoice screenshot in `#service-logs`, `#upgrade-logs`,
  `#repair-kit-logs`, or `#cleaning-kit-logs`.
- The bot detects the channel, OCRs the image, extracts the relevant
  fields (Customer Name + Total Amount, or Customer Name + Quantity),
  and appends a row to the matching Google Sheet.
- It reacts ✅ on success, 🔁 if the exact same image was already
  processed before (duplicate), or replies with a ⚠️ warning if OCR
  couldn't read something clearly.
- The **Dashboard** sheet recalculates automatically after every new
  entry: daily/weekly/monthly totals per category, all-time totals, and
  an employee leaderboard ranked by invoices processed.
- OCR failures and missing-field warnings are logged to `ocr_errors.log`
  in the project folder for easy debugging.

## Tips for better OCR accuracy

- Ask staff to upload clear, non-blurry, non-cropped screenshots.
- The parser looks for lines like `Customer: John Doe`, `Total: $250`,
  `Quantity: 3`. If your server's invoice format uses different wording
  (e.g. "Client" instead of "Customer"), add more patterns to the
  `NAME_PATTERNS` / `AMOUNT_PATTERNS` / `QUANTITY_PATTERNS` lists at the
  top of `ocr.py`.

## Extending it

- Want a live-updating leaderboard command? Add a `!leaderboard` command
  in `bot.py` that calls `sheets._leaderboard()`.
- Want per-employee revenue (not just invoice count) on the leaderboard?
  Extend `sheets._leaderboard()` to sum `row[2]` per employee instead of
  just counting rows.
