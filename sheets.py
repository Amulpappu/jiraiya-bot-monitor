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
    "ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsCiAgInByb2plY3RfaWQiOiAiZ2VudWlu"
    "ZS1oYWJpdGF0LTQ5MjExNi1rNyIsCiAgInByaXZhdGVfa2V5X2lkIjogImNkZmRhNjliNTkx"
    "Yzg0ZDMwOWM4YjU0ZmM4NDk1ZGEzZjFlNDAzYzgiLAogICJwcml2YXRlX2tleSI6ICItLS0t"
    "LUJFR0lOIFBSSVZBVEUgS0VZLS0tLS1cbk1JSUV2UUlCQURBTkJna3Foa2lHOXcwQkFRRUZB"
    "QVNDQktjd2dnU2pBZ0VBQW9JQkFRRFNobFloQUpkVU1UNklcblhqb3ZGZGFxNzVTWExab0JN"
    "UUVTemVJa1BxTldLbmZUOUpVdnN0ajVIU3NiY3hIMWwzNmtUTms3M3VzLzRKL0dcbmpvTEF5"
    "clIrQ2JHRVdWbFdCWjlmWlNVMnE0dEI0TTRCRFNBb2JpYVlYSmZwMlAxWjBUMEV4ZlZhNlJ4"
    "S2tOUWdcbk1YbVRLVTh3YXRFbG5YOXhIRjlJUmpKREF0VDJBQTZmZm1aV3M5N09pSEFYaUhO"
    "MnljNUdYV3FadXZla3IwNEFcbmtmQWNoV1pYUlZkMExMUDFMTWJRNTFzWEpkenFuQ1VyR2N4"
    "anlpQkFzWHF1WjMvdHF4U0hRNGJOSVF1M0EzNUlcbnRKSlV3Y2gybys3cy9TY1I1NUVUUGRo"
    "cFdscC9VSzFKYUhsMmRXa09BNFJNNU9Ua0ZWT3U1SkVJQ0loTVZjRzRcbkNzNlA5MlF4QWdN"
    "QkFBRUNnZ0VBQ3A2VjVPV0luS208d2FoK0p4NmpCTjJmdVZZR3F4bDNtRVVjSzQrZzBlR0Rc"
    "bnlLUnhhNVhxR2J2Wnp6Rkpaa0h4ZEpSL1QwUzJDWE41WDh6VHhlbWJ1L0ZkZStOOWJRaE0w"
    "eVV4SUw0N3dMT1lcbk5LZWV1QWRoYVVWZmNOOStIU3dmdDdoTUlYMDVqUDNjQTNFM2RKL01j"
    "N0Rwc3F2c2tDNDZGTFZjeHZKVFA0TG5cbkRVaW5vM3k2K3AvdlFBNkNrZ29SdXRIZkdObFhs"
    "WVJLRTc2bWpCT2NEVFpQN0F5WHNxMnBkL2NRRGJNR01uNnFcbnlBZTZzZnRpa0FnQ0daUG5P"
    "SVA0TW14TlVPU3dFaVVvUnROcmd5VmxUMkNYSllUVFVrcU9wNGZwZEp3ZmNpTHpcbmV4K0w4"
    "ZWNuVlNRUk45N3pWd1pKOWVUV3ZiMEdSNXZOYkpJOCt0RGZ3UUtCZ1FEc0VCc1d4SzZXRGFn"
    "djZpV1VcbmZJS3BUL3QrMzZVRnZOQjZnSElPNnE1YVpuOXQzUFdXSDdrWmwvYitkZnV2M0NM"
    "TU96RGthdlMwWXQ0MHRvbjRcbk5DcmMvU3pSNlgrZlA4aFFBTlpEallVYVBHaDFPQ0thREFl"
    "QWRTZ214SllVRDRteGpnOTFueUF3b1l3TmttUUtcbjdTaDNXQkM4TFV2MCtpNDFNNm1KRVRC"
    "cUlRS0JnUURrVGhLS0Y3OGx2a3hWcXI5b3ZGLzJOVTE1VllTWlpUNFRcbnd2bDZGb0NDY2Fq"
    "ZlhyUXdTcHRjbzNGUVdGUVJkOExtMWlRNXVHc2laMTV0d1VWNkkvdUtLZzVkRHpwUllwWURc"
    "bkJmYVQ0dkFaRDVuTmQyaXVYc3NFQkhGY3NVdS9tT0F3b0RhWko2MC93ZXJkNk4ycDdRcTd5"
    "Qi85cUlIYlZtZytcbjU3TnJZS1ZZRVFLQmdEVUF6TVJJOXhaVURLNXRlWENrb0VYWjRwTXpM"
    "Zjlpek1Da3RIZHE5Q2p5R0t5WFQwRWNcbjhGZXh5bENLTnkvZVVxWGVxSFN4R3k2aGdGai9u"
    "Mnp1Y2ExYTMwUm1sRFF5Z3d5TGs1QnBaemhqMWVSejdUai9cbmVITzhXbjZSNTB5cnpIUGtm"
    "TTRoSTM0bjE2VjRlQ1FINmUwYUJlL3FqOEo2cGdObURTdnNneDFoQW9HQWRLZkxcbjQxSFU4"
    "dVUwdmdVOFBya2FVNFRTN0crZERJQmw0dFVhZ3A2aTFZUmNKSjZRZGFoNWtERlhnaFZRQjRq"
    "cFJ1Z2VcbnBIdXVDbXRGSGRIR3ZXMUxaMEtzQ2pMd3Vvc2tXYkVmV0Z0NkVXUWVVNVZ6SUw0"
    "QkFER0E5enNFbUliMTd3SytcblF5MjU0YjBsVkhSYlp5dGU4NnFEWmlwSENCc3pzd2pUYmNk"
    "NVZQRUNnWUVBcXZ5SnRoNnFjVVJGbUNObWpYcVNcbmp1RkdOT0lSU0xRMGg5RnV2TitMTGZz"
    "WSsyRW1pcStsOWRLbmtkVUpzelhNRU11dnB4bXRoVThkV29XY1A4YnJcbkphSW95aWVnNytO"
    "Q2NUNkRoOEQ0R3VPbHI2azZIS2Y2aDJXVEk4NlJ2aHluL29aTmRsQkhnbnRzMlNGTHBiN1Rc"
    "bnpWWDkwcFpYOFZON1Bja05FUU9tWHZRPVxuLS0tLS1FTkQgUFJJVkFURSBLRVktLS0tLVxu"
    "IiwKICAiY2xpZW50X2VtYWlsIjogImppcmFpeWEtYm90QGdlbnVpbmUtaGFiaXRhdC00OTIx"
    "MTYtazcuaWFtLmdzZXJ2aWNlYWNjb3VudC5jb20iLAogICJjbGllbnRfaWQiOiAiMTAyNjE4"
    "ODA3NTA4MDc5MzE2MDcwIiwKICAiYXV0aF91cmkiOiAiaHR0cHM6Ly9hY2NvdW50cy5nb29n"
    "bGVhcGlzLmNvbS9vL29hdXRoMi9hdXRoIiwKICAidG9rZW5fdXJpIjogImh0dHBzOi8vb2F1"
    "dGgyLmdvb2dsZWFwaXMuY29tL3Rva2VuIiwKICAiYXV0aF9wcm92aWRlcl94NTA5X2NlcnRf"
    "dXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL29hdXRoMi92MS9jZXJ0cyIsCiAg"
    "ImNsaWVudF94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL3Jv"
    "Ym90L3YxL21ldGFkYXRhL3g1MDkvamlyYWl5YS1ib3QlNDBnZW51aW5lLWhhYml0YXQtNDky"
    "MTE2LWs3LmlhbS5nc2VydmljZWFjY291bnQuY29tIiwKICAidW5pdmVyc2VfZG9tYWluIjog"
    "Imdvb2dsZWFwaXMuY29tIgp9"
)


def ensure_credentials_file_exists():
    """Generates credentials.json from GOOGLE_CREDENTIALS_JSON or DEFAULT_CREDENTIALS_B64 if missing on disk."""
    if os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
        return True

    env_json = (os.getenv("GOOGLE_CREDENTIALS_JSON") or "").strip()
    if env_json:
        try:
            info = json.loads(env_json)
            with open(config.GOOGLE_CREDENTIALS_FILE, "w") as f:
                json.dump(info, f, indent=2)
            return True
        except Exception:
            pass

    env_b64 = (os.getenv("GOOGLE_CREDENTIALS_BASE64") or "").strip() or DEFAULT_CREDENTIALS_B64
    if env_b64:
        try:
            raw = base64.b64decode(env_b64).decode("utf-8", errors="ignore")
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
        env_json = (os.getenv("GOOGLE_CREDENTIALS_JSON") or "").strip()
        if env_json:
            try:
                info = json.loads(env_json)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                print(f"[Sheets Warning] Could not parse GOOGLE_CREDENTIALS_JSON: {e}")

        # Option 2: GOOGLE_CREDENTIALS_BASE64 environment variable
        if creds is None:
            env_b64 = (os.getenv("GOOGLE_CREDENTIALS_BASE64") or "").strip()
            if env_b64:
                try:
                    raw = base64.b64decode(env_b64).decode("utf-8", errors="ignore")
                    info = json.loads(raw)
                    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
                except Exception as e:
                    print(f"[Sheets Warning] Could not parse GOOGLE_CREDENTIALS_BASE64: {e}")

        # Option 3: Local credentials.json file
        if creds is None and os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
            try:
                creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
            except Exception as e:
                print(f"[Sheets Warning] Could not load {config.GOOGLE_CREDENTIALS_FILE}: {e}")

        # Option 4: Built-in DEFAULT_CREDENTIALS_B64 fallback
        if creds is None:
            try:
                raw = base64.b64decode(DEFAULT_CREDENTIALS_B64).decode("utf-8", errors="ignore")
                info = json.loads(raw)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                print(f"[Sheets Warning] Could not load built-in default credentials: {e}")

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

