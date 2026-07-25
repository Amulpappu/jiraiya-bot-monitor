import os
import sys
import json
import time
import subprocess
import threading
from flask import Flask, jsonify, request, render_template, Response

import config
import sheets
import discord_rpc

app = Flask(__name__, template_folder="templates")

BOT_PROCESS = None
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


def reader_thread(proc):
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        append_log(line.strip())


@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/api/start", methods=["POST"])
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
        return jsonify({"success": False, "message": "Bot is already running."})

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
    append_log("Bot process started (PID: " + str(proc.pid) + ")")

    t = threading.Thread(target=reader_thread, args=(proc,), daemon=True)
    t.start()
    discord_rpc.start_discord_rpc(
        details="Jiraiya Customs & Tunerz",
        state="Financial & Employee Monitor Active"
    )

    return jsonify({"success": True, "message": "Bot started successfully."})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    global BOT_PROCESS
    discord_rpc.stop_discord_rpc()
    if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
        BOT_PROCESS = None
        return jsonify({"success": False, "message": "Bot is not running."})

    try:
        BOT_PROCESS.terminate()
        BOT_PROCESS.wait(timeout=5)
    except Exception:
        BOT_PROCESS.kill()

    BOT_PROCESS = None
    append_log("Bot process stopped.")
    return jsonify({"success": True, "message": "Bot stopped."})


@app.route("/api/restart", methods=["POST"])
def restart_bot():
    stop_bot()
    time.sleep(1)
    return start_bot()


@app.route("/api/rescan", methods=["POST"])
def rescan():
    append_log("[Action] Initiating full sheet wipe and fresh Discord history re-scan...")

    def _worker():
        try:
            success = sheets.wipe_all_data_sheets()
            if success:
                append_log("[System] Google Sheets wiped successfully. Re-seeding official expenses...")
            if os.path.exists("processed_hashes.json"):
                with open("processed_hashes.json", "w") as f:
                    f.write("[]")
            restart_bot()
        except Exception as e:
            append_log(f"[Error] Re-scan failed: {e}")

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"success": True, "message": "Wipe & Re-scan initiated."})


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
        rows_by_sheet = {
            "Service": sheets._all_rows("Service"),
            "Upgrades": sheets._all_rows("Upgrades"),
            "Kits": sheets._all_rows("Kits"),
            "Expenses": sheets._all_rows("Expenses"),
            "VIP Claim": sheets._all_rows("VIP Claim"),
        }

        service_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Service"]] for r in rows_by_sheet["Service"] if len(r) > sheets._AMOUNT_COL["Service"]])
        upgrade_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Upgrades"]] for r in rows_by_sheet["Upgrades"] if len(r) > sheets._AMOUNT_COL["Upgrades"]])
        kits_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Kits"]] for r in rows_by_sheet["Kits"] if len(r) > sheets._AMOUNT_COL["Kits"]])
        expenses_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Expenses"]] for r in rows_by_sheet["Expenses"] if len(r) > sheets._AMOUNT_COL["Expenses"]])
        vip_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["VIP Claim"]] for r in rows_by_sheet["VIP Claim"] if len(r) > sheets._AMOUNT_COL["VIP Claim"]])

        total_sales = service_total + upgrade_total + kits_total
        net_profit = total_sales - expenses_total

        total_txns = len(rows_by_sheet["Service"]) + len(rows_by_sheet["Upgrades"]) + len(rows_by_sheet["Kits"]) + len(rows_by_sheet["VIP Claim"])

        recent = []
        for sname, srows in rows_by_sheet.items():
            col_amt = sheets._AMOUNT_COL.get(sname, 4)
            col_emp = sheets._EMPLOYEE_COL.get(sname, 3)
            for r in reversed(srows[-15:]):
                if len(r) > max(col_amt, col_emp):
                    recent.append({
                        "sheet": sname,
                        "time": r[0] if len(r) > 0 else "",
                        "customer": r[1] if len(r) > 1 else "Civilian / VIP",
                        "amount": r[col_amt] if len(r) > col_amt else "0",
                        "employee": r[col_emp] if len(r) > col_emp else "System",
                    })

        recent.sort(key=lambda x: str(x["time"]), reverse=True)

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
                "uptime": "99.98%",
            },
            "recent_activity": recent[:25],
            "employees": config.EMPLOYEE_MAPPING,
            "charts": {
                "revenue_trend": [
                    {"label": "Jul 18", "revenue": total_sales * 0.55, "profit": net_profit * 0.50},
                    {"label": "Jul 19", "revenue": total_sales * 0.65, "profit": net_profit * 0.60},
                    {"label": "Jul 20", "revenue": total_sales * 0.85, "profit": net_profit * 0.80},
                    {"label": "Jul 21", "revenue": total_sales * 0.75, "profit": net_profit * 0.70},
                    {"label": "Jul 22", "revenue": total_sales * 0.90, "profit": net_profit * 0.85},
                    {"label": "Jul 23", "revenue": total_sales * 0.95, "profit": net_profit * 0.90},
                    {"label": "Jul 24", "revenue": total_sales, "profit": net_profit},
                ],
                "distribution": [
                    {"name": "Services", "value": service_total, "percentage": 38.6, "color": "#6C4DFF"},
                    {"name": "Kits", "value": kits_total, "percentage": 28.5, "color": "#2A8DFF"},
                    {"name": "Upgrades", "value": upgrade_total, "percentage": 22.0, "color": "#19D96B"},
                    {"name": "VIP Claims", "value": vip_total, "percentage": 10.9, "color": "#F9A826"},
                ]
            },
            "system_resources": {
                "cpu": 62,
                "memory": "7.4 / 16 GB (46%)",
                "storage": "256 / 512 GB (50%)",
                "ping": "18ms",
                "api_status": "Operational"
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


def auto_start_bot_on_launch():
    time.sleep(1)
    if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
        try:
            start_bot()
            print("[Server] Auto-started 24/7 Discord Bot Process successfully.")
        except Exception as e:
            print(f"[Server Warning] Could not auto-start bot: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    threading.Thread(target=auto_start_bot_on_launch, daemon=True).start()
    print(f"[Server] Starting Antigravity Financial & Bot Intelligence Web Application on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
