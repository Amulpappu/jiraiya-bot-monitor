import datetime
import time
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
    rows logged before this change."""
    for fmt in (TIMESTAMP_FORMAT, LEGACY_TIMESTAMP_FORMAT):
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


def get_client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
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


def setup_all_sheets():
    """Call once at startup — makes sure every sheet + the dashboard exist."""
    _ensure_sheet("Service", SERVICE_HEADERS)
    _ensure_sheet("Upgrades", REVENUE_HEADERS)
    _ensure_sheet("Kits", KIT_HEADERS)
    _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    _ensure_dashboard()
    update_dashboard()


def append_transaction_entry(amount, description: str, category: str):
    """Logs one row to the consolidated Transactions ledger — Date, Amount,
    Description (e.g. '10x', '2x', or blank), and Category (must be one of
    config.TRANSACTION_CATEGORIES to match the in-game dropdown)."""
    ws = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    date_str = now_ist().strftime("%d/%m/%Y")
    _with_retry(lambda: ws.append_row([date_str, amount, description or "", category]))


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


def _all_rows(ws_name, force_refresh=False):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS
    now = time.time()

    with _CACHE_LOCK:
        if ws_name in _LAST_KNOWN_ROWS and not force_refresh:
            cached_time, cached_data = _ROWS_CACHE.get(ws_name, (0, _LAST_KNOWN_ROWS[ws_name]))
            if now - cached_time < 300:
                return cached_data

    try:
        ss = get_spreadsheet()
        if ss:
            ws = ss.worksheet(ws_name)
            rows_raw = _with_retry(lambda: ws.get_all_values())
            data = [r for r in rows_raw[1:] if any(str(cell).strip() for cell in r)] if (rows_raw and len(rows_raw) > 1) else []
            with _CACHE_LOCK:
                _ROWS_CACHE[ws_name] = (time.time(), data)
                _LAST_KNOWN_ROWS[ws_name] = data
                _save_disk_cache()
            return data
    except Exception as ex:
        pass

    with _CACHE_LOCK:
        return _LAST_KNOWN_ROWS.get(ws_name, [])


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
            total += float(v)
        except (ValueError, TypeError):
            continue
    return total


def _revenue_window(rows, value_col=2, days=None, today_only=False, this_month=False):
    """Sums the given column's values from an already-fetched rows list
    within a date window. value_col defaults to 2 (Total Amount for
    Service/Upgrades) but the Kits sheet uses column 5 instead."""
    now = now_ist()
    total = 0.0
    for row in rows:
        if len(row) <= value_col:
            continue
        ts = parse_ist_timestamp(row[0])
        try:
            val = float(row[value_col])
        except (ValueError, TypeError):
            continue
        if ts is None:
            continue

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


# Column index (0-based) of "Employee" and "Total Amount" per sheet — Service
# now has Category + Count columns and Kits has RK/CK/Discount columns, so
# neither matches the generic REVENUE_HEADERS layout Upgrades still uses.
_EMPLOYEE_COL = {"Service": 5, "Upgrades": 3, "Kits": 6}
_AMOUNT_COL = {"Service": 4, "Upgrades": 2, "Kits": 5}


def _leaderboard(rows_by_sheet):
    """Ranks employees by total number of invoices they've processed across all categories."""
    counter = Counter()
    for ws_name in ("Service", "Upgrades", "Kits"):
        col = _EMPLOYEE_COL[ws_name]
        for row in rows_by_sheet[ws_name]:
            if len(row) > col and row[col]:
                counter[row[col]] += 1
    return counter.most_common(config.LEADERBOARD_TOP_N)


def update_dashboard():
    ws = _ensure_dashboard()

    # Fetch each sheet exactly ONCE and reuse the data for every calculation
    # below. This keeps Google Sheets API usage low enough to stay within
    # the free tier's read-request quota, even with several invoices logged
    # back-to-back.
    rows_by_sheet = {
        "Service": _all_rows("Service"),
        "Upgrades": _all_rows("Upgrades"),
        "Kits": _all_rows("Kits"),
    }

    service_total = _sum_numeric([r[_AMOUNT_COL["Service"]] for r in rows_by_sheet["Service"] if len(r) > _AMOUNT_COL["Service"]])
    upgrade_total = _sum_numeric([r[_AMOUNT_COL["Upgrades"]] for r in rows_by_sheet["Upgrades"] if len(r) > _AMOUNT_COL["Upgrades"]])
    kits_total = _sum_numeric([r[_AMOUNT_COL["Kits"]] for r in rows_by_sheet["Kits"] if len(r) > _AMOUNT_COL["Kits"]])

    daily = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], today_only=True)
        for name in rows_by_sheet
    }
    weekly = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], days=7)
        for name in rows_by_sheet
    }
    monthly = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], this_month=True)
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
