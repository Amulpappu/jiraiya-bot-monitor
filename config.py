import os

# ── Discord ──────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
    if os.path.exists("token.txt"):
        try:
            with open("token.txt", "r", encoding="utf-8") as f:
                DISCORD_TOKEN = f.read().strip()
        except Exception:
            pass
    elif os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DISCORD_TOKEN="):
                        DISCORD_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    if not DISCORD_TOKEN:
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", os.path.join(APP_DIR, "credentials.json"))
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Code69-Employee Tracker")

# If you already have an existing Google Sheet you want the bot to use,
# paste its ID here (found in the sheet's URL, the long string of letters
# between "/d/" and "/edit"), e.g.:
# https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
# Leave as None to have the bot open-by-name (or create one) instead.
EXISTING_SPREADSHEET_ID = os.getenv("Code69-Employee Tracker", None)

# ── Tesseract OCR ───────────────────────────────────────
def find_tesseract_cmd():
    if os.getenv("TESSERACT_CMD"):
        return os.getenv("TESSERACT_CMD")
    if os.name == "posix":
        for p in ("/usr/bin/tesseract", "/usr/local/bin/tesseract", "tesseract"):
            if os.path.exists(p) or p == "tesseract":
                return p
    else:
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return "tesseract"

TESSERACT_CMD = find_tesseract_cmd()

# ── Local storage ────────────────────────────────────────
PROCESSED_HASHES_FILE = "processed_images.json"
ERROR_LOG_FILE = "ocr_errors.log"

# ── Category Filters ──────────────────────────────────────
# Categories/folders in Discord to strictly ignore (case-insensitive substring match)
EXCLUDED_CATEGORIES = ["mj fuels", "mj_fuels", "mjfuels", "no usage", "no_usage", "nousage"]

# ── Channel → Category mapping ──────────────────────────
# "fields" tells the OCR parser what data to look for in that channel's invoices.
CHANNEL_CONFIG = {
    "services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "service-log": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "service-logs": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "car-service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "car-services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "july-services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "august-services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "september-services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "july-service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "august-service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "september-service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆services": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆service": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆service-log": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆service-logs": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆ꜱᴇʀᴠɪᴄᴇꜱ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆ꜱᴇʀᴠɪᴄᴇ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆july-ꜱᴇʀᴠɪᴄᴇꜱ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆august-ꜱᴇʀᴠɪᴄᴇꜱ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "🛠️┆september-ꜱᴇʀᴠɪᴄᴇꜱ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "ꜱᴇʀᴠɪᴄᴇꜱ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},
    "ꜱᴇʀᴠɪᴄᴇ": {"category": "Car Service", "sheet_name": "Service", "fields": ["customer", "amount"], "category_channel": True},

    "upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "upgrade-log": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "upgrade-logs": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "car-upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "car-upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "july-upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "august-upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "september-upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "july-upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "august-upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "september-upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆upgrades": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆upgrade": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆upgrade-log": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆upgrade-logs": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆ᴜᴘɢʀᴀᴅᴇꜱ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆ᴜᴘɢʀᴀᴅᴇ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆july-ᴜᴘɢʀᴀᴅᴇꜱ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆august-ᴜᴘɢʀᴀᴅᴇꜱ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🔧┆september-ᴜᴘɢʀᴀᴅᴇꜱ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "ᴜᴘɢʀᴀᴅᴇꜱ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "ᴜᴘɢʀᴀᴅᴇ": {"category": "Car Upgrade", "sheet_name": "Upgrades", "fields": ["customer", "amount"]},
    "🧰┆july-ᴋɪᴛꜱ": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "july-kits": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "🧰┆august-ᴋɪᴛꜱ": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "august-kits": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "🧰┆september-ᴋɪᴛꜱ": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "september-kits": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "🧰┆ᴋɪᴛꜱ": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "kits": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "kit-logs": {
        "category": "Kit",
        "sheet_name": "Kits",
        "fields": ["customer", "amount"],
        "kit_channel": True,
    },
    "💸┆bill_claim": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "bill_claim": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "bill-claim": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "💸┆bill-claim": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "💸┆ʙɪʟʟ_ᴄʟᴀɪᴍ": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "💸┆ʙɪʟʟ-ᴄʟᴀɪᴍ": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "ʙɪʟʟ_ᴄʟᴀɪᴍ": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "ʙɪʟʟ-ᴄʟᴀɪᴍ": {
        "category": "Order",
        "sheet_name": "Expenses",
        "fields": ["amount"],
        "expense_channel": True,
    },
    "💸┆vip-claim-logs": {
        "category": "VIP Claim",
        "sheet_name": "VIP Claim",
        "fields": ["customer", "amount"],
        "vip_claim_channel": True,
    },
    "vip-claim-logs": {
        "category": "VIP Claim",
        "sheet_name": "VIP Claim",
        "fields": ["customer", "amount"],
        "vip_claim_channel": True,
    },
    "vip-claim": {
        "category": "VIP Claim",
        "sheet_name": "VIP Claim",
        "fields": ["customer", "amount"],
        "vip_claim_channel": True,
    },
}

SMALL_CAPS_MAP = str.maketrans({
    'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ꜰ': 'f', 'ɢ': 'g',
    'ʜ': 'h', 'ɪ': 'i', 'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l', 'ᴍ': 'm', 'ɴ': 'n',
    'ᴏ': 'o', 'ᴘ': 'p', 'ꞯ': 'q', 'ʀ': 'r', 'ꜱ': 's', 'ᴛ': 't', 'ᴜ': 'u',
    'ᴠ': 'v', 'ᴡ': 'w', 'x': 'x', 'ʏ': 'y', 'ᴢ': 'z'
})


def normalize_channel_name(name: str) -> str:
    """Translates unicode small capitals to standard ASCII lowercase."""
    if not name:
        return ""
    return name.translate(SMALL_CAPS_MAP).lower().strip()


def get_channel_config(channel_name: str):
    """
    Finds matching configuration for a given Discord channel or thread name.
    Returns (cfg_dict, canonical_key) or (None, None).
    """
    if not channel_name:
        return None, None

    raw_lower = channel_name.lower().strip()
    if raw_lower in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[raw_lower], raw_lower

    norm = normalize_channel_name(channel_name)
    if norm in CHANNEL_CONFIG:
        return CHANNEL_CONFIG[norm], norm

    n_clean = "".join(c for c in norm if c.isalnum())

    # Strictly ignore non-invoice system channels
    if n_clean in ("log", "logs", "serverlogs", "serverlogo", "auditlogs", "botlogs", "modlogs", "joinlogs", "rules", "announcements", "info", "general", "chat"):
        return None, None

    # Direct keyword pattern matching for maximum compatibility
    if "vip" in n_clean:
        return CHANNEL_CONFIG["vip-claim-logs"], "vip-claim-logs"
    if any(k in n_clean for k in ("billclaim", "bill_claim", "bill-claim", "expense", "expenses", "mechbill")):
        return CHANNEL_CONFIG["bill_claim"], "bill_claim"
    if "kit" in n_clean:
        return CHANNEL_CONFIG["july-kits"], "july-kits"
    if any(s in n_clean for s in ("service", "services", "carservice", "servicelog", "servicelogs")):
        return CHANNEL_CONFIG["services"], "services"
    if any(u in n_clean for u in ("upgrade", "upgrades", "carupgrade", "upgradelog", "upgradelogs")):
        return CHANNEL_CONFIG["upgrades"], "upgrades"

    # Fuzzy/clean match for configured keys
    for key, cfg in CHANNEL_CONFIG.items():
        key_norm = normalize_channel_name(key)
        k_clean = "".join(c for c in key_norm if c.isalnum())
        if k_clean and n_clean and len(n_clean) >= 4 and (k_clean == n_clean or k_clean in n_clean):
            return cfg, key

    return None, None


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

# ── Discord Reactions ──────────────────────────────────────
# True  = add emoji reactions (✅, ❓, 🔁) to Discord messages
# False = do NOT add emoji reactions (prevents mobile notification spam)
ENABLE_DISCORD_REACTIONS = False

# ── Duplicate handling ───────────────────────────────────
# True  = ignore repeated invoice screenshots (won't log or count them again)
# False = log and count every invoice every time, even exact repeats
IGNORE_DUPLICATE_IMAGES = False

# ── Employee Discord Tag → Name Mapping ──────────────────
# Maps Discord username/tag to in-game Employee Name.
# Add new employees here as they are hired! (case-insensitive, with/without @)
EMPLOYEE_MAPPING = {
    "candy__07": "Sandy",
    "candy__007": "Sandy",
    "jackzmf": "Sylas",
    "niveein_bex": "Benny",
    "niveein_benx": "Benny",
    "saron_jenish1923": "Lara",
    "saron_jenish": "Lara",
    "jarad007": "Maria",
    "jarad0007": "Maria",
    "demonwnl_1024": "Abrar",
    "tamilazhagan": "Arivu",
    "mrarivu": "Arivu",
    "astroeligaming": "Eli",
    "sandy.432": "Alexia",
    "amul_pappu": "Amul",
    "amulpappu": "Amul",
    "shuraim_ms": "Mitchell",
    "shuraim": "Mitchell",
    "petemitchell": "Mitchell",
    "jeeva_rj_": "Lissa",
    "jeeva_rj": "Lissa",
    "suriya2810": "Nesuko",
    "evoff9595": "Mikasa",
    ".tomcatgaming": "TomCat",
    "tomcatgaming": "TomCat",
    "balajisubramanian": "Mathew",
    "jiyana_shree": "Jiyana Shree",
    "tbkevil_44": "EVE",
    "redeye_49": "Redeye",
    "mohammedfarhaan": "Robb",
    "mohammed": "Robb",
    "rajyt300k": "Raj",
    "blari": "Meenu Kutty",
}


def add_employee_mapping(name: str, tag: str) -> bool:
    """Dynamically updates EMPLOYEE_MAPPING in runtime and appends to config.py source file."""
    if not name or not tag:
        return False
    clean_tag = tag.strip().lstrip("@").lower()
    clean_name = name.strip()
    EMPLOYEE_MAPPING[clean_tag] = clean_name

    try:
        config_path = os.path.abspath(__file__)
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Insert before closing brace of EMPLOYEE_MAPPING
        new_lines = []
        in_map = False
        inserted = False
        for line in lines:
            if "EMPLOYEE_MAPPING = {" in line:
                in_map = True
            if in_map and "}" in line and not inserted:
                new_lines.append(f'    "{clean_tag}": "{clean_name}",\n')
                inserted = True
            new_lines.append(line)

        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass
    return True


def delete_employee_mapping(name: str) -> bool:
    """Removes an employee from runtime EMPLOYEE_MAPPING dictionary and config.py source file."""
    if not name:
        return False
    clean_name = name.strip()
    keys_to_del = [k for k, v in EMPLOYEE_MAPPING.items() if v.lower() == clean_name.lower()]
    for k in keys_to_del:
        del EMPLOYEE_MAPPING[k]

    try:
        config_path = os.path.abspath(__file__)
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if any(f'"{k}"' in line for k in keys_to_del):
                continue
            new_lines.append(line)

        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass
    return True

