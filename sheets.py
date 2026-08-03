import os
import time
import datetime
import threading
import logging
import gspread
from google.oauth2.service_account import Credentials
import config

logger = logging.getLogger("sheets")
logger.setLevel(logging.INFO)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

_GSPREAD_CLIENT = None
_SPREADSHEET = None
_LOGGED_IDS_CACHE = None
_CACHE_LOCK = threading.Lock()

_ROWS_CACHE = {}
_LAST_KNOWN_ROWS = {}
_WORKSHEET_CACHE = {}

# Exact Headers requested by user
SERVICE_HEADERS = ["Date", "Customer Name", "Category", "Total Amount", "Staff", "Message ID"]
UPGRADE_HEADERS = ["Date", "Customer Name", "Total Amount", "Staff", "Message ID"]
KIT_HEADERS = ["Date", "Customer Name", "Category", "Total Amount", "Staff", "Message ID"]
EXPENSE_HEADERS = ["Date", "Amount", "Staff", "Message ID"]
VIP_CLAIM_HEADERS = ["Person Name", "Category", "Vehicle", "Staff", "Amount", "Status", "Timestamp", "Message ID"]
TRANSACTIONS_HEADERS = ["Date", "Amount", "Description", "Category", "Employee Name"]
EMPLOYEE_TRACKER_HEADERS = ["Employee Name", "Kit Logs", "Civilian Service", "Govt Service", "Service Logs", "Upgrade Logs", "Total Transactions", "Last Transaction Date"]

_AMOUNT_COL = {"Service": 3, "Upgrades": 2, "Kits": 3, "Expenses": 1, "VIP Claim": 4, "Transactions": 1}
_STAFF_COL = {"Service": 4, "Upgrades": 3, "Kits": 4, "Expenses": 2, "VIP Claim": 3, "Transactions": 4}

VIP_CATEGORIES = ["VIP", "Friends", "Twin", "Community", "Special"]
TRANSACTION_CATEGORIES = ["Repair Kit", "Cleaning Kit", "Car UpGrade", "Service-Civilian", "Service-Government", "Order"]


def _get_ist_dt(dt: datetime.datetime = None) -> datetime.datetime:
    if dt is None:
        return datetime.datetime.now(IST)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc).astimezone(IST)
    return dt.astimezone(IST)


def _with_retry(fn, attempts=6, base_delay=3):
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


def get_client():
    global _GSPREAD_CLIENT
    if _GSPREAD_CLIENT is not None:
        return _GSPREAD_CLIENT

    creds_path = config.CREDENTIALS_FILE
    if not os.path.exists(creds_path):
        logger.error(f"Credentials file '{creds_path}' not found!")
        return None

    try:
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        _GSPREAD_CLIENT = gspread.authorize(creds)
        return _GSPREAD_CLIENT
    except Exception as e:
        logger.error(f"Failed to authenticate Google Sheets API client: {e}")
        return None


def get_spreadsheet():
    global _SPREADSHEET
    if _SPREADSHEET is not None:
        return _SPREADSHEET

    client = get_client()
    if not client:
        return None

    try:
        _SPREADSHEET = _with_retry(lambda: client.open_by_key(config.SPREADSHEET_ID))
        return _SPREADSHEET
    except Exception as e:
        logger.error(f"Failed to open spreadsheet '{config.SPREADSHEET_ID}': {e}")
        return None


def _ensure_sheet(sheet_name: str, headers: list = None):
    global _WORKSHEET_CACHE
    if sheet_name in _WORKSHEET_CACHE:
        return _WORKSHEET_CACHE[sheet_name]

    ss = get_spreadsheet()
    if not ss:
        return None

    try:
        ws = _with_retry(lambda: ss.worksheet(sheet_name))
    except Exception:
        ws = None

    if not ws and headers:
        try:
            ws = _with_retry(lambda: ss.add_worksheet(title=sheet_name, rows=5000, cols=20))
            _with_retry(lambda: ws.append_row(headers))
        except Exception as e:
            logger.error(f"Failed to create worksheet '{sheet_name}': {e}")
            return None

    if ws:
        _WORKSHEET_CACHE[sheet_name] = ws
    return ws


def clear_rows_cache(ws_name=None, hard=False):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS, _WORKSHEET_CACHE, _LOGGED_IDS_CACHE
    with _CACHE_LOCK:
        if ws_name:
            _ROWS_CACHE.pop(ws_name, None)
            if hard:
                _LAST_KNOWN_ROWS.pop(ws_name, None)
        else:
            _ROWS_CACHE.clear()
            _WORKSHEET_CACHE.clear()
            _LOGGED_IDS_CACHE = None
            if hard:
                _LAST_KNOWN_ROWS.clear()


def _all_rows(ws_name: str, force_refresh=False) -> list:
    global _ROWS_CACHE, _LAST_KNOWN_ROWS
    now = time.time()

    with _CACHE_LOCK:
        if ws_name in _LAST_KNOWN_ROWS and not force_refresh:
            cached_time, cached_data = _ROWS_CACHE.get(ws_name, (0, _LAST_KNOWN_ROWS[ws_name]))
            if now - cached_time < 300:
                return cached_data

    # Synchronous fetch from Google Sheets
    try:
        ss = get_spreadsheet()
        if ss:
            ws = _ensure_sheet(ws_name)
            if ws:
                rows_raw = _with_retry(lambda: ws.get_all_values())
                data = [r for r in rows_raw[1:] if any(str(cell).strip() for cell in r)] if (rows_raw and len(rows_raw) > 1) else []
                with _CACHE_LOCK:
                    _ROWS_CACHE[ws_name] = (time.time(), data)
                    _LAST_KNOWN_ROWS[ws_name] = data
                return data
    except Exception as ex:
        logger.warning(f"Fetch warning for '{ws_name}': {ex}")

    with _CACHE_LOCK:
        return _LAST_KNOWN_ROWS.get(ws_name, [])


def _sum_numeric(vals) -> float:
    tot = 0.0
    for v in vals:
        if v is None: continue
        s = str(v).replace(",", "").replace("$", "").replace("₹", "").strip()
        try:
            tot += float(s)
        except ValueError:
            pass
    return tot


def add_logged_message_id(msg_id: str):
    global _LOGGED_IDS_CACHE
    if _LOGGED_IDS_CACHE is None:
        _LOGGED_IDS_CACHE = set()
    _LOGGED_IDS_CACHE.add(str(msg_id))


def get_all_logged_message_ids(force_refresh=False) -> set:
    global _LOGGED_IDS_CACHE
    if _LOGGED_IDS_CACHE is not None and not force_refresh:
        return _LOGGED_IDS_CACHE

    ids = set()
    for sname in ("Service", "Upgrades", "Kits", "Expenses", "VIP Claim"):
        rows = _all_rows(sname, force_refresh=force_refresh)
        for r in rows:
            if r and len(r) > 0:
                msg_id = str(r[-1]).strip()
                if msg_id and (msg_id.isdigit() or msg_id.startswith("MANUAL")):
                    ids.add(msg_id)

    _LOGGED_IDS_CACHE = ids
    return ids


def setup_all_sheets():
    """Initializes all worksheets in Google Sheets with proper user-specified headers."""
    sheet_headers = [
        ("Service", SERVICE_HEADERS),
        ("Upgrades", UPGRADE_HEADERS),
        ("Kits", KIT_HEADERS),
        ("Expenses", EXPENSE_HEADERS),
        ("VIP Claim", VIP_CLAIM_HEADERS),
        ("Transactions", TRANSACTIONS_HEADERS),
        ("Employee Tracker", EMPLOYEE_TRACKER_HEADERS),
        (config.DASHBOARD_SHEET_NAME, ["Metric", "Value"]),
    ]
    for sname, headers in sheet_headers:
        _ensure_sheet(sname, headers)
    logger.info("All Google Sheets worksheets setup and verified.")


def wipe_all_data_sheets():
    """Wipes data rows from Service, Upgrades, Kits, Expenses, VIP Claim, and Transactions worksheets."""
    clear_rows_cache(hard=True)
    ss = get_spreadsheet()
    if not ss:
        return

    sheets_to_wipe = [
        ("Service", SERVICE_HEADERS),
        ("Upgrades", UPGRADE_HEADERS),
        ("Kits", KIT_HEADERS),
        ("Expenses", EXPENSE_HEADERS),
        ("VIP Claim", VIP_CLAIM_HEADERS),
        ("Transactions", TRANSACTIONS_HEADERS),
    ]

    for sname, headers in sheets_to_wipe:
        try:
            ws = ss.worksheet(sname)
            _with_retry(lambda: ws.clear())
            _with_retry(lambda: ws.update("A1", [headers]))
        except Exception as e:
            logger.error(f"Error wiping sheet '{sname}': {e}")

    logger.info("All data worksheets wiped successfully.")


def append_user_audit_log(user_name: str, action_type: str, details: str = "", role: str = "Admin"):
    """Appends an audit log entry to the existing User_Audit_Logs worksheet."""
    try:
        ws = _ensure_sheet("User_Audit_Logs")
        if not ws:
            return
        dt_ist = _get_ist_dt()
        date_str = dt_ist.strftime("%Y-%m-%d %I:%M:%S %p")
        new_row = [date_str, action_type, user_name or "Anonymous", role, details]
        _with_retry(lambda: ws.append_row(new_row))

        with _CACHE_LOCK:
            if "User_Audit_Logs" in _LAST_KNOWN_ROWS:
                _LAST_KNOWN_ROWS["User_Audit_Logs"].append(new_row)
                _ROWS_CACHE["User_Audit_Logs"] = (time.time(), _LAST_KNOWN_ROWS["User_Audit_Logs"])
    except Exception as e:
        logger.error(f"Failed to append to User_Audit_Logs: {e}")


def append_transaction_entry(amount, employee: str, category: str, description: str = "", created_at: datetime.datetime = None, skip_tracker_update: bool = False):
    """Logs one row to the consolidated Transactions ledger: [Date, Amount, Description, Category, Employee Name]."""
    if amount is None:
        return
    try:
        num_amount = float(amount)
        if num_amount <= 0:
            return
    except (ValueError, TypeError):
        return

    dt_ist = _get_ist_dt(created_at)
    ws = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    if not ws:
        return

    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)
    cat_clean = category if category in TRANSACTION_CATEGORIES else "Order"
    new_row = [date_str, num_amount, description or "", cat_clean, employee or "Unknown"]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if "Transactions" in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Transactions"].append(new_row)
            _ROWS_CACHE["Transactions"] = (time.time(), _LAST_KNOWN_ROWS["Transactions"])

    if not skip_tracker_update:
        try:
            update_employee_tracker()
        except Exception as e:
            logger.error(f"Employee Tracker update failed: {e}")


def append_service_entry(category: str, total, employee: str, message_id: str, count=None, created_at: datetime.datetime = None, customer: str = None, skip_dashboard_update: bool = False):
    """Logs a Service invoice: [Date, Customer Name, Category (Civilian / Gov Employee), Total Amount, Staff, Message ID]."""
    ws = _ensure_sheet("Service", SERVICE_HEADERS)
    if not ws:
        return

    dt_ist = _get_ist_dt(created_at)
    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)
    cat_display = "Gov Employee" if any(g in str(category).lower() for g in ("pd", "ems", "taxi", "gov")) else "Civilian"

    new_row = [
        date_str,
        customer or "Unknown",
        cat_display,
        total,
        employee or "Unknown",
        message_id,
    ]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if "Service" in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Service"].append(new_row)
            _ROWS_CACHE["Service"] = (time.time(), _LAST_KNOWN_ROWS["Service"])

    add_logged_message_id(str(message_id))
    if not skip_dashboard_update:
        try:
            update_dashboard()
        except Exception:
            pass


def append_kit_entry(rk_qty: int, ck_qty: int, discount_pct: float, total: float, employee: str, message_id: str, created_at: datetime.datetime = None, customer: str = None, skip_dashboard_update: bool = False):
    """Logs a Kit sale: [Date, Customer Name, Category (Repair Kit / Cleaning Kit), Total Amount, Staff, Message ID]."""
    ws = _ensure_sheet("Kits", KIT_HEADERS)
    if not ws:
        return

    dt_ist = _get_ist_dt(created_at)
    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)

    parts = []
    if rk_qty > 0:
        parts.append(f"{rk_qty}x Repair Kit")
    if ck_qty > 0:
        parts.append(f"{ck_qty}x Cleaning Kit")

    cat_str = ", ".join(parts) if parts else "Repair Kit"

    new_row = [
        date_str,
        customer or "Unknown",
        cat_str,
        total,
        employee or "Unknown",
        message_id,
    ]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if "Kits" in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Kits"].append(new_row)
            _ROWS_CACHE["Kits"] = (time.time(), _LAST_KNOWN_ROWS["Kits"])

    add_logged_message_id(str(message_id))
    if not skip_dashboard_update:
        try:
            update_dashboard()
        except Exception:
            pass


def append_entry(sheet_name: str, value, employee: str, message_id: str, created_at: datetime.datetime = None, customer: str = None, skip_dashboard_update: bool = False):
    """Logs an Upgrade entry: [Date, Customer Name, Total Amount, Staff, Message ID]."""
    try:
        val_float = float(value)
        if val_float <= 0:
            return
    except (ValueError, TypeError):
        return

    ws = _ensure_sheet(sheet_name, UPGRADE_HEADERS)
    if not ws:
        return

    dt_ist = _get_ist_dt(created_at)
    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)
    new_row = [date_str, customer or "Unknown", val_float, employee or "Unknown", message_id]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if sheet_name in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS[sheet_name].append(new_row)
            _ROWS_CACHE[sheet_name] = (time.time(), _LAST_KNOWN_ROWS[sheet_name])

    add_logged_message_id(str(message_id))
    if not skip_dashboard_update:
        try:
            update_dashboard()
        except Exception:
            pass


def append_expense_entry(amount, employee: str, message_id: str, created_at: datetime.datetime = None, skip_dashboard_update: bool = False):
    """Logs an Expense / Bill Claim: [Date, Amount, Staff, Message ID]."""
    ws = _ensure_sheet("Expenses", EXPENSE_HEADERS)
    if not ws:
        return

    dt_ist = _get_ist_dt(created_at)
    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)
    new_row = [date_str, amount, employee or "Unknown", message_id]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if "Expenses" in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["Expenses"].append(new_row)
            _ROWS_CACHE["Expenses"] = (time.time(), _LAST_KNOWN_ROWS["Expenses"])

    add_logged_message_id(str(message_id))
    if not skip_dashboard_update:
        try:
            update_dashboard()
        except Exception:
            pass


def append_vip_claim_entry(person_name: str, category: str, vehicle: str, staff: str, amount: float, message_id: str, created_at: datetime.datetime = None, skip_dashboard_update: bool = False):
    """Logs a VIP Mech Claim entry: [Person Name, Category, Vehicle, Staff, Amount, Status, Timestamp, Message ID]."""
    ws = _ensure_sheet("VIP Claim", VIP_CLAIM_HEADERS)
    if not ws:
        return

    dt_ist = _get_ist_dt(created_at)
    date_str = dt_ist.strftime(TIMESTAMP_FORMAT)
    cat_clean = category if category in VIP_CATEGORIES else "VIP"

    new_row = [
        person_name or "Unknown",
        cat_clean,
        vehicle or "Unknown",
        staff or "Unknown",
        amount if amount is not None else 0,
        "Unclaimed",
        date_str,
        message_id,
    ]
    _with_retry(lambda: ws.append_row(new_row))

    with _CACHE_LOCK:
        if "VIP Claim" in _LAST_KNOWN_ROWS:
            _LAST_KNOWN_ROWS["VIP Claim"].append(new_row)
            _ROWS_CACHE["VIP Claim"] = (time.time(), _LAST_KNOWN_ROWS["VIP Claim"])

    add_logged_message_id(str(message_id))
    if not skip_dashboard_update:
        try:
            update_dashboard()
        except Exception:
            pass


def update_dashboard():
    """Calculates summary stats across all worksheets and updates Dashboard worksheet."""
    service_rows = _all_rows("Service")
    upgrade_rows = _all_rows("Upgrades")
    kit_rows = _all_rows("Kits")
    expense_rows = _all_rows("Expenses")

    service_rev = sum(_sum_numeric([r[3]]) for r in service_rows if len(r) > 3)
    upgrade_rev = sum(_sum_numeric([r[2]]) for r in upgrade_rows if len(r) > 2)
    kit_rev = sum(_sum_numeric([r[3]]) for r in kit_rows if len(r) > 3)
    expenses_tot = sum(_sum_numeric([r[1]]) for r in expense_rows if len(r) > 1)

    total_rev = service_rev + upgrade_rev + kit_rev
    net_profit = total_rev - expenses_tot
    total_txns = len(service_rows) + len(upgrade_rows) + len(kit_rows) + len(expense_rows)

    emp_counts = {}
    for rows, col in [(service_rows, 4), (upgrade_rows, 3), (kit_rows, 4)]:
        for r in rows:
            if len(r) > col:
                emp = str(r[col]).strip()
                if emp:
                    emp_counts[emp] = emp_counts.get(emp, 0) + 1

    top_emp = max(emp_counts, key=emp_counts.get) if emp_counts else "N/A"

    dashboard_data = [
        ["FINANCIAL SUMMARY", ""],
        ["Total Revenue", f"₹{total_rev:,.2f}"],
        ["Service Revenue", f"₹{service_rev:,.2f}"],
        ["Upgrades Revenue", f"₹{upgrade_rev:,.2f}"],
        ["Kits Revenue", f"₹{kit_rev:,.2f}"],
        ["Total Expenses", f"₹{expenses_tot:,.2f}"],
        ["Net Profit", f"₹{net_profit:,.2f}"],
        ["Total Transactions", total_txns],
        ["Top Performing Employee", top_emp],
        ["", ""],
        ["EMPLOYEE LEADERBOARD", "Transactions Logged"],
    ]

    for emp, count in sorted(emp_counts.items(), key=lambda x: x[1], reverse=True):
        dashboard_data.append([emp, count])

    ws = _ensure_sheet(config.DASHBOARD_SHEET_NAME, ["Metric", "Value"])
    if ws:
        try:
            _with_retry(lambda: ws.clear())
            _with_retry(lambda: ws.update("A1", dashboard_data))
        except Exception as e:
            logger.error(f"Failed to update Dashboard worksheet: {e}")


def update_employee_tracker():
    """Aggregates metrics per employee and updates Employee Tracker worksheet."""
    service_rows = _all_rows("Service")
    upgrade_rows = _all_rows("Upgrades")
    kit_rows = _all_rows("Kits")

    employees = {}

    def get_emp(name):
        n = str(name).strip() if name else "Unknown"
        if n not in employees:
            employees[n] = {
                "kits": 0, "civ_service": 0, "govt_service": 0,
                "service_logs": 0, "upgrades": 0, "last_date": ""
            }
        return employees[n]

    for r in service_rows:
        if len(r) > 4:
            e = get_emp(r[4])
            e["service_logs"] += 1
            cat = str(r[2]).lower() if len(r) > 2 else ""
            if "gov" in cat:
                e["govt_service"] += 1
            else:
                e["civ_service"] += 1
            if len(r) > 0 and r[0] > e["last_date"]:
                e["last_date"] = r[0]

    for r in upgrade_rows:
        if len(r) > 3:
            e = get_emp(r[3])
            e["upgrades"] += 1
            if len(r) > 0 and r[0] > e["last_date"]:
                e["last_date"] = r[0]

    for r in kit_rows:
        if len(r) > 4:
            e = get_emp(r[4])
            e["kits"] += 1
            if len(r) > 0 and r[0] > e["last_date"]:
                e["last_date"] = r[0]

    tracker_data = [EMPLOYEE_TRACKER_HEADERS]
    for emp_name, d in sorted(employees.items()):
        tot = d["kits"] + d["service_logs"] + d["upgrades"]
        tracker_data.append([
            emp_name,
            d["kits"],
            d["civ_service"],
            d["govt_service"],
            d["service_logs"],
            d["upgrades"],
            tot,
            d["last_date"]
        ])

    ws = _ensure_sheet("Employee Tracker", EMPLOYEE_TRACKER_HEADERS)
    if ws:
        try:
            _with_retry(lambda: ws.clear())
            _with_retry(lambda: ws.update("A1", tracker_data))
        except Exception as e:
            logger.error(f"Failed to update Employee Tracker worksheet: {e}")
