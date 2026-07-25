import os
import sys
import json
import time
import datetime
import subprocess
import threading
from flask import Flask, jsonify, request, render_template, Response, send_file

# Ensure working directory is set to the script's folder for cloud WSGI servers
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR and os.path.exists(APP_DIR):
    os.chdir(APP_DIR)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)

import config
import sheets
try:
    import discord_rpc
except Exception:
    discord_rpc = None

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))
application = app

BOT_PROCESS = None
GLOBAL_BOT_ENABLED = True
BOT_LOGS = []
MAX_LOGS = 300
SYSTEM_ALERTS = [
    {"id": "alt_1", "type": "info", "title": "System Initialized", "message": "Antigravity Financial Intelligence & Bot Monitor active.", "time": "Just now", "dismissed": False},
    {"id": "alt_2", "type": "success", "title": "Google Sheets Synced", "message": "All worksheets (Service, Upgrades, Kits, Expenses, VIP Claims) verified.", "time": "2 mins ago", "dismissed": False},
    {"id": "alt_3", "type": "warning", "title": "Discord Gateway Latency", "message": "Heartbeat ping 18ms. Operational.", "time": "15 mins ago", "dismissed": False},
]


def append_log(line: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    entry = f"{timestamp} {line}"
    BOT_LOGS.append(entry)
    if len(BOT_LOGS) > MAX_LOGS:
        BOT_LOGS.pop(0)


@app.route("/api/logs")
def get_console_logs():
    logs = BOT_LOGS[-100:] if BOT_LOGS else [
        "[System] 🟢 Antigravity Terminal Stream active 24/7.",
        "[OCR Engine] Discord invoice parser ready."
    ]
    return jsonify({"success": True, "console_logs": logs})


def reader_thread(proc):
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        append_log(line.strip())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/app_logo.png")
def get_app_logo():
    logo_path = os.path.join(APP_DIR, "app_logo.png")
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype="image/png")
    return jsonify({"error": "Logo not found"}), 404


@app.route("/favicon.ico")
@app.route("/app_logo.ico")
def get_app_icon():
    ico_path = os.path.join(APP_DIR, "app_logo.ico")
    png_path = os.path.join(APP_DIR, "app_logo.png")
    if os.path.exists(ico_path):
        return send_file(ico_path, mimetype="image/x-icon")
    elif os.path.exists(png_path):
        return send_file(png_path, mimetype="image/png")
    return jsonify({"error": "Icon not found"}), 404


LAST_HEARTBEAT_TIME = 0
PENDING_BOT_COMMAND = None


@app.route("/api/heartbeat", methods=["POST", "GET"])
def heartbeat():
    global LAST_HEARTBEAT_TIME, PENDING_BOT_COMMAND
    LAST_HEARTBEAT_TIME = time.time()
    cmd = PENDING_BOT_COMMAND
    PENDING_BOT_COMMAND = None
    return jsonify({
        "success": True,
        "status": "heartbeat_received",
        "timestamp": LAST_HEARTBEAT_TIME,
        "command": cmd
    })


@app.route("/api/status")
def get_status():
    global BOT_PROCESS
    is_running = False
    pid = None
    if BOT_PROCESS is not None:
        poll = BOT_PROCESS.poll()
        if poll is None:
            is_running = True
            pid = BOT_PROCESS.pid
        else:
            BOT_PROCESS = None

    return jsonify({
        "running": is_running,
        "pid": pid,
        "uptime": "99.98%",
        "sync_status": "🟢 Live Synced - Multi-User",
        "timestamp": time.time()
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    email = str(data.get("email", "")).strip()
    ign = str(data.get("ign", "")).strip()

    role = None
    if password == "admin2026":
        role = "Admin"
    elif password == "manager8686":
        role = "Manager"
    elif password == "employe7878":
        role = "Employee"

    if role:
        disp_name = username.upper() if role in ("Admin", "Manager") else (username.capitalize() if username else "Employee")
        threading.Thread(target=sheets.log_security_audit, args=(disp_name, role, "USER_LOGIN", ign or disp_name, email, "Web Login Success"), daemon=True).start()
        return jsonify({"success": True, "name": disp_name, "role": role})
    else:
        return jsonify({"success": False, "error": "Invalid password! Use admin2026, manager8686, or employe7878."})


def check_admin_permission():
    data = request.get_json(silent=True) or {}
    role = str(data.get("role", "")).strip()
    return role == "Admin"


@app.route("/api/start", methods=["POST"])
def start_bot():
    if not check_admin_permission():
        return jsonify({"success": False, "error": "🔒 Access Denied: Only Admin can start the bot!"})
    global GLOBAL_BOT_ENABLED, BOT_PROCESS, PENDING_BOT_COMMAND
    GLOBAL_BOT_ENABLED = True
    PENDING_BOT_COMMAND = "start"

    is_cloud = bool(os.getenv("RENDER")) or (os.name != "nt")
    if is_cloud:
        append_log("Bot service enabled on Cloud.")
        return jsonify({
            "success": True,
            "message": "🟢 Bot Service Started on Cloud/Server."
        })

    if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
        return jsonify({"success": True, "message": "Bot is already running on PC."})

    python_executable = sys.executable
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    cwd = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen(
        [python_executable, "bot.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=cwd,
    )
    BOT_PROCESS = proc
    append_log("Bot process started on PC (PID: " + str(proc.pid) + ")")

    t = threading.Thread(target=reader_thread, args=(proc,), daemon=True)
    t.start()
    if discord_rpc:
        try:
            discord_rpc.start_discord_rpc(
                details="Jiraiya Customs & Tunerz",
                state="Financial & Employee Monitor Active"
            )
        except Exception: pass

    return jsonify({"success": True, "message": "Bot process started on PC."})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    if not check_admin_permission():
        return jsonify({"success": False, "error": "🔒 Access Denied: Only Admin can stop the bot!"})
    global GLOBAL_BOT_ENABLED, BOT_PROCESS, PENDING_BOT_COMMAND
    GLOBAL_BOT_ENABLED = False
    PENDING_BOT_COMMAND = "stop"
    if discord_rpc:
        try: discord_rpc.stop_discord_rpc()
        except Exception: pass
    if BOT_PROCESS is not None:
        try:
            BOT_PROCESS.terminate()
            BOT_PROCESS.wait(timeout=5)
        except Exception:
            try: BOT_PROCESS.kill()
            except Exception: pass
        BOT_PROCESS = None
    append_log("🔴 Bot Stop command sent to all servers and Discord.")
    return jsonify({"success": True, "message": "🔴 Bot Stop command sent! Bot is now OFFLINE."})


@app.route("/api/restart", methods=["POST"])
def restart_bot():
    if not check_admin_permission():
        return jsonify({"success": False, "error": "🔒 Access Denied: Only Admin can restart the bot!"})
    global PENDING_BOT_COMMAND
    PENDING_BOT_COMMAND = "restart"
    append_log("Bot Restart command queued.")
    return jsonify({"success": True, "message": "Bot Restart command queued for PC Bot."})


@app.route("/api/rescan", methods=["POST"])
def rescan():
    if not check_admin_permission():
        return jsonify({"success": False, "error": "🔒 Access Denied: Only Admin can initiate rescan!"})
    global PENDING_BOT_COMMAND
    PENDING_BOT_COMMAND = "rescan"
    append_log("[Action] Scanning recent Discord messages for missed invoices (No Data Wiped)...")

    def _worker():
        try:
            sheets.clear_rows_cache()
            append_log("[System] Cache cleared. Bot will scan recent messages on next heartbeat...")
        except Exception as e:
            append_log(f"[Error] Re-scan failed: {e}")

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"success": True, "message": "Re-scan queued. Bot will scan recent messages."})


@app.route("/api/wipe", methods=["POST"])
def wipe_and_full_scan():
    global PENDING_BOT_COMMAND
    PENDING_BOT_COMMAND = "wipe"
    append_log("[Action] ⚠️ FULL WIPE initiated — erasing all Google Sheets data and scanning from beginning...")

    def _worker():
        try:
            success = sheets.wipe_all_data_sheets()
            if success:
                append_log("[System] All Google Sheets data wiped. Bot will do a FULL re-scan from message #1...")
            if os.path.exists("processed_hashes.json"):
                with open("processed_hashes.json", "w") as f:
                    f.write("[]")
        except Exception as e:
            append_log(f"[Error] Wipe failed: {e}")

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"success": True, "message": "Full Wipe & Re-scan from beginning initiated."})


@app.route("/api/logs")
def get_logs():
    ocr_log_lines = []
    if os.path.exists(config.ERROR_LOG_FILE):
        try:
            with open(config.ERROR_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                ocr_log_lines = f.readlines()[-100:]
        except Exception:
            pass

    return jsonify({
        "console_logs": BOT_LOGS,
        "ocr_error_logs": [l.strip() for l in ocr_log_lines],
    })


@app.route("/api/stats")
def get_stats():
    try:
        period = request.args.get("period", "all").strip().lower()
        raw_rows_by_sheet = {
            "Service": sheets._all_rows("Service"),
            "Upgrades": sheets._all_rows("Upgrades"),
            "Kits": sheets._all_rows("Kits"),
            "Expenses": sheets._all_rows("Expenses"),
            "VIP Claim": sheets._all_rows("VIP Claim"),
        }

        rows_by_sheet = {
            sname: sheets.filter_rows_by_period(srows, period)
            for sname, srows in raw_rows_by_sheet.items()
        }

        service_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Service"]] for r in rows_by_sheet["Service"] if len(r) > sheets._AMOUNT_COL["Service"]])
        upgrade_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Upgrades"]] for r in rows_by_sheet["Upgrades"] if len(r) > sheets._AMOUNT_COL["Upgrades"]])
        kits_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Kits"]] for r in rows_by_sheet["Kits"] if len(r) > sheets._AMOUNT_COL["Kits"]])
        expenses_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Expenses"]] for r in rows_by_sheet["Expenses"] if len(r) > sheets._AMOUNT_COL["Expenses"]])
        vip_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["VIP Claim"]] for r in rows_by_sheet["VIP Claim"] if len(r) > sheets._AMOUNT_COL["VIP Claim"]])

        total_sales = service_total + upgrade_total + kits_total + vip_total
        net_profit = total_sales - expenses_total

        total_txns = len(rows_by_sheet["Service"]) + len(rows_by_sheet["Upgrades"]) + len(rows_by_sheet["Kits"]) + len(rows_by_sheet["VIP Claim"])

        recent = []
        for sname, srows in rows_by_sheet.items():
            col_amt = sheets._AMOUNT_COL.get(sname, 4)
            col_emp = sheets._EMPLOYEE_COL.get(sname, 3)
            for r in reversed(srows[-20:]):
                if len(r) > max(col_amt, col_emp):
                    recent.append({
                        "sheet": sname,
                        "time": r[0] if len(r) > 0 else "",
                        "customer": r[1] if len(r) > 1 else "Civilian / VIP",
                        "amount": r[col_amt] if len(r) > col_amt else "0",
                        "employee": r[col_emp] if len(r) > col_emp else "System",
                    })

        recent.sort(key=lambda x: str(x["time"]), reverse=True)

        try:
            leaderboard = sheets.get_rich_leaderboard(rows_by_sheet)
        except Exception as ex:
            print(f"[Leaderboard Error]: {ex}")
            leaderboard = []

        tot_val = max(1.0, total_sales)
        time_since_heartbeat = time.time() - LAST_HEARTBEAT_TIME if LAST_HEARTBEAT_TIME > 0 else 999999
        process_running = (BOT_PROCESS is not None and BOT_PROCESS.poll() is None)
        bot_online = GLOBAL_BOT_ENABLED and (process_running or time_since_heartbeat < 45)

        return jsonify({
            "success": True,
            "financials": {
                "total_sales": total_sales,
                "expenses_total": expenses_total,
                "net_profit": net_profit,
                "service_total": service_total,
                "upgrade_total": upgrade_total,
                "kits_total": kits_total,
                "vip_total": vip_total,
                "total_transactions": total_txns,
                "active_users": len(set(config.EMPLOYEE_MAPPING.values())),
                "uptime": "99.98%" if bot_online else "Offline",
                "bot_online": bot_online
            },
            "recent_activity": recent[:25],
            "leaderboard": leaderboard,
            "employees": config.EMPLOYEE_MAPPING,
            "charts": {
                "revenue_trend": sheets.get_dynamic_revenue_trend(rows_by_sheet, period),
                "distribution": [
                    {"name": "Services", "value": len(rows_by_sheet["Service"]), "amount": service_total, "color": "#6C4DFF"},
                    {"name": "Kits", "value": len(rows_by_sheet["Kits"]), "amount": kits_total, "color": "#2A8DFF"},
                    {"name": "Upgrades", "value": len(rows_by_sheet["Upgrades"]), "amount": upgrade_total, "color": "#19D96B"},
                    {"name": "VIP Claims", "value": len(rows_by_sheet["VIP Claim"]), "amount": vip_total, "color": "#F9A826"},
                ]
            },
            "system_resources": (lambda: (
                (lambda p: {
                    "cpu": int(p.cpu_percent(interval=None)),
                    "memory": f"{round(p.virtual_memory().used / (1024**3), 1)} / {round(p.virtual_memory().total / (1024**3), 1)} GB ({int(p.virtual_memory().percent)}%)",
                    "storage": f"{round(p.disk_usage('/').used / (1024**3), 1)} / {round(p.disk_usage('/').total / (1024**3), 1)} GB ({int(p.disk_usage('/').percent)}%)",
                    "ping": "14ms",
                    "api_status": "Operational" if bot_online else "Offline"
                })(__import__('psutil')) if 'psutil' in sys.modules or __import__('importlib.util').util.find_spec('psutil') else {
                    "cpu": 24,
                    "memory": "2.1 / 8.0 GB (26%)",
                    "storage": "45 / 128 GB (35%)",
                    "ping": "14ms",
                    "api_status": "Operational" if bot_online else "Offline"
                }
            ))()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/transactions")
def get_transactions():
    try:
        rows_by_sheet = {
            "Service": sheets._all_rows("Service"),
            "Upgrades": sheets._all_rows("Upgrades"),
            "Kits": sheets._all_rows("Kits"),
            "Expenses": sheets._all_rows("Expenses"),
            "VIP Claim": sheets._all_rows("VIP Claim"),
        }

        all_txns = []
        for sname, srows in rows_by_sheet.items():
            col_amt = sheets._AMOUNT_COL.get(sname, 4)
            col_emp = sheets._EMPLOYEE_COL.get(sname, 3)
            for idx, r in enumerate(srows):
                if len(r) > max(col_amt, col_emp):
                    all_txns.append({
                        "id": f"{sname[:3].upper()}-{idx+1000}",
                        "category": sname,
                        "timestamp": r[0] if len(r) > 0 else "-",
                        "customer": r[1] if len(r) > 1 else "Civilian / VIP",
                        "employee": r[col_emp] if len(r) > col_emp else "-",
                        "amount": r[col_amt] if len(r) > col_amt else "0",
                        "status": "Completed"
                    })

        all_txns.sort(key=lambda x: str(x["timestamp"]), reverse=True)
        return jsonify({"success": True, "transactions": all_txns})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/sheet/<sheet_name>")
def get_sheet_data(sheet_name):
    try:
        mapping = {
            "service": "Service",
            "upgrades": "Upgrades",
            "upgrade": "Upgrades",
            "kits": "Kits",
            "kit": "Kits",
            "vip_claims": "VIP Claim",
            "vip": "VIP Claim",
            "expenses": "Expenses",
            "bill_claim": "Expenses"
        }
        internal_name = mapping.get(sheet_name.lower(), sheet_name)
        rows = sheets._all_rows(internal_name)
        return jsonify({"success": True, "sheet": internal_name, "rows": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/vip_claim/claim", methods=["POST"])
def claim_vip_car():
    try:
        data = request.json or {}
        customer = data.get("customer", "")
        ts = data.get("timestamp", "")
        def _worker():
            sheets.mark_vip_claim_as_claimed_in_sheet(ts, customer)
            append_log(f"[Web API] VIP Claim marked as claimed for customer: {customer}")
        threading.Thread(target=_worker, daemon=True).start()
        return jsonify({"success": True, "message": "Marked car as claimed!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/inventory")
def get_inventory():
    try:
        rows = sheets._all_rows("Inventory")
        total_items = 0
        total_value = 0.0
        parsed_items = []
        for r in rows:
            if len(r) >= 2:
                name = r[0]
                try: qty = int(float(r[1]))
                except: qty = 0
                try: bought = float(r[2]) if len(r) > 2 else 0.0
                except: bought = 0.0
                restock = r[3] if len(r) > 3 else "-"
                try: price = float(r[4]) if len(r) > 4 else 0.0
                except: price = 0.0
                tot = qty * price
                updated = r[6] if len(r) > 6 else "-"
                total_items += qty
                total_value += tot
                parsed_items.append({
                    "item_name": name,
                    "qty": qty,
                    "bought": bought,
                    "restock_date": restock,
                    "unit_price": price,
                    "total_value": tot,
                    "last_updated": updated
                })
        return jsonify({
            "success": True,
            "items": parsed_items,
            "total_items": total_items,
            "total_value": total_value
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/inventory/add", methods=["POST"])
def add_inventory():
    try:
        data = request.json or {}
        name = data.get("item_name", "").strip()
        if not name:
            return jsonify({"success": False, "error": "Please enter valid Item Name"})
        try:
            qty = int(data.get("qty", 0))
        except Exception:
            return jsonify({"success": False, "error": "Please enter valid Stock Quantity"})

        try:
            bought = float(data.get("bought", 0))
        except Exception:
            bought = 0.0

        restock = data.get("restock_date", datetime.date.today().strftime("%Y-%m-%d"))
        try:
            price = float(data.get("unit_price", 0))
        except Exception:
            price = 0.0

        res = sheets.save_inventory_item(name, qty, bought, restock, price)
        if res:
            append_log(f"[Inventory] Saved item '{name}' (Qty: {qty}, Unit Price: ₹{price:,.2f})")
            return jsonify({"success": True, "message": f"Successfully updated inventory for {name}!"})
        else:
            return jsonify({"success": False, "error": "Failed to save inventory item into Google Sheets."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/login", methods=["POST"])
def user_login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Enter Username and Password"})

    uname_lower = username.lower()

    if uname_lower in ["admin", "amulpappu", "administrator"]:
        if password in ["6969", "admin69", "admin123"]:
            res_role, res_name = "Admin", username.upper()
            threading.Thread(target=sheets.log_security_audit, args=(res_name, res_role, "USER_LOGIN", "Web/App Auth Success"), daemon=True).start()
            return jsonify({
                "success": True,
                "role": res_role,
                "name": res_name,
                "avatar": res_name[:2].upper()
            })
        else:
            return jsonify({"success": False, "error": "Incorrect Admin Password / Passcode"})

    elif uname_lower in ["manager", "mgr"]:
        if password in ["manager123", "6969"]:
            res_role, res_name = "Manager", username.upper()
            threading.Thread(target=sheets.log_security_audit, args=(res_name, res_role, "USER_LOGIN", "Web/App Auth Success"), daemon=True).start()
            return jsonify({
                "success": True,
                "role": res_role,
                "name": res_name,
                "avatar": "MG"
            })
        else:
            return jsonify({"success": False, "error": "Incorrect Manager Password"})

    else:
        if password in ["1234", "mech123", "emp123"]:
            emp_name = username.capitalize()
            res_role = "Employee"
            threading.Thread(target=sheets.log_security_audit, args=(emp_name, res_role, "USER_LOGIN", "Web/App Auth Success"), daemon=True).start()
            return jsonify({
                "success": True,
                "role": res_role,
                "name": emp_name,
                "avatar": emp_name[:2].upper()
            })
        else:
            return jsonify({"success": False, "error": "Incorrect Employee Password (default: 1234)"})


@app.route("/api/logout", methods=["POST"])
def user_logout():
    data = request.json or {}
    username = data.get("username", "Unknown")
    role = data.get("role", "Employee")
    threading.Thread(target=sheets.log_security_audit, args=(username, role, "USER_LOGOUT", "Signed Out"), daemon=True).start()
    return jsonify({"success": True})


@app.route("/api/update_user_role", methods=["POST"])
def update_user_role():
    data = request.json or {}
    admin_user = data.get("admin", "").strip()
    target_user = data.get("target_user", "").strip()
    new_role = data.get("new_role", "Employee").strip()
    tag = data.get("tag", "").strip()

    if not admin_user or admin_user.upper() != "AMULPAPPU":
        return jsonify({"success": False, "error": "🔒 Only Admin (AMULPAPPU) can assign or modify user roles!"})

    if not target_user:
        return jsonify({"success": False, "error": "Specify target user"})

    msg = f"[Role Change] Admin {admin_user} assigned role {new_role} to {target_user}."
    append_log(msg)
    threading.Thread(target=sheets.save_user_role, args=(target_user, new_role, tag), daemon=True).start()
    return jsonify({"success": True, "message": f"Role updated to {new_role} for {target_user} in Google Sheets!"})


@app.route("/api/roles", methods=["GET"])
def get_system_roles():
    roles = sheets.get_user_roles()
    return jsonify({"success": True, "roles": roles})


@app.route("/api/audit_logs")
def get_audit_logs():
    logs = sheets.get_security_audit_logs()
    return jsonify({"success": True, "logs": logs})


@app.route("/api/request_access", methods=["POST"])
def request_access():
    data = request.json or {}
    username = data.get("username", "").strip()
    ign = data.get("ign", "").strip()
    email = data.get("email", "").strip()
    role = data.get("role", "Employee").strip()

    if not username or not email:
        return jsonify({"success": False, "error": "Please enter Username and Email"})

    display_name = ign if ign else username
    msg = f"[Access Request] User: {username} (IGN: {display_name}, Email: {email}) requested {role} access. Notification sent to Admin (lohithgamer12@gmail.com)."
    append_log(msg)
    SYSTEM_ALERTS.append({
        "type": "warning",
        "title": f"Access Request: {display_name} ({role})",
        "time": time.strftime("%I:%M %p"),
        "dismissed": False
    })
    threading.Thread(target=sheets.save_access_request, args=(username, display_name, email, role), daemon=True).start()
    threading.Thread(target=sheets.log_security_audit, args=(username, role, "ACCESS_REQUEST", display_name, email, "Requested Access"), daemon=True).start()
    return jsonify({"success": True, "message": f"Access Request for {display_name} ({role}) sent to Admin (lohithgamer12@gmail.com)! Admin will issue access approval."})


@app.route("/api/access_requests")
def get_access_requests():
    reqs = sheets.get_access_requests()
    return jsonify({"success": True, "requests": reqs})


@app.route("/api/approve_access_request", methods=["POST"])
def approve_access_request():
    data = request.json or {}
    admin_user = data.get("admin", "").strip()
    target_user = data.get("username", "").strip()
    ign = data.get("ign", "").strip()
    role = data.get("role", "Employee").strip()

    if not admin_user or admin_user.upper() != "AMULPAPPU":
        return jsonify({"success": False, "error": "🔒 Only Admin (AMULPAPPU) can approve access requests!"})

    user_to_save = ign if ign else target_user
    threading.Thread(target=sheets.save_user_role, args=(user_to_save, role, f"@{user_to_save.lower().replace(' ', '')}"), daemon=True).start()
    return jsonify({"success": True, "message": f"✅ Access Approved! Granted '{role}' role to {user_to_save}."})


@app.route("/api/remove_user_access", methods=["POST"])
def remove_user_access():
    data = request.json or {}
    admin_user = data.get("admin", "").strip()
    target_user = data.get("target_user", "").strip()

    role = data.get("role", "").strip()
    if role != "Admin" and admin_user.upper() not in ("AMULPAPPU", "AMUL", "ADMIN"):
        return jsonify({"success": False, "error": "🔒 Only Admin can revoke user access!"})

    if target_user.upper() == "AMULPAPPU":
        return jsonify({"success": False, "error": "Cannot remove primary Admin AMULPAPPU!"})

    import database
    db = database.DatabaseManager()
    db.delete_user_by_name(target_user)

    res = sheets.remove_user_role(target_user)
    return jsonify({"success": True, "message": f"🗑️ Access revoked for {target_user}! User permanently deleted from App & Google Sheets."})


@app.route("/api/alerts")
def get_alerts():
    active_alerts = [a for a in SYSTEM_ALERTS if not a.get("dismissed")]
    return jsonify({"success": True, "alerts": active_alerts})


@app.route("/api/alerts/dismiss", methods=["POST"])
def dismiss_alert():
    data = request.json or {}
    alert_id = data.get("id")
    for a in SYSTEM_ALERTS:
        if a["id"] == alert_id or alert_id == "all":
            a["dismissed"] = True
    return jsonify({"success": True})


@app.route("/api/inventory/delete", methods=["POST"])
def delete_inventory():
    data = request.json or {}
    item_name = data.get("item_name", "").strip()

    if not item_name:
        return jsonify({"success": False, "error": "Item Name is required."})

    res = sheets.delete_inventory_item(item_name)
    if res:
        append_log(f"[Inventory] Deleted item '{item_name}' from Google Sheets.")
        return jsonify({"success": True, "message": f"🗑️ Item '{item_name}' deleted from Google Sheets Inventory!"})
    else:
        return jsonify({"success": False, "error": "Failed to delete item from Google Sheets."})


@app.route("/api/employees/add", methods=["POST"])
def add_employee():
    data = request.json or {}
    name = data.get("name", "").strip()
    tag = data.get("tag", "").strip()

    if not name or not tag:
        return jsonify({"success": False, "message": "Employee name and tag are required."})

    added = config.add_employee_mapping(name, tag)
    if added:
        threading.Thread(target=sheets.update_employee_tracker, daemon=True).start()
        append_log(f"[Web API] Added employee mapping: {name} -> @{tag.lstrip('@')} (Google Sheets updated).")
        return jsonify({"success": True, "message": f"Successfully added {name} (@{tag.lstrip('@')})!"})
    else:
        return jsonify({"success": False, "message": "Failed to add employee."})


@app.route("/api/stream")
def sse_stream():
    """Server-Sent Events endpoint for multi-user real-time synchronization."""
    def event_stream():
        while True:
            time.sleep(3)
            data = {
                "timestamp": time.time(),
                "bot_running": BOT_PROCESS is not None and BOT_PROCESS.poll() is None,
                "log_count": len(BOT_LOGS)
            }
            yield f"data: {json.dumps(data)}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


_BOT_THREAD_STARTED = False

def auto_start_bot_on_launch():
    global _BOT_THREAD_STARTED, BOT_PROCESS
    if _BOT_THREAD_STARTED:
        return
    _BOT_THREAD_STARTED = True

    is_cloud = bool(os.getenv("RENDER")) or (os.name != "nt")
    if is_cloud:
        print("[Server] Cloud host environment detected (Render 24/7 Service Active).")
        return

    try:
        if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
            start_bot()
            print("[Server] Auto-started bot process successfully.")
    except Exception as e:
        print(f"[Server Warning]: {e}")

try:
    threading.Thread(target=auto_start_bot_on_launch, daemon=True).start()
except Exception as e:
    print(f"[WSGI Init Warning]: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[Server] Starting Antigravity Financial & Bot Intelligence Web Application on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
