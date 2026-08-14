import json
import base64
import datetime
import time
import os
from collections import Counter

import gspread
from google.oauth2.service_account import Credentials

import config

# India Standard Time is a fixed UTC+5:30 offset (no daylight saving time),
# so a simple fixed-offset timezone works perfectly and needs no extra
# system timezone database (avoids the Windows "tzdata" issue).
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def now_ist():
    """Current time in Indian Standard Time (used for all logging/timestamps)."""
    return datetime.datetime.now(IST)


# 12-hour IST format, e.g. "2026-07-22 02:26:00 PM"
TIMESTAMP_FORMAT = "%Y-%m-%d %I:%M:%S %p"
# Old 24-hour format kept only so rows already written to the sheet
# before this change can still be parsed by the dashboard.
LEGACY_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_ist_timestamp(raw: str):
    """Parses a timestamp string written by this bot, trying the current
    12-hour format first and falling back to the old 24-hour format for
    rows logged before this change.
    Also handles the dd/mm/YYYY HH:MM:SS format used by older cache entries."""
    for fmt in (
        TIMESTAMP_FORMAT,          # "%Y-%m-%d %I:%M:%S %p"
        LEGACY_TIMESTAMP_FORMAT,   # "%Y-%m-%d %H:%M:%S"
        "%d/%m/%Y %H:%M:%S",       # older cache: "04/08/2026 17:40:56"
        "%d/%m/%Y %I:%M:%S %p",    # older cache (12-hr): "04/08/2026 05:40:56 PM"
    ):
        try:
            return datetime.datetime.strptime(raw, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client = None
_spreadsheet = None

REVENUE_HEADERS = ["Timestamp", "Customer Name", "Total Amount", "Employee", "Message ID"]
QTY_HEADERS = ["Timestamp", "Customer Name", "Quantity", "Employee", "Message ID"]
SERVICE_HEADERS = ["Timestamp", "Customer Name", "Category", "Count", "Total Amount", "Employee", "Message ID"]
KIT_HEADERS = [
    "Timestamp", "Customer Name", "Repair Kit Qty", "Cleaning Kit Qty",
    "Discount %", "Total Amount", "Employee", "Message ID",
]
TRANSACTIONS_HEADERS = ["Date", "Amount", "Description", "Category", "Employee", "Message ID"]
USER_AUDIT_HEADERS = ["Timestamp (IST)", "Action", "User", "Role", "Details"]


DEFAULT_CREDENTIALS_B64 = "eyJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsICJwcm9qZWN0X2lkIjogImdlbnVpbmUtaGFiaXRhdC00OTIxMTYtazciLCAicHJpdmF0ZV9rZXlfaWQiOiAiODZhYWE4ODQxMWJmOTlmNzA3YTcyNTBkZDY0NzYwNjczM2M4M2E2YSIsICJwcml2YXRlX2tleSI6ICItLS0tLUJFR0lOIFBSSVZBVEUgS0VZLS0tLS1cbk1JSUV2Z0lCQURBTkJna3Foa2lHOXcwQkFRRUZBQVNDQktnd2dnU2tBZ0VBQW9JQkFRQ1lZSjFuT1pHanI3U1NcblVETzJGanRZdHQraVJiemgvN0VMWmF6K2hzR0tIMUJaRWtNMjM1ZjZDQWlORkZvL1ZqRTZDNnE1bCtVTS9HWXhcblRlaHUvaklhWnhMRlVueWlma2tGZ1ZqK0krcnB2UmdCNTFEd3FjSllXNk5lWEJxWmpsb3ZSWjYyU2l1em5JNmlcbk5ZbE1nVW16TDg4VlA1d2lMUTE4WTZEb0JMa0hDY2dCZTI2bzZtTHVKcmV6dGcvTTNzakFHQzR0RVhWaExDeFhcbndUWmplaTdUMzBsZm53d2txR2F0VUpNa3NScnYzQlBYSW9wV1UwUUVER2g5TFZOZGJ4d1NkcHVSWDJYQ09RNnBcbjhQbmM5Y1BweTMwNWlRN0VoaHFOY3UwdnowYkpDR1d0NC9lRTR6bDRTanI3d3BZNko3YjZyRVJGejZ1VzBObFlcblp6YWpPcENUQWdNQkFBRUNnZ0VBT1hES1JUeFZZMi83ME4vODdsb3BHd010QUYzcm13SXBPbE9reC9vQ2dVL1dcbm1RMGlXMUFrV1RPb0RZNnJpbzZ5VmVCS0JsWjFHTlVZck9OaWlGeTRoRzF3alFQUVNlenpGK2t2by9Ya095SjJcbkoxbU1rSHhkNzdMenZjRllvYVFnNlFzRWpsRWRja0xGSGU2eWlDMkFtOVNjNnJTazVkazM2VGtoVWZWZHpvSFRcbmdwbXc4dTJCM1VxOHNmRG9DcGFrTGZXQ1NWTzBTbFNXU1hUTlNTSnVEUWlsRnE3UkpuRWFBZ0ZmUldIOExvQmZcbmFTMktaUHJWWE9HZFErblVoRnlVZW9ONm5sSzdoMHhvMEZnb3oraWEwNWlLR2VVRVoySW1RQUllTkQvSTZZdzFcbkV4dUVpUVZCMFJ4Y2ZWanhoMFUwTjQ3OWhtenp2ZVBPTy9EVlpGN053UUtCZ1FESFkybmsvTGVDWXNzRW5waVlcbnJicFQ3Q3NTQlJwU0I0eFh0VGgyWitSMFZSL2NXR2pFdDQybWJ6dnhzb0t3VEpOZUpSQVNwdmhBZjNRTzRkbjdcbmlDc3BsRmRaeHhZTUJIVkZnYjNUalVSc0JhTUVwUHZ1Y09uc05yb0FTNG8zd2RZY3k3N044Qmx2TkVwbVJXdlFcbllGaTYvNCs2OGNUcWlDMitxSVYxMjF2MTRRS0JnUUREcEROdFZmV0xnM3lzSktHdGdoTUhoOXdubmxWd1VocERcbnpRb1FQVDVDTkh3SFJHbWdOUjFRN2duWE5VSkR5NFBXZWVOdFhuOFBmK3dHSE1mTTNOUXhGeGNtL3RIU3dHaG1cblV2OEw2Rk1oM0RvbTltYW9qaWExSzhtak02VVlOMHYvVnN3cUgvU3J2cko3RE82WGdpMXp2WHdncDVhTXdxcGxcbjQ0R0pMMTJzOHdLQmdRQ2U2eXE4MjN3OFRSZTVUOXNhWGVXVC9EbDcvRnMxSkZVRWx5a3ducS9rMVBBM0JMUkVcbmpuUTFRcFZKbUZrM3dXRDMrWnhzOFc0T29rZFRrVW5YaEhtNmcwUjRCd2tZZlBrbmREaGpoRVlUdnc1bXBrVXlcbmtBYXlRaEJRS2VVNWVhSjVneDlLTHVObTBndTJwZ0Evcm5zcVdJVXJvSVd0MU9wNCt3S2NwRUVRb1FLQmdBellcbmFDUUNvOWVnTDN4aC8xZVVGY25GeXRlekZxc0VTUU13b0R1R3VlTEE3Vy9RdHhxMHdoTUJQaFlxUWdxUGZ6MkNcbnpVTHVGR3VoRzQ4ZkxxTXQwS1RVZmttcUszNnA4WERlZkM1ODk1QmVsRmJna01iNlptSTQyTWxsWjY2YVd0d09cbkIrT3dLM0ZuV1BLcFc3VUk4QkVNWE8wTDg5K1VISG9LSVFRdjN2ZXZBb0dCQUtKWEhvMGNpRTZaRUpCWGM1NWZcbmtIdUd2d0hxZEIvSXdxcTg2eXVTNW9pSzNoU3ordHBqK1FKbzZQU2RVdG8yQnJzQmVFbnQzSmFUc2xKTVhKRjhcbmZTL3VkSCs2MDNyVEZLVDhyaW5DUlNpVmp6YklaR1l5ejFJNzlUNFQ3WEFTQUNtSFo5WDdzWkpWMW5tZ3lCcmNcblNsci9GS0tEU0JhMGpycU8xNHpBUlhaMFxuLS0tLS1FTkQgUFJJVkFURSBLRVktLS0tLVxuIiwgImNsaWVudF9lbWFpbCI6ICJqaXJhaXlhLWJvdEBnZW51aW5lLWhhYml0YXQtNDkyMTE2LWs3LmlhbS5nc2VydmljZWFjY291bnQuY29tIiwgImNsaWVudF9pZCI6ICIxMDI2MTg4MDc1MDgwNzkzMTYwNzAiLCAiYXV0aF91cmkiOiAiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tL28vb2F1dGgyL2F1dGgiLCAidG9rZW5fdXJpIjogImh0dHBzOi8vb2F1dGgyLmdvb2dsZWFwaXMuY29tL3Rva2VuIiwgImF1dGhfcHJvdmlkZXJfeDUwOV9jZXJ0X3VybCI6ICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9vYXV0aDIvdjEvY2VydHMiLCAiY2xpZW50X3g1MDlfY2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vcm9ib3QvdjEvbWV0YWRhdGEveDUwOS9qaXJhaXlhLWJvdCU0MGdlbnVpbmUtaGFiaXRhdC00OTIxMTYtazcuaWFtLmdzZXJ2aWNlYWNjb3VudC5jb20iLCAidW5pdmVyc2VfZG9tYWluIjogImdvb2dsZWFwaXMuY29tIn0="


def parse_service_account_info(raw_str: str) -> dict:
    """Parses a Google service account dict from a raw JSON string or Base64 string, fixing escaped newlines if needed."""
    if not raw_str or not isinstance(raw_str, str):
        return None
    s = raw_str.strip()
    if not s:
        return None

    info = None
    # 1. Try direct JSON parse
    try:
        info = json.loads(s)
    except Exception:
        pass

    # 2. Try Base64 decode
    if not isinstance(info, dict):
        try:
            decoded = base64.b64decode(s).decode("utf-8", errors="ignore").strip()
            info = json.loads(decoded)
        except Exception:
            pass

    if isinstance(info, dict) and info.get("type") == "service_account":
        if "private_key" in info and isinstance(info["private_key"], str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        return info

    return None


def ensure_credentials_file_exists():
    """Generates credentials.json from GOOGLE_CREDENTIALS_JSON or DEFAULT_CREDENTIALS_B64."""
    info = (
        parse_service_account_info(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        or parse_service_account_info(os.getenv("GOOGLE_CREDENTIALS_BASE64"))
        or parse_service_account_info(DEFAULT_CREDENTIALS_B64)
    )

    if info:
        try:
            with open(config.GOOGLE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
            return True
        except Exception:
            pass
    return False


def get_client():
    global _client
    if _client is None:
        info = None

        # Priority 1: GOOGLE_CREDENTIALS_JSON environment variable
        env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if env_json:
            info = parse_service_account_info(env_json)

        # Priority 2: GOOGLE_CREDENTIALS_BASE64 environment variable
        if not info:
            env_b64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
            if env_b64:
                info = parse_service_account_info(env_b64)

        # Priority 3: Local credentials.json file
        if not info and os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
            try:
                with open(config.GOOGLE_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    info = parse_service_account_info(f.read())
            except Exception as e:
                print(f"[Sheets Warning] Could not load {config.GOOGLE_CREDENTIALS_FILE}: {e}")

        # Priority 4: Built-in DEFAULT_CREDENTIALS_B64 fallback
        if not info:
            info = parse_service_account_info(DEFAULT_CREDENTIALS_B64)

        if not info:
            raise FileNotFoundError(
                f"Google Service Account credentials missing! "
                f"Please add GOOGLE_CREDENTIALS_JSON in Render Environment Variables."
            )

        # Always keep credentials.json in sync with active credentials
        try:
            with open(config.GOOGLE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
        except Exception:
            pass

        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


DEFAULT_SHEET_HEADERS = {
    "Service": SERVICE_HEADERS,
    "Upgrades": REVENUE_HEADERS,
    "Kits": KIT_HEADERS,
    "Transactions": TRANSACTIONS_HEADERS,
    "User_Audit_Logs": USER_AUDIT_HEADERS,
    "Audit Logs": USER_AUDIT_HEADERS,
    "Inventory": ["Item Name", "Stock", "Bought", "Restock Date", "Unit Price", "Total Value", "Last Updated"],
    "Expenses": ["Date", "Amount", "Employee", "Description"],
}


def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        client = get_client()
        if config.EXISTING_SPREADSHEET_ID:
            _spreadsheet = _with_retry(lambda: client.open_by_key(config.EXISTING_SPREADSHEET_ID))
        else:
            try:
                _spreadsheet = _with_retry(lambda: client.open(config.SPREADSHEET_NAME))
            except gspread.SpreadsheetNotFound:
                _spreadsheet = _with_retry(lambda: client.create(config.SPREADSHEET_NAME))
    return _spreadsheet


def _apply_transactions_dropdown(ws):
    """Restricts the Category column (D) to a dropdown of config.TRANSACTION_CATEGORIES,
    matching the categories used in-game, so entries stay consistent."""
    try:
        requests = [{
            "setDataValidation": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,  # skip header row
                    "startColumnIndex": 3,  # column D = Category
                    "endColumnIndex": 4,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": c} for c in config.TRANSACTION_CATEGORIES],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        }]
        ws.spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        # Dropdown is a nice-to-have; don't let a validation-API hiccup
        # block the sheet itself from being created/used.
        print(f"Warning: couldn't apply Transactions category dropdown: {e}")


def _ensure_sheet(sheet_name: str, headers: list = None):
    if headers is None:
        headers = DEFAULT_SHEET_HEADERS.get(sheet_name, ["Column 1", "Column 2", "Column 3", "Column 4"])
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = _with_retry(lambda: ss.add_worksheet(title=sheet_name, rows=2000, cols=max(len(headers), 8)))
        if headers:
            _with_retry(lambda: ws.append_row(headers))
        if sheet_name == "Transactions":
            _apply_transactions_dropdown(ws)
    return ws


def append_user_audit_log(user_name: str, action: str, details: str = "", role: str = "Visitor"):
    """Logs user/visitor/admin action to the User_Audit_Logs sheet and memory cache."""
    try:
        # Sanitize details to never expose raw passwords
        clean_details = str(details or "")
        for pwd in [os.getenv("ADMIN_PASSWORD", "admin2026"), os.getenv("MANAGER_PASSWORD", "manager8686"), os.getenv("EMPLOYEE_PASSWORD", "employee7878")]:
            if pwd and pwd in clean_details:
                clean_details = clean_details.replace(pwd, "******")

        ws = _ensure_sheet("User_Audit_Logs", USER_AUDIT_HEADERS)
        date_str = now_ist().strftime(TIMESTAMP_FORMAT)
        row = [date_str, str(action).strip(), str(user_name or "Visitor").strip(), str(role or "Visitor").strip(), clean_details]
        
        # Append to Google Sheet with retry
        if ws:
            try:
                _with_retry(lambda: ws.append_row(row))
            except Exception as e:
                print(f"[Audit Log Warning] Google Sheet append error: {e}")

        # Update cache immediately so web views see it without lag
        with _CACHE_LOCK:
            if "User_Audit_Logs" not in _LAST_KNOWN_ROWS:
                _LAST_KNOWN_ROWS["User_Audit_Logs"] = []
            _LAST_KNOWN_ROWS["User_Audit_Logs"].append(row)
            _LAST_KNOWN_ROWS["Audit Logs"] = _LAST_KNOWN_ROWS["User_Audit_Logs"]
            _save_disk_cache()
    except Exception as e:
        print(f"Warning: Failed to log audit event: {e}")


def setup_all_sheets():
    """Call once at startup — makes sure every sheet + the dashboard exist."""
    _ensure_sheet("Service", SERVICE_HEADERS)
    _ensure_sheet("Upgrades", REVENUE_HEADERS)
    _ensure_sheet("Kits", KIT_HEADERS)
    _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    _ensure_sheet("User_Audit_Logs", USER_AUDIT_HEADERS)
    _ensure_sheet("Inventory")

    # Seed initial audit log if empty
    try:
        rows = _all_rows("User_Audit_Logs")
        if not rows:
            append_user_audit_log("System", "SYSTEM_INIT", "Jiraiya Financial System initialized", "System")
    except Exception:
        pass

    _ensure_dashboard()
    update_dashboard()


def is_message_already_logged(sheet_name: str, message_id: str) -> bool:
    if not message_id:
        return False
    msg_id_str = str(message_id).strip()
    if not msg_id_str:
        return False
    rows = _all_rows(sheet_name)
    msg_col_map = {"Service": 6, "Kits": 7, "Upgrades": 4, "Transactions": 5}
    col = msg_col_map.get(sheet_name, -1)
    if col >= 0:
        for r in rows:
            if len(r) > col and str(r[col]).strip() == msg_id_str:
                return True
    return False


def append_transaction_entry(amount, description: str, category: str, employee: str = "", message_id: str = "", timestamp: str = None):
    """Logs one row to the consolidated Transactions ledger — Date, Amount,
    Description, Category, Employee Name, and Message ID (with deduplication)."""
    if message_id and is_message_already_logged("Transactions", message_id):
        return
    ws = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    date_str = timestamp or now_ist().strftime(TIMESTAMP_FORMAT)
    row = [date_str, amount, description or "", category, employee or "", message_id or ""]
    _with_retry(lambda: ws.append_row(row))
    with _CACHE_LOCK:
        if "Transactions" not in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Transactions"] = []
        _LAST_KNOWN_ROWS["Transactions"].append(row)
        _save_disk_cache()


def append_service_entry(customer: str, category: str, total, employee: str, message_id: str, count=None, timestamp: str = None):
    if is_message_already_logged("Service", message_id):
        return
    ws = _ensure_sheet("Service", SERVICE_HEADERS)
    ts = timestamp or now_ist().strftime(TIMESTAMP_FORMAT)
    row = [
        ts,
        customer or "Unknown",
        category or "Unspecified",
        count if count is not None else "",
        total,
        employee,
        message_id,
    ]
    _with_retry(lambda: ws.append_row(row))
    with _CACHE_LOCK:
        if "Service" not in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Service"] = []
        _LAST_KNOWN_ROWS["Service"].append(row)
        _save_disk_cache()


def append_kit_entry(customer: str, rk_qty: int, ck_qty: int, discount_pct: float,
                      total: float, employee: str, message_id: str, timestamp: str = None):
    """Logs a Repair Kit / Cleaning Kit sale with its quantity breakdown."""
    if is_message_already_logged("Kits", message_id):
        return
    ws = _ensure_sheet("Kits", KIT_HEADERS)
    ts = timestamp or now_ist().strftime(TIMESTAMP_FORMAT)
    disc_str = f"{discount_pct * 100:.0f}%" if discount_pct else "0%"
    row = [
        ts,
        customer or "Unknown",
        rk_qty,
        ck_qty,
        disc_str,
        total,
        employee,
        message_id,
    ]
    _with_retry(lambda: ws.append_row(row))
    with _CACHE_LOCK:
        if "Kits" not in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Kits"] = []
        _LAST_KNOWN_ROWS["Kits"].append(row)
        _save_disk_cache()


def append_entry(sheet_name: str, customer: str, value, employee: str, message_id: str, timestamp: str = None):
    if is_message_already_logged(sheet_name, message_id):
        return
    ws = _ensure_sheet(sheet_name, REVENUE_HEADERS)
    ts = timestamp or now_ist().strftime(TIMESTAMP_FORMAT)
    row = [ts, customer or "Unknown", value, employee, message_id]

    _with_retry(lambda: ws.append_row(row))
    with _CACHE_LOCK:
        if sheet_name not in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS[sheet_name] = []
        _LAST_KNOWN_ROWS[sheet_name].append(row)
        _save_disk_cache()

    try:
        update_dashboard()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"Dashboard update failed (invoice was still saved): {e}")


# ── Dashboard & Caching Engine ───────────────────────────

import os
import json
import threading

_ROWS_CACHE = {}
_LAST_KNOWN_ROWS = {}
_CACHE_LOCK = threading.Lock()
_LAST_BATCH_FETCH_TIME = 0
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_cache.json")


def _load_disk_cache():
    global _LAST_KNOWN_ROWS
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _LAST_KNOWN_ROWS = json.load(f)
        except Exception:
            pass


def _save_disk_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_LAST_KNOWN_ROWS, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


_load_disk_cache()


def _ensure_dashboard():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(config.DASHBOARD_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = _with_retry(lambda: ss.add_worksheet(title=config.DASHBOARD_SHEET_NAME, rows=200, cols=10))
    return ws


# Cache TTL: 45 seconds for batch requests to guarantee high responsiveness and stay well below the 60 req/min quota
_CACHE_TTL_SECONDS = 45

BATCH_WORKSHEET_RANGES = [
    "Service!A:G",
    "Kits!A:H",
    "Upgrades!A:E",
    "Transactions!A:F",
    "User_Audit_Logs!A:E",
    "Inventory!A:G",
    "Expenses!A:D",
]


def _with_retry(fn, attempts=5, base_delay=2):
    """Retries a Google Sheets API call on transient network or rate-limit (429) errors with exponential backoff."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            is_rate_limit = "429" in str(e) or "Quota exceeded" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_rate_limit and attempt < attempts - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"[Sheets Retry] Rate limit hit, backing off for {sleep_time}s (attempt {attempt + 1}/{attempts})...")
                time.sleep(sleep_time)
                continue
            if attempt < attempts - 1 and ("timed out" in str(e).lower() or "connection reset" in str(e).lower()):
                time.sleep(base_delay)
                continue
            raise


def _fetch_all_sheets_batch(force_refresh: bool = False):
    """Fetches ALL worksheet data in a SINGLE batch API request (values_batch_get)
    to completely eliminate 429 quota exhaustion and update memory/disk cache."""
    global _LAST_BATCH_FETCH_TIME
    now = time.time()

    with _CACHE_LOCK:
        if not force_refresh and (now - _LAST_BATCH_FETCH_TIME) < _CACHE_TTL_SECONDS and _LAST_KNOWN_ROWS:
            return _LAST_KNOWN_ROWS

    try:
        ss = get_spreadsheet()
        if ss:
            res = _with_retry(lambda: ss.values_batch_get(BATCH_WORKSHEET_RANGES))
            vr = res.get("valueRanges", []) if isinstance(res, dict) else []

            with _CACHE_LOCK:
                for v in vr:
                    rng = v.get("range", "")
                    sheet_name = rng.split("!")[0].replace("'", "").strip()
                    values = v.get("values", [])
                    data = [r for r in values[1:] if any(str(cell).strip() for cell in r)] if (values and len(values) > 1) else []
                    _LAST_KNOWN_ROWS[sheet_name] = data
                    _ROWS_CACHE[sheet_name] = (now, data)

                if "User_Audit_Logs" in _LAST_KNOWN_ROWS:
                    _LAST_KNOWN_ROWS["Audit Logs"] = _LAST_KNOWN_ROWS["User_Audit_Logs"]
                    _ROWS_CACHE["Audit Logs"] = _ROWS_CACHE.get("User_Audit_Logs", (now, _LAST_KNOWN_ROWS["User_Audit_Logs"]))

                _LAST_BATCH_FETCH_TIME = now
                _save_disk_cache()
                return _LAST_KNOWN_ROWS
    except Exception as e:
        print(f"[Sheets Batch Fetch Warning] Could not batch fetch from Google Sheets: {e}")

    with _CACHE_LOCK:
        return _LAST_KNOWN_ROWS


def _all_rows(ws_name: str, force_refresh: bool = False):
    """Returns all data rows (excluding header) from a given worksheet name.
    Uses unified batch cached data with graceful offline fallback."""
    target_ws = "User_Audit_Logs" if ws_name in ("User_Audit_Logs", "Audit Logs") else ws_name
    _fetch_all_sheets_batch(force_refresh=force_refresh)

    with _CACHE_LOCK:
        return list(_LAST_KNOWN_ROWS.get(target_ws, _LAST_KNOWN_ROWS.get(ws_name, [])))


def clear_rows_cache(ws_name=None):
    global _LAST_BATCH_FETCH_TIME
    with _CACHE_LOCK:
        _LAST_BATCH_FETCH_TIME = 0
        if ws_name and ws_name in _ROWS_CACHE:
            del _ROWS_CACHE[ws_name]


def _sum_numeric(values):
    total = 0.0
    for v in values:
        try:
            total += float(str(v).replace(",", "").replace("₹", "").strip())
        except (ValueError, TypeError):
            continue
    return total


def get_row_amount(sheet_name: str, row: list) -> float:
    """Extracts numerical total amount from a sheet row, dynamically handling legacy and current column layouts."""
    if not row or not isinstance(row, (list, tuple)):
        return 0.0

    val = 0.0
    if sheet_name == "Service":
        # 7-col: [Timestamp, Customer, Category, Count, Total Amount, Employee, Message ID] -> index 4
        # 6-col: [Timestamp, Customer, Category, Total Amount, Employee, Message ID] -> index 3
        if len(row) >= 7:
            val = row[4]
        elif len(row) >= 5:
            val = row[3]
        elif len(row) >= 3:
            val = row[2]
    elif sheet_name == "Kits":
        # 8-col: [Timestamp, Customer, RK Qty, CK Qty, Discount %, Total Amount, Employee, Message ID] -> index 5
        # 6/7-col legacy: [Timestamp, Customer, Details, Total Amount, Employee, Message ID] -> index 3
        if len(row) >= 8:
            val = row[5]
        elif len(row) in (6, 7):
            val = row[3]
        elif len(row) >= 3:
            val = row[2]
    elif sheet_name == "Upgrades":
        # 5-col: [Timestamp, Customer, Total Amount, Employee, Message ID] -> index 2
        if len(row) >= 3:
            val = row[2]
    else:
        if len(row) >= 3:
            val = row[2]

    try:
        return float(str(val).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return 0.0


def get_row_employee(sheet_name: str, row: list) -> str:
    """Extracts employee name from a sheet row, dynamically handling legacy and current column layouts,
    and normalizing Discord tags / decorative fonts to assigned employee names."""
    if not row or not isinstance(row, (list, tuple)):
        return ""

    raw_emp = ""
    if sheet_name == "Service":
        if len(row) >= 6:
            raw_emp = str(row[5]).strip()
        elif len(row) == 5:
            raw_emp = str(row[4]).strip()
    elif sheet_name == "Kits":
        if len(row) >= 7:
            raw_emp = str(row[6]).strip()
        elif len(row) == 6:
            raw_emp = str(row[5]).strip()
        elif len(row) >= 4:
            raw_emp = str(row[3]).strip()
    elif sheet_name in ("Upgrades", "Transactions"):
        if len(row) >= 4:
            raw_emp = str(row[3]).strip()

    return config.normalize_employee_name(raw_emp)


def _revenue_window(rows, sheet_name=None, days=None, today_only=False, this_month=False):
    """Sums amounts from a rows list within a date window."""
    now = now_ist()
    total = 0.0
    for row in rows:
        if not row:
            continue
        ts = parse_ist_timestamp(row[0])
        if ts is None:
            continue
        val = get_row_amount(sheet_name, row)

        include = False
        if today_only and ts.date() == now.date():
            include = True
        elif this_month and ts.year == now.year and ts.month == now.month:
            include = True
        elif days is not None and (now - ts).days <= days:
            include = True

        if include:
            total += val
    return total


def _leaderboard(rows_by_sheet):
    """Ranks employees by total number of invoices they've processed across all categories."""
    counter = Counter()
    for ws_name in ("Service", "Upgrades", "Kits"):
        for row in rows_by_sheet[ws_name]:
            emp = get_row_employee(ws_name, row)
            if emp and emp.lower() not in ("unknown", "high command", "high comman"):
                counter[emp] += 1
    return counter.most_common(config.LEADERBOARD_TOP_N)


def update_dashboard():
    ws = _ensure_dashboard()

    rows_by_sheet = {
        "Service": _all_rows("Service"),
        "Upgrades": _all_rows("Upgrades"),
        "Kits": _all_rows("Kits"),
    }

    service_total = sum(get_row_amount("Service", r) for r in rows_by_sheet["Service"])
    upgrade_total = sum(get_row_amount("Upgrades", r) for r in rows_by_sheet["Upgrades"])
    kits_total = sum(get_row_amount("Kits", r) for r in rows_by_sheet["Kits"])

    daily = {
        name: _revenue_window(rows_by_sheet[name], sheet_name=name, today_only=True)
        for name in rows_by_sheet
    }
    weekly = {
        name: _revenue_window(rows_by_sheet[name], sheet_name=name, days=7)
        for name in rows_by_sheet
    }
    monthly = {
        name: _revenue_window(rows_by_sheet[name], sheet_name=name, this_month=True)
        for name in rows_by_sheet
    }

    leaderboard = _leaderboard(rows_by_sheet)
    updated_at = now_ist().strftime(TIMESTAMP_FORMAT) + " IST"

    rows = [
        ["CODE Jiraiya Customs and Tunerz — Dashboard", ""],
        [f"Last updated: {updated_at}", ""],
        ["", ""],
        ["DAILY TOTALS", ""],
        ["Service Revenue", daily["Service"]],
        ["Upgrade Revenue", daily["Upgrades"]],
        ["Kits Revenue", daily["Kits"]],
        ["", ""],
        ["WEEKLY TOTALS (last 7 days)", ""],
        ["Service Revenue", weekly["Service"]],
        ["Upgrade Revenue", weekly["Upgrades"]],
        ["Kits Revenue", weekly["Kits"]],
        ["", ""],
        ["MONTHLY TOTALS (this month)", ""],
        ["Service Revenue", monthly["Service"]],
        ["Upgrade Revenue", monthly["Upgrades"]],
        ["Kits Revenue", monthly["Kits"]],
        ["", ""],
        ["ALL-TIME TOTALS", ""],
        ["Total Service Revenue", service_total],
        ["Total Upgrade Revenue", upgrade_total],
        ["Total Kits Revenue", kits_total],
        ["", ""],
        ["EMPLOYEE LEADERBOARD (invoices processed)", ""],
    ]
    for name, count in leaderboard:
        rows.append([name, count])

    _with_retry(lambda: ws.clear())
    _with_retry(lambda: ws.update("A1", rows))

