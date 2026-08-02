import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Read secrets from environment variables for Render deployment
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
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

# Pricing config updated per user specification: Civilian = ₹7,000, PD/EMS/TAXI/GOV = ₹10,000
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
# "combined_logs": True means channel handles both Services & Upgrades (e.g. 🌀┆aug-ʟᴏɢꜱ)
CHANNEL_CONFIG = {
    # Services & Upgrades Combined Channels
    "🌀┆aug-ʟᴏɢꜱ": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-logs": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-log": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "aug-upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "august-logs": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "august-services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "august-upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "july-logs": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "july-services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "july-upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "september-logs": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "september-services": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "september-upgrades": {"category": "Combined", "sheet_name": "Service", "combined_logs": True},
    "services": {"category": "Car Service", "sheet_name": "Service", "combined_logs": True},
    "service": {"category": "Car Service", "sheet_name": "Service", "combined_logs": True},
    "upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "combined_logs": True},
    "upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "combined_logs": True},

    # Kit Channels
    "🧰┆aug-ᴋɪᴛꜱ": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "aug-kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "august-kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "july-kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "september-kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "kits": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},
    "kit-logs": {"category": "Kit", "sheet_name": "Kits", "kit_channel": True},

    # VIP Claim Channels
    "💸┆vip-claim-logs": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-claim-logs": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-claim": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-claims": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},
    "vip-logs": {"category": "VIP Claim", "sheet_name": "VIP Claim", "vip_claim_channel": True},

    # Bill Claim / Expense Channels
    "💸┆ʙɪʟʟ_ᴄ🇱ᴀɪᴍ": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "💸┆ʙɪʟʟ_ᴄʟᴀɪᴍ": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill-claim": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill_claim": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill-claims": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "bill_claims": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
    "expenses": {"category": "Expense", "sheet_name": "Expenses", "expense_channel": True},
}

EMPLOYEE_MAPPING = {
    "@amulpappu": "AMULPAPPU",
    "amulpappu": "AMULPAPPU",
    "amul": "AMULPAPPU",
    "@blari": "Meenu Kutty",
    "blari": "Meenu Kutty",
    "meenu kutty": "Meenu Kutty",
    "meenu": "Meenu Kutty",
    "@eli": "Eli",
    "eli": "Eli",
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


def add_employee_mapping(name: str, tag: str) -> bool:
    clean_name = name.strip()
    clean_tag = "@" + tag.strip().lstrip("@")
    if clean_name and clean_tag:
        EMPLOYEE_MAPPING[clean_tag.lower()] = clean_name
        EMPLOYEE_MAPPING[clean_tag.lstrip("@").lower()] = clean_name
        return True
    return False
