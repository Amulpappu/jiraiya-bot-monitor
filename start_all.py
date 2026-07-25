import os
import sys
import threading
import subprocess
import time

def run_bot():
    print("[Launcher] Starting Discord Bot process in background...")
    while True:
        try:
            proc = subprocess.run([sys.executable, "bot.py"])
            print(f"[Launcher] Bot process exited with code {proc.returncode}. Restarting in 5s...")
        except Exception as e:
            print(f"[Launcher Error] Bot process failed: {e}")
        time.sleep(5)

def run_web():
    port = int(os.environ.get("PORT", 5000))
    print(f"[Launcher] Starting Web Dashboard on 0.0.0.0:{port}...")
    import monitor_app
    monitor_app.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_bot.start()
    run_web()
