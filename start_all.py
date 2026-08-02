import os
import sys
import time
import threading
import subprocess

def run_bot():
    print("[Launcher] Starting Jiraiya Discord Bot background process...")
    try:
        subprocess.run([sys.executable, "bot.py"])
    except Exception as e:
        print(f"[Launcher ERROR] Bot process exception: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[Launcher] Starting Render Web Service listening on 0.0.0.0:{port}...")

    # Launch bot in daemon thread so Web server opens PORT instantly for Render HTTP health check
    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_bot.start()

    from monitor_app import app
    app.run(host="0.0.0.0", port=port, debug=False)
