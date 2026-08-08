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
    Supports channels with Unicode, emojis, month names (august/aug), and special Discord formatting."""
    if not channel_name:
        return None, None

    # Exact match check
    if channel_name in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[channel_name], channel_name

    c_low = str(channel_name).lower().strip()
    if c_low in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[c_low], c_low

    # Strip unicode decorators, emojis, special chars -> plain ASCII words only
    import unicodedata
    try:
        # Normalize unicode small caps / decorative letters to ASCII equivalent
        normalized = unicodedata.normalize("NFKD", c_low)
        normalized = "".join(c for c in normalized if ord(c) < 128)
    except Exception:
        normalized = c_low

    clean = normalized.replace("┆", " ").replace("-", " ").replace("_", " ").replace(".", " ").strip()
    # Remove emoji characters
    import re
    clean = re.sub(r"[^\x00-\x7F]+", " ", clean).strip()
    clean = re.sub(r"\s+", " ", clean)

    # Kit channel detection (also check raw unicode small-cap letters: ᴋɪᴛꜱ)
    if any(k in clean for k in ("kit", "kits", "rk", "ck", "repair", "cleaning")):
        return _KIT_CONFIG, "Kits"
    # Raw unicode check for small-cap "ᴋɪᴛ" (Discord decorative font)
    if "\u1d0b\u026a\u1d1b" in c_low or "kit" in c_low:
        return _KIT_CONFIG, "Kits"

    # Upgrade channel detection (check upgrades before generic service/logs)
    if any(k in clean for k in ("upgrade", "upgrades", "mod", "mods", "car up")):
        return _UPGRADE_CONFIG, "Upgrades"

    # Service channel detection
    if any(k in clean for k in ("service", "services", "civ", "pd", "ems", "gov", "taxi")):
        return _SERVICE_CONFIG, "Service"

    # Aug-logs / monthly combined logs channel -> treat as service
    if any(k in clean for k in ("log", "logs", "aug", "august", "sept", "oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul")):
        return _SERVICE_CONFIG, "Service"

    return None, None


EMPLOYEE_DISCORD_MAP = {
    "candy__07": "Sandy",
    "jackzmf": "Sylas",
    "niveein_bex": "Benny",
    "saron_jenish1923": "Lara",
    "jarad0007": "Maria",
    "demonwnl_1024": "Abrar",
    "tamilazhagan": "Arivu",
    "astroeligaming": "Eli",
    "sandy.432": "Alexia",
    "amul_pappu": "Amul",
    "shuraim_ms": "Mitchell",
    "jeeva_rj_": "Lissa",
    "suriya2810": "Nesuko",
    "evoff9595": "Mikasa",
    "tomcatgaming": "TomCat",
    "balajisubramanian": "Mathew",
    "jiyana_shree": "Jiyana Shree",
    "tbkevil_44": "EVE",
    "blari": "Meenu Kutty",
}

EMPLOYEE_NAME_FALLBACKS = {
    "sandy": "Sandy",
    "sylas": "Sylas",
    "benny": "Benny",
    "lara": "Lara",
    "maria": "Maria",
    "abrar": "Abrar",
    "arivu": "Arivu",
    "eli": "Eli",
    "alexia": "Alexia",
    "amul": "Amul",
    "mitchell": "Mitchell",
    "lissa": "Lissa",
    "nesuko": "Nesuko",
    "mikasa": "Mikasa",
    "tomcat": "TomCat",
    "mathew": "Mathew",
    "jiyana": "Jiyana Shree",
    "jiraya": "Jiyana Shree",
    "fisher": "Jiyana Shree",
    "eve": "EVE",
    "meenu": "Meenu Kutty",
    "questless": "QuestlessSoul",
}


def normalize_employee_name(raw: str) -> str:
    """Normalizes Discord tags, handles Unicode decorative fonts, and maps to assigned employee names."""
    if not raw or not str(raw).strip():
        return "Unknown"
    import unicodedata
    raw_str = str(raw).strip()
    clean_tag = raw_str.lower().lstrip("@")
    if clean_tag in EMPLOYEE_DISCORD_MAP:
        return EMPLOYEE_DISCORD_MAP[clean_tag]

    norm = unicodedata.normalize("NFKD", raw_str)
    ascii_str = norm.encode("ascii", "ignore").decode("ascii").strip()
    low = (ascii_str + " " + raw_str).lower()

    for key, mapped_name in EMPLOYEE_NAME_FALLBACKS.items():
        if key in low:
            return mapped_name

    if "mohammed" in low or "fart" in low:
        return "Unknown"

    return ascii_str.title() if ascii_str else raw_str


def resolve_employee_from_author(author) -> str:
    """Extracts clean display name or nickname from Discord Author, mapped to assigned employee name."""
    if not author:
        return "Unknown"
    # Check Discord tag / username handle first (e.g. @amul_pappu, @jiyana_shree)
    username = getattr(author, "name", None)
    if username:
        mapped = normalize_employee_name(username)
        if mapped != username and mapped != "Unknown":
            return mapped

    display_name = getattr(author, "display_name", None) or getattr(author, "name", None) or "Unknown"
    return normalize_employee_name(display_name)

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
    # ── Service channels ───────────────────────────────────
    "services": _SERVICE_CONFIG,
    "service": _SERVICE_CONFIG,
    "service-logs": _SERVICE_CONFIG,
    "service logs": _SERVICE_CONFIG,

    # August combined logs (threads inside here are service/upgrade)
    "\U0001f300\u2546aug-\u029f\u1d0f\u0262\ua731": _SERVICE_CONFIG,  # 🌀┆aug-ʟᴏɢꜱ
    "aug-logs": _SERVICE_CONFIG,
    "aug logs": _SERVICE_CONFIG,
    "august-logs": _SERVICE_CONFIG,
    "august logs": _SERVICE_CONFIG,

    # ── Upgrade channels ───────────────────────────────────
    "car upgrade": _UPGRADE_CONFIG,
    "car-upgrade": _UPGRADE_CONFIG,
    "upgrade-logs": _UPGRADE_CONFIG,
    "upgrades": _UPGRADE_CONFIG,

    # ── Kit channels ───────────────────────────────────────
    "\U0001f9f0\u2546aug-\u1d0b\u026a\u1d1b\ua731": _KIT_CONFIG,  # 🧰┆aug-ᴋɪᴛꜱ
    "\U0001f9f0\u2546july-\u1d0b\u026a\u1d1b\ua731": _KIT_CONFIG,  # 🧰┆july-ᴋɪᴛꜱ
    "aug-kits": _KIT_CONFIG,
    "aug kits": _KIT_CONFIG,
    "august-kits": _KIT_CONFIG,
    "august kits": _KIT_CONFIG,
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
    "civilian": 7000,
    "govt": 10000,
    "ems": 10000,
    "pd": 10000,
    "gov": 10000,
    "taxi": 10000,
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
