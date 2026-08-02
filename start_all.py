import os
import sys
import threading
import subprocess

def run_bot():
    print("[Launcher] Starting Jiraiya Discord Bot...")
    subprocess.run([sys.executable, "bot.py"])

def run_web():
    print("[Launcher] Starting Jiraiya Web Dashboard Monitor...")
    from monitor_app import app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_bot.start()
    run_web()
