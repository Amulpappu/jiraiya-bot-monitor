import os
import json
import time
import datetime
from collections import defaultdict

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
    "sheet_theme": {
        "header_color": "#1F2937",
        "success_color": "#064E3B",
        "warning_color": "#78350F",
        "error_color": "#7F1D1D",
        "transaction_color": "#1E1B4B",
        "log_highlight": "#312E81",
        "alt_row_color": "#111827",
    },
    "bot_config": {
        "bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
        "guild_id": "1327473501075122259",
        "spreadsheet_id": os.getenv("EXISTING_SPREADSHEET_ID", "1yDRe6R_G2QdYvXfE-OIdG5iK-RlhEaWc3w8Pq0k72gU"),
        "credentials_file": "credentials.json",
        "auto_sync_interval": 15,
        "auto_backup": True,
        "startup_autostart": True,
        "log_reading_interval": 5,
    },
    "notifications": {
        "desktop_notifications": True,
        "discord_notifications": True,
        "sound_notifications": True,
        "bot_offline_alert": True,
        "sync_failed_alert": True,
        "new_transaction_alert": True,
        "employee_activity_alert": True,
    }
}

DEFAULT_USERS = [
    {
        "id": "1",
        "display_name": "AMULPAPPU",
        "discord_username": "AMULPAPPU",
        "discord_tag": "@amulpappu",
        "discord_id": "123456789012345678",
        "email": "admin@jiraiya.customs",
        "role": "Administrator",
        "permissions": "Full Access",
        "status": "Active",
        "last_login": "2026-07-25 03:30:00 IST",
        "created_at": "2026-07-01",
    },
    {
        "id": "2",
        "display_name": "Eli",
        "discord_username": "eli_tuner",
        "discord_tag": "@eli",
        "discord_id": "234567890123456789",
        "email": "eli@jiraiya.customs",
        "role": "Chief Mechanic",
        "permissions": "Employees, Services, Kits, Upgrades",
        "status": "Active",
        "last_login": "2026-07-24 22:15:00 IST",
        "created_at": "2026-07-05",
    },
    {
        "id": "3",
        "display_name": "Meenu Kutty",
        "discord_username": "blari",
        "discord_tag": "@blari",
        "discord_id": "345678901234567890",
        "email": "meenu@jiraiya.customs",
        "role": "Manager",
        "permissions": "Dashboard, Logs, Transactions, Employees, Reports",
        "status": "Active",
        "last_login": "2026-07-24 21:45:00 IST",
        "created_at": "2026-07-23",
    }
]

DEFAULT_ALERTS = [
    {"timestamp": "2026-07-25 03:30:00", "type": "System Status", "message": "Bot monitor initialised and connected.", "severity": "info"},
    {"timestamp": "2026-07-25 03:22:00", "type": "Employee Added", "message": "Staff mapped: Meenu Kutty -> @blari", "severity": "success"},
    {"timestamp": "2026-07-25 03:10:00", "type": "Sheet Sync", "message": "Google Sheets full sync completed successfully.", "severity": "success"},
    {"timestamp": "2026-07-24 22:15:00", "type": "VIP Claim", "message": "VIP Claim parsed: Emily - Teddy (₹24,750)", "severity": "primary"},
]

DEFAULT_INVENTORY = [
    {"id": "1", "item_name": "Repair Kit", "category": "Kits", "qty": 286, "unit_price": 500, "min_alert": 50, "last_updated": "2026-07-25 03:00:00"},
    {"id": "2", "item_name": "Cleaning Kit", "category": "Kits", "qty": 204, "unit_price": 300, "min_alert": 40, "last_updated": "2026-07-25 03:00:00"},
    {"id": "3", "item_name": "Turbocharger Stage 3", "category": "Upgrades", "qty": 35, "unit_price": 25000, "min_alert": 5, "last_updated": "2026-07-24 18:30:00"},
    {"id": "4", "item_name": "Engine Synthetic Oil", "category": "Tuning", "qty": 120, "unit_price": 1500, "min_alert": 20, "last_updated": "2026-07-24 16:00:00"},
    {"id": "5", "item_name": "Kevlar Body Armor", "category": "Parts", "qty": 50, "unit_price": 12000, "min_alert": 10, "last_updated": "2026-07-23 20:00:00"},
    {"id": "6", "item_name": "High Performance Brake Pads", "category": "Parts", "qty": 80, "unit_price": 4500, "min_alert": 15, "last_updated": "2026-07-23 15:00:00"},
]

DEFAULT_EXPENSES = [
    {"timestamp": "2026-07-24 20:00:00", "amount": 45000, "employee": "Eli", "category": "Inventory Restock", "desc": "Purchased 100x Repair Kits"},
    {"timestamp": "2026-07-24 16:30:00", "amount": 28000, "employee": "AMULPAPPU", "category": "Shop Maintenance", "desc": "Hydraulic lift maintenance service"},
    {"timestamp": "2026-07-23 18:00:00", "amount": 15000, "employee": "Meenu Kutty", "category": "Tools & Supplies", "desc": "Pneumatic wrench & cleaning supplies"},
]


class DatabaseManager:
    def __init__(self):
        self.data = {
            "settings": DEFAULT_SETTINGS,
            "users": DEFAULT_USERS,
            "alerts": DEFAULT_ALERTS,
            "inventory": DEFAULT_INVENTORY,
            "expenses": DEFAULT_EXPENSES,
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
                    self.data["inventory"] = saved.get("inventory", DEFAULT_INVENTORY)
                    self.data["expenses"] = saved.get("expenses", DEFAULT_EXPENSES)
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

    def add_user(self, user_dict):
        user_dict["id"] = str(len(self.data["users"]) + 1)
        user_dict["created_at"] = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        user_dict["last_login"] = "Never"
        self.data["users"].append(user_dict)
        self.save()
        return user_dict

    def update_user(self, user_id, updated_fields):
        for u in self.data["users"]:
            if u["id"] == str(user_id):
                u.update(updated_fields)
                break
        self.save()

    def delete_user(self, user_id):
        self.data["users"] = [u for u in self.data["users"] if u["id"] != str(user_id)]
        self.save()

    def get_alerts(self):
        return self.data.get("alerts", DEFAULT_ALERTS)

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

    def get_inventory(self):
        return self.data.get("inventory", DEFAULT_INVENTORY)

    def add_or_update_inventory_item(self, item_name, category, qty, unit_price, min_alert):
        now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        items = self.get_inventory()
        found = False
        for item in items:
            if item["item_name"].strip().lower() == item_name.strip().lower():
                item["category"] = category
                item["qty"] = int(qty)
                item["unit_price"] = float(unit_price)
                item["min_alert"] = int(min_alert)
                item["last_updated"] = now_str
                found = True
                break

        if not found:
            new_item = {
                "id": str(len(items) + 1),
                "item_name": item_name.strip(),
                "category": category,
                "qty": int(qty),
                "unit_price": float(unit_price),
                "min_alert": int(min_alert),
                "last_updated": now_str
            }
            items.append(new_item)

    def delete_inventory_item(self, item_name):
        items = self.get_inventory()
        self.data["inventory"] = [i for i in items if i["item_name"].strip().lower() != item_name.strip().lower()]
        self.save()

    def get_expenses(self):
        return self.data.get("expenses", DEFAULT_EXPENSES)

    def add_expense(self, amount, employee, category, desc):
        now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        exp = {
            "timestamp": now_str,
            "amount": float(amount),
            "employee": employee,
            "category": category,
            "desc": desc
        }
        self.data.get("expenses", DEFAULT_EXPENSES).insert(0, exp)
        self.save()
        return exp

    def delete_expense(self, timestamp_str, amount_val):
        exps = self.get_expenses()
        self.data["expenses"] = [e for e in exps if not (e.get("timestamp") == timestamp_str and abs(e.get("amount", 0) - amount_val) < 1)]
        self.save()


db = DatabaseManager()


def get_date_range_bounds(preset_name: str, custom_start=None, custom_end=None):
    now = datetime.datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    preset = (preset_name or "All Time").lower()

    if "today" in preset:
        return today_start, today_end
    elif "yesterday" in preset:
        yest = today_start - datetime.timedelta(days=1)
        yest_end = yest.replace(hour=23, minute=59, second=59)
        return yest, yest_end
    elif "last 7" in preset:
        return today_start - datetime.timedelta(days=7), today_end
    elif "last 30" in preset:
        return today_start - datetime.timedelta(days=30), today_end
    elif "this week" in preset or "week" in preset:
        start_of_week = today_start - datetime.timedelta(days=today_start.weekday())
        return start_of_week, today_end
    elif "this month" in preset or "month" in preset:
        start_of_month = today_start.replace(day=1)
        return start_of_month, today_end
    elif "previous month" in preset:
        first_of_this_month = today_start.replace(day=1)
        last_of_prev_month = first_of_this_month - datetime.timedelta(days=1)
        first_of_prev_month = last_of_prev_month.replace(day=1)
        return first_of_prev_month, last_of_prev_month.replace(hour=23, minute=59, second=59)
    elif "this year" in preset or "year" in preset:
        start_of_year = today_start.replace(month=1, day=1)
        return start_of_year, today_end
    elif "custom" in preset and custom_start and custom_end:
        return custom_start, custom_end

    return None, None
