import os
import json
import time
import datetime

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DATA_DIR, "app_database.json")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

DEFAULT_SETTINGS = {
    "theme": {
        "primary_color": "#6C4DFF",
        "secondary_color": "#2A8DFF",
        "success_color": "#19D96B",
        "warning_color": "#F9A826",
        "danger_color": "#FF5C5C",
        "bg_color": "#090B14",
        "card_bg": "#131826",
        "sidebar_bg": "#0E1320",
        "border_color": "#20283C",
    },
    "bot_config": {
        "bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
        "guild_id": "1327473501075122259",
        "spreadsheet_id": os.getenv("EXISTING_SPREADSHEET_ID", "1yDRe6R_G2QdYvXfE-OIdG5iK-RlhEaWc3w8Pq0k72gU"),
        "credentials_file": "credentials.json",
        "auto_sync_interval": 15,
        "auto_backup": True,
        "startup_autostart": True,
    },
}

DEFAULT_USERS = [
    {
        "id": "1",
        "display_name": "AMULPAPPU",
        "discord_username": "AMULPAPPU",
        "role": "Administrator",
        "status": "Active",
        "last_login": "Just Now",
    }
]

DEFAULT_ALERTS = [
    {"timestamp": "2026-08-02 16:45:00", "type": "System Initialized", "message": "Jiraiya Financial Intelligence & Bot Monitor active.", "severity": "info"}
]


class DatabaseManager:
    def __init__(self):
        self.data = {
            "settings": DEFAULT_SETTINGS,
            "users": DEFAULT_USERS,
            "alerts": DEFAULT_ALERTS,
            "inventory": [],
            "expenses": [],
            "last_sync": datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        }
        self.load()

    def load(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.data["settings"] = saved.get("settings", DEFAULT_SETTINGS)
                    self.data["users"] = saved.get("users", DEFAULT_USERS)
                    self.data["alerts"] = saved.get("alerts", DEFAULT_ALERTS)
                    self.data["inventory"] = saved.get("inventory", [])
                    self.data["expenses"] = saved.get("expenses", [])
                    self.data["last_sync"] = saved.get("last_sync", "")
            except Exception:
                self.save()
        else:
            self.save()

    def save(self):
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_settings(self):
        return self.data.get("settings", DEFAULT_SETTINGS)

    def update_settings(self, new_settings):
        self.data["settings"] = new_settings
        self.save()

    def get_users(self):
        return self.data.get("users", DEFAULT_USERS)

    def add_alert(self, alert_type, message, severity="info"):
        now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        self.data["alerts"].insert(0, {
            "timestamp": now_str,
            "type": alert_type,
            "message": message,
            "severity": severity
        })
        self.data["alerts"] = self.data["alerts"][:100]
        self.save()


db = DatabaseManager()
