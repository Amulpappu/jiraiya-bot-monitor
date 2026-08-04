import os

# ── Discord ──────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ── Google Sheets ────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Code69-Employee Tracker")

# If you already have an existing Google Sheet you want the bot to use,
# paste its ID here (found in the sheet's URL, the long string of letters
# between "/d/" and "/edit"), e.g.:
# https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
# Leave as None to have the bot open-by-name (or create one) instead.
EXISTING_SPREADSHEET_ID = os.getenv("EXISTING_SPREADSHEET_ID", os.getenv("Code69-Employee Tracker", "1Tz2YxzNO0ibySgftxNGltulxx0o7NLx3HCLbk-RpNRM"))


def get_channel_config(channel_name: str):
    """Dynamically resolves channel configuration based on exact or fuzzy channel name matching.
    Supports current month channels (e.g. august-kits, august-service, august-upgrades) and custom names."""
    if not channel_name:
        return None, None

    # Exact match check
    if channel_name in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[channel_name], channel_name

    c_low = str(channel_name).lower().strip()
    if c_low in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[c_low], c_low

    # Normalized name check
    clean = c_low.replace("┆", " ").replace("-", " ").replace("_", " ").strip()

    if any(k in clean for k in ("kit", "kits", "rk", "ck", "repair", "cleaning")):
        return _KIT_CONFIG, "Kits"

    if any(k in clean for k in ("service", "services", "civ", "pd", "ems", "gov", "taxi")):
        return _SERVICE_CONFIG, "Service"

    if any(k in clean for k in ("upgrade", "upgrades", "mod", "mods")):
        return _UPGRADE_CONFIG, "Upgrades"

    return None, None


def resolve_employee_from_author(author) -> str:
    """Extracts clean display name or nickname from Discord Author."""
    if not author:
        return "Unknown"
    name = getattr(author, "display_name", None) or getattr(author, "name", None) or "Unknown"
    import re
    name_clean = re.sub(r"[^\w\s\.-]", "", name).strip()
    return name_clean or name

# ── Tesseract OCR ────────────────────────────────────────
# On Windows, uncomment and point this at your tesseract.exe install path.
# On Linux/Mac (after `apt install tesseract-ocr` or `brew install tesseract`),
# leave this as None — pytesseract will find it automatically.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
# Example Windows value:
# TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Local storage ────────────────────────────────────────
PROCESSED_HASHES_FILE = "processed_images.json"
ERROR_LOG_FILE = "ocr_errors.log"

# ── Channel → Category mapping ──────────────────────────
# "fields" tells the OCR parser what data to look for in that channel's invoices.
_SERVICE_CONFIG = {
    "category": "Car Service",
    "sheet_name": "Service",
    "fields": ["customer", "amount"],
    "category_channel": True,  # triggers text-based civ/pd/ems/gov/taxi category parsing
}

_UPGRADE_CONFIG = {
    "category": "Car Upgrade",
    "sheet_name": "Upgrades",
    "fields": ["customer", "amount"],
}

_KIT_CONFIG = {
    "category": "Kit",
    "sheet_name": "Kits",
    "fields": ["customer", "amount"],
    "kit_channel": True,  # triggers text-based RK/CK quantity parsing instead of OCR amount
}

CHANNEL_CONFIG = {
    "services": _SERVICE_CONFIG,
    "service": _SERVICE_CONFIG,
    "service-logs": _SERVICE_CONFIG,
    "service logs": _SERVICE_CONFIG,

    "car upgrade": _UPGRADE_CONFIG,
    "car-upgrade": _UPGRADE_CONFIG,
    "upgrade-logs": _UPGRADE_CONFIG,
    "upgrades": _UPGRADE_CONFIG,

    "🧰┆july-ᴋɪᴛꜱ": _KIT_CONFIG,
    "july-kits": _KIT_CONFIG,
    "july kits": _KIT_CONFIG,
    "kits": _KIT_CONFIG,
    "repair-kit-logs": _KIT_CONFIG,
    "cleaning-kit-logs": _KIT_CONFIG,
}

# ── Transactions ledger (consolidated log, matches in-game dropdown) ────
TRANSACTION_CATEGORIES = [
    "Repair Kit",
    "Cleaning Kit",
    "Car UpGrade",
    "Service-Civilian",
    "Service-Government",
    "Order",
]

# ── Service pricing (flat rate by customer category) ─────
SERVICE_PRICES = {
    "civilian": 3000,
    "ems": 5000,
    "pd": 5000,
    "gov": 5000,
    "taxi": 5000,
}

# ── Kit pricing & discount ───────────────────────────────
# Repair Kit (rk) and Cleaning Kit (ck) unit prices.
KIT_PRICES = {
    "rk": 1000,
    "ck": 900,
}

# Discount is based on COMBINED quantity (rk qty + ck qty in one bill),
# applied to both kit types at the same %. (min, max, discount_fraction)
KIT_DISCOUNT_BRACKETS = [
    (700, 900, 0.10),
    (500, 699, 0.08),
    (300, 499, 0.05),
    (100, 299, 0.03),
]

DASHBOARD_SHEET_NAME = "Dashboard"
LEADERBOARD_TOP_N = 10

# ── Duplicate handling ───────────────────────────────────
# True  = ignore repeated invoice screenshots (won't log or count them again)
# False = log and count every invoice every time, even exact repeats
IGNORE_DUPLICATE_IMAGES = False
