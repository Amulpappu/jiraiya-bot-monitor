import os
import sys
import time
import datetime
from flask import Flask, jsonify, request, render_template, session, redirect, url_for

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import config
import sheets
import database

db = database.DatabaseManager()

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))
app.secret_key = os.getenv("SECRET_KEY", "jiraiya-secret-key-2026")
application = app

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin2026")
IS_MAINTENANCE_MODE = False
MAINTENANCE_MESSAGE = "The website is currently undergoing scheduled maintenance. Please check back shortly!"


@app.route("/")
def index():
    return render_template("index.html", is_maintenance=IS_MAINTENANCE_MODE, maintenance_msg=MAINTENANCE_MESSAGE)


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

    if not user_name:
        return jsonify({"success": False, "error": "Please enter your Name!"}), 400

    if password != ADMIN_PASSWORD:
        sheets.append_user_audit_log(user_name, "LOGIN_FAILED", "Invalid Password Attempt", role="Visitor")
        return jsonify({"success": False, "error": "Invalid Password! Access Denied."}), 401

    session["user_name"] = user_name
    session["is_admin"] = True

    # Log successful login to User_Audit_Logs sheet
    sheets.append_user_audit_log(user_name, "USER_LOGIN", "Web/App Auth Success", role="Admin")

    return jsonify({
        "success": True,
        "message": f"Welcome {user_name}!",
        "user_name": user_name,
        "is_admin": True
    })


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


@app.route("/api/dashboard")
def get_dashboard_data():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        expense_rows = sheets._all_rows("Expenses")

        service_rev = sum(sheets._sum_numeric([r[3]]) for r in service_rows if len(r) > 3)
        upgrade_rev = sum(sheets._sum_numeric([r[2]]) for r in upgrade_rows if len(r) > 2)
        kit_rev = sum(sheets._sum_numeric([r[3]]) for r in kit_rows if len(r) > 3)
        expenses_tot = sum(sheets._sum_numeric([r[1]]) for r in expense_rows if len(r) > 1)

        total_rev = service_rev + upgrade_rev + kit_rev
        net_profit = total_rev - expenses_tot

        return jsonify({
            "success": True,
            "total_revenue": total_rev,
            "service_revenue": service_rev,
            "upgrade_revenue": upgrade_rev,
            "kit_revenue": kit_rev,
            "total_expenses": expenses_tot,
            "net_profit": net_profit,
            "total_transactions": len(service_rows) + len(upgrade_rows) + len(kit_rows) + len(expense_rows),
            "maintenance_mode": IS_MAINTENANCE_MODE
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
