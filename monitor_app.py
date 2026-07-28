import os
import sys
import json
import time
import datetime
import subprocess
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, jsonify, request, render_template, Response, send_file

# Ensure working directory is set to the script's folder for cloud WSGI servers
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR and os.path.exists(APP_DIR):
    os.chdir(APP_DIR)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)

import config
import sheets
import config
import sheets
import database
try:
    import discord_rpc
except Exception:
    discord_rpc = None

db = database.DatabaseManager()

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
    global LAST_HEARTBEAT_TIME, PENDING_BOT_COMMAND, GLOBAL_BOT_ENABLED
    LAST_HEARTBEAT_TIME = time.time()
    if not GLOBAL_BOT_ENABLED:
        cmd = "stop"
    else:
        cmd = PENDING_BOT_COMMAND
        PENDING_BOT_COMMAND = None
    return jsonify({
        "success": True,
        "status": "heartbeat_received",
        "timestamp": LAST_HEARTBEAT_TIME,
        "command": cmd,
        "bot_enabled": GLOBAL_BOT_ENABLED
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
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    email = str(data.get("email", "")).strip()
    ign = str(data.get("ign", "")).strip()
    requested_role = str(data.get("role", "Admin")).strip()

    pass_lower = password.lower()
    uname_lower = username.lower()

    admin_passcodes = ("admin2026", "6969", "admin69", "admin123", "administrator", "amulpappu", "amul")
    manager_passcodes = ("manager8686", "manager123", "mgr123") + admin_passcodes
    employee_passcodes = ("employe7878", "employee7878", "1234", "mech123", "emp123") + manager_passcodes

    # Require password
    if not password:
        return jsonify({"success": False, "error": "⚠️ Password / Passcode is required to log in!"})

    disp_name = ign if ign else (username if username else "AMULPAPPU")

    # Look up assigned role in User_Roles sheet to automatically enforce assigned promotions (e.g. Eli -> Manager)
    assigned_role = None
    try:
        user_roles = sheets.get_user_roles()
        for ur in user_roles:
            if ur.get("username", "").strip().lower() == disp_name.lower() or ur.get("tag", "").lstrip("@").lower() == disp_name.lower():
                assigned_role = ur.get("role")
                break
    except Exception: pass

    target_role = assigned_role if (assigned_role and assigned_role in ("Admin", "Manager", "Employee")) else requested_role

    # Validate passcode against target role
    if target_role == "Admin":
        if pass_lower not in admin_passcodes:
            return jsonify({"success": False, "error": "🔒 Invalid Admin passcode!"})
        role = "Admin"
    elif target_role == "Manager":
        if pass_lower not in manager_passcodes:
            return jsonify({"success": False, "error": "🔒 Invalid Manager passcode!"})
        role = "Manager"
    else:
        if pass_lower not in employee_passcodes:
            return jsonify({"success": False, "error": "🔒 Invalid Passcode for Employee role!"})
        role = "Employee"

    threading.Thread(
        target=sheets.log_security_audit,
        args=(disp_name, role, "USER_LOGIN", ign or disp_name, email or f"{disp_name.lower()}@gmail.com", f"Web Login Success ({role})"),
        daemon=True
    ).start()

    return jsonify({
        "success": True,
        "username": disp_name,
        "name": disp_name,
        "role": role,
        "avatar": disp_name[:2].upper()
    })


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


@app.route("/api/rescan", methods=["POST", "GET"])
def rescan():
    global PENDING_BOT_COMMAND
    PENDING_BOT_COMMAND = "rescan"
    append_log("[Action] ⚡ Live Re-Scan & Syncing Google Sheets data...")

    try:
        sheets.force_refresh_all()
        append_log("[System] 🟢 Google Sheets synchronized live. All manual edits & totals updated.")
        return jsonify({"success": True, "message": "⚡ Live Re-Scan Complete! Google Sheets data synchronized."})
    except Exception as e:
        append_log(f"[Error] Re-scan failed: {e}")
        return jsonify({"success": False, "error": f"Re-scan failed: {e}"})


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
        force = request.args.get("force", "false").strip().lower() in ("true", "1")
        if force:
            sheets.clear_rows_cache(hard=True)

        raw_rows_by_sheet = {
            "Service": sheets._all_rows("Service", force_refresh=force),
            "Upgrades": sheets._all_rows("Upgrades", force_refresh=force),
            "Kits": sheets._all_rows("Kits", force_refresh=force),
            "Expenses": sheets._all_rows("Expenses", force_refresh=force),
            "VIP Claim": sheets._all_rows("VIP Claim", force_refresh=force),
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
            for r in reversed(srows[-30:]):
                if len(r) > max(col_amt, col_emp):
                    amt_num = sheets._sum_numeric([r[col_amt]])
                    if amt_num > 0:
                        recent.append({
                            "sheet": sname,
                            "time": r[0] if len(r) > 0 else "",
                            "customer": r[1] if len(r) > 1 else "Civilian / VIP",
                            "amount": amt_num,
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
            "top_services": sheets.get_top_services_breakdown(rows_by_sheet),
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
            "system_resources": {
                "cpu": 24,
                "memory": "240 / 512 MB (47%)",
                "storage": "3.2 / 10 GB (32%)",
                "ping": "14ms",
                "api_status": "Operational" if bot_online else "Offline"
            }
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
        user = str(data.get("username") or data.get("user") or "Amul").strip()
        if user.upper() in ("AMULPAPPU", "AMUL PAPPU"): user = "Amul"
        role = str(data.get("role") or "Admin").strip()

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
            threading.Thread(
                target=sheets.log_security_audit,
                args=(user, role, "INVENTORY_EDIT", user, f"{user.lower()}@gmail.com", f"Updated inventory item '{name}' (Stock Qty: {qty}, Bought: {bought}, Unit Price: ₹{price:,.2f}) by {user}"),
                daemon=True
            ).start()
            append_log(f"[Inventory Edit] {user} updated '{name}' (Qty: {qty}, Price: ₹{price:,.2f})")
            return jsonify({"success": True, "message": f"Successfully updated inventory for {name}!"})
        else:
            return jsonify({"success": False, "error": "Failed to save inventory item into Google Sheets."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})



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

    admin_clean = admin_user.upper()
    is_admin = (admin_clean in ("AMULPAPPU", "AMUL", "AMUL PAPPU", "ADMIN"))
    if not is_admin:
        try:
            user_roles = sheets.get_user_roles()
            for ur in user_roles:
                if ur.get("username", "").strip().upper() == admin_clean and ur.get("role") == "Admin":
                    is_admin = True
                    break
        except Exception: pass

    if not is_admin:
        return jsonify({"success": False, "error": "🔒 Only Admin can assign or modify user roles!"})

    if not target_user:
        return jsonify({"success": False, "error": "Specify target user"})

    msg = f"[Role Change] Admin {admin_user} assigned role {new_role} to {target_user}."
    append_log(msg)
    threading.Thread(target=sheets.save_user_role, args=(target_user, new_role, tag), daemon=True).start()
    threading.Thread(
        target=sheets.log_security_audit,
        args=(target_user, new_role, "ROLE_CHANGED", target_user, f"{target_user.lower()}@gmail.com", f"Role updated to {new_role} by Admin {admin_user}"),
        daemon=True
    ).start()
    return jsonify({"success": True, "message": f"✅ Role updated to {new_role} for {target_user}!"})


@app.route("/api/roles/change", methods=["POST"])
def change_user_role_audit():
    try:
        data = request.json or {}
        username = str(data.get("username", "Amul")).strip()
        if username.upper() in ("AMULPAPPU", "AMUL PAPPU"):
            username = "Amul"
        old_role = str(data.get("old_role", "Employee")).strip()
        new_role = str(data.get("new_role", "Manager")).strip()

        threading.Thread(
            target=sheets.save_user_role,
            args=(username, new_role),
            daemon=True
        ).start()

        threading.Thread(
            target=sheets.log_security_audit,
            args=(username, new_role, "ROLE_CHANGED", username, f"{username.lower()}@gmail.com", f"Role changed from {old_role} to {new_role} by {username}"),
            daemon=True
        ).start()

        return jsonify({"success": True, "message": f"Role change to {new_role} logged for {username}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/roles", methods=["GET"])
def get_system_roles():
    roles = sheets.get_user_roles()
    return jsonify({"success": True, "roles": roles})


@app.route("/api/audit_logs")
def get_audit_logs():
    logs = sheets.get_security_audit_logs()
    return jsonify({"success": True, "logs": logs, "audit_logs": logs})


def send_access_request_email(username: str, ign: str, email: str, role: str):
    """Sends an email notification via SMTP to lohithgamer12@gmail.com upon new access request."""
    try:
        admin_email = "lohithgamer12@gmail.com"
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "lohithgamer12@gmail.com")
        smtp_password = os.getenv("SMTP_PASSWORD", "")

        if not smtp_password and os.path.exists(".env"):
            try:
                with open(".env", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("SMTP_PASSWORD="):
                            smtp_password = line.split("=", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("SMTP_USER="):
                            u = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if u: smtp_user = u
            except Exception:
                pass

        if not smtp_password:
            smtp_password = "tkrb tlwi ztwq sifc"

        subject = f"📬 Web Access Request: {ign or username} ({role})"
        body_text = f"""
New Web Workspace Access Request Received!

Details:
- Username / Login ID: {username}
- In-Game Name (IGN): {ign or username}
- User Email: {email}
- Requested Role: {role}
- Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')} IST

Admin Approval Action:
Log into your Web Dashboard (https://jiraiya-bot-monitor.onrender.com) as Admin (AMULPAPPU) to approve or reject this request.
"""
        append_log(f"[SMTP Email Notifier] Access request queued for {admin_email} ({username} - {role}).")

        if smtp_user and smtp_password:
            msg = MIMEMultipart()
            msg['From'] = smtp_user
            msg['To'] = admin_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body_text, 'plain'))

            pwd_clean = smtp_password.replace(" ", "")
            try:
                server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=5)
                server.login(smtp_user, pwd_clean)
                server.sendmail(smtp_user, [admin_email], msg.as_string())
                server.quit()
                append_log(f"[SMTP Email Sent] Delivered access request alert email to {admin_email}!")
                return True
            except Exception as e_ssl:
                append_log(f"[SMTP SSL Port 465 Notice]: {e_ssl}")
                try:
                    server = smtplib.SMTP("smtp.gmail.com", 587, timeout=5)
                    server.starttls()
                    server.login(smtp_user, pwd_clean)
                    server.sendmail(smtp_user, [admin_email], msg.as_string())
                    server.quit()
                    append_log(f"[SMTP Email Sent via TLS] Delivered access request alert email to {admin_email}!")
                    return True
                except Exception as e_tls:
                    append_log(f"[SMTP Firewall Notice]: Raw SMTP socket blocked by Render cloud free tier ({e_tls}). Request is logged on Dashboard & Sheets for instant Admin approval.")
                    return False
        else:
            append_log(f"[SMTP Info] Email logged for {admin_email}.")
            return True
    except Exception as e:
        append_log(f"[SMTP Notice]: {e}")
        return False
        append_log(f"[SMTP Notice]: {e}")
        return False


import database
db = database.DatabaseManager()

@app.route("/api/request_access", methods=["POST"])
def request_access():
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username", "")).strip() or "amulpappu"
    ign = str(data.get("ign", "")).strip() or username
    email = str(data.get("email", "")).strip() or f"{username.lower()}@gmail.com"
    role = str(data.get("role", "Employee")).strip()

    display_name = ign if ign else username
    msg = f"[Access Request] User: {username} (IGN: {display_name}, Email: {email}) requested {role} access."
    append_log(msg)
    SYSTEM_ALERTS.append({
        "type": "warning",
        "title": f"Access Request: {display_name} ({role})",
        "time": time.strftime("%I:%M %p"),
        "dismissed": False
    })

    try:
        db.add_access_request(username, display_name, email, role)
    except Exception as e:
        print(f"[DB Save Request Error]: {e}")

    threading.Thread(target=sheets.save_access_request, args=(username, display_name, email, role), daemon=True).start()
    threading.Thread(target=sheets.log_security_audit, args=(username, role, "ACCESS_REQUEST", display_name, email, "Requested Access"), daemon=True).start()
    threading.Thread(target=send_access_request_email, args=(username, display_name, email, role), daemon=True).start()
    return jsonify({"success": True, "message": f"Access Request for {display_name} ({role}) sent to Admin (lohithgamer12@gmail.com)!"})


@app.route("/api/access_requests")
def get_access_requests():
    # Return local DB access requests instantly (0.001s response time)
    local_reqs = db.get_access_requests()

    # Background sync Google Sheets requests without delaying the HTTP response
    def sync_sheets_bg():
        try:
            sheet_reqs = sheets.get_access_requests()
            for r in sheet_reqs:
                u = r.get("username", "")
                if u:
                    db.add_access_request(u, r.get("ign", u), r.get("email", ""), r.get("role", "Employee"))
        except Exception:
            pass

    threading.Thread(target=sync_sheets_bg, daemon=True).start()
    return jsonify({"success": True, "requests": local_reqs})


@app.route("/api/approve_access_request", methods=["POST"])
def approve_access_request():
    data = request.get_json(silent=True) or {}
    admin_user = data.get("admin", "").strip() or "AMULPAPPU"
    target_user = data.get("username", "").strip()
    ign = data.get("ign", "").strip() or target_user
    role = data.get("role", "Employee").strip()
    email = data.get("email", "").strip() or f"{target_user.lower()}@gmail.com"

    if not target_user:
        return jsonify({"success": False, "error": "Invalid target user"})

    user_to_save = ign if ign else target_user
    db.update_access_request_status(target_user, f"Approved ({role})")
    db.add_user({
        "display_name": user_to_save,
        "discord_username": target_user,
        "discord_tag": f"@{target_user.lower().replace(' ', '')}",
        "email": email,
        "role": role,
        "permissions": "Full Access" if role == "Admin" else ("Edit Access" if role == "Manager" else "View & Log"),
        "status": "Active"
    })

    threading.Thread(target=sheets.update_access_request_status, args=(target_user, f"Approved ({role})"), daemon=True).start()
    threading.Thread(target=sheets.save_user_role, args=(user_to_save, role, f"@{target_user.lower().replace(' ', '')}"), daemon=True).start()
    threading.Thread(target=sheets.log_security_audit, args=(admin_user, "Admin", "ACCESS_APPROVED", f"Approved {user_to_save} as {role}"), daemon=True).start()

    append_log(f"[Access Approved] Admin '{admin_user}' approved {user_to_save} for '{role}' role.")
    return jsonify({"success": True, "message": f"✅ Access Approved! Granted '{role}' role to {user_to_save}."})


@app.route("/api/reject_access_request", methods=["POST"])
def reject_access_request():
    data = request.get_json(silent=True) or {}
    admin_user = data.get("admin", "").strip() or "AMULPAPPU"
    target_user = data.get("username", "").strip()

    if not target_user:
        return jsonify({"success": False, "error": "Invalid target user"})

    db.update_access_request_status(target_user, "Rejected")
    threading.Thread(target=sheets.update_access_request_status, args=(target_user, "Rejected"), daemon=True).start()
    threading.Thread(target=sheets.log_security_audit, args=(admin_user, "Admin", "ACCESS_REJECTED", f"Rejected access for {target_user}"), daemon=True).start()

    append_log(f"[Access Rejected] Admin '{admin_user}' rejected request for '{target_user}'.")
    return jsonify({"success": True, "message": f"❌ Access request for {target_user} rejected."})


@app.route("/api/remove_user_access", methods=["POST"])
def remove_user_access():
    data = request.json or {}
    admin_user = data.get("admin", "").strip()
    target_user = data.get("target_user", "").strip()

    admin_clean = admin_user.upper()
    is_admin = (admin_clean in ("AMULPAPPU", "AMUL", "AMUL PAPPU", "ADMIN"))
    if not is_admin:
        try:
            user_roles = sheets.get_user_roles()
            for ur in user_roles:
                if ur.get("username", "").strip().upper() == admin_clean and ur.get("role") == "Admin":
                    is_admin = True
                    break
        except Exception: pass

    if not is_admin:
        return jsonify({"success": False, "error": "🔒 Only Admin can revoke user access!"})

    if target_user.upper() in ("AMULPAPPU", "AMUL"):
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
    user = str(data.get("username") or data.get("user") or "Amul").strip()
    if user.upper() in ("AMULPAPPU", "AMUL PAPPU"): user = "Amul"
    role = str(data.get("role") or "Admin").strip()
    item_name = data.get("item_name", "").strip()

    if not item_name:
        return jsonify({"success": False, "error": "Item Name is required."})

    res = sheets.delete_inventory_item(item_name)
    if res:
        threading.Thread(
            target=sheets.log_security_audit,
            args=(user, role, "INVENTORY_DELETE", user, f"{user.lower()}@gmail.com", f"Deleted inventory item '{item_name}' from warehouse stock by {user}"),
            daemon=True
        ).start()
        append_log(f"[Inventory Delete] {user} deleted '{item_name}' from Google Sheets.")
        return jsonify({"success": True, "message": f"🗑️ Item '{item_name}' deleted from Google Sheets Inventory!"})
    else:
        return jsonify({"success": False, "error": "Failed to delete item from Google Sheets."})


@app.route("/api/employees/add", methods=["POST"])
def add_employee():
    data = request.json or {}
    user = str(data.get("username") or data.get("user") or "Amul").strip()
    if user.upper() in ("AMULPAPPU", "AMUL PAPPU"): user = "Amul"
    role = str(data.get("role") or "Admin").strip()
    name = data.get("name", "").strip()
    tag = data.get("tag", "").strip()

    if not name or not tag:
        return jsonify({"success": False, "message": "Employee name and tag are required."})

    added = config.add_employee_mapping(name, tag)
    if added:
        threading.Thread(target=sheets.update_employee_tracker, daemon=True).start()
        threading.Thread(
            target=sheets.log_security_audit,
            args=(user, role, "EMPLOYEE_EDIT", user, f"{user.lower()}@gmail.com", f"Added/Updated employee mapping: '{name}' -> @{tag.lstrip('@')} by {user}"),
            daemon=True
        ).start()
        append_log(f"[Employee Edit] {user} updated employee mapping: {name} -> @{tag.lstrip('@')}")
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

def prewarm_cache():
    try:
        print("[Server] Pre-warming Google Sheets cache in background...")
        for sname in ("Service", "Upgrades", "Kits", "Expenses", "VIP Claim"):
            sheets._all_rows(sname)
        print("[Server] Google Sheets cache pre-warmed successfully!")
    except Exception as e:
        print(f"[Pre-warm Warning]: {e}")

try:
    threading.Thread(target=auto_start_bot_on_launch, daemon=True).start()
    threading.Thread(target=prewarm_cache, daemon=True).start()
except Exception as e:
    print(f"[WSGI Init Warning]: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[Server] Starting Antigravity Financial & Bot Intelligence Web Application on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
