import os
import sys
import time
import threading
import subprocess
import urllib.request

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://jiraiya-bot-monitor.onrender.com")


def run_bot():
    print("[Launcher] Starting Jiraiya Discord Bot background process...")
    try:
        env = os.environ.copy()
        env["RUNNING_IN_START_ALL"] = "1"
        subprocess.run([sys.executable, "bot.py"], env=env)
    except Exception as e:
        print(f"[Launcher ERROR] Bot process exception: {e}")


def run_keep_alive():
    """Pings Render web app every 10 minutes to prevent Render free tier from sleeping."""
    time.sleep(30)
    while True:
        try:
            url = f"{RENDER_URL}/api/status"
            req = urllib.request.Request(url, headers={"User-Agent": "RenderKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.getcode()
                print(f"[KeepAlive] Self pinged {url} -> Status {status}")
        except Exception as e:
            print(f"[KeepAlive] Ping exception: {e}")
        time.sleep(600)


if __name__ == "__main__":
    os.environ["RUNNING_IN_START_ALL"] = "1"
    port = int(os.environ.get("PORT", 5000))
    print(f"[Launcher] Starting Render Web Service listening on 0.0.0.0:{port}...")

    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_bot.start()

    t_ping = threading.Thread(target=run_keep_alive, daemon=True)
    t_ping.start()

    from monitor_app import app
    app.run(host="0.0.0.0", port=port, debug=False)
