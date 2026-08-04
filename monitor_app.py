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
    return render_template("index.html", is_maintenance=IS_MAINTENANCE_MODE, maintenance_msg=MAINTENANCE_MESSAGE)


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
        return jsonify({"success": True, "logs": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def collapse_and_deduplicate_transactions(service_rows, upgrade_rows, kit_rows, expense_rows, tx_rows):
    """
    Collapses and deduplicates transactions so that summary invoice rows and
    line-item detail rows for the same transaction are NEVER mixed or double-listed.
    """
    tx_stamps = set()
    items = []

    if tx_rows:
        for r in tx_rows:
            if len(r) >= 4:
                dt = str(r[0]).strip()
                amt = r[1]
                desc = r[2] if len(r) > 2 and r[2] else "N/A"
                cat = r[3] or "Transaction"
                staff = r[4] if len(r) > 4 else ""
                tx_stamps.add((dt, staff))
                items.append({
                    "date": dt,
                    "type": cat,
                    "customer": desc,
                    "amount": amt,
                    "staff": staff
                })

    for r in service_rows:
        if len(r) > 4:
            dt = str(r[0]).strip()
            staff = str(r[4]).strip()
            if (dt, staff) not in tx_stamps:
                items.append({
                    "date": dt,
                    "type": "Service",
                    "customer": r[1],
                    "amount": r[3],
                    "staff": staff
                })

    for r in upgrade_rows:
        if len(r) > 3:
            dt = str(r[0]).strip()
            staff = str(r[3]).strip()
            if (dt, staff) not in tx_stamps:
                items.append({
                    "date": dt,
                    "type": "Upgrade",
                    "customer": r[1],
                    "amount": r[2],
                    "staff": staff
                })

    for r in kit_rows:
        if len(r) > 4:
            dt = str(r[0]).strip()
            staff = str(r[4]).strip()
            if (dt, staff) not in tx_stamps:
                items.append({
                    "date": dt,
                    "type": "Kit",
                    "customer": r[1],
                    "amount": r[3],
                    "staff": staff
                })

    for r in expense_rows:
        if len(r) > 2:
            items.append({
                "date": r[0],
                "type": "Expense",
                "customer": "Business Claim",
                "amount": f"-{r[1]}",
                "staff": r[2]
            })

    def parse_dt(item):
        d_str = str(item.get("date", ""))
        try:
            parts = d_str.split(" ")
            d_parts = parts[0].split("/")
            t_parts = parts[1].split(":") if len(parts) > 1 else [0, 0, 0]
            if len(d_parts) == 3:
                return datetime.datetime(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]),
                                         int(t_parts[0]), int(t_parts[1]), int(t_parts[2]) if len(t_parts) > 2 else 0)
        except Exception:
            pass
        return datetime.datetime.min

    items.sort(key=parse_dt, reverse=True)
    return items


@app.route("/api/dashboard")
def get_dashboard_data():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        expense_rows = sheets._all_rows("Expenses")
        tx_rows = sheets._all_rows("Transactions")

        service_rev = sum(sheets._sum_numeric([r[3]]) for r in service_rows if len(r) > 3)
        upgrade_rev = sum(sheets._sum_numeric([r[2]]) for r in upgrade_rows if len(r) > 2)
        kit_rev = sum(sheets._sum_numeric([r[3]]) for r in kit_rows if len(r) > 3)
        expenses_tot = sum(sheets._sum_numeric([r[1]]) for r in expense_rows if len(r) > 1)

        total_sales = service_rev + upgrade_rev + kit_rev
        tax = round(total_sales * 0.15, 2)
        profit = round(total_sales - expenses_tot - tax, 2)
        total_txns = len(service_rows) + len(upgrade_rows) + len(kit_rows) + len(expense_rows)

        # Count unique employees
        emp_set = set()
        emp_counts = {}
        for rows, col in [(service_rows, 4), (upgrade_rows, 3), (kit_rows, 4)]:
            for r in rows:
                if len(r) > col:
                    emp = str(r[col]).strip()
                    if emp and emp.lower() not in ("unknown", "high command", "high comman"):
                        emp_set.add(emp)
                        emp_counts[emp] = emp_counts.get(emp, 0) + 1

        top_employees = sorted(emp_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Deduplicated recent transactions
        all_tx = collapse_and_deduplicate_transactions(service_rows, upgrade_rows, kit_rows, expense_rows, tx_rows)
        recent = all_tx[:10]

        # Daily revenue breakdown for chart (group by day)
        daily_rev = {}
        for rows, col in [(service_rows, 3), (upgrade_rows, 2), (kit_rows, 3)]:
            for r in rows:
                if len(r) > col:
                    date_str = str(r[0]).strip()
                    day = date_str.split(" ")[0] if " " in date_str else date_str
                    amt = sheets._sum_numeric([r[col]])
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
        rows = sheets._all_rows("Employee Tracker")
        employees = []
        for r in rows:
            if len(r) >= 7:
                name = str(r[0]).strip()
                if name and name.lower() not in ("unknown", "high command", "high comman"):
                    employees.append({
                        "name": name,
                        "kits": r[1],
                        "civilian": r[2],
                        "govt": r[3],
                        "service_logs": r[4],
                        "upgrades": r[5],
                        "total": r[6],
                        "last_date": r[7] if len(r) > 7 else ""
                    })

        # Dynamic fallback if sheet is empty
        if not employees:
            service_rows = sheets._all_rows("Service")
            upgrade_rows = sheets._all_rows("Upgrades")
            kit_rows = sheets._all_rows("Kits")
            emp_stats = {}
            for r in service_rows:
                if len(r) > 4:
                    staff = str(r[4]).strip()
                    if staff and staff.lower() not in ("unknown", "high command", "high comman"):
                        if staff not in emp_stats:
                            emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0]}
                        cat = str(r[2]).strip().lower()
                        if "civ" in cat:
                            emp_stats[staff]["civilian"] += 1
                        else:
                            emp_stats[staff]["govt"] += 1
                        emp_stats[staff]["service"] += 1
                        emp_stats[staff]["total"] += 1
                        emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

            for r in upgrade_rows:
                if len(r) > 3:
                    staff = str(r[3]).strip()
                    if staff and staff.lower() not in ("unknown", "high command", "high comman"):
                        if staff not in emp_stats:
                            emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0]}
                        emp_stats[staff]["upgrades"] += 1
                        emp_stats[staff]["total"] += 1
                        emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

            for r in kit_rows:
                if len(r) > 4:
                    staff = str(r[4]).strip()
                    if staff and staff.lower() not in ("unknown", "high command", "high comman"):
                        if staff not in emp_stats:
                            emp_stats[staff] = {"kits": 0, "civilian": 0, "govt": 0, "service": 0, "upgrades": 0, "total": 0, "last_date": r[0]}
                        emp_stats[staff]["kits"] += 1
                        emp_stats[staff]["total"] += 1
                        emp_stats[staff]["last_date"] = max(emp_stats[staff]["last_date"], r[0])

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

        return jsonify({"success": True, "employees": employees})
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



@app.route("/api/wipe", methods=["POST"])
def api_wipe():
    """Wipes all data sheets and triggers bot rescan. Password protected."""
    data = request.get_json() or {}
    password = data.get("password", "").strip()
    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "error": "Invalid password!"}), 401
    try:
        # Touch wipe_trigger.flag to signal bot to wipe memory & rescan
        with open("wipe_trigger.flag", "w") as f:
            import time as _t
            f.write(str(_t.time()))
        return jsonify({"success": True, "message": "All data wiped! Bot will now rescan all Discord channels."})
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

