import os
import datetime
import time
import threading
from collections import Counter, defaultdict

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


def _get_ist_dt(created_at: datetime.datetime = None) -> datetime.datetime:
    """Converts a datetime (e.g. message.created_at) to Indian Standard Time (IST).
    Falls back to current IST time if created_at is None."""
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        return created_at.astimezone(IST)
    return now_ist()


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
EXPENSE_HEADERS = ["Timestamp", "Amount", "Employee", "Category", "Description", "Message ID"]
INVENTORY_HEADERS = ["Item Name", "Quantity in Stock", "Bought This Month", "Restock Date", "Unit Price", "Total Value", "Last Updated"]
VIP_CLAIM_HEADERS = ["Person Name", "Category", "Vehicle", "Staff", "Amount", "Timestamp", "Message ID"]
TRANSACTIONS_HEADERS = ["Date", "Transaction Amount", "Description", "Transaction Type", "Employee Name"]
EMPLOYEE_TRACKER_HEADERS = [
    "Employee Name",
    "Kit Logs",
    "Service Logs",
    "Upgrade Logs",
    "Total Transactions",
    "Last Transaction Date",
]


def get_client():
    global _client
    if _client is None:
        try:
            raw_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
            if raw_json:
                import json
                info = json.loads(raw_json)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            else:
                creds_file = getattr(config, "GOOGLE_CREDENTIALS_FILE", "credentials.json")
                if not os.path.exists(creds_file):
                    print(f"[Sheets Warning] Credentials file '{creds_file}' not found.")
                    return None
                creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
            _client = gspread.authorize(creds)
        except Exception as e:
            print(f"[Sheets Auth Error]: {e}")
            return None
    return _client


def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        try:
            client = get_client()
            if not client:
                return None
            if getattr(config, "EXISTING_SPREADSHEET_ID", ""):
                _spreadsheet = _with_retry(lambda: client.open_by_key(config.EXISTING_SPREADSHEET_ID))
            else:
                try:
                    _spreadsheet = _with_retry(lambda: client.open(config.SPREADSHEET_NAME))
                except Exception:
                    _spreadsheet = _with_retry(lambda: client.create(config.SPREADSHEET_NAME))
        except Exception as e:
            print(f"[Get Spreadsheet Error]: {e}")
            return None
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


_ROWS_CACHE = {}
_LAST_KNOWN_ROWS = {}
_CACHE_TTL = 30  # seconds cache validity for monitor/dashboard reads
_WORKSHEET_CACHE = {}


_LOGGED_IDS_CACHE = None


def clear_rows_cache(ws_name=None):
    """Invalidates cached row data when a new invoice is logged or sheets are wiped."""
    global _ROWS_CACHE, _LAST_KNOWN_ROWS, _LOGGED_IDS_CACHE, _WORKSHEET_CACHE
    _LOGGED_IDS_CACHE = None
    _ROWS_CACHE.clear()
    _LAST_KNOWN_ROWS.clear()
    _WORKSHEET_CACHE.clear()


def _all_rows(ws_name, force_refresh=False, fast_cached_only=False):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS
    now = time.time()

    # Fast instant non-blocking lookup if cached data exists
    if not force_refresh and (ws_name in _ROWS_CACHE or ws_name in _LAST_KNOWN_ROWS):
        cached_time, cached_data = _ROWS_CACHE.get(ws_name, (0, _LAST_KNOWN_ROWS.get(ws_name, [])))
        if now - cached_time > 15 and not fast_cached_only:
            def _async_bg_refresh(w_name):
                try:
                    ss = get_spreadsheet()
                    if ss:
                        ws = ss.worksheet(w_name)
                        if ws:
                            d = ws.get_all_values()[1:]
                            _ROWS_CACHE[w_name] = (time.time(), d)
                            _LAST_KNOWN_ROWS[w_name] = d
                except Exception:
                    pass
            threading.Thread(target=_async_bg_refresh, args=(ws_name,), daemon=True).start()
        return cached_data

    # Cold startup or explicit force_refresh
    try:
        ss = get_spreadsheet()
        if not ss:
            return _LAST_KNOWN_ROWS.get(ws_name, _ROWS_CACHE.get(ws_name, (0, []))[1] if ws_name in _ROWS_CACHE else [])
        try:
            ws = ss.worksheet(ws_name)
        except Exception:
            ws = None
            if ws_name in ("VIP Claim", "VIP Claims", "VIP Log"):
                for alt in ("VIP Claim", "VIP Log", "VIP Claims", "vip_claims"):
                    try:
                        ws = ss.worksheet(alt)
                        if ws: break
                    except Exception: pass
            if not ws:
                return _LAST_KNOWN_ROWS.get(ws_name, [])

        data = ws.get_all_values()[1:]
        _ROWS_CACHE[ws_name] = (now, data)
        _LAST_KNOWN_ROWS[ws_name] = data
        return data
    except Exception as e:
        if ws_name in _LAST_KNOWN_ROWS:
            return _LAST_KNOWN_ROWS[ws_name]
        if ws_name in _ROWS_CACHE:
            return _ROWS_CACHE[ws_name][1]
        return []


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


VIP_CLAIM_CATEGORIES = ["VIP", "Friends", "Twin", "Community", "Special"]


def _apply_vip_claim_dropdown(ws):
    """Restricts the Category column (B) to a dropdown of VIP_CLAIM_CATEGORIES."""
    try:
        requests = [{
            "setDataValidation": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,  # skip header row
                    "startColumnIndex": 1,  # column B = Category
                    "endColumnIndex": 2,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": c} for c in VIP_CLAIM_CATEGORIES],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        }]
        ws.spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"Warning: couldn't apply VIP Claim category dropdown: {e}")


def _ensure_sheet(sheet_name: str, headers: list):
    global _WORKSHEET_CACHE
    if sheet_name in _WORKSHEET_CACHE:
        return _WORKSHEET_CACHE[sheet_name]

    ss = get_spreadsheet()
    try:
        ws = _with_retry(lambda: ss.worksheet(sheet_name))
    except gspread.WorksheetNotFound:
        ws = _with_retry(lambda: ss.add_worksheet(title=sheet_name, rows=2000, cols=len(headers)))
        _with_retry(lambda: ws.append_row(headers))
        if sheet_name == "Transactions":
            _apply_transactions_dropdown(ws)
        elif sheet_name == "VIP Claim":
            _apply_vip_claim_dropdown(ws)

    _WORKSHEET_CACHE[sheet_name] = ws
    return ws


def add_or_update_inventory(item_name: str, qty: int, bought: float, restock_date: str, unit_price: float):
    ws = _ensure_sheet("Inventory", INVENTORY_HEADERS)
    now_str = now_ist().strftime("%Y-%m-%d %I:%M %p")
    tot_val = qty * unit_price
    new_row = [item_name, str(qty), str(bought), restock_date, str(unit_price), str(tot_val), now_str]

    all_data = _with_retry(lambda: ws.get_all_values())
    found_idx = -1
    for idx, row in enumerate(all_data):
        if idx > 0 and len(row) > 0 and row[0].strip().lower() == item_name.strip().lower():
            found_idx = idx + 1
            break

    if found_idx > 0:
        _with_retry(lambda: ws.update(f"A{found_idx}:G{found_idx}", [new_row]))
    else:
        _with_retry(lambda: ws.append_row(new_row))

    clear_rows_cache("Inventory")
    return new_row


def clean_non_july_logs():
    """
    Scans Service, Upgrades, Kits, Expenses, Transactions, and VIP Claim sheets,
    removing any historical rows that do NOT belong to July 2026.
    """
    try:
        ss = get_spreadsheet()
        sheets_and_headers = [
            ("Service", SERVICE_HEADERS),
            ("Upgrades", REVENUE_HEADERS),
            ("Kits", KIT_HEADERS),
            ("Expenses", EXPENSE_HEADERS),
            ("VIP Claim", VIP_CLAIM_HEADERS),
            ("Upgrades", REVENUE_HEADERS),
            ("Kits", KIT_HEADERS),
            ("Expenses", EXPENSE_HEADERS),
            ("Transactions", TRANSACTIONS_HEADERS),
        ]

        for ws_name, headers in sheets_and_headers:
            try:
                ws = ss.worksheet(ws_name)
                rows = _with_retry(lambda: ws.get_all_values())
                if not rows or len(rows) <= 1:
                    continue

                header = rows[0]
                cleaned = [header]
                removed_count = 0

                for row in rows[1:]:
                    if not row or not row[0].strip():
                        continue
                    dt_str = row[0].strip()
                    is_july = False

                    if dt_str.startswith("2026-07") or "/07/2026" in dt_str or "-07-2026" in dt_str:
                        is_july = True
                    else:
                        parsed_dt = parse_ist_timestamp(dt_str)
                        if parsed_dt and parsed_dt.year == 2026 and parsed_dt.month == 7:
                            is_july = True

                    if is_july:
                        cleaned.append(row)
                    else:
                        removed_count += 1

                if removed_count > 0:
                    _with_retry(lambda: ws.clear())
                    _with_retry(lambda: ws.update("A1", cleaned))
                    clear_rows_cache(ws_name)
                    print(f"Cleaned {removed_count} non-July row(s) from sheet '{ws_name}'.")

            except Exception as e:
                import logging
                logging.getLogger("sheets").error(f"Failed to clean non-July logs from {ws_name}: {e}")

        clear_rows_cache()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"clean_non_july_logs failed: {e}")


def clean_invalid_customer_names():
    """Replaces invalid customer names (e.g. 'OnDuty', 'FIRST NAME', 'Total', 'We Me', 'C4', 'Lb')
    with 'Unknown' across Service, Upgrades, and Kits sheets."""
    import ocr
    try:
        ss = get_spreadsheet()
        for ws_name in ("Service", "Upgrades", "Kits"):
            try:
                ws = ss.worksheet(ws_name)
                rows = _with_retry(lambda: ws.get_all_values())
                if not rows or len(rows) <= 1:
                    continue

                header = rows[0]
                cleaned = [header]
                modified = False
                cust_col = 1  # Col B (0-indexed)

                for row in rows[1:]:
                    if len(row) > cust_col:
                        c_name = row[cust_col].strip()
                        if not ocr._is_valid_name(c_name):
                            row[cust_col] = "Unknown"
                            modified = True
                    cleaned.append(row)

                if modified:
                    _with_retry(lambda: ws.clear())
                    _with_retry(lambda: ws.update("A1", cleaned))
                    clear_rows_cache(ws_name)
                    print(f"Cleaned invalid customer names in sheet '{ws_name}'.")

            except Exception as e:
                import logging
                logging.getLogger("sheets").error(f"Failed to clean customer names in {ws_name}: {e}")

    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"clean_invalid_customer_names failed: {e}")


def clean_invalid_service_amounts():
    """Removes invalid high service amounts (> ₹100,000 or Unspecified category) from the Service sheet."""
    try:
        ss = get_spreadsheet()
        ws = ss.worksheet("Service")
        rows = _with_retry(lambda: ws.get_all_values())
        if not rows or len(rows) <= 1:
            return

        header = rows[0]
        cleaned = [header]
        removed_count = 0

        for row in rows[1:]:
            if not row or len(row) <= 4:
                continue
            cat = row[2].strip() if len(row) > 2 else ""
            amt_str = row[4].strip() if len(row) > 4 else "0"

            try:
                amt_val = float(amt_str)
            except ValueError:
                amt_val = 0.0

            if amt_val > 100000 or cat.lower() == "unspecified":
                removed_count += 1
            else:
                cleaned.append(row)

        if removed_count > 0:
            _with_retry(lambda: ws.clear())
            _with_retry(lambda: ws.update("A1", cleaned))
            clear_rows_cache("Service")
            print(f"Cleaned {removed_count} invalid high service row(s) from 'Service' sheet.")
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"clean_invalid_service_amounts failed: {e}")


def reset_dashboard_to_zero():
    """Wipes the Dashboard sheet and resets all metrics to 0."""
    try:
        ws = _ensure_sheet("Dashboard", ["CODE Jiraiya Customs and Tunerz — Financial Dashboard", ""])
        updated_at = now_ist().strftime(TIMESTAMP_FORMAT) + " IST"
        rows = [
            ["CODE Jiraiya Customs and Tunerz — Financial Dashboard", ""],
            [f"Last updated: {updated_at}", ""],
            ["", ""],
            ["DAILY FINANCIALS (Today)", ""],
            ["Service Revenue", 0],
            ["Upgrade Revenue", 0],
            ["Kits Revenue", 0],
            ["TOTAL SALES", 0],
            ["TOTAL EXPENSES", 0],
            ["NET PROFIT", 0],
            ["", ""],
            ["WEEKLY FINANCIALS (Last 7 Days)", ""],
            ["Service Revenue", 0],
            ["Upgrade Revenue", 0],
            ["Kits Revenue", 0],
            ["TOTAL SALES", 0],
            ["TOTAL EXPENSES", 0],
            ["NET PROFIT", 0],
            ["", ""],
            ["MONTHLY FINANCIALS (This Month)", ""],
            ["Service Revenue", 0],
            ["Upgrade Revenue", 0],
            ["Kits Revenue", 0],
            ["TOTAL SALES", 0],
            ["TOTAL EXPENSES", 0],
            ["NET PROFIT", 0],
            ["", ""],
            ["ALL-TIME FINANCIALS", ""],
            ["Total Service Revenue", 0],
            ["Total Upgrade Revenue", 0],
            ["Total Kits Revenue", 0],
            ["TOTAL SALES", 0],
            ["TOTAL EXPENSES", 0],
            ["NET PROFIT", 0],
            ["", ""],
            ["EMPLOYEE LEADERBOARD (invoices/bills processed)", ""],
        ]
        _with_retry(lambda: ws.clear())
        _with_retry(lambda: ws.update("A1", rows))
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"reset_dashboard_to_zero failed: {e}")


def wipe_all_data_sheets():
    """
    Ultra-fast sheet wiping (< 1 second) using a single Google Sheets API batch_update request.
    Wipes all data rows (row 2 onwards) across Service, Upgrades, Kits, Expenses, Transactions,
    Dashboard, and Employee Tracker sheets, and resets cached state for fresh re-scanning.
    """
    global _LOGGED_IDS_CACHE, _ROWS_CACHE, _LAST_KNOWN_ROWS, _WORKSHEET_CACHE
    _LOGGED_IDS_CACHE = set()
    _ROWS_CACHE.clear()
    _LAST_KNOWN_ROWS.clear()
    _WORKSHEET_CACHE.clear()

    try:
        ss = get_spreadsheet()
        sheets_and_headers = [
            ("Service", SERVICE_HEADERS),
            ("Upgrades", REVENUE_HEADERS),
            ("Kits", KIT_HEADERS),
            ("Expenses", EXPENSE_HEADERS),
            ("Transactions", TRANSACTIONS_HEADERS),
            ("Employee Tracker", EMPLOYEE_TRACKER_HEADERS),
        ]

        batch_requests = []
        for ws_name, headers in sheets_and_headers:
            try:
                ws = _ensure_sheet(ws_name, headers)
                # Ensure row 1 headers are accurate (e.g. Transactions 5 columns)
                _with_retry(lambda: ws.update("A1", [headers]))
                batch_requests.append({
                    "updateCells": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 1,  # clear row 2 onwards
                        },
                        "fields": "userEnteredValue"
                    }
                })
            except Exception as e:
                import logging
                logging.getLogger("sheets").error(f"Error preparing wipe for {ws_name}: {e}")

        if batch_requests:
            _with_retry(lambda: ss.batch_update({"requests": batch_requests}))

        try:
            ws_txn = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
            _apply_transactions_dropdown(ws_txn)
        except Exception:
            pass

        reset_dashboard_to_zero()
        clear_rows_cache()
        print("All sheets successfully wiped via fast batch request for fresh re-scan.")
        return True
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"wipe_all_data_sheets failed: {e}")
        return False


def setup_all_sheets():
    """Call once at startup — makes sure every sheet + dashboard + employee tracker exist."""
    _ensure_sheet("Service", SERVICE_HEADERS)
    _ensure_sheet("Upgrades", REVENUE_HEADERS)
    _ensure_sheet("Kits", KIT_HEADERS)
    _ensure_sheet("Expenses", EXPENSE_HEADERS)
    _ensure_sheet("Inventory", INVENTORY_HEADERS)
    _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    _ensure_employee_tracker()
    _ensure_dashboard()
    clean_non_july_logs()
    clean_invalid_customer_names()
    clean_invalid_service_amounts()
    clean_transactions_sheet()

    update_dashboard()
    update_employee_tracker()


def append_expense_entry(amount, employee: str, category: str = "General", desc: str = "", created_at: datetime.datetime = None):
    try:
        amt = float(amount)
        if amt <= 0:
            return
    except (ValueError, TypeError):
        return

    ws = _ensure_sheet("Expenses", EXPENSE_HEADERS)
    ts = _get_ist_dt(created_at).strftime(TIMESTAMP_FORMAT)
    resolved_emp = resolve_name(employee)
    row = [ts, amt, resolved_emp, category, desc, ""]
    _with_retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))
    clear_rows_cache("Expenses")


def save_inventory_item_to_sheet(item_name: str, qty: int, bought_month: int, restock_date: str, unit_price: float):
    ws = _ensure_sheet("Inventory", INVENTORY_HEADERS)
    rows = _all_rows("Inventory")
    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    tot_val = qty * unit_price

    found_idx = -1
    for idx, r in enumerate(rows, start=2):
        if r and r[0].strip().lower() == item_name.strip().lower():
            found_idx = idx
            break

    row_values = [item_name.strip(), qty, bought_month, restock_date, unit_price, tot_val, now_str]

    if found_idx > 1:
        _with_retry(lambda: ws.update(f"A{found_idx}:G{found_idx}", [row_values]))
    else:
        _with_retry(lambda: ws.append_row(row_values, value_input_option="USER_ENTERED"))

    clear_rows_cache("Inventory")


def delete_inventory_row_from_sheet(item_name: str):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS
    item_lower = item_name.strip().lower()

    # 1. Instantly purge from memory caches
    if "Inventory" in _LAST_KNOWN_ROWS:
        _LAST_KNOWN_ROWS["Inventory"] = [r for r in _LAST_KNOWN_ROWS["Inventory"] if r and r[0].strip().lower() != item_lower]
    if "Inventory" in _ROWS_CACHE:
        _ROWS_CACHE["Inventory"] = (time.time(), _LAST_KNOWN_ROWS.get("Inventory", []))

    # 2. Asynchronously delete from Google Sheets API
    def _do_cloud_delete():
        try:
            ws = _ensure_sheet("Inventory", INVENTORY_HEADERS)
            all_vals = _with_retry(lambda: ws.get_all_values())
            for idx, r in enumerate(all_vals, start=1):
                if idx > 1 and r and r[0].strip().lower() == item_lower:
                    _with_retry(lambda: ws.delete_rows(idx))
                    break
        except Exception as e:
            import logging
            logging.getLogger("sheets").error(f"delete_inventory_row_from_sheet error: {e}")

    threading.Thread(target=_do_cloud_delete, daemon=True).start()


def delete_expense_row_from_sheet(timestamp_str: str, amount_val: float):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS

    # 1. Instantly purge from memory caches
    if "Expenses" in _LAST_KNOWN_ROWS:
        new_exp_rows = []
        for r in _LAST_KNOWN_ROWS["Expenses"]:
            if not r:
                continue
            amt_str = r[1].replace('.','',1).replace(',','').replace('-','').strip() if len(r) > 1 else "0"
            amt = float(amt_str) if amt_str.isdigit() else 0.0
            if r[0] == timestamp_str or (amount_val > 0 and abs(amt - amount_val) < 1):
                continue
            new_exp_rows.append(r)
        _LAST_KNOWN_ROWS["Expenses"] = new_exp_rows

    if "Expenses" in _ROWS_CACHE:
        _ROWS_CACHE["Expenses"] = (time.time(), _LAST_KNOWN_ROWS.get("Expenses", []))

    # 2. Asynchronously delete from Google Sheets API
    def _do_cloud_delete():
        try:
            ws = _ensure_sheet("Expenses", EXPENSE_HEADERS)
            all_vals = _with_retry(lambda: ws.get_all_values())
            for idx, r in enumerate(all_vals, start=1):
                if idx > 1 and r and len(r) > 1:
                    amt_str = r[1].replace('.','',1).replace(',','').replace('-','').strip()
                    amt = float(amt_str) if amt_str.isdigit() else 0.0
                    if r[0] == timestamp_str or (amount_val > 0 and abs(amt - amount_val) < 1):
                        _with_retry(lambda: ws.delete_rows(idx))
                        break
        except Exception as e:
            import logging
            logging.getLogger("sheets").error(f"delete_expense_row_from_sheet error: {e}")

    threading.Thread(target=_do_cloud_delete, daemon=True).start()


def mark_vip_claim_as_claimed_in_sheet(timestamp_str: str, customer_name: str):
    global _ROWS_CACHE, _LAST_KNOWN_ROWS
    cust_lower = customer_name.strip().lower()

    # 1. Update memory cache instantly
    if "VIP Claim" in _LAST_KNOWN_ROWS:
        for r in _LAST_KNOWN_ROWS["VIP Claim"]:
            if r and ((len(r) > 5 and r[5] == timestamp_str) or (len(r) > 0 and r[0].strip().lower() == cust_lower)):
                while len(r) < 7:
                    r.append("")
                r[6] = "Claimed"

    if "VIP Claim" in _ROWS_CACHE:
        _ROWS_CACHE["VIP Claim"] = (time.time(), _LAST_KNOWN_ROWS.get("VIP Claim", []))

    # 2. Update Google Sheets API asynchronously
    def _do_cloud_mark():
        try:
            ws = _ensure_sheet("VIP Claim", ["Customer Name", "Vehicle Claimed", "Staff Name", "Msg ID", "Amount", "Timestamp", "Status"])
            all_vals = _with_retry(lambda: ws.get_all_values())
            for idx, r in enumerate(all_vals, start=1):
                if idx > 1 and r:
                    ts_match = len(r) > 5 and r[5] == timestamp_str
                    cust_match = len(r) > 0 and r[0].strip().lower() == cust_lower
                    if ts_match or cust_match:
                        _with_retry(lambda: ws.update_cell(idx, 7, "Claimed"))
                        break
        except Exception as e:
            import logging
            logging.getLogger("sheets").error(f"mark_vip_claim_as_claimed_in_sheet error: {e}")

    threading.Thread(target=_do_cloud_mark, daemon=True).start()


def append_transaction_entry(amount, employee: str, category: str, description: str = "", created_at: datetime.datetime = None, skip_tracker_update: bool = False):
    """Logs one row to the consolidated Transactions ledger — Date (only DD/MM/YYYY when posted in Discord),
    Transaction Amount, Description, Transaction Type (Category), and Employee Name.
    Never logs entries with $0 or invalid amounts.
    Automatically triggers Employee Tracker sheet update unless skip_tracker_update is True."""
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
    date_str = dt_ist.strftime("%d/%m/%Y")
    _with_retry(lambda: ws.append_row([date_str, num_amount, description or "", category, employee or "Unknown"]))
    clear_rows_cache("Transactions")

    if not skip_tracker_update:
        try:
            update_employee_tracker()
        except Exception as e:
            import logging
            logging.getLogger("sheets").error(f"Employee Tracker update failed: {e}")


def append_service_entry(customer: str, category: str, total, employee: str, message_id: str, count=None, created_at: datetime.datetime = None):
    """Logs a service invoice with timestamp (date + time in IST) when posted in Discord."""
    ws = _ensure_sheet("Service", SERVICE_HEADERS)
    dt_ist = _get_ist_dt(created_at)
    timestamp = dt_ist.strftime(TIMESTAMP_FORMAT)
    _with_retry(lambda: ws.append_row([
        timestamp,
        customer or "Unknown",
        category or "Unspecified",
        count if count is not None else "",
        total,
        employee,
        message_id,
    ]))
    clear_rows_cache("Service")
    add_logged_message_id(str(message_id))


def append_kit_entry(customer: str, rk_qty: int, ck_qty: int, discount_pct: float,
                      total: float, employee: str, message_id: str, created_at: datetime.datetime = None):
    """Logs a Repair Kit / Cleaning Kit sale with timestamp (date + time in IST) when posted in Discord."""
    ws = _ensure_sheet("Kits", KIT_HEADERS)
    dt_ist = _get_ist_dt(created_at)
    timestamp = dt_ist.strftime(TIMESTAMP_FORMAT)
    _with_retry(lambda: ws.append_row([
        timestamp,
        customer or "Unknown",
        rk_qty,
        ck_qty,
        discount_pct,
        total,
        employee,
        message_id,
    ]))
    clear_rows_cache("Kits")
    add_logged_message_id(str(message_id))


def append_entry(sheet_name: str, customer: str, value, employee: str, message_id: str, created_at: datetime.datetime = None):
    ws = _ensure_sheet(sheet_name, REVENUE_HEADERS)
    dt_ist = _get_ist_dt(created_at)
    timestamp = dt_ist.strftime(TIMESTAMP_FORMAT)
    row = [timestamp, customer or "Unknown", value, employee, message_id]

    # The invoice row itself is the important part — save it first, and let
    # any failure here surface to the caller (bot.py) as a real save failure.
    _with_retry(lambda: ws.append_row(row))
    clear_rows_cache(sheet_name)
    add_logged_message_id(str(message_id))

    try:
        update_dashboard()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"Dashboard update failed (invoice was still saved): {e}")


def append_expense_entry(amount, employee: str, message_id: str, created_at: datetime.datetime = None):
    """Logs an expense/bill claim with timestamp (date + time in IST) when posted in Discord."""
    ws = _ensure_sheet("Expenses", EXPENSE_HEADERS)
    dt_ist = _get_ist_dt(created_at)
    timestamp = dt_ist.strftime(TIMESTAMP_FORMAT)
    _with_retry(lambda: ws.append_row([
        timestamp,
        amount,
        employee or "Unknown",
        message_id,
    ]))
    clear_rows_cache("Expenses")
    add_logged_message_id(str(message_id))
    try:
        update_dashboard()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"Dashboard update failed: {e}")


def append_vip_claim_entry(person_name: str, category: str, vehicle: str, staff: str, amount: float, message_id: str, created_at: datetime.datetime = None):
    """Logs a VIP Mech Claim entry with exact columns: Person Name, Category, Vehicle, Staff, Amount, Timestamp, Message ID."""
    ws = _ensure_sheet("VIP Claim", VIP_CLAIM_HEADERS)
    dt_ist = _get_ist_dt(created_at)
    timestamp = dt_ist.strftime(TIMESTAMP_FORMAT)
    _with_retry(lambda: ws.append_row([
        person_name or "Unknown",
        category or "VIP",
        vehicle or "Unknown",
        staff or "Unknown",
        amount if amount is not None else 0,
        timestamp,
        message_id,
    ]))
    clear_rows_cache("VIP Claim")
    add_logged_message_id(str(message_id))
    try:
        update_dashboard()
    except Exception as e:
        import logging
        logging.getLogger("sheets").error(f"Dashboard update failed: {e}")


def get_all_logged_message_ids(force_refresh=False) -> set:
    """Returns set of all message IDs logged across Service, Upgrades, Kits, Expenses, and VIP Claim sheets."""
    global _LOGGED_IDS_CACHE
    if not force_refresh and _LOGGED_IDS_CACHE is not None:
        return _LOGGED_IDS_CACHE

    logged = set()
    for ws_name, msg_col in [("Service", 6), ("Upgrades", 4), ("Kits", 7), ("Expenses", 3), ("VIP Claim", 6)]:
        for r in _all_rows(ws_name):
            if len(r) > msg_col and r[msg_col].strip():
                logged.add(r[msg_col].strip())
    _LOGGED_IDS_CACHE = logged
    return logged


def add_logged_message_id(msg_id: str):
    """Instantly adds a message ID to the in-memory cache to maintain 0ms duplicate lookups."""
    global _LOGGED_IDS_CACHE
    if _LOGGED_IDS_CACHE is not None and msg_id:
        _LOGGED_IDS_CACHE.add(str(msg_id))


def set_official_expenses():
    """Sets the Expenses sheet to the exact 12 official manual entries from Image 2."""
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet("Expenses")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="Expenses", rows=200, cols=4)

    official_rows = [
        EXPENSE_HEADERS,
        ["2026-07-01 12:00:00 AM", "74000", "Manual (Food and Water)", "MANUAL_01"],
        ["2026-07-01 11:46:25 PM", "407300", "Amul (Sicily Logistics ID: 92)", "1521942571520229542"],
        ["2026-07-02 05:27:31 PM", "377300", "Amul (Yazhi Logistics Id: 374)", "1522209607899152425"],
        ["2026-07-03 03:42:31 PM", "1392250", "Amul (Yazhi Logistics Id: 378)", "1522545568709345392"],
        ["2026-07-03 03:42:38 PM", "70000", "Amul (Yazhi Logistics Id: 380)", "1522545599025647686"],
        ["2026-07-04 09:45:51 AM", "490000", "Amul (Yazhi Logistics ID: 381)", "1522818201526865930"],
        ["2026-07-06 05:33:02 PM", "290800", "Amul (Yazhi Logistics ID: 386)", "1523660547684307065"],
        ["2026-07-09 11:10:27 AM", "290850", "Amul (Sicily Logistics ID: 102)", "1524651429195681832"],
        ["2026-07-06 12:00:00 PM", "234800", "Amul (Km Logistics ID: 31)", "MANUAL_02"],
        ["2026-07-10 12:00:00 PM", "1181700", "Amul (Yazhi Logistics: 391,389)", "MANUAL_03"],
        ["2026-07-10 03:49:28 PM", "506475", "Amul (Sicily Logistics: 106)", "1525446423384948806"],
        ["2026-07-12 09:19:46 PM", "506475", "Amul (Sicily Logistics ID: 32)", "1525891934022013139"],
        ["2026-07-17 08:44:59 PM", "414800", "Amul (Yaazhi Logistics Order 403)", "1527695119682375882"],
        ["2026-07-17 09:22:11 PM", "414800", "Amul (Sicily Logistics Code 89)", "1527704481414906147"],
    ]

    ws.clear()
    ws.update("A1", official_rows)
    clear_rows_cache("Expenses")
    try:
        update_dashboard()
    except Exception:
        pass


def reset_all_data_sheets():
    """Wipes all data rows across Service, Upgrades, Kits, Expenses, Transactions, and Employee Tracker sheets."""
    ss = get_spreadsheet()
    sheets_and_headers = [
        ("Service", SERVICE_HEADERS),
        ("Upgrades", REVENUE_HEADERS),
        ("Kits", KIT_HEADERS),
        ("Expenses", EXPENSE_HEADERS),
        ("Transactions", TRANSACTIONS_HEADERS),
        ("Employee Tracker", EMPLOYEE_TRACKER_HEADERS),
    ]
    for ws_name, headers in sheets_and_headers:
        try:
            ws = ss.worksheet(ws_name)
            ws.clear()
            ws.append_row(headers)
        except Exception as e:
            import logging
            logging.getLogger("sheets").error(f"Failed to reset sheet {ws_name}: {e}")
    clear_rows_cache()
    try:
        update_dashboard()
    except Exception:
        pass
    try:
        update_employee_tracker()
    except Exception:
        pass


# ── Dashboard ────────────────────────────────────────────

def _ensure_dashboard():
    ss = get_spreadsheet()
    try:
        ws = _with_retry(lambda: ss.worksheet(config.DASHBOARD_SHEET_NAME))
    except gspread.WorksheetNotFound:
        ws = _with_retry(lambda: ss.add_worksheet(title=config.DASHBOARD_SHEET_NAME, rows=200, cols=10))
    return ws





def _sum_numeric(values):
    total = 0.0
    for v in values:
        try:
            total += float(v)
        except (ValueError, TypeError):
            continue
    return total


def filter_rows_by_period(rows, period="all"):
    """Filters rows by timestamp period: all, today, week, month, year."""
    if not period or period.lower() == "all":
        return rows

    now = now_ist()
    period = period.lower()
    filtered = []

    for r in rows:
        if not r or len(r) == 0 or not r[0]:
            continue

        raw_ts = str(r[0]).strip()
        dt = None
        for fmt in (TIMESTAMP_FORMAT, LEGACY_TIMESTAMP_FORMAT, "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(raw_ts, fmt).replace(tzinfo=IST)
                break
            except Exception:
                continue

        if not dt:
            filtered.append(r)
            continue

        if period == "today":
            if dt.date() == now.date():
                filtered.append(r)
        elif period == "week":
            if (now - dt).days <= 7:
                filtered.append(r)
        elif period == "month":
            if dt.year == now.year and dt.month == now.month:
                filtered.append(r)
        elif period == "year":
            if dt.year == now.year:
                filtered.append(r)
        else:
            filtered.append(r)

    return filtered


def get_dynamic_revenue_trend(rows_by_sheet, period="all"):
    """Group revenue and expenses by date/hour for line chart rendering."""
    events = []

    for sname in ("Service", "Upgrades", "Kits", "VIP Claim"):
        col_amt = _AMOUNT_COL.get(sname, 4)
        for r in rows_by_sheet.get(sname, []):
            if len(r) > col_amt and r[0]:
                amt = _sum_numeric([r[col_amt]])
                dt = None
                for fmt in (TIMESTAMP_FORMAT, LEGACY_TIMESTAMP_FORMAT, "%Y-%m-%d"):
                    try:
                        dt = datetime.datetime.strptime(str(r[0]).strip(), fmt).replace(tzinfo=IST)
                        break
                    except Exception:
                        continue
                if dt:
                    events.append((dt, amt, 0.0))

    col_exp = _AMOUNT_COL.get("Expenses", 1)
    for r in rows_by_sheet.get("Expenses", []):
        if len(r) > col_exp and r[0]:
            amt = _sum_numeric([r[col_exp]])
            dt = None
            for fmt in (TIMESTAMP_FORMAT, LEGACY_TIMESTAMP_FORMAT, "%Y-%m-%d"):
                try:
                    dt = datetime.datetime.strptime(str(r[0]).strip(), fmt).replace(tzinfo=IST)
                    break
                except Exception:
                    continue
            if dt:
                events.append((dt, 0.0, amt))

    if not events:
        return [
            {"label": "Start", "revenue": 0, "profit": 0},
            {"label": "Today", "revenue": 0, "profit": 0}
        ]

    events.sort(key=lambda x: x[0])
    grouped = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0})

    p_clean = period.lower() if period else "all"
    if p_clean == "today":
        fmt = "%I %p"
    elif p_clean in ("week", "month"):
        fmt = "%b %d"
    else:
        fmt = "%m-%d"

    for dt, rev, exp in events:
        label = dt.strftime(fmt)
        grouped[label]["revenue"] += rev
        grouped[label]["expense"] += exp

    trend = []
    for label, vals in grouped.items():
        r = round(vals["revenue"], 2)
        p = round(vals["revenue"] - vals["expense"], 2)
        trend.append({"label": label, "revenue": r, "profit": p})

    if len(trend) == 1:
        trend.insert(0, {"label": "Start", "revenue": 0, "profit": 0})

    return trend


def get_top_services_breakdown(rows_by_sheet):
    """Calculates live category counts and revenue share from Google Sheets data separating Civilian vs Government services."""
    civ_count = 0
    govt_count = 0
    civ_amt = 0.0
    govt_amt = 0.0

    col_svc_amt = _AMOUNT_COL.get("Service", 4)
    for r in rows_by_sheet.get("Service", []):
        amt = _sum_numeric([r[col_svc_amt]]) if len(r) > col_svc_amt else 3000.0
        row_str = " ".join([str(cell).lower() for cell in r[:4]])
        is_govt = any(g in row_str for g in ("pd", "ems", "taxi", "govt", "government", "cop", "police", "medic"))
        if is_govt or (amt >= 5000 and amt % 5000 == 0 and amt % 3000 != 0):
            cnt = max(1, int(round(amt / 5000.0))) if amt >= 5000 else 1
            govt_count += cnt
            govt_amt += amt
        else:
            cnt = max(1, int(round(amt / 3000.0))) if amt >= 3000 else 1
            civ_count += cnt
            civ_amt += amt

    upg_count = len(rows_by_sheet.get("Upgrades", []))
    kit_count = len(rows_by_sheet.get("Kits", []))
    vip_count = len(rows_by_sheet.get("VIP Claim", []))

    col_upg = _AMOUNT_COL.get("Upgrades", 2)
    col_kit = _AMOUNT_COL.get("Kits", 5)
    col_vip = _AMOUNT_COL.get("VIP Claim", 4)

    upg_amt = _sum_numeric([r[col_upg] for r in rows_by_sheet.get("Upgrades", []) if len(r) > col_upg])
    kit_amt = _sum_numeric([r[col_kit] for r in rows_by_sheet.get("Kits", []) if len(r) > col_kit])
    vip_amt = _sum_numeric([r[col_vip] for r in rows_by_sheet.get("VIP Claim", []) if len(r) > col_vip])

    raw_items = [
        {"name": "Civilian Service (₹3k)", "count": civ_count, "amount": civ_amt, "color": "#6C4DFF"},
        {"name": "Govt Service (PD/EMS/₹5k)", "count": govt_count, "amount": govt_amt, "color": "#2A8DFF"},
        {"name": "Upgrades Installed", "count": upg_count, "amount": upg_amt, "color": "#19D96B"},
        {"name": "Kits Issued", "count": kit_count, "amount": kit_amt, "color": "#F9A826"},
        {"name": "VIP Claims", "count": vip_count, "amount": vip_amt, "color": "#E056FD"},
    ]

    raw_items.sort(key=lambda x: x["count"], reverse=True)
    max_count = max([x["count"] for x in raw_items]) if raw_items else 1

    for item in raw_items:
        percent = int((item["count"] / max(1, max_count)) * 100)
        item["percent"] = max(12, percent)

    return raw_items


# Column index (0-based) of "Employee" and "Total Amount" per sheet
_EMPLOYEE_COL = {"Service": 5, "Upgrades": 3, "Kits": 6, "Expenses": 2, "VIP Claim": 3}
_AMOUNT_COL = {"Service": 4, "Upgrades": 2, "Kits": 5, "Expenses": 1, "VIP Claim": 4}


def resolve_employee(raw_name: str) -> str:
    if not raw_name:
        return "Unknown"
    cleaned = raw_name.strip()
    tag_clean = "@" + cleaned.lstrip("@").lower()
    if tag_clean in config.EMPLOYEE_MAPPING:
        return config.EMPLOYEE_MAPPING[tag_clean]
    for emp_val in config.EMPLOYEE_MAPPING.values():
        if emp_val.lower() == cleaned.lower():
            return emp_val
    return cleaned


def get_rich_leaderboard(rows_by_sheet):
    """Generates detailed employee performance metrics per mechanic with stable deterministic sorting."""
    stats = {}

    emp_set = set(config.EMPLOYEE_MAPPING.values())
    emp_set.update(["Eli", "Meenu", "AMULPAPPU"])

    for emp_name in emp_set:
        rev_map = getattr(config, "REVERSE_MAPPING", {})
        tag = rev_map.get(emp_name, f"@{emp_name.lower().replace(' ', '')}")
        stats[emp_name] = {
            "name": emp_name,
            "tag": tag,
            "civilian_service": 0,
            "govt_service": 0,
            "service": 0,
            "kits": 0,
            "upgrades": 0,
            "total_logs": 0,
            "points": 0
        }

    for r in rows_by_sheet.get("Service", []):
        if not r or len(r) < 2:
            continue

        # Detect employee column index dynamically
        emp_raw = ""
        if len(r) > 5 and r[5].strip():
            emp_raw = r[5]
        elif len(r) > 3 and r[3].strip() and not r[3].strip().isdigit():
            emp_raw = r[3]
        elif len(r) > 1 and r[1].strip():
            emp_raw = r[1]

        if not emp_raw:
            continue

        emp = resolve_employee(emp_raw)
        if emp not in stats:
            stats[emp] = {
                "name": emp,
                "tag": f"@{emp.lower().replace(' ', '')}",
                "civilian_service": 0,
                "govt_service": 0,
                "service": 0,
                "kits": 0,
                "upgrades": 0,
                "total_logs": 0,
                "points": 0
            }

        # Detect total amount
        col_amt = _AMOUNT_COL.get("Service", 4)
        amt = 3000.0
        if len(r) > col_amt:
            amt = _sum_numeric([r[col_amt]])
        elif len(r) > 2 and _sum_numeric([r[2]]) > 0:
            amt = _sum_numeric([r[2]])

        if amt <= 0:
            amt = 3000.0

        # Check Category column (col 2) and row text
        cat_val = str(r[2]).strip().lower() if len(r) > 2 else ""
        row_str = " ".join([str(cell).lower() for cell in r[:5]])

        is_govt = ("govt" in cat_val or "government" in cat_val or "pd" in cat_val or "ems" in cat_val or "taxi" in cat_val or
                   any(g in row_str for g in ("pd", "ems", "taxi", "govt", "government", "cop", "police", "medic")) or
                   (amt >= 5000 and amt % 5000 == 0 and amt % 3000 != 0))

        if is_govt:
            cnt = max(1, int(round(amt / 5000.0))) if amt >= 5000 else 1
            stats[emp]["govt_service"] += cnt
            stats[emp]["service"] += cnt
        else:
            cnt = max(1, int(round(amt / 3000.0))) if amt >= 3000 else 1
            stats[emp]["civilian_service"] += cnt
            stats[emp]["service"] += cnt

    for r in rows_by_sheet.get("Kits", []):
        if not r or len(r) < 2:
            continue
        emp_raw = r[6] if len(r) > 6 and r[6].strip() else (r[3] if len(r) > 3 and r[3].strip() else "")
        if emp_raw:
            emp = resolve_employee(emp_raw)
            if emp not in stats:
                stats[emp] = {
                    "name": emp,
                    "tag": f"@{emp.lower().replace(' ', '')}",
                    "civilian_service": 0,
                    "govt_service": 0,
                    "service": 0,
                    "kits": 0,
                    "upgrades": 0,
                    "total_logs": 0,
                    "points": 0
                }
            stats[emp]["kits"] += 1

    for r in rows_by_sheet.get("Upgrades", []):
        if not r or len(r) < 2:
            continue
        emp_raw = r[3] if len(r) > 3 and r[3].strip() else (r[1] if len(r) > 1 and r[1].strip() else "")
        if emp_raw:
            emp = resolve_employee(emp_raw)
            if emp not in stats:
                stats[emp] = {
                    "name": emp,
                    "tag": f"@{emp.lower().replace(' ', '')}",
                    "civilian_service": 0,
                    "govt_service": 0,
                    "service": 0,
                    "kits": 0,
                    "upgrades": 0,
                    "total_logs": 0,
                    "points": 0
                }
            stats[emp]["upgrades"] += 1

    for emp_info in stats.values():
        tot = emp_info["civilian_service"] + emp_info["govt_service"] + emp_info["kits"] + emp_info["upgrades"]
        emp_info["total_logs"] = tot
        emp_info["points"] = tot

    # Stable deterministic sorting by (-total_logs, -service, name)
    sorted_list = sorted(stats.values(), key=lambda x: (-x["total_logs"], -x["service"], x["name"]))

    for rank, item in enumerate(sorted_list, start=1):
        item["rank"] = rank

    return sorted_list


def update_dashboard():
    ws = _ensure_dashboard()

    rows_by_sheet = {
        "Service": _all_rows("Service"),
        "Upgrades": _all_rows("Upgrades"),
        "Kits": _all_rows("Kits"),
        "Expenses": _all_rows("Expenses"),
    }

    service_total = _sum_numeric([r[_AMOUNT_COL["Service"]] for r in rows_by_sheet["Service"] if len(r) > _AMOUNT_COL["Service"]])
    upgrade_total = _sum_numeric([r[_AMOUNT_COL["Upgrades"]] for r in rows_by_sheet["Upgrades"] if len(r) > _AMOUNT_COL["Upgrades"]])
    kits_total = _sum_numeric([r[_AMOUNT_COL["Kits"]] for r in rows_by_sheet["Kits"] if len(r) > _AMOUNT_COL["Kits"]])
    expenses_total = _sum_numeric([r[_AMOUNT_COL["Expenses"]] for r in rows_by_sheet["Expenses"] if len(r) > _AMOUNT_COL["Expenses"]])

    total_sales = service_total + upgrade_total + kits_total
    net_profit = total_sales - expenses_total

    daily = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], today_only=True)
        for name in rows_by_sheet
    }
    daily_sales = daily["Service"] + daily["Upgrades"] + daily["Kits"]
    daily_expenses = daily["Expenses"]
    daily_profit = daily_sales - daily_expenses

    weekly = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], days=7)
        for name in rows_by_sheet
    }
    weekly_sales = weekly["Service"] + weekly["Upgrades"] + weekly["Kits"]
    weekly_expenses = weekly["Expenses"]
    weekly_profit = weekly_sales - weekly_expenses

    monthly = {
        name: _revenue_window(rows_by_sheet[name], value_col=_AMOUNT_COL[name], this_month=True)
        for name in rows_by_sheet
    }
    monthly_sales = monthly["Service"] + monthly["Upgrades"] + monthly["Kits"]
    monthly_expenses = monthly["Expenses"]
    monthly_profit = monthly_sales - monthly_expenses

    leaderboard = _leaderboard(rows_by_sheet)
    updated_at = now_ist().strftime(TIMESTAMP_FORMAT) + " IST"

    rows = [
        ["CODE Jiraiya Customs and Tunerz — Financial Dashboard", ""],
        [f"Last updated: {updated_at}", ""],
        ["", ""],
        ["DAILY FINANCIALS (Today)", ""],
        ["Service Revenue", daily["Service"]],
        ["Upgrade Revenue", daily["Upgrades"]],
        ["Kits Revenue", daily["Kits"]],
        ["TOTAL SALES", daily_sales],
        ["TOTAL EXPENSES", daily_expenses],
        ["NET PROFIT", daily_profit],
        ["", ""],
        ["WEEKLY FINANCIALS (Last 7 Days)", ""],
        ["Service Revenue", weekly["Service"]],
        ["Upgrade Revenue", weekly["Upgrades"]],
        ["Kits Revenue", weekly["Kits"]],
        ["TOTAL SALES", weekly_sales],
        ["TOTAL EXPENSES", weekly_expenses],
        ["NET PROFIT", weekly_profit],
        ["", ""],
        ["MONTHLY FINANCIALS (This Month)", ""],
        ["Service Revenue", monthly["Service"]],
        ["Upgrade Revenue", monthly["Upgrades"]],
        ["Kits Revenue", monthly["Kits"]],
        ["TOTAL SALES", monthly_sales],
        ["TOTAL EXPENSES", monthly_expenses],
        ["NET PROFIT", monthly_profit],
        ["", ""],
        ["ALL-TIME FINANCIALS", ""],
        ["Total Service Revenue", service_total],
        ["Total Upgrade Revenue", upgrade_total],
        ["Total Kits Revenue", kits_total],
        ["TOTAL SALES", total_sales],
        ["TOTAL EXPENSES", expenses_total],
        ["NET PROFIT", net_profit],
        ["", ""],
        ["EMPLOYEE LEADERBOARD (invoices/bills processed)", ""],
    ]
    for name, count in leaderboard:
        rows.append([name, count])

    _with_retry(lambda: ws.clear())
    _with_retry(lambda: ws.update("A1", rows))


# ── Employee Tracker ─────────────────────────────────────

def _ensure_employee_tracker():
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet("Employee Tracker")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="Employee Tracker", rows=500, cols=len(EMPLOYEE_TRACKER_HEADERS))
        ws.append_row(EMPLOYEE_TRACKER_HEADERS)
    return ws


def resolve_name(raw_name: str) -> str:
    if not raw_name:
        return "Unknown"
    cleaned = raw_name.strip().lstrip("@").lower()
    mapping = {k.strip().lstrip("@").lower(): v for k, v in config.EMPLOYEE_MAPPING.items()}
    if cleaned in mapping:
        return mapping[cleaned]
    base = cleaned.split("#")[0]
    if base in mapping:
        return mapping[base]
    for official in config.EMPLOYEE_MAPPING.values():
        if official.lower() == cleaned:
            return official
    return raw_name.strip()


def update_employee_tracker():
    """
    Aggregates invoice counts across Service, Upgrades, and Kits sheets
    and populates the Employee Tracker sheet with accurate counts and dates per employee.
    """
    rows_by_sheet = {
        "Service": _all_rows("Service"),
        "Upgrades": _all_rows("Upgrades"),
        "Kits": _all_rows("Kits"),
    }

    valid_employees = set(config.EMPLOYEE_MAPPING.values())
    tracker_data = {
        emp: {"kit": 0, "service": 0, "upgrade": 0, "last_date": ""}
        for emp in valid_employees
    }

    # Service Sheet: Col 0 = Timestamp, Col 5 = Employee
    for row in rows_by_sheet["Service"]:
        if len(row) > 5 and row[5].strip():
            if row[0] and not (row[0].startswith("2026-07") or "/07/2026" in row[0] or "-07-2026" in row[0]):
                continue
            emp = resolve_name(row[5])
            if emp in valid_employees:
                tracker_data[emp]["service"] += 1
                if row[0]:
                    tracker_data[emp]["last_date"] = row[0].split()[0]

    # Upgrades Sheet: Col 0 = Timestamp, Col 3 = Employee
    for row in rows_by_sheet["Upgrades"]:
        if len(row) > 3 and row[3].strip():
            if row[0] and not (row[0].startswith("2026-07") or "/07/2026" in row[0] or "-07-2026" in row[0]):
                continue
            emp = resolve_name(row[3])
            if emp in valid_employees:
                tracker_data[emp]["upgrade"] += 1
                if row[0]:
                    tracker_data[emp]["last_date"] = row[0].split()[0]

    # Kits Sheet: Col 0 = Timestamp, Col 6 = Employee
    for row in rows_by_sheet["Kits"]:
        if len(row) > 6 and row[6].strip():
            if row[0] and not (row[0].startswith("2026-07") or "/07/2026" in row[0] or "-07-2026" in row[0]):
                continue
            emp = resolve_name(row[6])
            if emp in valid_employees:
                tracker_data[emp]["kit"] += 1
                if row[0]:
                    tracker_data[emp]["last_date"] = row[0].split()[0]

    # Sort employees by Total Transactions descending
    sorted_emps = sorted(
        tracker_data.items(),
        key=lambda item: (item[1]["kit"] + item[1]["service"] + item[1]["upgrade"]),
        reverse=True,
    )

    tracker_rows = [EMPLOYEE_TRACKER_HEADERS]
    for emp_name, stats in sorted_emps:
        kit_cnt = stats["kit"]
        svc_cnt = stats["service"]
        upg_cnt = stats["upgrade"]
        tot_cnt = kit_cnt + svc_cnt + upg_cnt
        last_date = stats["last_date"]
        tracker_rows.append([
            emp_name,
            kit_cnt,
            svc_cnt,
            upg_cnt,
            tot_cnt,
            last_date,
        ])

    ws_tracker = _ensure_employee_tracker()
    _with_retry(lambda: ws_tracker.clear())
    _with_retry(lambda: ws_tracker.update("A1", tracker_rows))


def clean_transactions_sheet():
    """
    Cleans up invalid entries in the Transactions sheet by removing:
    1. Rows where Category is 'Order' (expenses).
    2. Rows where Employee Name is not a recognized company employee (e.g. '10x', '20k', etc.).
    Also migrates legacy 4-column layout to 5-column layout (Date, Amount, Description, Transaction Type, Employee Name).
    """
    valid_employees = set(config.EMPLOYEE_MAPPING.values())
    ws_txn = _ensure_sheet("Transactions", TRANSACTIONS_HEADERS)
    rows = _with_retry(lambda: ws_txn.get_all_values())
    if not rows:
        return

    cleaned = [TRANSACTIONS_HEADERS]
    for row in rows[1:]:
        if not row or len(row) < 3:
            continue

        # Handle legacy 4-col rows: [Date, Amount, Employee, Type]
        if len(row) == 4 and row[3].strip() in config.TRANSACTION_CATEGORIES:
            dt_val = row[0].strip()
            amt_val = row[1].strip()
            emp_name = row[2].strip()
            txn_type = row[3].strip()
            desc_val = ""
        else:
            dt_val = row[0].strip() if len(row) > 0 else ""
            amt_val = row[1].strip() if len(row) > 1 else ""
            desc_val = row[2].strip() if len(row) > 2 else ""
            txn_type = row[3].strip() if len(row) > 3 else ""
            emp_name = row[4].strip() if len(row) > 4 else ""

        if txn_type.lower() == "order":
            continue
        if emp_name and emp_name not in valid_employees:
            continue

        cleaned.append([dt_val, amt_val, desc_val, txn_type, emp_name])

    _with_retry(lambda: ws_txn.clear())
    _with_retry(lambda: ws_txn.update("A1", cleaned))
    _apply_transactions_dropdown(ws_txn)
def mark_vip_claim_as_claimed_in_sheet(timestamp: str = "", customer: str = ""):
    """Marks a VIP Claim as 'Claimed' in Google Sheets tab 'VIP Claim' or 'VIP Log'."""
    try:
        sh = get_spreadsheet()
        if not sh: return False
        ws = None
        for name in ("VIP Claim", "VIP Log", "VIP Claims", "vip_claims"):
            try:
                ws = sh.worksheet(name)
                if ws: break
            except Exception: pass
        if not ws: return False

        rows = ws.get_all_values()
        cust_clean = customer.strip().lower() if customer else ""
        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 1:
                row_cust = str(r[1]).strip().lower()
                row_ts = str(r[0]).strip()
                if (cust_clean and cust_clean in row_cust) or (timestamp and timestamp in row_ts):
                    status_col = 6 if len(r) >= 6 else 5
                    ws.update_cell(idx, status_col, "Claimed")
                    clear_rows_cache()
                    print(f"[VIP Claim] Marked row {idx} as Claimed for {customer}")
                    return True
        return False
    except Exception as e:
        print(f"[Mark VIP Claim Error]: {e}")
        return False


def log_security_audit(username: str, role: str, action_type: str, ign: str = "", email: str = "", details: str = ""):
    """Logs user login, access requests, and role permission events to Google Sheets tab 'User_Audit_Logs'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return
        try:
            ws = sh.worksheet("User_Audit_Logs")
        except Exception:
            ws = sh.add_worksheet(title="User_Audit_Logs", rows=100, cols=10)
            ws.append_row(["Timestamp (IST)", "Action Type", "User Name", "In-Game Name (IGN)", "Email Address", "Role", "Details"])

        row = [now_ist().strftime(TIMESTAMP_FORMAT), action_type, username, ign or username, email or "N/A", role, details]
        ws.append_row(row)
        clear_rows_cache("User_Audit_Logs")
    except Exception as e:
        print(f"[Audit Log Error]: {e}")


def get_security_audit_logs():
    """Fetches recent security audit logs from Google Sheets 'User_Audit_Logs'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return []
        try:
            ws = sh.worksheet("User_Audit_Logs")
            rows = _with_retry(lambda: ws.get_all_values())
            if len(rows) <= 1:
                return []
            headers = [h.strip() for h in rows[0]]
            logs = []
            for r in rows[1:]:
                if len(r) >= 4:
                    logs.append({
                        "timestamp": r[0],
                        "action": r[1],
                        "user": r[2],
                        "ign": r[3] if len(r) > 3 else r[2],
                        "email": r[4] if len(r) > 4 else "",
                        "role": r[5] if len(r) > 5 else (r[3] if len(r) > 3 else "Employee"),
                        "details": r[6] if len(r) > 6 else ""
                    })
            return list(reversed(logs[-50:]))
        except Exception:
            return []
    except Exception as e:
        print(f"[Get Audit Logs Error]: {e}")
        return []


def get_user_roles():
    """Fetches user roles from Google Sheets tab 'User_Roles'."""
    default_roles = [
        {"username": "AMULPAPPU", "role": "Admin", "tag": "@Amulpappu", "updated": now_ist().strftime(TIMESTAMP_FORMAT)}
    ]
    try:
        sh = get_spreadsheet()
        if not sh:
            return default_roles
        try:
            ws = sh.worksheet("User_Roles")
        except Exception:
            ws = sh.add_worksheet(title="User_Roles", rows=50, cols=5)
            ws.append_row(["Username", "Role", "Discord Tag", "Last Updated (IST)"])
            for dr in default_roles:
                ws.append_row([dr["username"], dr["role"], dr["tag"], dr["updated"]])
            return default_roles

        rows = _with_retry(lambda: ws.get_all_values())
        if len(rows) <= 1:
            return default_roles

        user_map = {}
        for dr in default_roles:
            user_map[dr["username"].lower()] = dr

        for r in rows[1:]:
            if len(r) >= 2 and r[0].strip():
                u_name = r[0].strip()
                u_role = r[1].strip()
                u_tag = r[2].strip() if len(r) > 2 else f"@{u_name.lower()}"
                u_time = r[3].strip() if len(r) > 3 else now_ist().strftime(TIMESTAMP_FORMAT)
                user_map[u_name.lower()] = {
                    "username": u_name,
                    "role": u_role,
                    "tag": u_tag,
                    "updated": u_time
                }
        return list(user_map.values())
    except Exception as e:
        print(f"[Get User Roles Error]: {e}")
        return default_roles


def save_user_role(username: str, role: str, discord_tag: str = ""):
    """Updates or inserts a user's role in Google Sheets tab 'User_Roles'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return False
        try:
            ws = sh.worksheet("User_Roles")
        except Exception:
            ws = sh.add_worksheet(title="User_Roles", rows=50, cols=5)
            ws.append_row(["Username", "Role", "Discord Tag", "Last Updated (IST)"])

        rows = _with_retry(lambda: ws.get_all_values())
        updated = False
        now_str = now_ist().strftime(TIMESTAMP_FORMAT)
        u_lower = username.lower()

        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 0 and r[0].strip().lower() == u_lower:
                tag_val = discord_tag if discord_tag else (r[2].strip() if len(r) > 2 else f"@{username.lower()}")
                ws.update_cell(idx, 2, role)
                ws.update_cell(idx, 3, tag_val)
                ws.update_cell(idx, 4, now_str)
                updated = True
                break

        if not updated:
            tag_val = discord_tag if discord_tag else f"@{username.lower()}"
            ws.append_row([username, role, tag_val, now_str])

        log_security_audit(username, role, "ROLE_ASSIGNED", ign=username, details=f"Assigned {role} role in User Settings")
        clear_rows_cache("User_Roles")
        return True
    except Exception as e:
        print(f"[Save User Role Error]: {e}")
        return False


def remove_user_role(username: str):
    """Removes a user's role entry from Google Sheets tab 'User_Roles'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return False
        ws = None
        try:
            ws = sh.worksheet("User_Roles")
        except Exception:
            return False

        rows = _with_retry(lambda: ws.get_all_values())
        if not rows or len(rows) <= 1:
            return False

        u_lower = username.strip().lower()
        header = rows[0]
        new_rows = [header]
        removed = False

        for r in rows[1:]:
            if len(r) > 0 and r[0].strip():
                row_u = r[0].strip().lower()
                if row_u == u_lower or u_lower in row_u or row_u in u_lower:
                    removed = True
                    continue
            new_rows.append(r)

        if removed:
            _with_retry(lambda: ws.clear())
            _with_retry(lambda: ws.update("A1", new_rows))
            clear_rows_cache()
            log_security_audit(username, "None", "ACCESS_REVOKED", ign=username, details="User access revoked and deleted from Google Sheets")
            print(f"[Sheets Security] Deleted user '{username}' from User_Roles tab.")
            return True
        return False
    except Exception as e:
        print(f"[Remove User Role Error]: {e}")
        return False


def get_inventory_items():
    """Fetches all inventory stock items from Google Sheets tab 'Inventory'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return []
        try:
            ws = sh.worksheet("Inventory")
        except Exception:
            ws = sh.add_worksheet(title="Inventory", rows=100, cols=8)
            ws.append_row(["Item Name", "Quantity in Stock", "Bought This Month", "Restock Date", "Unit Cost (₹)", "Total Value (₹)", "Last Updated"])
            return []

        rows = ws.get_all_values()
        if len(rows) <= 1:
            return []

        items = []
        for r in rows[1:]:
            if len(r) > 0 and r[0].strip():
                item_name = r[0].strip()
                qty = int(_sum_numeric([r[1]])) if len(r) > 1 else 0
                bought = _sum_numeric([r[2]]) if len(r) > 2 else 0
                restock_date = r[3].strip() if len(r) > 3 and r[3].strip() else datetime.now().strftime("%Y-%m-%d")
                unit_price = _sum_numeric([r[4]]) if len(r) > 4 else 0
                total_value = _sum_numeric([r[5]]) if len(r) > 5 else (qty * unit_price)
                last_updated = r[6].strip() if len(r) > 6 else ""

                items.append({
                    "item_name": item_name,
                    "qty": qty,
                    "bought": bought,
                    "restock_date": restock_date,
                    "unit_price": unit_price,
                    "total_value": total_value,
                    "last_updated": last_updated
                })
        return items
    except Exception as e:
        print(f"[Get Inventory Items Error]: {e}")
        return []


def save_inventory_item(item_name: str, qty: int, bought: float, restock_date: str, unit_price: float):
    """Saves or updates an inventory item in Google Sheets tab 'Inventory' with robust caching and error handling."""
    now_str = now_ist().strftime(TIMESTAMP_FORMAT)
    total_val = float(qty) * float(unit_price)
    u_clean = item_name.strip()
    u_lower = u_clean.lower()
    new_row = [u_clean, str(qty), str(bought), str(restock_date), str(unit_price), str(total_val), now_str]

    # Update in-memory cache immediately so UI reflects change instantly (0ms latency)
    try:
        cached_rows = _LAST_KNOWN_ROWS.get("Inventory", [])
        updated_in_cache = False
        new_cached = []
        for r in cached_rows:
            if len(r) > 0 and r[0].strip().lower() == u_lower:
                new_cached.append(new_row)
                updated_in_cache = True
            else:
                new_cached.append(r)
        if not updated_in_cache:
            new_cached.append(new_row)
        _ROWS_CACHE["Inventory"] = (time.time(), new_cached)
        _LAST_KNOWN_ROWS["Inventory"] = new_cached
    except Exception as ex:
        print(f"[Inventory Cache Update Error]: {ex}")

    # Perform Google Sheets sync in background thread so HTTP response never blocks or fails
    def _sync_to_sheets():
        try:
            sh = get_spreadsheet()
            if not sh:
                return
            try:
                ws = sh.worksheet("Inventory")
            except Exception:
                ws = sh.add_worksheet(title="Inventory", rows=100, cols=8)
                ws.append_row(["Item Name", "Quantity in Stock", "Bought This Month", "Restock Date", "Unit Cost (₹)", "Total Value (₹)", "Last Updated"])

            rows = ws.get_all_values()
            updated = False
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) > 0 and r[0].strip().lower() == u_lower:
                    try:
                        ws.update(range_name=f"A{idx}:G{idx}", values=[new_row])
                    except Exception:
                        try:
                            ws.update_cell(idx, 2, str(qty))
                            ws.update_cell(idx, 5, str(unit_price))
                            ws.update_cell(idx, 6, str(total_val))
                            ws.update_cell(idx, 7, now_str)
                        except Exception: pass
                    updated = True
                    break

            if not updated:
                ws.append_row(new_row)
        except Exception as e:
            print(f"[Inventory Sheets Sync Error]: {e}")

    threading.Thread(target=_sync_to_sheets, daemon=True).start()
    return True


def delete_inventory_item(item_name: str):
    """Deletes an item row from Google Sheets tab 'Inventory'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return False
        ws = sh.worksheet("Inventory")
        rows = ws.get_all_values()
        u_lower = item_name.strip().lower()
        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 0 and r[0].strip().lower() == u_lower:
                ws.delete_rows(idx)
                break
        clear_rows_cache("Inventory")
        log_security_audit("System", "Inventory", "INVENTORY_DELETED", f"Item: {item_name}")
        return True
    except Exception as e:
        print(f"[Delete Inventory Item Error]: {e}")
        return False


def save_access_request(username: str, ign: str, email: str, role: str):
    """Saves a user access request into Google Sheets tab 'Access_Requests'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return False
        try:
            ws = sh.worksheet("Access_Requests")
        except Exception:
            ws = sh.add_worksheet(title="Access_Requests", rows=50, cols=6)
            ws.append_row(["Timestamp (IST)", "Username", "In Game Name", "Email", "Requested Role", "Status"])

        now_str = now_ist().strftime(TIMESTAMP_FORMAT)
        ws.append_row([now_str, username, ign, email, role, "Pending Approval"])
        clear_rows_cache("Access_Requests")
        log_security_audit(username, role, "ACCESS_REQUESTED", f"IGN: {ign}, Email: {email}")
        return True
    except Exception as e:
        print(f"[Save Access Request Error]: {e}")
        return False


def get_access_requests():
    """Fetches all pending access requests from Google Sheets tab 'Access_Requests'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return []
        try:
            ws = sh.worksheet("Access_Requests")
            rows = _with_retry(lambda: ws.get_all_values())
            if len(rows) <= 1:
                return []
            reqs = []
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 5:
                    reqs.append({
                        "row_idx": idx,
                        "timestamp": r[0],
                        "username": r[1],
                        "ign": r[2],
                        "email": r[3],
                        "role": r[4],
                        "status": r[5] if len(r) > 5 else "Pending Approval"
                    })
            return list(reversed(reqs))
        except Exception:
            return []
    except Exception as e:
        print(f"[Get Access Requests Error]: {e}")
        return []


def update_access_request_status(username: str, status: str):
    """Updates status for a user access request in Google Sheets tab 'Access_Requests'."""
    try:
        sh = get_spreadsheet()
        if not sh:
            return False
        try:
            ws = sh.worksheet("Access_Requests")
            rows = _with_retry(lambda: ws.get_all_values())
            u_clean = username.strip().lower()
            for idx, r in enumerate(rows[1:], start=2):
                if len(r) >= 2 and (r[1].strip().lower() == u_clean or r[2].strip().lower() == u_clean):
                    ws.update_cell(idx, 6, status)
                    clear_rows_cache("Access_Requests")
                    return True
        except Exception:
            return False
        return False
    except Exception as e:
        print(f"[Update Access Request Status Error]: {e}")
        return False


def preload_sheets_cache():
    """Pre-warms all worksheet caches in memory asynchronously for instant 15ms web response times."""
    def _bg_preloader():
        for s in ("Service", "Upgrades", "Kits", "Expenses", "VIP Claim", "Inventory"):
            try:
                _all_rows(s, force_refresh=True)
            except Exception:
                pass
    threading.Thread(target=_bg_preloader, daemon=True).start()

# Auto-start async cache pre-warming
preload_sheets_cache()

