import os
import sys
import time
import datetime
from flask import Flask, jsonify, request, render_template, send_file

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import config
import sheets
import database

db = database.DatabaseManager()

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))
application = app


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    return jsonify({
        "running": True,
        "status": "🟢 Operational",
        "sync_status": "🟢 Live Synced",
        "timestamp": time.time()
    })


@app.route("/api/dashboard")
def get_dashboard_data():
    try:
        service_rows = sheets._all_rows("Service")
        upgrade_rows = sheets._all_rows("Upgrades")
        kit_rows = sheets._all_rows("Kits")
        expense_rows = sheets._all_rows("Expenses")

        service_rev = sum(sheets._sum_numeric([r[3]]) for r in service_rows if len(r) > 3)
        upgrade_rev = sum(sheets._sum_numeric([r[3]]) for r in upgrade_rows if len(r) > 3)
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
            "total_transactions": len(service_rows) + len(upgrade_rows) + len(kit_rows) + len(expense_rows)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
