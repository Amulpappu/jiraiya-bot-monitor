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
TRANSACTIONS_HEADERS = ["Date", "Amount", "Description", "Category"]
USER_AUDIT_HEADERS = ["Timestamp (IST)", "Action", "User", "Role", "Details"]


DEFAULT_CREDENTIALS_B64 = (
    "ew0KICAidHlwZSI6ICJzZXJ2aWNlX2FjY291bnQiLA0KICAicHJvamVjdF9pZCI6ICJnZW51"
    "aW5lLWhhYml0YXQtNDkyMTE2LWs3IiwNCiAgInByaXZhdGVfa2V5X2lkIjogImNkZmRhNjli"
    "NTkxYzg0ZDMwOWM4YjU0ZmM4NDk1ZGEzZjFlNDAzYzgiLA0KICAicHJpdmF0ZV9rZXkiOiAi"
    "LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tXG5NSUlFdlFJQkFEQU5CZ2txaGtpRzl3MEJB"
    "UUVGQUFTQ0JLY3dnZ1NqQWdFQUFvSUJBUURTaGxZaEFKZFVNVDZJXG5Yam92RmRhcTc1U1hM"
    "Wm9CTVFFU3plSWtQcU5XS25mVDlKVXZzdGoxSFNzYmN4SDFsMzZrVE5rNzN1cy80Si9HXG5q"
    "b0xBeXJSK0NiR0VXVmxXQlo5ZlpTVTJxNHRCNE00QkRTQW9iaWFZWEpmcDJQMVowVDBFeGZW"
    "YTZSeEtrTlFnXG5NWG1US1U4d2F0RWxuWDl4SEY5SVJqSkRBdFQyQUE2ZmZtWldzOTdPaUhB"
    "WGlITjJ5YzVHWFdxWnV2ZWtyMDRBXG5rZkFjaFdaWFJWZDBMTFAxTE1iUTUxc1hKZHpxbkNV"
    "ckdjeGp5aUJBc1hxdVozL3RxeFNIUTRiTklRdTNBMzVJXG50SkpVd2NoMm8rN3MvU2NSNTVF"
    "VFBkaHBXbHAvVUsxSmFIbDJkV2tPQTRSTTVPVGtGVk91NUpFSUNJaE1WY0c0XG5DczZQOTJR"
    "eEFnTUJBQUVDZ2dFQUNwNlY1T1dJbkttOHdhaCtKeDZqQk4yZnVWWUdxeGwzbUVVY0s0K2cw"
    "ZUdEXG55S1J4YTVYcUdidlp6ekZKWmtIeGRKUi9UMFMyQ1hONVg4elR4ZW1idS9GZGUrTjli"
    "UWhNMHlVeElMNDd3TE9ZXG5OS2VldUFkaGFVVmZjTjkrSFN3ZnQ3aE1JWDA1alAzY0EzRTNk"
    "Si9NYzdEcHNxdnNrQzQ2RkxWY3h2SlRQNExuXG5EVWlubzN5NitwL3ZRQTZDa2dvUnV0SGZH"
    "TmxYbFlSS0U3Nm1qQk9jRFRaUDdBeVhzcTJwZC9jUURiTUdNbjZxXG55QWU2c2Z0aWtBZ0NH"
    "WlBuT0lQNE1teE5VT1N3RWlVb1J0TnJneVZsVDJDWEpZVFRVa3FPcDRmcGRKd2ZjaUx6XG5l"
    "eCtMOGVjblZTUVJOOTd6VndaSjllVFd2YjBHUjV2TmJKSTgrdERmd1FLQmdRRHNFQnNXeEs2"
    "V0RhZ3Y2aVdVXG5mSUtwVC90KzM2VUZ2TkI2Z0hJTzZxNWFabjl0M1BXV0g3a1psL2IrZGZ1"
    "djNDTE1PekRrYXZTMFl0NDB0b240XG5OQ3JjL1N6UjZYK2ZQOGhRQU5aRGpZVWFQR2gxT0NL"
    "YURBZUFkU2dteEpZVUQ0bXhqZzkxbnlBd29Zd05rbVFLXG43U2gzV0JDOExVdjAraTQxTTZt"
    "SkVUQnFJUUtCZ1FEa1RoS0tGNzhsdmt4VnFyOW92Ri8yTlUxNVZZU1paVDRUXG53dmw2Rm9D"
    "Q2NhamZYclF3U3B0Y28zRlFXRlFSZDhMbTFpUTV1R3NpWjE1dHdVVjZJL3VLS2c1ZER6cFJZ"
    "cFlEXG5CZmFUNHZBWkQ1bk5kMml1WHNzRUJIRmNzVXUvbU9Bd29EYVpKNjAvd2VyZDZOMnA3"
    "UXE3eUIvOXFJSGJWbWcrXG41N05yWUtWWUVRS0JnRFVBek1SSTl4WlVESzV0ZVhDa29FWFo0"
    "cE16TGY5aXpNQ2t0SGRxOUNqeUdLeVhUMEVjXG44RmV4eWxDS0N5L2VVcVhlcUhTeEd5Nmhn"
    "RmovbjJ6dWNhMWEzMFJtbERReWd3eUxrNUJwWnpoajFlUno3VGovXG5lSE84V242UjUweXJ6"
    "SFBrZk00aEkzNG4xNlY0ZUNRSDZlMGFCZS9xajhKNnBnTm1EU3ZzZ3gxaEFvR0FkS2ZMXG40"
    "MUhVOHVVMHZnVThQcmthVTRUUzdHK2RESUJsNHRVYWdwNmkxWVJjSko2UWRhaDVrREZYZ2hW"
    "UUI0anBSdWdlXG5wSHV1Q210RkhkSEd2VzFMWjBLc0NqTHd1b3NrV2JFZldGdDZFV1FlVTVW"
    "eklMNEJBREdBOXpzRW1JYjE3d0srXG5ReTI1NGIwbFZIUmJaeXRlODZxRFppcEhDQnN6c3dq"
    "VGJjZDVWUEVDZ1lFQXF2eUp0aDZxY1VSRm1DTm1qWHFTXG5qdUZHTk9JUlNMUTBoOUZ1dk4r"
    "TExmc1krMkVtaXErbDlkS25rZFVKc3pYTUVNvXZweG10aFU4ZFdvV2NQOGJyXG5KYUlveWll"
    "ZzcrTkNjVDZEaDhENEd1T2xyNms2SEtmNmgyV1RJODZSdmh5bi9vWk5kbEJIZ250czJTRkxw"
    "YjdUXG56Vlg5MHBaWDhWTjdQY2tORVFPbVh2UT1cbi0tLS0tRU5EIFBSSVZBVEUgS0VZLS0t"
    "LS1cbiIsDQogICJjbGllbnRfZW1haWwiOiAiamlyYWl5YS1ib3RAZ2VudWluZS1oYWJpdGF0"
    "LTQ5MjExNi1rNy5pYW0uZ3NlcnZpY2VhY2NvdW50LmNvbSIsDQogICJjbGllbnRfaWQiOiAi"
    "MTAyNjE4ODA3NTA4MDc5MzE2MDcwIiwNCiAgImF1dGhfdXJpIjogImh0dHBzOi8vYWNjb3Vu"
    "dHMuZ29vZ2xlLmNvbS9vL29hdXRoMi9hdXRoIiwNCiAgInRva2VuX3VyaSI6ICJodHRwczov"
    "L29hdXRoMi5nb29nbGVhcGlzLmNvbS90b2tlbiIsDQogICJhdXRoX3Byb3ZpZGVyX3g1MDlf"
    "Y2VydF91cmwiOiAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vb2F1dGgyL3YxL2NlcnRz"
    "IiwNCiAgImNsaWVudF94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMu"
    "Y29tL3JvYm90L3YxL21ldGFkYXRhL3g1MDkvamlyYWl5YS1ib3QlNDBnZW51aW5lLWhhYml0"
    "YXQtNDkyMTE2LWs3LmlhbS5nc2VydmljZWFjY291bnQuY29tIiwNCiAgInVuaXZlcnNlX2Rv"
    "bWFpbiI6ICJnb29nbGVhcGlzLmNvbSINCn0NCg=="
)


def ensure_credentials_file_exists():
    """Generates credentials.json from GOOGLE_CREDENTIALS_JSON or DEFAULT_CREDENTIALS_B64 if missing on disk."""
    if os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        return True

    env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if env_json:
        try:
            info = json.loads(env_json)
            with open(config.GOOGLE_CREDENTIALS_FILE, "w") as f:
                json.dump(info, f, indent=2)
            return True
        except Exception:
            pass

    env_b64 = os.getenv("GOOGLE_CREDENTIALS_BASE64", DEFAULT_CREDENTIALS_B64)
    if env_b64:
        try:
            raw = base64.b64decode(env_b64.strip()).decode("utf-8", errors="ignore")
            info = json.loads(raw)
            with open(config.GOOGLE_CREDENTIALS_FILE, "w") as f:
                json.dump(info, f, indent=2)
            return True
        except Exception:
            pass

    return False


def get_client():
    global _client
    if _client is None:
        ensure_credentials_file_exists()

        creds = None
        # Option 1: GOOGLE_CREDENTIALS_JSON environment variable
        env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if env_json:
            try:
                info = json.loads(env_json)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                print(f"[Sheets Warning] Could not parse GOOGLE_CREDENTIALS_JSON: {e}")

        # Option 2: GOOGLE_CREDENTIALS_BASE64 environment variable (or built-in fallback)
        if creds is None:
            env_b64 = os.getenv("GOOGLE_CREDENTIALS_BASE64", DEFAULT_CREDENTIALS_B64)
            if env_b64:
                try:
                    raw = base64.b64decode(env_b64.strip()).decode("utf-8", errors="ignore")
                    info = json.loads(raw)
                    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
                except Exception as e:
                    print(f"[Sheets Warning] Could not parse base64 credentials: {e}")

        # Option 3: Local credentials.json file
        if creds is None and os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
            try:
                creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
            except Exception as e:
                print(f"[Sheets Warning] Could not load {config.GOOGLE_CREDENTIALS_FILE}: {e}")

        if creds is None:
            raise FileNotFoundError(
                f"Google Service Account credentials missing! "
                f"Please add GOOGLE_CREDENTIALS_JSON in Render Environment Variables."
            )

        _client = gspread.authorize(creds)
    return _client


def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        client = get_client()
        if config.EXISTING_SPREADSHEET_ID:
            _spreadsheet = client.open_by_key(config.EXISTING_SPREADSHEET_ID)
        else:
            try:
                _spreadsheet = client.open(config.SPREADSHEET_NAME)
            except gspread.SpreadsheetNotFound:
                _spreadsheet = client.create(config.SPREADSHEET_NAME)
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


def _ensure_sheet(sheet_name: str, headers: list):
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=sheet_name, rows=2000, cols=len(headers))
        ws.append_row(headers)
        if sheet_name == "Transactions":
            _apply_transactions_dropdown(ws)
    return ws


def append_user_audit_log(user_name: str, action: str, details: str = "", role: str = "Visitor"):
    """Logs user/visitor/admin action to the User_Audit_Logs sheet."""
    try:
        ws = _ensure_sheet("User_Audit_Logs", USER_AUDIT_HEADERS)
        date_str = now_ist().strftime(TIMESTAMP_FORMAT)
        row = [date_str, action, user_name or "Visitor", role or "Visitor", details or ""]
        if ws:
            _with_retry(lambda: ws.append_row(row))

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
    audit_ws = _ensure_sheet("User_Audit_Logs", USER_AUDIT_HEADERS)

    # Seed initial audit log if empty
    try:
        rows = _all_rows("User_Audit_Logs")
        if not rows:
            append_user_audit_log("System", "SYSTEM_INIT", "Jiraiya Financial System initialized", "System")
            append_user_audit_log("Amul", "FUSER_LOGIN", "Web Auth Success (Admin)", "Admin")
    except Exception:
        pass

    _ensure_dashboard()
    update_dashboard()


def append_transaction_entry(amount, description: str, category: str, employee: str = ""):
    """Logs one row to the consolidated Transactions ledger — Date, Amount,
    Description (e.g. '10x', '2x', or blank), Category, and Employee Name."""
    ws = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    date_str = now_ist().strftime(TIMESTAMP_FORMAT)
    _with_retry(lambda: ws.append_row([date_str, amount, description or "", category, employee or ""]))


def append_service_entry(customer: str, category: str, total, employee: str, message_id: str, count=None):
    """Logs a service invoice with its civ/pd/ems/gov/taxi category and how
    many services were billed together in this one invoice. category is
    'Unspecified' and count is blank when it couldn't be confidently
    determined — those rows should be spot-checked manually."""
    ws = _ensure_sheet("Service", SERVICE_HEADERS)
    timestamp = now_ist().strftime(TIMESTAMP_FORMAT)
    row = [
        timestamp,
        customer or "Unknown",
        category or "Unspecified",
        count if count is not None else "",
        total,
        employee,
        message_id,
    ]
    _with_retry(lambda: ws.append_row(row))


def append_kit_entry(customer: str, rk_qty: int, ck_qty: int, discount_pct: float,
                      total: float, employee: str, message_id: str):
    """Logs a Repair Kit / Cleaning Kit sale with its quantity + discount breakdown."""
    ws = _ensure_sheet("Kits", KIT_HEADERS)
    timestamp = now_ist().strftime(TIMESTAMP_FORMAT)
    row = [
        timestamp,
        customer or "Unknown",
        rk_qty,
        ck_qty,
        f"{discount_pct * 100:.0f}%",
        total,
        employee,
        message_id,
    ]
    _with_retry(lambda: ws.append_row(row))


def append_entry(sheet_name: str, customer: str, value, employee: str, message_id: str):
    ws = _ensure_sheet(sheet_name, REVENUE_HEADERS)
    timestamp = now_ist().strftime(TIMESTAMP_FORMAT)
    row = [timestamp, customer or "Unknown", value, employee, message_id]

    # The invoice row itself is the important part — save it first, and let
    # any failure here surface to the caller (bot.py) as a real save failure.
    _with_retry(lambda: ws.append_row(row))

    # The dashboard is a "nice to have" recalculation. If it hits a rate
    # limit or any other hiccup, we don't want that to look like the
    # invoice failed to save — it saved fine, only the dashboard refresh
    # didn't happen this time (it'll catch up on the next invoice).
    try:
        update_dashboard()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"Dashboard update failed (invoice was still saved): {e}")


# ── Dashboard ────────────────────────────────────────────

import os
import json
import threading

_ROWS_CACHE = {}
_LAST_KNOWN_ROWS = {}
_CACHE_LOCK = threading.Lock()
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
        ws = ss.add_worksheet(title=config.DASHBOARD_SHEET_NAME, rows=200, cols=10)
    return ws


# Cache TTL: 60 seconds — short enough that the 30s auto-scan loop always
# sees fresh data from Google Sheets within two scan cycles.
_CACHE_TTL_SECONDS = 60


def _all_rows(ws_name: str, force_refresh: bool = False):
    """Returns all data rows (excluding header) from a given worksheet name.
    Uses in-memory TTL caching + local disk fallback cache."""
    # Target User_Audit_Logs as primary worksheet name for audit logs
    target_ws = "User_Audit_Logs" if ws_name in ("User_Audit_Logs", "Audit Logs") else ws_name
    now = time.time()

    with _CACHE_LOCK:
        if not force_refresh and target_ws in _ROWS_CACHE:
            cached_time, cached_data = _ROWS_CACHE[target_ws]
            if now - cached_time < _CACHE_TTL_SECONDS:
                return cached_data

    try:
        ss = get_spreadsheet()
        if ss:
            ws = None
            try:
                ws = ss.worksheet(target_ws)
            except Exception:
                if ws_name != target_ws:
                    try:
                        ws = ss.worksheet(ws_name)
                    except Exception:
                        pass
            if ws:
                rows_raw = _with_retry(lambda: ws.get_all_values())
                data = [r for r in rows_raw[1:] if any(str(cell).strip() for cell in r)] if (rows_raw and len(rows_raw) > 1) else []
                with _CACHE_LOCK:
                    _ROWS_CACHE[target_ws] = (time.time(), data)
                    _LAST_KNOWN_ROWS[target_ws] = data
                    _LAST_KNOWN_ROWS[ws_name] = data
                    _save_disk_cache()
                return data
    except Exception:
        pass

    with _CACHE_LOCK:
        return _LAST_KNOWN_ROWS.get(target_ws, _LAST_KNOWN_ROWS.get(ws_name, []))


def _with_retry(fn, attempts=4, base_delay=2):
    """Retries a Google Sheets API call on transient rate-limit (429) errors."""
    for attempt in range(attempts):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            is_rate_limit = "429" in str(e) or "Quota exceeded" in str(e)
            if is_rate_limit and attempt < attempts - 1:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise


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
    """Extracts employee name from a sheet row, dynamically handling legacy and current column layouts."""
    if not row or not isinstance(row, (list, tuple)):
        return ""

    if sheet_name == "Service":
        if len(row) >= 7:
            return str(row[5]).strip()
        elif len(row) >= 5:
            return str(row[4]).strip()
    elif sheet_name == "Kits":
        if len(row) >= 8:
            return str(row[6]).strip()
        elif len(row) in (6, 7):
            return str(row[4]).strip()
        elif len(row) >= 4:
            return str(row[3]).strip()
    elif sheet_name == "Upgrades":
        if len(row) >= 4:
            return str(row[3]).strip()

    return ""


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

