import os
import sys
import time
import datetime
import json
from flask import Flask, jsonify, request, render_template, session, redirect, url_for

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import config
import sheets
import database

db = database.DatabaseManager()

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"), static_folder=os.path.join(APP_DIR, "static"))
app.secret_key = os.getenv("SECRET_KEY", "jiraiya-secret-key-2026")
application = app

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin2026")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD", "manager8686")
EMPLOYEE_PASSWORD = os.getenv("EMPLOYEE_PASSWORD", "employee7878")
IS_MAINTENANCE_MODE = False
MAINTENANCE_MESSAGE = "The website is currently undergoing scheduled maintenance. Please check back shortly!"


PERMISSIONS_FILE = os.path.join(APP_DIR, "role_permissions.json")

DEFAULT_ROLE_PERMISSIONS = {
    "Admin": {
        "dashboard": True,
        "employees": True,
        "transactions": True,
        "inventory": True,
        "audit": True,
        "maintenance": True,
        "wipe": True
    },
    "Manager": {
        "dashboard": True,
        "employees": True,
        "transactions": True,
        "inventory": True,
        "audit": False,
        "maintenance": False,
        "wipe": False
    },
    "Employee": {
        "dashboard": False,
        "employees": True,
        "transactions": True,
        "inventory": True,
        "audit": False,
        "maintenance": False,
        "wipe": False
    }
}


def load_role_permissions():
    if os.path.exists(PERMISSIONS_FILE):
        try:
            with open(PERMISSIONS_FILE, "r") as f:
                saved = json.load(f)
                perms = json.loads(json.dumps(DEFAULT_ROLE_PERMISSIONS))
                for role, options in saved.items():
                    if role in perms:
                        perms[role].update(options)
                return perms
        except Exception as e:
            print(f"[PERMISSIONS] Load error: {e}")
    return json.loads(json.dumps(DEFAULT_ROLE_PERMISSIONS))


def save_role_permissions(perms):
    try:
        with open(PERMISSIONS_FILE, "w") as f:
            json.dump(perms, f, indent=2)
        return True
    except Exception as e:
        print(f"[PERMISSIONS] Save error: {e}")
        return False


@app.route("/")
def index():
    user_name = session.get("user_name")
    role = session.get("user_role", "Visitor")
    if user_name and user_name.lower() not in ("guest", "visitor", "unknown"):
        try:
            sheets.append_user_audit_log(user_name, "FUSER_LOGIN", f"Web/App Auth Success ({role})", role=role)
        except Exception:
            pass
    return render_template("index.html", is_maintenance=IS_MAINTENANCE_MODE, maintenance_msg=MAINTENANCE_MESSAGE)


@app.route("/api/session", methods=["POST"])
def sync_user_session():
    data = request.get_json() or {}
    user_name = data.get("name", "").strip()
    role = data.get("role", "Employee").strip().title()

    if user_name and user_name.lower() not in ("guest", "visitor", "unknown"):
        session["user_name"] = user_name
        session["user_role"] = role
        session["is_admin"] = (role == "Admin")
        session["is_manager"] = (role in ("Admin", "Manager"))
        session["is_employee"] = True

        try:
            sheets.append_user_audit_log(user_name, "FUSER_LOGIN", f"Web/App Auth Success ({role})", role=role)
        except Exception:
            pass

        return jsonify({"success": True, "user_name": user_name, "user_role": role})

    return jsonify({"success": False}), 400


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/api/permissions", methods=["GET"])
def get_permissions():
    perms = load_role_permissions()
    return jsonify({"success": True, "permissions": perms})


@app.route("/api/permissions", methods=["POST"])
def update_permissions():
    data = request.get_json() or {}
    new_perms = data.get("permissions")
    password = data.get("password", "").strip()
    user_name = data.get("user_name", session.get("user_name", "Admin"))

    if password and password != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Admin password required to update access control!"}), 401

    if not new_perms or not isinstance(new_perms, dict):
        return jsonify({"success": False, "error": "Invalid permissions payload!"}), 400

    current = load_role_permissions()
    for r in ("Admin", "Manager", "Employee"):
        if r in new_perms and isinstance(new_perms[r], dict):
            for opt, val in new_perms[r].items():
                current[r][opt] = bool(val)

    if save_role_permissions(current):
        sheets.append_user_audit_log(user_name, "ROLE_PERMISSIONS_UPDATE", "Updated dynamic access control settings", role="Admin")
        return jsonify({"success": True, "message": "Access control permissions saved successfully!", "permissions": current})
    return jsonify({"success": False, "error": "Failed to save permissions file!"}), 500


@app.route("/api/status")
def get_status():
    return jsonify({
        "running": True,
        "status": "🟢 Operational" if not IS_MAINTENANCE_MODE else "⚠️ Under Maintenance",
        "sync_status": "🟢 Live Synced",
        "maintenance_mode": IS_MAINTENANCE_MODE,
        "timestamp": time.time()
    })


@app.route("/api/login", methods=["POST"])
def user_login():
    data = request.get_json() or {}
    user_name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "Admin").strip().title()

    if not user_name:
        return jsonify({"success": False, "error": "Please enter your Name!"}), 400
    if not password:
        return jsonify({"success": False, "error": "Please enter Password!"}), 400

    target_pass = ADMIN_PASSWORD
    if role == "Manager":
        target_pass = MANAGER_PASSWORD
    elif role == "Employee":
        target_pass = EMPLOYEE_PASSWORD

    if password != target_pass and password != ADMIN_PASSWORD:
        sheets.append_user_audit_log(user_name, "LOGIN_FAILED", f"Invalid Password Attempt for {role}", role=role)
        return jsonify({"success": False, "error": f"Invalid Password for {role} role! Access Denied."}), 401

    is_admin = (role == "Admin" or password == ADMIN_PASSWORD)
    is_manager = (role in ("Admin", "Manager") or password in (ADMIN_PASSWORD, MANAGER_PASSWORD))
    is_employee = True

    session["user_name"] = user_name
    session["user_role"] = role
    session["is_admin"] = is_admin
    session["is_manager"] = is_manager
    session["is_employee"] = is_employee

    sheets.append_user_audit_log(user_name, "USER_LOGIN", f"Web Auth Success ({role})", role=role)

    return jsonify({
        "success": True,
        "message": f"Welcome {user_name} ({role})!",
        "user_name": user_name,
        "user_role": role,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "is_employee": is_employee
    })


@app.route("/api/me", methods=["GET"])
def get_current_user():
    user_name = session.get("user_name")
    role = session.get("user_role", "Employee")
    if not user_name:
        return jsonify({"logged_in": False, "role": "Visitor"})
    return jsonify({
        "logged_in": True,
        "user_name": user_name,
        "user_role": role,
        "is_admin": session.get("is_admin", False),
        "is_manager": session.get("is_manager", False),
        "is_employee": True
    })


@app.route("/api/logout", methods=["POST"])
def user_logout():
    user_name = session.get("user_name", "User")
    role = session.get("user_role", "User")
    session.clear()
    sheets.append_user_audit_log(user_name, "USER_LOGOUT", f"User logged out ({role})", role=role)
    return jsonify({"success": True, "message": "Logged out successfully!"})


@app.route("/api/maintenance/status", methods=["GET"])
def get_maintenance_status():
    return jsonify({
        "enabled": IS_MAINTENANCE_MODE,
        "message": MAINTENANCE_MESSAGE
    })


@app.route("/api/maintenance/toggle", methods=["POST"])
def toggle_maintenance():
    global IS_MAINTENANCE_MODE, MAINTENANCE_MESSAGE
    data = request.get_json() or {}
    user_name = data.get("name") or session.get("user_name") or "Admin"
    password = data.get("password", "").strip()

    if password and password != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Invalid Password! Cannot toggle maintenance mode."}), 401

    enabled = data.get("enabled")
    if enabled is None:
        IS_MAINTENANCE_MODE = not IS_MAINTENANCE_MODE
    else:
        IS_MAINTENANCE_MODE = bool(enabled)

    custom_msg = data.get("message")
    if custom_msg:
        MAINTENANCE_MESSAGE = custom_msg

    status_str = "ENABLED" if IS_MAINTENANCE_MODE else "DISABLED"
    details_str = f"Maintenance Mode set to {status_str}"

    # Log maintenance toggle to User_Audit_Logs sheet
    sheets.append_user_audit_log(user_name, "MAINTENANCE_TOGGLE", details_str, role="Admin")

    return jsonify({
        "success": True,
        "enabled": IS_MAINTENANCE_MODE,
        "message": MAINTENANCE_MESSAGE,
        "status_text": f"Maintenance Mode is now {status_str}!"
    })


@app.route("/api/audit-logs", methods=["GET"])
def get_audit_logs():
    try:
        rows = sheets._all_rows("User_Audit_Logs")
        logs = []
        for r in rows:
            if len(r) >= 4:
                logs.append([
                    r[0],
                    r[1],
                    r[2],
                    r[3] if len(r) > 3 else "Visitor",
                    r[4] if len(r) > 4 else ""
                ])
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def collapse_and_deduplicate_transactions(service_rows, upgrade_rows, kit_rows, expense_rows, tx_rows=None):
    """
    Combines Service, Upgrade, Kit, and Expense sheet entries into a clean,
    deduplicated transaction list matching Google Sheets 1:1.
    """
    items = []

    for r in service_rows:
        if len(r) >= 3:
            dt = str(r[0]).strip()
            cust = str(r[1]).strip() if len(r) > 1 and r[1] else "Unknown"
            cat = str(r[2]).strip() if len(r) > 2 and r[2] else "Civilian"
            count = str(r[3]).strip() if len(r) > 3 and r[3] else ""
            amt = sheets.get_row_amount("Service", r)
            staff = sheets.get_row_employee("Service", r)

            type_tag = "Service-Government" if cat.upper() in ("GOVT", "GOVERNMENT", "PD", "EMS") else "Service-Civilian"
            cat_display = f"{count}x {cat}" if count and count != "1" else f"Service ({cat})"
            items.append({
                "date": dt,
                "type": type_tag,
                "customer": cust if cust not in ("Unknown", "") else cat_display,
                "amount": amt,
                "staff": staff
            })

    for r in upgrade_rows:
        if len(r) >= 3:
            dt = str(r[0]).strip()
            cust = str(r[1]).strip() if len(r) > 1 and r[1] else "Car Upgrade Invoice"
            amt = sheets.get_row_amount("Upgrades", r)
            staff = sheets.get_row_employee("Upgrades", r)
            items.append({
                "date": dt,
                "type": "Car Upgrade",
                "customer": cust if cust else "Car Upgrade Invoice",
                "amount": amt,
                "staff": staff
            })

    for r in kit_rows:
        if len(r) >= 3:
            dt = str(r[0]).strip()
            cust = str(r[1]).strip() if len(r) > 1 and r[1] else "Unknown"
            details = ""
            if len(r) >= 8:
                rk = str(r[2]).strip()
                ck = str(r[3]).strip()
                parts = []
                if rk and rk != "0": parts.append(f"{rk}x Repair Kit")
                if ck and ck != "0": parts.append(f"{ck}x Cleaning Kit")
                details = ", ".join(parts) if parts else "Kit Sale"
            elif len(r) >= 3:
                details = str(r[2]).strip() or "Kit Sale"

            amt = sheets.get_row_amount("Kits", r)
            staff = sheets.get_row_employee("Kits", r)
            items.append({
                "date": dt,
                "type": "Kit",
                "customer": details if details else cust,
                "amount": amt,
                "staff": staff
            })

    for r in expense_rows:
        if len(r) > 1:
            dt = str(r[0]).strip()
            amt = f"-{r[1]}"
            staff = str(r[2]).strip() if len(r) > 2 else ""
            desc = str(r[3]).strip() if len(r) > 3 and r[3] else "Business Claim"
            items.append({
                "date": dt,
                "type": "Expense",
                "customer": desc,
                "amount": amt,
                "staff": staff
            })

    def parse_dt(item):
        d_str = str(item.get("date", "") if isinstance(item, dict) else item).strip()
        if not d_str:
            return datetime.datetime.min
        try:
            if "-" in d_str:
                parts = d_str.split(" ")
                ymd = parts[0].split("-")
                if len(ymd) == 3:
                    year, month, day = int(ymd[0]), int(ymd[1]), int(ymd[2])
                    hour, minute, sec = 0, 0, 0
                    if len(parts) > 1:
                        t_parts = parts[1].split(":")
                        if len(t_parts) >= 2:
                            hour = int(t_parts[0])
                            minute = int(t_parts[1])
                            if len(t_parts) >= 3:
                                sec = int(t_parts[2])
                            if len(parts) > 2 and parts[2].upper() == "PM" and hour < 12:
                                hour += 12
                            elif len(parts) > 2 and parts[2].upper() == "AM" and hour == 12:
                                hour = 0
                    return datetime.datetime(year, month, day, hour, minute, sec)
            elif "/" in d_str:
                parts = d_str.split(" ")
                dmy = parts[0].split("/")
                if len(dmy) == 3:
                    day, month, year = int(dmy[0]), int(dmy[1]), int(dmy[2])
                    return datetime.datetime(year, month, day)
        except Exception:
            pass
        return datetime.datetime.min

    # User directive: Only include August 2026 (Month 8) onwards for official employees, sorted newest first
    aug_start = datetime.datetime(2026, 8, 1, 0, 0, 0)
    aug_items = [
        it for it in items
        if parse_dt(it) >= aug_start and it.get("staff") in config.OFFICIAL_EMPLOYEE_NAMES
    ]
    aug_items.sort(key=parse_dt, reverse=True)
    return aug_items


@app.route("/api/dashboard")
def get_dashboard_data():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        expense_rows = sheets._all_rows("Expenses")
        tx_rows = sheets._all_rows("Transactions")

        service_rev = sum(sheets.get_row_amount("Service", r) for r in service_rows)
        upgrade_rev = sum(sheets.get_row_amount("Upgrades", r) for r in upgrade_rows)
        kit_rev = sum(sheets.get_row_amount("Kits", r) for r in kit_rows)
        expenses_tot = sum(sheets._sum_numeric([r[1]]) for r in expense_rows if len(r) > 1)

        total_sales = service_rev + upgrade_rev + kit_rev
        tax = round(total_sales * 0.15, 2)
        profit = round(total_sales - expenses_tot - tax, 2)
        total_txns = len(service_rows) + len(upgrade_rows) + len(kit_rows) + len(expense_rows)

        # Count unique official employees only
        emp_set = set()
        emp_counts = {}
        for s_name, rows in [("Service", service_rows), ("Upgrades", upgrade_rows), ("Kits", kit_rows)]:
            for r in rows:
                emp = sheets.get_row_employee(s_name, r)
                if emp and emp in config.OFFICIAL_EMPLOYEE_NAMES:
                    emp_set.add(emp)
                    emp_counts[emp] = emp_counts.get(emp, 0) + 1

        top_employees = sorted(emp_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Deduplicated recent transactions
        all_tx = collapse_and_deduplicate_transactions(service_rows, upgrade_rows, kit_rows, expense_rows, tx_rows)
        recent = all_tx[:10]

        # Daily revenue breakdown for chart (group by day)
        daily_rev = {}
        for s_name, rows in [("Service", service_rows), ("Upgrades", upgrade_rows), ("Kits", kit_rows)]:
            for r in rows:
                if len(r) > 0:
                    date_str = str(r[0]).strip()
                    day = date_str.split(" ")[0] if " " in date_str else date_str
                    amt = sheets.get_row_amount(s_name, r)
                    daily_rev[day] = daily_rev.get(day, 0) + amt

        def parse_date_key(d_str):
            try:
                parts = d_str.split("/")
                if len(parts) == 3:
                    return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
            except Exception:
                pass
            return datetime.date.min

        chart_data = sorted(daily_rev.items(), key=lambda x: parse_date_key(x[0]))

        return jsonify({
            "success": True,
            "total_sales": total_sales,
            "total_expenses": expenses_tot,
            "tax": tax,
            "profit": profit,
            "total_transactions": total_txns,
            "total_employees": len(emp_set),
            "service_revenue": service_rev,
            "upgrade_revenue": upgrade_rev,
            "kit_revenue": kit_rev,
            "service_count": len(service_rows),
            "upgrade_count": len(upgrade_rows),
            "kit_count": len(kit_rows),
            "expense_count": len(expense_rows),
            "top_employees": [{"name": e[0], "count": e[1]} for e in top_employees],
            "recent_transactions": recent,
            "chart_labels": [c[0] for c in chart_data],
            "chart_values": [c[1] for c in chart_data],
            "maintenance_mode": IS_MAINTENANCE_MODE
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/transactions")
def get_all_transactions():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        expense_rows = sheets._all_rows("Expenses")
        tx_rows = sheets._all_rows("Transactions")

        all_tx = collapse_and_deduplicate_transactions(service_rows, upgrade_rows, kit_rows, expense_rows, tx_rows)
        return jsonify({"success": True, "transactions": all_tx})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/employee-tracker")
def get_employee_tracker():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        emp_stats = {}

        for r in service_rows:
            staff = sheets.get_row_employee("Service", r)
            if staff and staff in config.OFFICIAL_EMPLOYEE_NAMES:
                if staff not in emp_stats:
                    emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0] if r else ""}
                cat = str(r[2]).strip().lower() if len(r) > 2 else ""
                if "civ" in cat:
                    emp_stats[staff]["civilian"] += 1
                else:
                    emp_stats[staff]["govt"] += 1
                emp_stats[staff]["service"] += 1
                emp_stats[staff]["total"] += 1
                if r and r[0]: emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

        for r in upgrade_rows:
            staff = sheets.get_row_employee("Upgrades", r)
            if staff and staff in config.OFFICIAL_EMPLOYEE_NAMES:
                if staff not in emp_stats:
                    emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0] if r else ""}
                emp_stats[staff]["upgrades"] += 1
                emp_stats[staff]["total"] += 1
                if r and r[0]: emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

        for r in kit_rows:
            staff = sheets.get_row_employee("Kits", r)
            if staff and staff in config.OFFICIAL_EMPLOYEE_NAMES:
                if staff not in emp_stats:
                    emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0] if r else ""}
                emp_stats[staff]["kits"] += 1
                if r and r[0]: emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

        employees = []
        for name, s in emp_stats.items():
            employees.append({
                "name": name,
                "kits": str(s["kits"]),
                "civilian": str(s["civilian"]),
                "govt": str(s["govt"]),
                "service_logs": str(s["service"]),
                "upgrades": str(s["upgrades"]),
                "total": str(s["total"]),
                "last_date": s["last_date"]
            })

        # Sort employees by total logged services/upgrades descending
        employees.sort(key=lambda x: int(x["total"]), reverse=True)
        return jsonify({"success": True, "employees": employees})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/wipe", methods=["POST"])
def api_wipe():
    """Wipes all data sheets (preserving headers) and signals bot to rescan."""
    data = request.get_json() or {}
    password = data.get("password", "").strip()
    user_name = data.get("user_name", session.get("user_name", "Admin"))
    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Invalid password!"}), 401
    try:
        ss = sheets.get_spreadsheet()
        wiped_sheets = []
        HEADER_MAP = {
            "Service": sheets.SERVICE_HEADERS,
            "Kits": sheets.KIT_HEADERS,
            "Upgrades": sheets.REVENUE_HEADERS,
            "Transactions": sheets.TRANSACTIONS_HEADERS,
        }
        for sheet_name in ["Service", "Kits", "Upgrades", "Transactions", "Employee Tracker", "August Employee Tracker"]:
            try:
                ws = ss.worksheet(sheet_name)
                header = HEADER_MAP.get(sheet_name) or ws.row_values(1)
                sheets._with_retry(lambda w=ws: w.clear())
                if header:
                    sheets._with_retry(lambda w=ws, h=header: w.append_row(h))
                wiped_sheets.append(sheet_name)
            except Exception as e:
                print(f"[Wipe] Could not wipe {sheet_name}: {e}")

        # Clear all local caches (web app process)
        with sheets._CACHE_LOCK:
            sheets._ROWS_CACHE.clear()
            sheets._LAST_KNOWN_ROWS.clear()
            sheets._save_disk_cache()

        # Clear processed image hashes
        try:
            if os.path.exists("processed_images.json"):
                with open("processed_images.json", "w") as f:
                    json.dump([], f)
        except Exception:
            pass

        # Signal bot process to rescan
        with open("wipe_trigger.flag", "w") as f:
            import time as _t
            f.write(str(_t.time()))

        sheets.append_user_audit_log(user_name, "DATA_WIPE", f"Wiped sheets: {', '.join(wiped_sheets)}", "Admin")

        return jsonify({"success": True, "message": f"Wiped {', '.join(wiped_sheets)}! Bot will rescan Discord channels."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/inventory")
def get_inventory():
    try:
        rows = sheets._all_rows("Inventory")
        items = []
        for i, r in enumerate(rows):
            if len(r) >= 6:
                items.append({
                    "row_index": i + 2,  # 1-indexed header + data
                    "name": r[0],
                    "stock": r[1],
                    "bought": r[2],
                    "restock_date": r[3],
                    "unit_price": r[4],
                    "total_value": r[5],
                    "last_updated": r[6] if len(r) > 6 else ""
                })
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/inventory/create", methods=["POST"])
def create_inventory_item():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    stock = data.get("stock", 0)
    unit_price = data.get("unit_price", 0)
    user_name = data.get("user_name", session.get("user_name", "Admin"))

    if not name:
        return jsonify({"success": False, "error": "Item name is required!"}), 400

    try:
        stock_val = int(stock)
        price_val = float(unit_price)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid stock or price!"}), 400

    import datetime as _dt
    now_str = _dt.datetime.now(sheets.IST).strftime("%Y-%m-%d %I:%M:%S %p")
    total_value = stock_val * price_val
    new_row = [name, stock_val, 0, now_str, price_val, total_value, now_str]

    try:
        ws = sheets._ensure_sheet("Inventory")
        if ws:
            sheets._with_retry(lambda: ws.append_row(new_row))
            sheets.clear_rows_cache("Inventory")
            sheets.append_user_audit_log(user_name, "INVENTORY_CREATE", f"Created item: {name} (Stock: {stock_val}, Price: {price_val})")
            return jsonify({"success": True, "message": f"Item '{name}' created!"})
        return jsonify({"success": False, "error": "Could not access Inventory sheet!"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/inventory/update", methods=["POST"])
def update_inventory_item():
    data = request.get_json() or {}
    row_index = data.get("row_index")
    name = data.get("name", "").strip()
    stock = data.get("stock", 0)
    unit_price = data.get("unit_price", 0)
    user_name = data.get("user_name", session.get("user_name", "Admin"))

    if not row_index:
        return jsonify({"success": False, "error": "Row index required!"}), 400

    try:
        stock_val = int(stock)
        price_val = float(unit_price)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid stock or price!"}), 400

    import datetime as _dt
    now_str = _dt.datetime.now(sheets.IST).strftime("%Y-%m-%d %I:%M:%S %p")
    total_value = stock_val * price_val

    try:
        ws = sheets._ensure_sheet("Inventory")
        if ws:
            row_num = int(row_index)
            updated_row = [name, stock_val, data.get("bought", 0), data.get("restock_date", now_str), price_val, total_value, now_str]
            cell_range = f"A{row_num}:G{row_num}"
            sheets._with_retry(lambda: ws.update(cell_range, [updated_row]))
            sheets.clear_rows_cache("Inventory")
            sheets.append_user_audit_log(user_name, "INVENTORY_UPDATE", f"Updated item: {name} (Stock: {stock_val}, Price: {price_val})")
            return jsonify({"success": True, "message": f"Item '{name}' updated!"})
        return jsonify({"success": False, "error": "Could not access Inventory sheet!"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    """Triggers a full channel rescan from the web (no password needed — read-only)."""
    # Signal the bot to rescan by touching a flag file
    try:
        with open("rescan_trigger.flag", "w") as f:
            import time as _t
            f.write(str(_t.time()))
        return jsonify({"success": True, "message": "Rescan triggered."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

