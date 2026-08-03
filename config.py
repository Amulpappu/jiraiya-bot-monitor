import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Read secrets from environment variables for Render deployment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SPREADSHEET_ID = os.getenv("EXISTING_SPREADSHEET_ID", "1Tz2YxzNO0ibySgftxNGltulxx0o7NLx3HCLbk-RpNRM")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Write GOOGLE_CREDENTIALS_JSON from environment variable to credentials.json if present
g_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if g_json and not os.path.exists(CREDENTIALS_FILE):
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            f.write(g_json)
    except Exception:
        pass

DASHBOARD_SHEET_NAME = "Dashboard"

SERVICE_PRICES = {
    "civilian": 7000.0,
    "govt": 10000.0,
    "pd": 10000.0,
    "ems": 10000.0,
    "taxi": 10000.0,
    "government": 10000.0,
    "car service": 7000.0,
}

KIT_PRICES = {
    "rk": 1000.0,
    "ck": 900.0,
}

PROCESSED_HASHES_FILE = "processed_images.json"
IGNORE_DUPLICATE_IMAGES = True

# Channel mapping configuration
CHANNEL_CONFIG = {
    # Services & Upgrades Combined Channels & Threads
    "🌀┆aug-ʟᴏɢꜱ": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-logs": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-log": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "service": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "upgrade": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},

    # Kit Channels
    "🧰┆aug-ᴋɪᴛꜱ": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "aug-kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "kit-logs": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},

    # VIP Claim Channels
    "💸┆vip-claim-logs": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-claim-logs": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-claim": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},

    # Bill Claim / Expense Channels
    "💸┆ʙɪ🇱🇱_ᴄ🇱ᴀɪᴍ": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "💸┆ʙɪ🇱🇱_ᴄʟᴀɪᴍ": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "💸┆ʙɪʟʟ_ᴄʟᴀɪᴍ": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill-claim": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill_claim": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
}

# Employee Name <-> Discord Tag Mapping (from User Image 2)
EMPLOYEE_MAPPING = {
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
    ".tomcatgaming": "TomCat",
    "tomcatgaming": "TomCat",
    "balajisubramanian": "Mathew",
    "jiyana_shree": "Jiyana Shree",
    "tbkevil_44": "EVE",
    "blari": "Meenu Kutty",

    # Alternate display name keys
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
    "jiyana shree": "Jiyana Shree",
    "eve": "EVE",
    "meenu kutty": "Meenu Kutty",
}


def normalize_channel_name(name: str) -> str:
    if not name:
        return ""
    clean = re.sub(r"[^\w\s\-┆]", "", name).strip().lower()
    return clean


def get_channel_config(channel_name: str):
    if not channel_name:
        return None, None
    raw_lower = channel_name.strip().lower()
    if raw_lower in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[raw_lower], raw_lower

    norm = normalize_channel_name(channel_name)
    if norm in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[norm], norm

    for key, cfg in CHANNEL_CONFIG.items():
        key_norm = normalize_channel_name(key)
        if key_norm and (key_norm in norm or norm in key_norm):
            return cfg, key

    return None, None


def resolve_employee_from_author(author) -> str:
    """Resolves Discord author to exact Employee Name using Image 2 mapping table."""
    if not author:
        return "Unknown"

    if isinstance(author, str):
        clean = author.strip().lstrip("@").lower()
        if clean in EMPLOYEE_MAPPING:
            return EMPLOYEE_MAPPING[clean]
        return author.strip().lstrip("@")

    uname = str(getattr(author, "name", "")).strip().lstrip("@").lower()
    dname = str(getattr(author, "display_name", "")).strip().lstrip("@").lower()
    gname = str(getattr(author, "global_name", "") or "").strip().lstrip("@").lower()

    for key in (uname, dname, gname):
        if key in EMPLOYEE_MAPPING:
            return EMPLOYEE_MAPPING[key]

    fallback = getattr(author, "display_name", None) or getattr(author, "name", "Unknown")
    return str(fallback).strip().lstrip("@")
