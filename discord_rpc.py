import os
import time
import threading
import logging
import config

try:
    from pypresence import Presence
    PYPRESENCE_AVAILABLE = True
except ImportError:
    PYPRESENCE_AVAILABLE = False

DISCORD_CLIENT_ID = getattr(config, "DISCORD_CLIENT_ID", "1527473505875132588")

_rpc = None
_rpc_thread = None
_running = False
_start_time = None


def start_discord_rpc(details="Jiraiya Customs & Tunerz", state="Financial & Employee Monitor Active"):
    """
    Connects to local Discord Rich Presence (RPC) and updates your Discord profile status 
    showing live playing activity, timer, and custom links.
    """
    global _running, _rpc_thread, _start_time
    if not PYPRESENCE_AVAILABLE:
        logging.warning("pypresence module not installed, skipping Discord Rich Presence.")
        return

    if _running:
        return

    _running = True
    _start_time = time.time()

    def _update_loop():
        global _rpc, _running
        while _running:
            try:
                if _rpc is None:
                    _rpc = Presence(DISCORD_CLIENT_ID)
                    _rpc.connect()

                _rpc.update(
                    details=details,
                    state=state,
                    start=_start_time,
                    large_image="app_logo",
                    large_text="Jiraiya Customs & Tunerz",
                    buttons=[
                        {"label": "Web Dashboard", "url": "http://localhost:5000"},
                    ]
                )
            except Exception:
                # Discord desktop app closed or connecting
                _rpc = None

            time.sleep(15)

    _rpc_thread = threading.Thread(target=_update_loop, daemon=True)
    _rpc_thread.start()


def stop_discord_rpc():
    """Stops the Discord Rich Presence status."""
    global _running, _rpc
    _running = False
    if _rpc:
        try:
            _rpc.close()
        except Exception:
            pass
        _rpc = None
