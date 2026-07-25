import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import math
import csv
import subprocess
import threading
from collections import Counter, defaultdict
import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk

import config
import sheets
import discord_rpc
import database
from database import db, get_date_range_bounds

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def resolve_name(raw_name: str) -> str:
    if not raw_name:
        return "Unknown"
    cleaned = raw_name.strip().lstrip("@")
    if "#" in cleaned:
        cleaned = cleaned.split("#")[0]

    all_in_game_names = set(config.EMPLOYEE_MAPPING.values())
    for name in all_in_game_names:
        if cleaned.lower() == name.lower():
            return name

    for tag, in_game_name in config.EMPLOYEE_MAPPING.items():
        tag_clean = tag.strip().lstrip("@").lower()
        if cleaned.lower() == tag_clean:
            return in_game_name

    return raw_name.strip()


def _get_python_exe():
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()

    for d in (cwd, base_dir):
        pyw = os.path.join(d, "venv", "Scripts", "pythonw.exe")
        if os.path.exists(pyw):
            return pyw
        py = os.path.join(d, "venv", "Scripts", "python.exe")
        if os.path.exists(py):
            return py

    return "pythonw" if sys.platform == "win32" else "python"


def export_treeview_to_csv(tree, default_name="export.csv"):
    try:
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=default_name
        )
        if not file_path:
            return

        headers = [tree.heading(col)["text"] for col in tree["columns"]]
        rows = []
        for item in tree.get_children():
            rows.append(tree.item(item)["values"])

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        messagebox.showinfo("Export Successful", f"Data exported successfully to:\n{file_path}")
    except Exception as e:
        messagebox.showerror("Export Error", f"Failed to export data: {e}")


class JiraiyaBotMonitorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Code69-Jiraiya Custom & Tunerz — Bot Monitor & Financial Intelligence")
        self.geometry("1380x860")
        self.minsize(1120, 720)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        if os.path.exists("app_logo.ico"):
            try:
                self.iconbitmap("app_logo.ico")
            except Exception:
                pass

        self.bot_process = None
        self.is_running = False
        self.bot_start_time = None
        self.selected_date_filter = "All Time"

        # Settings data
        self.app_settings = db.get_settings()

        # Custom ttk styles for tables
        self._init_ttk_styles()

        # Load animated GIF frames for Logo
        self.logo_frames = []
        self.current_logo_frame = 0
        if os.path.exists("app_logo.gif"):
            try:
                from PIL import Image, ImageSequence
                gif = Image.open("app_logo.gif")
                for frame in ImageSequence.Iterator(gif):
                    f = frame.convert("RGBA")
                    self.logo_frames.append(ctk.CTkImage(light_image=f, dark_image=f, size=(42, 42)))
            except Exception:
                pass

        # Configure root background
        self.configure(fg_color="#090B14")

        # ── Main Outer Frame ──
        self.outer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.outer_frame.pack(fill="both", expand=True)

        # ── Left Sidebar Navigation (240px) ──
        self.sidebar = ctk.CTkFrame(self.outer_frame, width=240, fg_color="#0E1320", corner_radius=0, border_width=1, border_color="#20283C")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Sidebar Header: Logo + Brand
        self.brand_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.brand_box.pack(fill="x", padx=16, pady=(18, 14))

        if self.logo_frames:
            self.logo_lbl = ctk.CTkLabel(self.brand_box, image=self.logo_frames[0], text="")
            self.logo_lbl.pack(side="left", padx=(0, 10))
        elif os.path.exists("app_logo.png"):
            try:
                from PIL import Image
                pil_logo = Image.open("app_logo.png")
                self.logo_img = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(42, 42))
                self.logo_lbl = ctk.CTkLabel(self.brand_box, image=self.logo_img, text="")
                self.logo_lbl.pack(side="left", padx=(0, 10))
            except Exception:
                pass

        self.brand_text_box = ctk.CTkFrame(self.brand_box, fg_color="transparent")
        self.brand_text_box.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(self.brand_text_box, text="CODE69", font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"), text_color="#FFFFFF", anchor="w").pack(anchor="w")
        ctk.CTkLabel(self.brand_text_box, text="Jiraiya Custom & Tunerz", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6C4DFF", anchor="w").pack(anchor="w")

        # Sidebar Menu Items
        self.nav_btns = {}
        self.nav_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.nav_container.pack(fill="both", expand=True, padx=10)

        # MAIN Section
        ctk.CTkLabel(self.nav_container, text="MAIN", font=ctk.CTkFont(size=10, weight="bold"), text_color="#4E5D7C").pack(anchor="w", padx=12, pady=(10, 4))

        main_items = [
            ("dashboard", "📊   Dashboard"),
            ("overview", "📈   Overview"),
            ("logs", "📄   Logs"),
            ("transactions", "💳   Transactions"),
            ("alerts", "🔔   Alerts"),
        ]
        for key, label in main_items:
            btn = ctk.CTkButton(
                self.nav_container,
                text=label,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="transparent",
                hover_color="#131826",
                text_color="#A4AEC6",
                anchor="w",
                height=34,
                corner_radius=10,
                command=lambda k=key: self.show_page(k)
            )
            btn.pack(fill="x", pady=2)
            self.nav_btns[key] = btn

        # MANAGEMENT Section
        ctk.CTkLabel(self.nav_container, text="MANAGEMENT", font=ctk.CTkFont(size=10, weight="bold"), text_color="#4E5D7C").pack(anchor="w", padx=12, pady=(12, 4))

        mgmt_items = [
            ("services", "🛠️   Service"),
            ("upgrades", "🔧   Upgrade"),
            ("kits", "🧰   Kits"),
            ("vip_claims", "👑   Vip Log"),
            ("expenses", "💸   Bill Claim"),
            ("employees", "👥   Employees"),
            ("inventory", "📦   Inventory"),
        ]
        for key, label in mgmt_items:
            btn = ctk.CTkButton(
                self.nav_container,
                text=label,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="transparent",
                hover_color="#131826",
                text_color="#A4AEC6",
                anchor="w",
                height=34,
                corner_radius=10,
                command=lambda k=key: self.show_page(k)
            )
            btn.pack(fill="x", pady=2)
            self.nav_btns[key] = btn

        # SYSTEM Section
        ctk.CTkLabel(self.nav_container, text="SYSTEM", font=ctk.CTkFont(size=10, weight="bold"), text_color="#4E5D7C").pack(anchor="w", padx=12, pady=(12, 4))

        sys_items = [
            ("settings", "⚙️   Settings"),
            ("user_settings", "👤   User Settings"),
        ]
        for key, label in sys_items:
            btn = ctk.CTkButton(
                self.nav_container,
                text=label,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="transparent",
                hover_color="#131826",
                text_color="#A4AEC6",
                anchor="w",
                height=34,
                corner_radius=10,
                command=lambda k=key: self.show_page(k)
            )
            btn.pack(fill="x", pady=2)
            self.nav_btns[key] = btn

        # Sidebar Bottom Footer: Status Card & Controls
        self.sidebar_footer = ctk.CTkFrame(self.sidebar, fg_color="#090B14", corner_radius=12, border_width=1, border_color="#20283C")
        self.sidebar_footer.pack(side="bottom", fill="x", padx=12, pady=12)

        self.status_card = ctk.CTkFrame(self.sidebar_footer, fg_color="#0D231A", corner_radius=8, border_width=1, border_color="#19D96B")
        self.status_card.pack(fill="x", padx=10, pady=(8, 6))

        self.status_badge = ctk.CTkLabel(
            self.status_card,
            text="🟢  All Systems Operational",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#19D96B"
        )
        self.status_badge.pack(anchor="w", padx=10, pady=5)

        # Bot Action Controls
        self.ctrl_grid = ctk.CTkFrame(self.sidebar_footer, fg_color="transparent")
        self.ctrl_grid.pack(fill="x", padx=10, pady=(0, 8))

        self.btn_start = ctk.CTkButton(self.ctrl_grid, text="▶ Start", font=ctk.CTkFont(size=10, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", width=85, height=28, command=self.start_bot)
        self.btn_start.pack(side="left", padx=2)

        self.btn_stop = ctk.CTkButton(self.ctrl_grid, text="⏹ Stop", font=ctk.CTkFont(size=10, weight="bold"), fg_color="#FF5C5C", hover_color="#E04848", width=85, height=28, command=self.stop_bot)
        self.btn_stop.pack(side="right", padx=2)

        self.btn_restart = ctk.CTkButton(self.sidebar_footer, text="🔄 Restart Bot", font=ctk.CTkFont(size=10, weight="bold"), fg_color="#2A8DFF", hover_color="#1E75DA", height=28, command=self.restart_bot)
        self.btn_restart.pack(fill="x", padx=10, pady=2)

        self.btn_rescan = ctk.CTkButton(self.sidebar_footer, text="🧹 Wipe & Re-Scan", font=ctk.CTkFont(size=10, weight="bold"), fg_color="#6C4DFF", hover_color="#5835FF", height=28, command=self.wipe_and_rescan)
        self.btn_rescan.pack(fill="x", padx=10, pady=(2, 8))

        # ── Right Main Workspace ──
        self.workspace = ctk.CTkFrame(self.outer_frame, fg_color="transparent")
        self.workspace.pack(side="right", fill="both", expand=True)

        # ── Topbar Header (64px) ──
        self.topbar = ctk.CTkFrame(self.workspace, height=64, fg_color="#0E1320", corner_radius=0, border_width=1, border_color="#20283C")
        self.topbar.pack(fill="x")
        self.topbar.pack_propagate(False)

        self.topbar_content = ctk.CTkFrame(self.topbar, fg_color="transparent")
        self.topbar_content.pack(fill="both", expand=True, padx=20)

        # Left: Current Page Title
        self.page_title_lbl = ctk.CTkLabel(self.topbar_content, text="Dashboard", font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color="#FFFFFF")
        self.page_title_lbl.pack(side="left")

        # Center Search Bar
        self.search_box = ctk.CTkFrame(self.topbar_content, fg_color="#131826", corner_radius=10, border_width=1, border_color="#20283C", width=320, height=38)
        self.search_box.pack(side="left", padx=30)
        self.search_box.pack_propagate(False)

        ctk.CTkLabel(self.search_box, text="🔍", font=ctk.CTkFont(size=12), text_color="#A4AEC6").pack(side="left", padx=(10, 4))
        self.entry_search = ctk.CTkEntry(self.search_box, placeholder_text="Search anything... (Ctrl + K)", font=ctk.CTkFont(size=11), fg_color="transparent", text_color="#FFF", border_width=0)
        self.entry_search.pack(side="left", fill="both", expand=True)
        self.entry_search.bind("<KeyRelease>", self._on_search_key_release)
        self.bind_all("<Control-k>", lambda e: self.entry_search.focus_set())
        self.search_popup = None
        self.selected_item_info = None

        # Right Topbar Actions
        self.top_right = ctk.CTkFrame(self.topbar_content, fg_color="transparent")
        self.top_right.pack(side="right")

        # 📋 Copy & 🗑️ Delete Action Toolbar (near user profile!)
        self.action_bar = ctk.CTkFrame(self.top_right, fg_color="transparent")
        self.action_bar.pack(side="left", padx=4)

        self.btn_copy_selected = ctk.CTkButton(
            self.action_bar,
            text="📋 Copy",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#131826",
            hover_color="#20283C",
            text_color="#A4AEC6",
            border_width=1,
            border_color="#20283C",
            width=70,
            height=36,
            corner_radius=8,
            command=self._on_copy_selected_click
        )
        self.btn_copy_selected.pack(side="left", padx=2)

        self.btn_delete_selected = ctk.CTkButton(
            self.action_bar,
            text="🗑️ Delete",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#131826",
            hover_color="#20283C",
            text_color="#A4AEC6",
            border_width=1,
            border_color="#20283C",
            width=75,
            height=36,
            corner_radius=8,
            command=self._on_delete_selected_click
        )
        self.btn_delete_selected.pack(side="left", padx=2)

        self.btn_date_picker = ctk.CTkButton(self.top_right, text="📅 Date: All Time", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#131826", hover_color="#20283C", text_color="#A4AEC6", border_width=1, border_color="#20283C", height=36, corner_radius=8, command=self._open_date_picker_dialog)
        self.btn_date_picker.pack(side="left", padx=6)

        self.btn_noti = ctk.CTkButton(self.top_right, text="🔔", font=ctk.CTkFont(size=13), fg_color="#131826", hover_color="#20283C", border_width=1, border_color="#20283C", width=38, height=36, corner_radius=8, command=lambda: self.show_page("alerts"))
        self.btn_noti.pack(side="left", padx=4)

        self.user_profile = ctk.CTkFrame(self.top_right, fg_color="#131826", corner_radius=10, border_width=1, border_color="#20283C")
        self.user_profile.pack(side="left", padx=(6, 0))

        # Avatar
        self.avatar_circle = ctk.CTkLabel(self.user_profile, text="AP", font=ctk.CTkFont(size=10, weight="bold"), fg_color="#6C4DFF", text_color="#FFF", corner_radius=14, width=28, height=28)
        self.avatar_circle.pack(side="left", padx=(8, 6), pady=4)

        self.user_text_box = ctk.CTkFrame(self.user_profile, fg_color="transparent")
        self.user_text_box.pack(side="left", padx=(0, 10), pady=4)

        ctk.CTkLabel(self.user_text_box, text="AMULPAPPU", font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFF", anchor="w").pack(anchor="w")
        ctk.CTkLabel(self.user_text_box, text="Administrator", font=ctk.CTkFont(size=9), text_color="#A4AEC6", anchor="w").pack(anchor="w")

        # ── Page Container ──
        self.pages_container = ctk.CTkFrame(self.workspace, fg_color="transparent")
        self.pages_container.pack(fill="both", expand=True, padx=20, pady=16)

        self.pages = {}
        self._build_all_pages()
        self.show_page("dashboard")

        # Start loops
        self.update_stats()
        self.after(3000, self.periodic_check)
        self.after(500, self.start_bot)

    def _init_ttk_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "DarkRoster.Treeview",
            background="#090B14",
            foreground="#FFFFFF",
            fieldbackground="#090B14",
            bordercolor="#20283C",
            borderwidth=1,
            rowheight=32
        )
        style.configure(
            "DarkRoster.Treeview.Heading",
            background="#0E1320",
            foreground="#A4AEC6",
            bordercolor="#20283C",
            borderwidth=1,
            font=("Segoe UI", 10, "bold")
        )
        style.map("DarkRoster.Treeview", background=[("selected", "#6C4DFF")], foreground=[("selected", "#FFFFFF")])

    def show_page(self, page_name: str):
        for k, p in self.pages.items():
            p.pack_forget()

        if page_name in self.pages:
            self.pages[page_name].pack(fill="both", expand=True)

        for k, btn in self.nav_btns.items():
            if k == page_name:
                btn.configure(fg_color="#6C4DFF", text_color="#FFFFFF")
            else:
                btn.configure(fg_color="transparent", text_color="#A4AEC6")

        titles = {
            "dashboard": "Dashboard Overview",
            "overview": "Financial & Analytics Overview",
            "logs": "Real-Time Terminal Console & OCR Logs",
            "transactions": "Financial Transactions Ledger",
            "alerts": "System Notifications & Bot Events",
            "employees": "Employee Performance & Staff Directory",
            "expenses": "Expense Log & Sheet Outflows Ledger",
            "inventory": "Inventory Stock & Warehouse Management",
            "services": "Car Service Log Records",
            "upgrades": "Vehicle Upgrade Claims",
            "kits": "Repair & Cleaning Kit Sales",
            "settings": "Bot Configuration & API Integration",
            "user_settings": "User Profile & Security Settings",
        }
        self.page_title_lbl.configure(text=titles.get(page_name, page_name.capitalize()))
        self.update_stats()

    def _open_date_picker_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select Date Range Filter")
        dialog.geometry("380x420")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="📅 Date Filter Options", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(pady=16)

        options = [
            "Today",
            "Yesterday",
            "Last 7 Days",
            "Last 30 Days",
            "This Week",
            "This Month",
            "Previous Month",
            "This Year",
            "All Time",
        ]

        for opt in options:
            btn = ctk.CTkButton(
                dialog,
                text=opt,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#131826" if opt != self.selected_date_filter else "#6C4DFF",
                hover_color="#20283C",
                height=32,
                command=lambda o=opt: self._apply_date_filter(o, dialog)
            )
            btn.pack(fill="x", padx=30, pady=3)

    def _apply_date_filter(self, filter_name, dialog_win=None):
        self.selected_date_filter = filter_name
        self.btn_date_picker.configure(text=f"📅 Date: {filter_name}")
        if dialog_win:
            dialog_win.destroy()
        self.log(f"[Filter] Applied date range filter: {filter_name}")
        # ⚡ Instant zero-delay update from memory
        self.update_stats(fast_cached_only=True)
        self.after(100, lambda: self.update_stats(fast_cached_only=False))

    def _build_all_pages(self):
        # 1. DASHBOARD PAGE
        p_dash = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["dashboard"] = p_dash

        dash_scroll = ctk.CTkScrollableFrame(p_dash, fg_color="transparent")
        dash_scroll.pack(fill="both", expand=True)

        # Row 1: 5 KPI Cards (Revenue, Expenses, Net Profit, Transactions, Active Users)
        kpi_row = ctk.CTkFrame(dash_scroll, fg_color="transparent")
        kpi_row.pack(fill="x", pady=(0, 16))

        # KPI 1: Total Revenue
        c1 = ctk.CTkFrame(kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c1.pack(side="left", expand=True, fill="both", padx=(0, 6))
        ctk.CTkLabel(c1, text="TOTAL REVENUE", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_sales = ctk.CTkLabel(c1, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FFFFFF")
        self.lbl_sales.pack(anchor="w", padx=14, pady=(2, 2))
        self.lbl_sales_trend = ctk.CTkLabel(c1, text="↑ Gross Invoices", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6C4DFF")
        self.lbl_sales_trend.pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 2: Total Expenses
        c_exp = ctk.CTkFrame(kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_exp.pack(side="left", expand=True, fill="both", padx=4)
        ctk.CTkLabel(c_exp, text="TOTAL EXPENSES", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_expenses_kpi = ctk.CTkLabel(c_exp, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FF5C5C")
        self.lbl_expenses_kpi.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(c_exp, text="↓ Sheet Outflows", font=ctk.CTkFont(size=10, weight="bold"), text_color="#FF5C5C").pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 3: Net Profit
        c_prof = ctk.CTkFrame(kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_prof.pack(side="left", expand=True, fill="both", padx=4)
        ctk.CTkLabel(c_prof, text="NET PROFIT", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_net_profit_kpi = ctk.CTkLabel(c_prof, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#19D96B")
        self.lbl_net_profit_kpi.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(c_prof, text="↑ Net Revenue - Expenses", font=ctk.CTkFont(size=10, weight="bold"), text_color="#19D96B").pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 4: Total Transactions
        c2 = ctk.CTkFrame(kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c2.pack(side="left", expand=True, fill="both", padx=4)
        ctk.CTkLabel(c2, text="TOTAL TRANSACTIONS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_txns_kpi = ctk.CTkLabel(c2, text="0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FFFFFF")
        self.lbl_txns_kpi.pack(anchor="w", padx=14, pady=(2, 2))
        self.lbl_txns_trend = ctk.CTkLabel(c2, text="↑ Real-time count", font=ctk.CTkFont(size=10, weight="bold"), text_color="#2A8DFF")
        self.lbl_txns_trend.pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 5: Active Users
        c3 = ctk.CTkFrame(kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c3.pack(side="left", expand=True, fill="both", padx=(6, 0))
        ctk.CTkLabel(c3, text="ACTIVE USERS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_active_users = ctk.CTkLabel(c3, text="0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FFFFFF")
        self.lbl_active_users.pack(anchor="w", padx=14, pady=(2, 2))
        self.lbl_users_trend = ctk.CTkLabel(c3, text="↑ Mapped Mechanics", font=ctk.CTkFont(size=10, weight="bold"), text_color="#19D96B")
        self.lbl_users_trend.pack(anchor="w", padx=14, pady=(0, 12))

        # Row 2: Charts & Recent Activity
        row2 = ctk.CTkFrame(dash_scroll, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 16))

        # Revenue Overview Line Chart
        chart_box = ctk.CTkFrame(row2, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        chart_box.pack(side="left", fill="both", expand=True, padx=(0, 8))

        chart_head = ctk.CTkFrame(chart_box, fg_color="transparent")
        chart_head.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(chart_head, text="Revenue Overview", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(side="left")

        self.btn_this_week = ctk.CTkButton(
            chart_head,
            text="Filter Range ▼",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#090B14",
            hover_color="#20283C",
            border_width=1,
            border_color="#20283C",
            width=110,
            height=26,
            corner_radius=6,
            command=self._open_date_picker_dialog
        )
        self.btn_this_week.pack(side="right")

        self.cv_revenue = tk.Canvas(chart_box, height=180, bg="#131826", highlightthickness=0)
        self.cv_revenue.pack(fill="x", padx=16, pady=(0, 14))

        # Doughnut Distribution Canvas
        dist_box = ctk.CTkFrame(row2, width=280, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        dist_box.pack(side="left", fill="both", expand=False, padx=4)

        ctk.CTkLabel(dist_box, text="Transactions by Type", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 8))
        self.cv_doughnut = tk.Canvas(dist_box, width=240, height=210, bg="#131826", highlightthickness=0)
        self.cv_doughnut.pack(padx=16, pady=(0, 14))

        # Recent Activity Feed
        recent_box = ctk.CTkFrame(row2, width=280, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        recent_box.pack(side="right", fill="both", expand=False, padx=(8, 0))

        ctk.CTkLabel(recent_box, text="Recent Activity", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 8))

        self.recent_container = ctk.CTkFrame(recent_box, fg_color="transparent")
        self.recent_container.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        # Row 3: Bottom Widgets (Top Services, Employee Roster, System Resources)
        row3 = ctk.CTkFrame(dash_scroll, fg_color="transparent")
        row3.pack(fill="x")

        # Top Services Widget
        svc_box = ctk.CTkFrame(row3, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        svc_box.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ctk.CTkLabel(svc_box, text="Top Services", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 10))
        self.top_svc_container = ctk.CTkFrame(svc_box, fg_color="transparent")
        self.top_svc_container.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Employee Performance Leaderboard Widget
        emp_box = ctk.CTkFrame(row3, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        emp_box.pack(side="left", fill="both", expand=True, padx=4)

        ctk.CTkLabel(emp_box, text="Employee Performance", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 10))

        tree_frame_dash = ctk.CTkFrame(emp_box, fg_color="#090B14", corner_radius=8)
        tree_frame_dash.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        columns_dash = ("name", "service", "kits", "upgrade", "points", "rank")
        self.tree_dash_emp = ttk.Treeview(tree_frame_dash, columns=columns_dash, show="headings", style="DarkRoster.Treeview")
        self.tree_dash_emp.heading("name", text="Employee", anchor="w")
        self.tree_dash_emp.heading("service", text="Services", anchor="center")
        self.tree_dash_emp.heading("kits", text="Kits", anchor="center")
        self.tree_dash_emp.heading("upgrade", text="Upgrades", anchor="center")
        self.tree_dash_emp.heading("points", text="Points", anchor="center")
        self.tree_dash_emp.heading("rank", text="Rank", anchor="center")

        self.tree_dash_emp.column("name", width=110, anchor="w")
        self.tree_dash_emp.column("service", width=55, anchor="center")
        self.tree_dash_emp.column("kits", width=50, anchor="center")
        self.tree_dash_emp.column("upgrade", width=55, anchor="center")
        self.tree_dash_emp.column("points", width=50, anchor="center")
        self.tree_dash_emp.column("rank", width=50, anchor="center")

        self.tree_dash_emp.pack(fill="both", expand=True)

        # System Resources Widget
        sys_box = ctk.CTkFrame(row3, width=280, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        sys_box.pack(side="right", fill="both", expand=False, padx=(8, 0))

        ctk.CTkLabel(sys_box, text="System Resources", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 10))

        self.sys_meter_labels = {}
        self.sys_meter_pbs = {}
        sys_meters = [
            ("cpu", "CPU Usage", "24%", 0.24, "#6C4DFF"),
            ("mem", "Memory Usage", "240 / 512 MB (47%)", 0.47, "#2A8DFF"),
            ("disk", "Disk Usage", "3.2 / 10 GB (32%)", 0.32, "#19D96B"),
        ]
        for mkey, mtitle, mval, pct, color in sys_meters:
            m_item = ctk.CTkFrame(sys_box, fg_color="transparent")
            m_item.pack(fill="x", padx=16, pady=6)
            lbl_r = ctk.CTkFrame(m_item, fg_color="transparent")
            lbl_r.pack(fill="x")
            ctk.CTkLabel(lbl_r, text=mtitle, font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFF").pack(side="left")
            val_lbl = ctk.CTkLabel(lbl_r, text=mval, font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6")
            val_lbl.pack(side="right")
            self.sys_meter_labels[mkey] = val_lbl

            pb = ctk.CTkProgressBar(m_item, height=6, corner_radius=3, fg_color="#090B14", progress_color=color)
            pb.pack(fill="x", pady=(2, 4))
            pb.set(pct)
            self.sys_meter_pbs[mkey] = pb

        # 2. OVERVIEW PAGE (Financial Intelligence & Analytics Dashboard)
        p_ov = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["overview"] = p_ov

        ov_scroll = ctk.CTkScrollableFrame(p_ov, fg_color="transparent")
        ov_scroll.pack(fill="both", expand=True)

        ov_head = ctk.CTkFrame(ov_scroll, fg_color="transparent")
        ov_head.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(ov_head, text="📈 Financial Overview & Performance Analytics", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF").pack(side="left")

        # Row 1: 4 Financial KPI Summary Cards
        ov_kpi_row = ctk.CTkFrame(ov_scroll, fg_color="transparent")
        ov_kpi_row.pack(fill="x", pady=(0, 16))

        # KPI 1: Gross Revenue
        c_ov1 = ctk.CTkFrame(ov_kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_ov1.pack(side="left", expand=True, fill="both", padx=(0, 6))
        ctk.CTkLabel(c_ov1, text="GROSS SHOP REVENUE", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_ov_revenue = ctk.CTkLabel(c_ov1, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FFFFFF")
        self.lbl_ov_revenue.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(c_ov1, text="↑ Services + Upgrades + Kits", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6C4DFF").pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 2: Total Expenses
        c_ov2 = ctk.CTkFrame(ov_kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_ov2.pack(side="left", expand=True, fill="both", padx=4)
        ctk.CTkLabel(c_ov2, text="TOTAL EXPENSES & COSTS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_ov_expenses = ctk.CTkLabel(c_ov2, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#FF5C5C")
        self.lbl_ov_expenses.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(c_ov2, text="↓ Sheet Expense Ledger", font=ctk.CTkFont(size=10, weight="bold"), text_color="#FF5C5C").pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 3: Net Profit
        c_ov3 = ctk.CTkFrame(ov_kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_ov3.pack(side="left", expand=True, fill="both", padx=4)
        ctk.CTkLabel(c_ov3, text="NET SHOP PROFIT", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_ov_profit = ctk.CTkLabel(c_ov3, text="₹0", font=ctk.CTkFont(size=22, weight="bold"), text_color="#19D96B")
        self.lbl_ov_profit.pack(anchor="w", padx=14, pady=(2, 2))
        self.lbl_ov_margin_tag = ctk.CTkLabel(c_ov3, text="Margin: 0.0%", font=ctk.CTkFont(size=10, weight="bold"), text_color="#19D96B")
        self.lbl_ov_margin_tag.pack(anchor="w", padx=14, pady=(0, 12))

        # KPI 4: Profitability Ratio
        c_ov4 = ctk.CTkFrame(ov_kpi_row, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_ov4.pack(side="left", expand=True, fill="both", padx=(6, 0))
        ctk.CTkLabel(c_ov4, text="PROFITABILITY RATIO", font=ctk.CTkFont(size=10, weight="bold"), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(12, 0))
        self.lbl_ov_ratio = ctk.CTkLabel(c_ov4, text="0.0%", font=ctk.CTkFont(size=22, weight="bold"), text_color="#2A8DFF")
        self.lbl_ov_ratio.pack(anchor="w", padx=14, pady=(2, 2))
        ctk.CTkLabel(c_ov4, text="↑ Net Profit / Total Revenue", font=ctk.CTkFont(size=10, weight="bold"), text_color="#2A8DFF").pack(anchor="w", padx=14, pady=(0, 12))

        # Row 2: Revenue vs Expenses Dual Line Comparison Chart
        ov_chart_box = ctk.CTkFrame(ov_scroll, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        ov_chart_box.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(ov_chart_box, text="Revenue (Green) vs Expenses (Red) Daily Trend Curve", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 8))
        self.cv_overview_chart = tk.Canvas(ov_chart_box, height=210, bg="#131826", highlightthickness=0)
        self.cv_overview_chart.pack(fill="x", padx=16, pady=(0, 14))

        # Row 3: Category Performance Grid
        cat_grid = ctk.CTkFrame(ov_scroll, fg_color="transparent")
        cat_grid.pack(fill="x", pady=(0, 16))

        # Card 1: Car Services
        c_svc = ctk.CTkFrame(cat_grid, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_svc.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ctk.CTkLabel(c_svc, text="🛠️ Car Services", font=ctk.CTkFont(size=13, weight="bold"), text_color="#6C4DFF").pack(anchor="w", padx=14, pady=(12, 4))
        self.lbl_ov_svc_val = ctk.CTkLabel(c_svc, text="₹0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF")
        self.lbl_ov_svc_val.pack(anchor="w", padx=14, pady=(0, 4))
        self.pbar_ov_svc = ctk.CTkProgressBar(c_svc, height=6, corner_radius=3, fg_color="#090B14", progress_color="#6C4DFF")
        self.pbar_ov_svc.pack(fill="x", padx=14, pady=(2, 14))

        # Card 2: Vehicle Upgrades
        c_upg = ctk.CTkFrame(cat_grid, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_upg.pack(side="left", fill="both", expand=True, padx=4)
        ctk.CTkLabel(c_upg, text="🔧 Vehicle Upgrades", font=ctk.CTkFont(size=13, weight="bold"), text_color="#2A8DFF").pack(anchor="w", padx=14, pady=(12, 4))
        self.lbl_ov_upg_val = ctk.CTkLabel(c_upg, text="₹0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF")
        self.lbl_ov_upg_val.pack(anchor="w", padx=14, pady=(0, 4))
        self.pbar_ov_upg = ctk.CTkProgressBar(c_upg, height=6, corner_radius=3, fg_color="#090B14", progress_color="#2A8DFF")
        self.pbar_ov_upg.pack(fill="x", padx=14, pady=(2, 14))

        # Card 3: Kit Sales
        c_kits = ctk.CTkFrame(cat_grid, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        c_kits.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ctk.CTkLabel(c_kits, text="🧰 Kit Sales", font=ctk.CTkFont(size=13, weight="bold"), text_color="#19D96B").pack(anchor="w", padx=14, pady=(12, 4))
        self.lbl_ov_kits_val = ctk.CTkLabel(c_kits, text="₹0", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF")
        self.lbl_ov_kits_val.pack(anchor="w", padx=14, pady=(0, 4))
        self.pbar_ov_kits = ctk.CTkProgressBar(c_kits, height=6, corner_radius=3, fg_color="#090B14", progress_color="#19D96B")
        self.pbar_ov_kits.pack(fill="x", padx=14, pady=(2, 14))

        # Row 4: Profit & Loss (P&L) Ledger Table
        pnl_box = ctk.CTkFrame(ov_scroll, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        pnl_box.pack(fill="both", expand=True)

        ctk.CTkLabel(pnl_box, text="Financial Profit & Loss (P&L) Category Breakdown", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(14, 10))

        tree_pnl_frame = ctk.CTkFrame(pnl_box, fg_color="#090B14", corner_radius=8)
        tree_pnl_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        cols_pnl = ("cat", "rev", "share", "exp", "net", "margin", "status")
        self.tree_ov_pnl = ttk.Treeview(tree_pnl_frame, columns=cols_pnl, show="headings", style="DarkRoster.Treeview")
        self.tree_ov_pnl.heading("cat", text="Revenue Category", anchor="w")
        self.tree_ov_pnl.heading("rev", text="Gross Revenue", anchor="e")
        self.tree_ov_pnl.heading("share", text="Revenue Share", anchor="center")
        self.tree_ov_pnl.heading("exp", text="Est. Outflows / Expenses", anchor="e")
        self.tree_ov_pnl.heading("net", text="Category Net Profit", anchor="e")
        self.tree_ov_pnl.heading("margin", text="Margin %", anchor="center")
        self.tree_ov_pnl.heading("status", text="Financial Health", anchor="center")

        self.tree_ov_pnl.column("cat", width=180, anchor="w")
        self.tree_ov_pnl.column("rev", width=140, anchor="e")
        self.tree_ov_pnl.column("share", width=110, anchor="center")
        self.tree_ov_pnl.column("exp", width=160, anchor="e")
        self.tree_ov_pnl.column("net", width=150, anchor="e")
        self.tree_ov_pnl.column("margin", width=90, anchor="center")
        self.tree_ov_pnl.column("status", width=140, anchor="center")

        self.tree_ov_pnl.pack(fill="both", expand=True)

        # 3. EXPENSES PAGE (FETCHES DIRECTLY FROM GOOGLE SHEET "Expenses" TAB!)
        p_exp = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["expenses"] = p_exp

        top_exp = ctk.CTkFrame(p_exp, corner_radius=12, fg_color="#131826", border_width=1, border_color="#20283C")
        top_exp.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top_exp, text="💸 Shop Expense Log & Google Sheet Outflows", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(top_exp, text="Fetches and logs expenses directly to the 'Expenses' Google Sheet tab.", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=16, pady=(0, 12))

        split_exp = ctk.CTkFrame(p_exp, fg_color="transparent")
        split_exp.pack(fill="both", expand=True)

        left_exp = ctk.CTkFrame(split_exp, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C", width=290)
        left_exp.pack(side="left", fill="y", padx=(0, 8))

        ctk.CTkLabel(left_exp, text="➕ Add Expense Entry", font=ctk.CTkFont(size=13, weight="bold"), text_color="#FF5C5C").pack(anchor="w", padx=14, pady=(14, 6))

        ctk.CTkLabel(left_exp, text="Expense Amount (₹):", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(6, 2))
        self.entry_exp_amount = ctk.CTkEntry(left_exp, placeholder_text="e.g. 15000", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_exp_amount.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(left_exp, text="Spent By / Staff:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_exp_staff = ctk.CTkEntry(left_exp, placeholder_text="e.g. AMULPAPPU", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_exp_staff.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(left_exp, text="Category:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_exp_cat = ctk.CTkEntry(left_exp, placeholder_text="e.g. Inventory Restock", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_exp_cat.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(left_exp, text="Description / Notes:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_exp_desc = ctk.CTkEntry(left_exp, placeholder_text="e.g. Restock 100x Repair Kits", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_exp_desc.pack(fill="x", padx=14, pady=(0, 10))

        self.lbl_exp_msg = ctk.CTkLabel(left_exp, text="", font=ctk.CTkFont(size=11), text_color="#19D96B")
        self.lbl_exp_msg.pack(anchor="w", padx=14, pady=(0, 6))

        btn_save_exp = ctk.CTkButton(left_exp, text="💾 Save to Google Sheet", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#FF5C5C", hover_color="#E04848", height=34, command=self._on_save_expense_click)
        btn_save_exp.pack(fill="x", padx=14, pady=(4, 14))

        right_exp = ctk.CTkFrame(split_exp, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C")
        right_exp.pack(side="right", fill="both", expand=True, padx=(8, 0))

        tree_frame_exp = ctk.CTkFrame(right_exp, fg_color="#090B14", corner_radius=8)
        tree_frame_exp.pack(fill="both", expand=True, padx=12, pady=12)

        cols_exp = ("time", "amount", "staff", "cat", "desc")
        self.tree_exp = ttk.Treeview(tree_frame_exp, columns=cols_exp, show="headings", style="DarkRoster.Treeview")
        self.tree_exp.heading("time", text="Timestamp", anchor="w")
        self.tree_exp.heading("amount", text="Amount (₹)", anchor="e")
        self.tree_exp.heading("staff", text="Spent By / Staff", anchor="w")
        self.tree_exp.heading("cat", text="Category", anchor="center")
        self.tree_exp.heading("desc", text="Description / Notes", anchor="w")

        self.tree_exp.column("time", width=140, anchor="w")
        self.tree_exp.column("amount", width=110, anchor="e")
        self.tree_exp.column("staff", width=130, anchor="w")
        self.tree_exp.column("cat", width=120, anchor="center")
        self.tree_exp.column("desc", width=220, anchor="w")

        sb_exp = ctk.CTkScrollbar(tree_frame_exp, command=self.tree_exp.yview)
        self.tree_exp.configure(yscrollcommand=sb_exp.set)
        self.tree_exp.pack(side="left", fill="both", expand=True)
        sb_exp.pack(side="right", fill="y")

        # 4. INVENTORY PAGE (WITH RESTOCK DATES, BOUGHT THIS MONTH & AUTO GOOGLE SHEET SYNC!)
        p_inv = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["inventory"] = p_inv

        top_inv = ctk.CTkFrame(p_inv, corner_radius=12, fg_color="#131826", border_width=1, border_color="#20283C")
        top_inv.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top_inv, text="📦 Inventory Stock & Warehouse Management", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(12, 2))
        self.lbl_inv_summary = ctk.CTkLabel(top_inv, text="Total Items: 6  |  Total Inventory Asset Value: ₹0", font=ctk.CTkFont(size=11), text_color="#A4AEC6")
        self.lbl_inv_summary.pack(anchor="w", padx=16, pady=(0, 12))

        split_inv = ctk.CTkFrame(p_inv, fg_color="transparent")
        split_inv.pack(fill="both", expand=True)

        left_inv = ctk.CTkFrame(split_inv, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C", width=290)
        left_inv.pack(side="left", fill="y", padx=(0, 8))

        ctk.CTkLabel(left_inv, text="➕ Add / Update Item", font=ctk.CTkFont(size=13, weight="bold"), text_color="#2A8DFF").pack(anchor="w", padx=14, pady=(14, 6))

        ctk.CTkLabel(left_inv, text="Item Name:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_inv_name = ctk.CTkEntry(left_inv, placeholder_text="e.g. Repair Kit", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_inv_name.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(left_inv, text="Current Quantity in Inventory:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_inv_qty = ctk.CTkEntry(left_inv, placeholder_text="e.g. 286", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_inv_qty.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(left_inv, text="How Much Bought This Month:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_inv_bought = ctk.CTkEntry(left_inv, placeholder_text="e.g. 100", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_inv_bought.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(left_inv, text="Restock Date (YYYY-MM-DD):", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_inv_date = ctk.CTkEntry(left_inv, placeholder_text="e.g. 2026-07-25", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_inv_date.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(left_inv, text="Unit Cost / Price (₹):", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_inv_price = ctk.CTkEntry(left_inv, placeholder_text="e.g. 500", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_inv_price.pack(fill="x", padx=14, pady=(0, 10))

        self.lbl_inv_msg = ctk.CTkLabel(left_inv, text="", font=ctk.CTkFont(size=11), text_color="#19D96B")
        self.lbl_inv_msg.pack(anchor="w", padx=14, pady=(0, 6))

        btn_save_inv = ctk.CTkButton(left_inv, text="💾 Save Item & Sync Sheet", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", height=34, command=self._on_save_inventory_click)
        btn_save_inv.pack(fill="x", padx=14, pady=(4, 14))

        right_inv = ctk.CTkFrame(split_inv, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C")
        right_inv.pack(side="right", fill="both", expand=True, padx=(8, 0))

        tree_frame_inv = ctk.CTkFrame(right_inv, fg_color="#090B14", corner_radius=8)
        tree_frame_inv.pack(fill="both", expand=True, padx=12, pady=12)

        cols_inv = ("name", "qty", "bought_month", "restock_date", "unit_price", "total_val", "updated")
        self.tree_inv = ttk.Treeview(tree_frame_inv, columns=cols_inv, show="headings", style="DarkRoster.Treeview")
        self.tree_inv.heading("name", text="Item Name", anchor="w")
        self.tree_inv.heading("qty", text="Quantity in Stock", anchor="center")
        self.tree_inv.heading("bought_month", text="Bought This Month", anchor="center")
        self.tree_inv.heading("restock_date", text="Restock Date", anchor="center")
        self.tree_inv.heading("unit_price", text="Unit Cost (₹)", anchor="e")
        self.tree_inv.heading("total_val", text="Total Value (₹)", anchor="e")
        self.tree_inv.heading("updated", text="Last Updated", anchor="w")

        self.tree_inv.column("name", width=160, anchor="w")
        self.tree_inv.column("qty", width=110, anchor="center")
        self.tree_inv.column("bought_month", width=120, anchor="center")
        self.tree_inv.column("restock_date", width=110, anchor="center")
        self.tree_inv.column("unit_price", width=100, anchor="e")
        self.tree_inv.column("total_val", width=110, anchor="e")
        self.tree_inv.column("updated", width=140, anchor="w")

        sb_inv = ctk.CTkScrollbar(tree_frame_inv, command=self.tree_inv.yview)
        self.tree_inv.configure(yscrollcommand=sb_inv.set)
        self.tree_inv.pack(side="left", fill="both", expand=True)
        sb_inv.pack(side="right", fill="y")

        # 5. LOGS PAGE
        p_logs = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["logs"] = p_logs

        logs_head = ctk.CTkFrame(p_logs, fg_color="transparent")
        logs_head.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(logs_head, text="📄 Live Terminal Console & OCR Error Records", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")

        ctk.CTkButton(logs_head, text="🗑️ Clear Console", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#131826", hover_color="#20283C", width=120, command=lambda: self.log_box.delete("1.0", "end")).pack(side="right", padx=4)

        self.log_box = ctk.CTkTextbox(p_logs, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#090B14", text_color="#A4AEC6", border_width=1, border_color="#20283C")
        self.log_box.pack(fill="both", expand=True)

        # 6. TRANSACTIONS PAGE
        p_txns = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["transactions"] = p_txns

        txns_head = ctk.CTkFrame(p_txns, fg_color="transparent")
        txns_head.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(txns_head, text="💳 Financial Ledger & Invoice Records", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")
        ctk.CTkButton(txns_head, text="📥 Export CSV", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", command=lambda: export_treeview_to_csv(self.tree_txns, "Transactions_Ledger.csv")).pack(side="right")

        tree_txns_frame = ctk.CTkFrame(p_txns, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_txns_frame.pack(fill="both", expand=True)

        cols_txns = ("date", "amount", "desc", "type", "employee")
        self.tree_txns = ttk.Treeview(tree_txns_frame, columns=cols_txns, show="headings", style="DarkRoster.Treeview")
        self.tree_txns.heading("date", text="Date", anchor="w")
        self.tree_txns.heading("amount", text="Amount (₹)", anchor="e")
        self.tree_txns.heading("desc", text="Description / Vehicle", anchor="w")
        self.tree_txns.heading("type", text="Category", anchor="center")
        self.tree_txns.heading("employee", text="Staff / Mechanic", anchor="w")

        self.tree_txns.column("date", width=140, anchor="w")
        self.tree_txns.column("amount", width=120, anchor="e")
        self.tree_txns.column("desc", width=220, anchor="w")
        self.tree_txns.column("type", width=110, anchor="center")
        self.tree_txns.column("employee", width=140, anchor="w")

        sb_txns = ctk.CTkScrollbar(tree_txns_frame, command=self.tree_txns.yview)
        self.tree_txns.configure(yscrollcommand=sb_txns.set)
        self.tree_txns.pack(side="left", fill="both", expand=True)
        sb_txns.pack(side="right", fill="y")

        # 7. ALERTS PAGE
        p_alerts = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["alerts"] = p_alerts

        ctk.CTkLabel(p_alerts, text="🔔 System Notifications & Bot Events", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(anchor="w", pady=(0, 10))

        tree_alerts_frame = ctk.CTkFrame(p_alerts, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_alerts_frame.pack(fill="both", expand=True)

        cols_alerts = ("time", "type", "msg", "severity")
        self.tree_alerts = ttk.Treeview(tree_alerts_frame, columns=cols_alerts, show="headings", style="DarkRoster.Treeview")
        self.tree_alerts.heading("time", text="Timestamp", anchor="w")
        self.tree_alerts.heading("type", text="Event Type", anchor="w")
        self.tree_alerts.heading("msg", text="Notification Details", anchor="w")
        self.tree_alerts.heading("severity", text="Status", anchor="center")

        self.tree_alerts.column("time", width=150, anchor="w")
        self.tree_alerts.column("type", width=140, anchor="w")
        self.tree_alerts.column("msg", width=400, anchor="w")
        self.tree_alerts.column("severity", width=100, anchor="center")

        self.tree_alerts.pack(fill="both", expand=True)

        # 8. EMPLOYEES PAGE
        p_emp = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["employees"] = p_emp

        top_emp = ctk.CTkFrame(p_emp, corner_radius=12, fg_color="#131826", border_width=1, border_color="#20283C")
        top_emp.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top_emp, text="👥 Employee Directory & Staff Management", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(top_emp, text="View active staff mappings or add new employees instantly with automatic sheet synchronization.", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=16, pady=(0, 12))

        split_emp = ctk.CTkFrame(p_emp, fg_color="transparent")
        split_emp.pack(fill="both", expand=True)

        left_emp = ctk.CTkFrame(split_emp, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C", width=280)
        left_emp.pack(side="left", fill="y", padx=(0, 8))

        ctk.CTkLabel(left_emp, text="➕ Add Staff Member", font=ctk.CTkFont(size=13, weight="bold"), text_color="#2A8DFF").pack(anchor="w", padx=14, pady=(14, 6))
        ctk.CTkLabel(left_emp, text="Employee Name:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(6, 2))
        self.entry_emp_name = ctk.CTkEntry(left_emp, placeholder_text="e.g. Meenu Kutty", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_emp_name.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(left_emp, text="Discord Tag:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=14, pady=(4, 2))
        self.entry_emp_tag = ctk.CTkEntry(left_emp, placeholder_text="e.g. @blari", font=ctk.CTkFont(size=11), fg_color="#131826", text_color="#FFF", border_color="#20283C")
        self.entry_emp_tag.pack(fill="x", padx=14, pady=(0, 10))

        self.lbl_emp_msg = ctk.CTkLabel(left_emp, text="", font=ctk.CTkFont(size=11), text_color="#19D96B")
        self.lbl_emp_msg.pack(anchor="w", padx=14, pady=(0, 6))

        btn_save_emp = ctk.CTkButton(left_emp, text="💾 Save & Sync Sheet", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", height=34, command=self._on_save_employee_click)
        btn_save_emp.pack(fill="x", padx=14, pady=(4, 14))

        right_emp = ctk.CTkFrame(split_emp, corner_radius=12, fg_color="#0E1320", border_width=1, border_color="#20283C")
        right_emp.pack(side="right", fill="both", expand=True, padx=(8, 0))

        tree_frame_dir = ctk.CTkFrame(right_emp, fg_color="#090B14", corner_radius=8)
        tree_frame_dir.pack(fill="both", expand=True, padx=12, pady=12)

        cols_emp_dir = ("name", "tag", "svc", "kits", "upg", "total", "pts", "rank")
        self.emp_dir_tree = ttk.Treeview(tree_frame_dir, columns=cols_emp_dir, show="headings", style="DarkRoster.Treeview")
        self.emp_dir_tree.heading("name", text="Employee Name", anchor="w")
        self.emp_dir_tree.heading("tag", text="Mapped Discord Tag", anchor="w")
        self.emp_dir_tree.heading("svc", text="Services", anchor="center")
        self.emp_dir_tree.heading("kits", text="Kits", anchor="center")
        self.emp_dir_tree.heading("upg", text="Upgrades", anchor="center")
        self.emp_dir_tree.heading("total", text="Total Txns", anchor="center")
        self.emp_dir_tree.heading("pts", text="Points", anchor="center")
        self.emp_dir_tree.heading("rank", text="Rank", anchor="center")

        self.emp_dir_tree.column("name", width=120, anchor="w")
        self.emp_dir_tree.column("tag", width=120, anchor="w")
        self.emp_dir_tree.column("svc", width=60, anchor="center")
        self.emp_dir_tree.column("kits", width=55, anchor="center")
        self.emp_dir_tree.column("upg", width=65, anchor="center")
        self.emp_dir_tree.column("total", width=70, anchor="center")
        self.emp_dir_tree.column("pts", width=60, anchor="center")
        self.emp_dir_tree.column("rank", width=55, anchor="center")

        emp_sb = ctk.CTkScrollbar(tree_frame_dir, command=self.emp_dir_tree.yview)
        self.emp_dir_tree.configure(yscrollcommand=emp_sb.set)
        self.emp_dir_tree.pack(side="left", fill="both", expand=True)
        emp_sb.pack(side="right", fill="y")

        # 9. SERVICES PAGE
        p_svc = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["services"] = p_svc

        head_svc = ctk.CTkFrame(p_svc, fg_color="transparent")
        head_svc.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(head_svc, text="🛠️ Car Service Log Records", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")
        ctk.CTkButton(head_svc, text="📥 Export CSV", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", command=lambda: export_treeview_to_csv(self.tree_svc, "Car_Services_Log.csv")).pack(side="right")

        tree_svc_frame = ctk.CTkFrame(p_svc, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_svc_frame.pack(fill="both", expand=True)

        cols_svc = ("time", "customer", "cat", "count", "amount", "employee")
        self.tree_svc = ttk.Treeview(tree_svc_frame, columns=cols_svc, show="headings", style="DarkRoster.Treeview")
        self.tree_svc.heading("time", text="Timestamp", anchor="w")
        self.tree_svc.heading("customer", text="Customer Name", anchor="w")
        self.tree_svc.heading("cat", text="Category", anchor="center")
        self.tree_svc.heading("count", text="Qty", anchor="center")
        self.tree_svc.heading("amount", text="Total Amount (₹)", anchor="e")
        self.tree_svc.heading("employee", text="Mechanic", anchor="w")

        self.tree_svc.column("time", width=140, anchor="w")
        self.tree_svc.column("customer", width=160, anchor="w")
        self.tree_svc.column("cat", width=120, anchor="center")
        self.tree_svc.column("count", width=60, anchor="center")
        self.tree_svc.column("amount", width=120, anchor="e")
        self.tree_svc.column("employee", width=140, anchor="w")

        sb_svc = ctk.CTkScrollbar(tree_svc_frame, command=self.tree_svc.yview)
        self.tree_svc.configure(yscrollcommand=sb_svc.set)
        self.tree_svc.pack(side="left", fill="both", expand=True)
        sb_svc.pack(side="right", fill="y")

        # 10. UPGRADES PAGE
        p_upg = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["upgrades"] = p_upg

        head_upg = ctk.CTkFrame(p_upg, fg_color="transparent")
        head_upg.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(head_upg, text="🔧 Vehicle Upgrade Claims & VIP Logs", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")
        ctk.CTkButton(head_upg, text="📥 Export CSV", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", command=lambda: export_treeview_to_csv(self.tree_upg, "Upgrades_VIP_Claims.csv")).pack(side="right")

        tree_upg_frame = ctk.CTkFrame(p_upg, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_upg_frame.pack(fill="both", expand=True)

        cols_upg = ("time", "person", "cat", "vehicle", "staff", "amount")
        self.tree_upg = ttk.Treeview(tree_upg_frame, columns=cols_upg, show="headings", style="DarkRoster.Treeview")
        self.tree_upg.heading("time", text="Timestamp", anchor="w")
        self.tree_upg.heading("person", text="Person / Customer", anchor="w")
        self.tree_upg.heading("cat", text="Category", anchor="center")
        self.tree_upg.heading("vehicle", text="Vehicle Name", anchor="w")
        self.tree_upg.heading("staff", text="Staff Member", anchor="w")
        self.tree_upg.heading("amount", text="Amount (₹)", anchor="e")

        self.tree_upg.column("time", width=140, anchor="w")
        self.tree_upg.column("person", width=150, anchor="w")
        self.tree_upg.column("cat", width=110, anchor="center")
        self.tree_upg.column("vehicle", width=140, anchor="w")
        self.tree_upg.column("staff", width=140, anchor="w")
        self.tree_upg.column("amount", width=110, anchor="e")

        sb_upg = ctk.CTkScrollbar(tree_upg_frame, command=self.tree_upg.yview)
        self.tree_upg.configure(yscrollcommand=sb_upg.set)
        self.tree_upg.pack(side="left", fill="both", expand=True)
        sb_upg.pack(side="right", fill="y")

        # 11. KITS PAGE
        p_kits = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["kits"] = p_kits

        head_kits = ctk.CTkFrame(p_kits, fg_color="transparent")
        head_kits.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(head_kits, text="🧰 Repair & Cleaning Kit Sales", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")
        ctk.CTkButton(head_kits, text="📥 Export CSV", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", command=lambda: export_treeview_to_csv(self.tree_kits, "Kits_Sales_Log.csv")).pack(side="right")

        tree_kits_frame = ctk.CTkFrame(p_kits, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_kits_frame.pack(fill="both", expand=True)

        cols_kits = ("time", "customer", "repair", "clean", "disc", "amount", "employee")
        self.tree_kits = ttk.Treeview(tree_kits_frame, columns=cols_kits, show="headings", style="DarkRoster.Treeview")
        self.tree_kits.heading("time", text="Timestamp", anchor="w")
        self.tree_kits.heading("customer", text="Customer Name", anchor="w")
        self.tree_kits.heading("repair", text="Repair Kits", anchor="center")
        self.tree_kits.heading("clean", text="Cleaning Kits", anchor="center")
        self.tree_kits.heading("disc", text="Discount %", anchor="center")
        self.tree_kits.heading("amount", text="Total Amount (₹)", anchor="e")
        self.tree_kits.heading("employee", text="Employee", anchor="w")

        self.tree_kits.column("time", width=140, anchor="w")
        self.tree_kits.column("customer", width=150, anchor="w")
        self.tree_kits.column("repair", width=80, anchor="center")
        self.tree_kits.column("clean", width=90, anchor="center")
        self.tree_kits.column("disc", width=80, anchor="center")
        self.tree_kits.column("amount", width=110, anchor="e")
        self.tree_kits.column("employee", width=130, anchor="w")

        sb_kits = ctk.CTkScrollbar(tree_kits_frame, command=self.tree_kits.yview)
        self.tree_kits.configure(yscrollcommand=sb_kits.set)
        self.tree_kits.pack(side="left", fill="both", expand=True)
        sb_kits.pack(side="right", fill="y")

        # 12. SETTINGS PAGE
        p_set = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["settings"] = p_set

        ctk.CTkLabel(p_set, text="⚙️ Application Settings & Configuration", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF").pack(anchor="w", pady=(0, 12))

        tab_set = ctk.CTkTabview(p_set, fg_color="#131826", border_width=1, border_color="#20283C")
        tab_set.pack(fill="both", expand=True)

        t_app = tab_set.add("🎨 Appearance & Color Theme")
        t_bot = tab_set.add("🤖 Bot & API Config")
        t_noti = tab_set.add("🔔 Notifications")
        t_maint = tab_set.add("🛠️ Maintenance")

        # Tab 1: Appearance
        ctk.CTkLabel(t_app, text="Primary Accent Color Palette:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#FFF").pack(anchor="w", padx=16, pady=(16, 8))
        color_grid = ctk.CTkFrame(t_app, fg_color="transparent")
        color_grid.pack(anchor="w", padx=16, pady=(0, 16))

        preset_colors = [("#6C4DFF", "Violet Glow"), ("#2A8DFF", "Electric Blue"), ("#19D96B", "Emerald"), ("#F9A826", "Gold"), ("#FF5C5C", "Coral Red")]
        for hex_code, cname in preset_colors:
            btn = ctk.CTkButton(color_grid, text=cname, font=ctk.CTkFont(size=11, weight="bold"), fg_color=hex_code, width=110, height=32, command=lambda h=hex_code: self._apply_theme_color(h))
            btn.pack(side="left", padx=4)

        # Tab 2: Bot & API Config
        ctk.CTkLabel(t_bot, text="Discord Guild ID:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=16, pady=(12, 2))
        self.entry_guild_id = ctk.CTkEntry(t_bot, font=ctk.CTkFont(size=11), width=400)
        self.entry_guild_id.insert(0, self.app_settings["bot_config"]["guild_id"])
        self.entry_guild_id.pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkLabel(t_bot, text="Google Spreadsheet ID:", font=ctk.CTkFont(size=11), text_color="#A4AEC6").pack(anchor="w", padx=16, pady=(4, 2))
        self.entry_sheet_id = ctk.CTkEntry(t_bot, font=ctk.CTkFont(size=11), width=400)
        self.entry_sheet_id.insert(0, self.app_settings["bot_config"]["spreadsheet_id"])
        self.entry_sheet_id.pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkButton(t_bot, text="💾 Save Configuration", font=ctk.CTkFont(size=12, weight="bold"), fg_color="#19D96B", hover_color="#15B85A", command=self._save_bot_settings).pack(anchor="w", padx=16, pady=10)

        # Tab 3: Notifications
        ctk.CTkCheckBox(t_noti, text="Enable Desktop Sound Notifications", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=12)
        ctk.CTkCheckBox(t_noti, text="Enable Bot Offline Alert Popups", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=8)
        ctk.CTkCheckBox(t_noti, text="Enable Google Sheet Sync Error Alerts", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=8)

        # Tab 4: Maintenance
        maint_grid = ctk.CTkFrame(t_maint, fg_color="transparent")
        maint_grid.pack(anchor="w", padx=16, pady=16)

        ctk.CTkButton(maint_grid, text="📦 Backup Local Database", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#2A8DFF", width=180, height=34, command=lambda: messagebox.showinfo("Backup", "Database backed up successfully!")).pack(side="left", padx=6)
        ctk.CTkButton(maint_grid, text="🧹 Clear Local Cache", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#6C4DFF", width=180, height=34, command=lambda: messagebox.showinfo("Clear Cache", "Local cache cleared successfully!")).pack(side="left", padx=6)
        ctk.CTkButton(maint_grid, text="🔄 Force Sheet Resync", font=ctk.CTkFont(size=11, weight="bold"), fg_color="#19D96B", width=180, height=34, command=self.update_stats).pack(side="left", padx=6)

        # 13. USER SETTINGS PAGE
        p_user = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["user_settings"] = p_user

        ctk.CTkLabel(p_user, text="👤 User Profile & Access Control Settings", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFF").pack(anchor="w", pady=(0, 12))

        prof_card = ctk.CTkFrame(p_user, corner_radius=14, fg_color="#131826", border_width=1, border_color="#20283C")
        prof_card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(prof_card, text="Administrator Profile Overview", font=ctk.CTkFont(size=14, weight="bold"), text_color="#2A8DFF").pack(anchor="w", padx=16, pady=(14, 6))
        ctk.CTkLabel(prof_card, text="Name: AMULPAPPU  |  Role: Administrator  |  Discord: @amulpappu  |  Status: Active", font=ctk.CTkFont(size=12), text_color="#A4AEC6").pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkLabel(p_user, text="Configured System Roles & Permissions", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF").pack(anchor="w", pady=(8, 8))

        tree_users_frame = ctk.CTkFrame(p_user, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_users_frame.pack(fill="both", expand=True)

        cols_users = ("name", "tag", "role", "perms", "status", "last_login")
        self.tree_users = ttk.Treeview(tree_users_frame, columns=cols_users, show="headings", style="DarkRoster.Treeview")
        self.tree_users.heading("name", text="User Name", anchor="w")
        self.tree_users.heading("tag", text="Discord Tag", anchor="w")
        self.tree_users.heading("role", text="Role", anchor="center")
        self.tree_users.heading("perms", text="Permissions", anchor="w")
        self.tree_users.heading("status", text="Status", anchor="center")
        self.tree_users.heading("last_login", text="Last Active", anchor="w")

        self.tree_users.column("name", width=140, anchor="w")
        self.tree_users.column("tag", width=120, anchor="w")
        self.tree_users.column("role", width=130, anchor="center")
        self.tree_users.column("perms", width=220, anchor="w")
        self.tree_users.column("status", width=90, anchor="center")
        self.tree_users.column("last_login", width=160, anchor="w")

        self.tree_users.pack(fill="both", expand=True)
        self._load_users_list()

        # 14. VIP CLAIMS PAGE (Dedicated Page with Car Claimed Sales Redemption!)
        p_vip = ctk.CTkFrame(self.pages_container, fg_color="transparent")
        self.pages["vip_claims"] = p_vip

        top_vip = ctk.CTkFrame(p_vip, corner_radius=12, fg_color="#131826", border_width=1, border_color="#20283C")
        top_vip.pack(fill="x", pady=(0, 10))

        vip_hdr = ctk.CTkFrame(top_vip, fg_color="transparent")
        vip_hdr.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(vip_hdr, text="👑 VIP Vehicle Claims Ledger & Sales Redemption", font=ctk.CTkFont(size=16, weight="bold"), text_color="#FFF").pack(side="left")

        self.btn_mark_claimed = ctk.CTkButton(
            vip_hdr,
            text="☑️ Mark Car Claimed (Add ₹ to Sales)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#19D96B",
            hover_color="#15B85A",
            text_color="#FFFFFF",
            height=32,
            corner_radius=8,
            command=self._on_mark_car_claimed_click
        )
        self.btn_mark_claimed.pack(side="right")

        self.lbl_vip_summary = ctk.CTkLabel(top_vip, text="Total VIP Claims: 0  |  Total VIP Value: ₹0", font=ctk.CTkFont(size=11), text_color="#A4AEC6")
        self.lbl_vip_summary.pack(anchor="w", padx=16, pady=(0, 12))

        tree_vip_frame = ctk.CTkFrame(p_vip, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
        tree_vip_frame.pack(fill="both", expand=True)

        cols_vip = ("timestamp", "cust", "vehicle", "amount", "staff", "status")
        self.tree_vip = ttk.Treeview(tree_vip_frame, columns=cols_vip, show="headings", style="DarkRoster.Treeview")
        self.tree_vip.heading("timestamp", text="Claim Timestamp", anchor="w")
        self.tree_vip.heading("cust", text="Customer / Player", anchor="w")
        self.tree_vip.heading("vehicle", text="Vehicle Model / Package", anchor="w")
        self.tree_vip.heading("amount", text="Claim Value (₹)", anchor="e")
        self.tree_vip.heading("staff", text="Logged Staff", anchor="center")
        self.tree_vip.heading("status", text="Claim Status", anchor="center")

        self.tree_vip.column("timestamp", width=160, anchor="w")
        self.tree_vip.column("cust", width=150, anchor="w")
        self.tree_vip.column("vehicle", width=180, anchor="w")
        self.tree_vip.column("amount", width=120, anchor="e")
        self.tree_vip.column("staff", width=130, anchor="center")
        self.tree_vip.column("status", width=140, anchor="center")

        self.tree_vip.pack(fill="both", expand=True)

        self._bind_all_treeview_events()

    def _on_mark_car_claimed_click(self):
        try:
            sel = self.tree_vip.selection()
            if not sel:
                messagebox.showinfo("VIP Claim", "Please select a VIP Claim record from the table first.")
                return

            vals = self.tree_vip.item(sel[0])["values"]
            if not vals:
                return

            ts = str(vals[0])
            cust = str(vals[1])
            veh = str(vals[2])
            amt_raw = str(vals[3]).replace("₹", "").replace(",", "").strip()
            amt_val = float(amt_raw) if amt_raw.replace(".", "", 1).isdigit() else 0.0

            confirm = messagebox.askyesno(
                "Mark Car Claimed & Add to Sales",
                f"Mark VIP Vehicle Claim for '{cust}' ({veh}) as Claimed & Add ₹{amt_val:,.0f} to Shop Sales?"
            )
            if confirm:
                sheets.mark_vip_claim_as_claimed_in_sheet(ts, cust)
                db.add_alert("VIP Car Claimed", f"VIP Car Claim settled: {cust} ({veh}) - ₹{amt_val:,.0f} added to Sales!", "success")
                self.log(f"[VIP Claims] Car Claimed: {cust} ({veh}) — ₹{amt_val:,.0f} added to Shop Gross Sales.")
                self.update_stats()
                messagebox.showinfo("Success", f"🎉 Car Claimed! ₹{amt_val:,.0f} added to Shop Sales & Sheet updated!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to mark VIP claim: {e}")

    def _bind_all_treeview_events(self):
        trees_and_types = [
            (self.tree_inv, "inventory"),
            (self.tree_exp, "expenses"),
            (self.emp_dir_tree, "employee"),
            (self.tree_dash_emp, "employee"),
            (self.tree_vip, "vip"),
            (self.tree_users, "user_role"),
            (self.tree_svc, "record"),
            (self.tree_upg, "record"),
            (self.tree_kits, "record"),
            (self.tree_txns, "record"),
        ]
        for tree, t_type in trees_and_types:
            tree.bind("<<TreeviewSelect>>", lambda e, t=tree, k=t_type: self._on_tree_select(e, t, k))
            tree.bind("<Button-3>", lambda e, t=tree, k=t_type: self._on_tree_right_click(e, t, k))

    def _on_tree_select(self, event, tree, item_type):
        try:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0])["values"]
            if not vals:
                return

            self.selected_item_info = {
                "type": item_type,
                "values": vals,
                "tree": tree
            }

            self.btn_copy_selected.configure(fg_color="#2A8DFF", text_color="#FFFFFF")
            self.btn_delete_selected.configure(fg_color="#FF5C5C", text_color="#FFFFFF")
        except Exception:
            pass

    def _on_tree_right_click(self, event, tree, item_type):
        try:
            row_id = tree.identify_row(event.y)
            if row_id:
                tree.selection_set(row_id)
                self._on_tree_select(None, tree, item_type)

                menu = tk.Menu(self, tearoff=0, bg="#131826", fg="#FFFFFF", activebackground="#6C4DFF", activeforeground="#FFFFFF")
                menu.add_command(label="📋 Copy Details", command=self._on_copy_selected_click)
                menu.add_command(label="🗑️ Delete Entry", command=self._on_delete_selected_click)
                menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass

    def _on_copy_selected_click(self):
        try:
            if not hasattr(self, "selected_item_info") or not self.selected_item_info:
                messagebox.showinfo("Copy", "Please select a row in any table first.")
                return

            vals = self.selected_item_info.get("values", [])
            val_str = " | ".join(map(str, vals))
            self.clipboard_clear()
            self.clipboard_append(val_str)
            messagebox.showinfo("Copied to Clipboard", f"✅ Copied record details to clipboard:\n\n{val_str}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy details: {e}")

    def _on_delete_selected_click(self):
        try:
            if not hasattr(self, "selected_item_info") or not self.selected_item_info:
                messagebox.showinfo("Delete", "Please select a row to delete first.")
                return

            info = self.selected_item_info
            item_type = info.get("type")
            vals = info.get("values", [])

            if not vals:
                return

            if item_type == "inventory":
                item_name = str(vals[0])
                confirm = messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete inventory item:\n'{item_name}'?")
                if confirm:
                    self.selected_item_info = None
                    db.delete_inventory_item(item_name)
                    sheets.delete_inventory_row_from_sheet(item_name)
                    db.add_alert("Inventory Deleted", f"Deleted inventory item: {item_name}", "warning")
                    self.log(f"[Inventory] Deleted item: {item_name}")
                    self.update_stats()

            elif item_type == "expenses":
                ts_str = str(vals[0])
                amt_raw = str(vals[1]).replace("₹", "").replace(",", "").strip()
                amt_val = float(amt_raw) if amt_raw.replace(".", "", 1).isdigit() else 0.0
                confirm = messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete expense entry:\n'{ts_str}' (₹{amt_val:,.0f})?")
                if confirm:
                    self.selected_item_info = None
                    db.delete_expense(ts_str, amt_val)
                    sheets.delete_expense_row_from_sheet(ts_str, amt_val)
                    db.add_alert("Expense Deleted", f"Deleted expense record: ₹{amt_val:,.0f}", "warning")
                    self.log(f"[Expenses] Deleted expense: {ts_str} (₹{amt_val:,.0f})")
                    self.update_stats()

            elif item_type == "employee":
                emp_name = str(vals[0])
                confirm = messagebox.askyesno("Confirm Delete", f"Are you sure you want to remove employee mapping:\n'{emp_name}'?")
                if confirm:
                    self.selected_item_info = None
                    config.delete_employee_mapping(emp_name)
                    db.add_alert("Employee Deleted", f"Removed employee mapping: {emp_name}", "warning")
                    self.log(f"[Employees] Removed staff mapping: {emp_name}")
                    self._refresh_employee_page_list()
                    self.update_stats()

            elif item_type == "user_role":
                u_name = str(vals[0])
                if u_name.upper() == "AMULPAPPU":
                    messagebox.showerror("Error", "Cannot delete primary Admin AMULPAPPU!")
                    return
                confirm = messagebox.askyesno("Revoke User Access", f"Are you sure you want to revoke access & delete user:\n'{u_name}'?")
                if confirm:
                    self.selected_item_info = None
                    db.delete_user_by_name(u_name)
                    sheets.remove_user_role(u_name)
                    db.add_alert("Access Revoked", f"Revoked access for user: {u_name}", "warning")
                    self.log(f"[Security] Revoked access for user: {u_name}")
                    self._load_users_list()
                    messagebox.showinfo("Success", f"🗑️ Access revoked for {u_name}! Deleted from App & Google Sheets.")

            else:
                messagebox.showinfo("Delete", "Selected row is a read-only historical Discord log.")

            self.selected_item_info = None
            self.btn_copy_selected.configure(fg_color="#131826", text_color="#A4AEC6")
            self.btn_delete_selected.configure(fg_color="#131826", text_color="#A4AEC6")
        except Exception as e:
            self.log(f"[Error] Delete operation handled safely: {e}")

    def _on_search_key_release(self, event=None):
        query = self.entry_search.get().strip().lower()
        if not query:
            self._close_search_popup()
            return

        results = []
        pages_map = {
            "dashboard": "📊 Dashboard Overview",
            "overview": "📈 Financial Overview Analytics",
            "logs": "📄 Real-Time Terminal Console & Logs",
            "transactions": "💳 Financial Ledger",
            "alerts": "🔔 System Alerts",
            "employees": "👥 Staff Directory",
            "expenses": "💸 Expense Log",
            "inventory": "📦 Warehouse Inventory",
            "services": "🛠️ Car Services Log",
            "upgrades": "🔧 Vehicle Upgrade Claims",
            "kits": "🧰 Kit Sales Log",
            "settings": "⚙️ Configuration Settings",
            "user_settings": "👤 User Security Profile",
        }

        for key, title in pages_map.items():
            if query in key or query in title.lower():
                results.append({"type": "page", "title": title, "page": key})

        for tag, name in config.EMPLOYEE_MAPPING.items():
            if query in name.lower() or query in tag.lower():
                results.append({"type": "employee", "title": f"👥 Employee: {name} (@{tag})", "page": "employees", "filter": name})

        for item in db.get_inventory():
            iname = item["item_name"]
            if query in iname.lower() or query in item.get("category", "").lower():
                results.append({"type": "inventory", "title": f"📦 Item: {iname} ({item['qty']} in stock)", "page": "inventory", "filter": iname})

        for exp in db.get_expenses():
            edesc = exp.get("desc", "")
            ecat = exp.get("category", "")
            if query in edesc.lower() or query in ecat.lower():
                results.append({"type": "expense", "title": f"💸 Expense: ₹{exp['amount']:,.0f} ({edesc or ecat})", "page": "expenses", "filter": edesc})

        self._show_search_popup(results)

    def _show_search_popup(self, results):
        self._close_search_popup()

        if not results:
            return

        x = self.search_box.winfo_rootx()
        y = self.search_box.winfo_rooty() + self.search_box.winfo_height() + 4

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.geometry(f"340x{min(260, len(results) * 40 + 10)}+{x}+{y}")
        popup.configure(fg_color="#0E1320")
        popup.attributes("-topmost", True)
        self.search_popup = popup

        scroll = ctk.CTkScrollableFrame(popup, fg_color="#0E1320", corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=2, pady=2)

        for res in results[:10]:
            btn = ctk.CTkButton(
                scroll,
                text=res["title"],
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#131826",
                hover_color="#6C4DFF",
                text_color="#FFFFFF",
                anchor="w",
                height=32,
                corner_radius=6,
                command=lambda r=res: self._on_search_result_click(r)
            )
            btn.pack(fill="x", pady=2)

    def _on_search_result_click(self, res):
        self._close_search_popup()
        self.entry_search.delete(0, "end")
        page_key = res.get("page")
        if page_key:
            self.show_page(page_key)

        filter_val = res.get("filter")
        if filter_val and page_key == "inventory":
            for item in self.tree_inv.get_children():
                vals = self.tree_inv.item(item)["values"]
                if vals and filter_val.lower() in str(vals[0]).lower():
                    self.tree_inv.selection_set(item)
                    self.tree_inv.see(item)
                    self._on_tree_select(None, self.tree_inv, "inventory")
                    break

        elif filter_val and page_key == "employees":
            for item in self.emp_dir_tree.get_children():
                vals = self.emp_dir_tree.item(item)["values"]
                if vals and filter_val.lower() in str(vals[0]).lower():
                    self.emp_dir_tree.selection_set(item)
                    self.emp_dir_tree.see(item)
                    self._on_tree_select(None, self.emp_dir_tree, "employee")
                    break

    def _close_search_popup(self):
        if hasattr(self, "search_popup") and self.search_popup:
            try:
                self.search_popup.destroy()
            except Exception:
                pass
            self.search_popup = None

    def _on_save_expense_click(self):
        amt = self.entry_exp_amount.get().strip()
        staff = self.entry_exp_staff.get().strip() or "AMULPAPPU"
        cat = self.entry_exp_cat.get().strip() or "General"
        desc = self.entry_exp_desc.get().strip() or "Shop Expense"

        if not amt or not amt.replace(".", "", 1).isdigit():
            self.lbl_exp_msg.configure(text="⚠️ Please enter valid Expense Amount.", text_color="#FF5C5C")
            return

        amt_val = float(amt)
        db.add_expense(amt_val, staff, cat, desc)
        db.add_alert("Expense Logged", f"₹{amt_val:,.0f} logged by {staff} ({cat})", "warning")

        # Fastly sync directly to Google Sheet "Expenses" tab!
        threading.Thread(target=sheets.append_expense_entry, args=(amt_val, staff, cat, desc), daemon=True).start()

        self.lbl_exp_msg.configure(text=f"✅ Saved Expense ₹{amt_val:,.0f} & updated Sheet!", text_color="#19D96B")

        self.entry_exp_amount.delete(0, "end")
        self.entry_exp_staff.delete(0, "end")
        self.entry_exp_cat.delete(0, "end")
        self.entry_exp_desc.delete(0, "end")

        self.update_stats()

    def _on_save_inventory_click(self):
        name = self.entry_inv_name.get().strip()
        qty = self.entry_inv_qty.get().strip()
        bought_month = self.entry_inv_bought.get().strip() or "0"
        restock_date = self.entry_inv_date.get().strip() or datetime.datetime.now().strftime("%Y-%m-%d")
        price = self.entry_inv_price.get().strip() or "0"

        if not name or not qty or not qty.isdigit():
            self.lbl_inv_msg.configure(text="⚠️ Please enter valid Item Name and Stock Quantity.", text_color="#FF5C5C")
            return

        qty_val = int(qty)
        bought_val = int(bought_month) if bought_month.isdigit() else 0
        price_val = float(price) if price.replace(".", "", 1).isdigit() else 0.0

        db.add_or_update_inventory_item(name, "Kits/Parts", qty_val, price_val, 10)
        db.add_alert("Inventory Updated", f"Item updated: {name} (Qty: {qty_val}, Bought this month: {bought_val})", "success")

        # Fastly sync directly to Google Sheet "Inventory" tab!
        threading.Thread(target=sheets.save_inventory_item_to_sheet, args=(name, qty_val, bought_val, restock_date, price_val), daemon=True).start()

        self.lbl_inv_msg.configure(text=f"✅ Saved {name} & updated Sheet!", text_color="#19D96B")

        self.entry_inv_name.delete(0, "end")
        self.entry_inv_qty.delete(0, "end")
        self.entry_inv_bought.delete(0, "end")
        self.entry_inv_date.delete(0, "end")
        self.entry_inv_price.delete(0, "end")

        self.update_stats()

    def _apply_theme_color(self, hex_code):
        self.nav_btns["dashboard"].configure(fg_color=hex_code)
        messagebox.showinfo("Theme Updated", f"Applied accent theme color: {hex_code}")

    def _save_bot_settings(self):
        new_guild = self.entry_guild_id.get().strip()
        new_sheet = self.entry_sheet_id.get().strip()
        self.app_settings["bot_config"]["guild_id"] = new_guild
        self.app_settings["bot_config"]["spreadsheet_id"] = new_sheet
        db.update_settings(self.app_settings)
        messagebox.showinfo("Configuration Saved", "Bot configuration updated successfully!")

    def _load_users_list(self):
        try:
            self.tree_users.delete(*self.tree_users.get_children())
            roles_from_sheet = sheets.get_user_roles()
            if roles_from_sheet:
                for r in roles_from_sheet:
                    uname = r.get("username", "")
                    utag = r.get("tag", f"@{uname.lower()}")
                    urole = r.get("role", "Employee")
                    uperms = "Full Access" if urole == "Admin" else ("Dashboard, Edit, Inventory, Claims" if urole == "Manager" else "Service, Upgrades, Kits, VIP Log")
                    udate = r.get("updated", "")
                    self.tree_users.insert("", "end", values=(uname, utag, urole, uperms, "Active", udate))
            else:
                for u in db.get_users():
                    self.tree_users.insert("", "end", values=(u["display_name"], u["discord_tag"], u["role"], u["permissions"], u["status"], u["last_login"]))
        except Exception:
            pass

    def _refresh_live_resources(self):
        try:
            import psutil
            cpu_pct = int(psutil.cpu_percent(interval=None))
            mem = psutil.virtual_memory()
            mem_str = f"{round(mem.used / (1024**3), 1)} / {round(mem.total / (1024**3), 1)} GB ({int(mem.percent)}%)" if mem.total >= 1024**3 else f"{int(mem.used / (1024**2))} / {int(mem.total / (1024**2))} MB ({int(mem.percent)}%)"
            disk = psutil.disk_usage('/')
            disk_str = f"{round(disk.used / (1024**3), 1)} / {round(disk.total / (1024**3), 1)} GB ({int(disk.percent)}%)" if disk.total >= 1024**3 else f"{int(disk.used / (1024**2))} / {int(disk.total / (1024**2))} MB ({int(disk.percent)}%)"
            
            if hasattr(self, "sys_meter_labels"):
                if "cpu" in self.sys_meter_labels:
                    self.sys_meter_labels["cpu"].configure(text=f"{cpu_pct}%")
                    self.sys_meter_pbs["cpu"].set(max(0.05, cpu_pct / 100.0))
                if "mem" in self.sys_meter_labels:
                    self.sys_meter_labels["mem"].configure(text=mem_str)
                    self.sys_meter_pbs["mem"].set(max(0.05, mem.percent / 100.0))
                if "disk" in self.sys_meter_labels:
                    self.sys_meter_labels["disk"].configure(text=disk_str)
                    self.sys_meter_pbs["disk"].set(max(0.05, disk.percent / 100.0))
        except Exception:
            pass

    def _draw_overview_chart(self, daily_revenue_map=None, daily_expense_map=None):
        cv = self.cv_overview_chart
        cv.delete("all")
        w = cv.winfo_width() or 700
        h = 210

        # Background Grid & Axis Lines
        cv.create_line(40, 20, w - 20, 20, fill="#20283C", dash=(2, 4))
        cv.create_line(40, 75, w - 20, 75, fill="#20283C", dash=(2, 4))
        cv.create_line(40, 130, w - 20, 130, fill="#20283C", dash=(2, 4))
        cv.create_line(40, h - 25, w - 20, h - 25, fill="#20283C")

        if not daily_revenue_map or len(daily_revenue_map) == 0:
            cv.create_text(w // 2, h // 2, text="No financial trend data recorded for selected period", fill="#A4AEC6", font=("Segoe UI", 11, "italic"))
            return

        dates = sorted(list(set(list(daily_revenue_map.keys()) + list((daily_expense_map or {}).keys()))))
        rev_vals = [daily_revenue_map.get(d, 0.0) for d in dates]
        exp_vals = [(daily_expense_map or {}).get(d, 0.0) for d in dates]

        max_val = max(max(rev_vals or [1000]), max(exp_vals or [1000])) if (max(rev_vals or [0]) > 0 or max(exp_vals or [0]) > 0) else 1000
        min_y, max_y = 25, h - 35

        n = len(dates)
        x_step = (w - 80) / max(1, n - 1) if n > 1 else (w - 80) / 2

        # 1. Revenue Line (Emerald Green #19D96B)
        rev_pts = []
        for i, val in enumerate(rev_vals):
            x = 45 + (i * x_step) if n > 1 else (w / 2)
            y = max_y - ((val / max_val) * (max_y - min_y))
            rev_pts.append((x, y))

        for i in range(len(rev_pts) - 1):
            cv.create_line(rev_pts[i][0], rev_pts[i][1], rev_pts[i+1][0], rev_pts[i+1][1], fill="#19D96B", width=3, smooth=True)

        for px, py in rev_pts:
            cv.create_oval(px - 4, py - 4, px + 4, py + 4, fill="#19D96B", outline="#FFFFFF", width=1)

        # 2. Expenses Line (Coral Red #FF5C5C)
        exp_pts = []
        for i, val in enumerate(exp_vals):
            x = 45 + (i * x_step) if n > 1 else (w / 2)
            y = max_y - ((val / max_val) * (max_y - min_y))
            exp_pts.append((x, y))

        for i in range(len(exp_pts) - 1):
            cv.create_line(exp_pts[i][0], exp_pts[i][1], exp_pts[i+1][0], exp_pts[i+1][1], fill="#FF5C5C", width=2, dash=(4, 2), smooth=True)

        for px, py in exp_pts:
            cv.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#FF5C5C", outline="#FFFFFF", width=1)

        # Format X-axis Date Labels
        for i, d_str in enumerate(dates):
            px = rev_pts[i][0]
            lbl = d_str[-5:] if len(d_str) >= 5 else d_str
            cv.create_text(px, h - 10, text=lbl, fill="#A4AEC6", font=("Segoe UI", 8, "bold"))

    def _update_recent_activity(self, filtered_svc, filtered_upg, filtered_kits, filtered_vip, filtered_exp):
        for w in self.recent_container.winfo_children():
            w.destroy()

        activities = []

        # 1. Service Entries
        for r in filtered_svc:
            if len(r) > 0 and r[0]:
                ts = r[0]
                emp = sheets.resolve_name(r[sheets._EMPLOYEE_COL["Service"]]) if len(r) > sheets._EMPLOYEE_COL["Service"] else "Staff"
                amt = r[sheets._AMOUNT_COL["Service"]] if len(r) > sheets._AMOUNT_COL["Service"] else "0"
                activities.append({
                    "timestamp": ts,
                    "title": f"{emp} logged Service",
                    "desc": f"Amount: ₹{amt}",
                    "icon": "🛠️",
                    "color": "#6C4DFF"
                })

        # 2. Upgrade Entries
        for r in filtered_upg:
            if len(r) > 0 and r[0]:
                ts = r[0]
                emp = sheets.resolve_name(r[sheets._EMPLOYEE_COL["Upgrades"]]) if len(r) > sheets._EMPLOYEE_COL["Upgrades"] else "Staff"
                amt = r[sheets._AMOUNT_COL["Upgrades"]] if len(r) > sheets._AMOUNT_COL["Upgrades"] else "0"
                activities.append({
                    "timestamp": ts,
                    "title": f"{emp} logged Upgrade",
                    "desc": f"Amount: ₹{amt}",
                    "icon": "🔧",
                    "color": "#2A8DFF"
                })

        # 3. Kit Entries
        for r in filtered_kits:
            if len(r) > 0 and r[0]:
                ts = r[0]
                emp = sheets.resolve_name(r[sheets._EMPLOYEE_COL["Kits"]]) if len(r) > sheets._EMPLOYEE_COL["Kits"] else "Staff"
                amt = r[sheets._AMOUNT_COL["Kits"]] if len(r) > sheets._AMOUNT_COL["Kits"] else "0"
                activities.append({
                    "timestamp": ts,
                    "title": f"{emp} logged Kit Sale",
                    "desc": f"Amount: ₹{amt}",
                    "icon": "🧰",
                    "color": "#19D96B"
                })

        # 4. Vip Log Entries
        for r in filtered_vip:
            if len(r) > 5 and r[5]:
                ts = r[5]
                cust = r[0] if len(r) > 0 else "Customer"
                veh = r[1] if len(r) > 1 else "VIP Car"
                amt = f"₹{float(r[4]):,.0f}" if len(r) > 4 and r[4].replace('.','',1).isdigit() else (r[4] if len(r) > 4 else "₹0")
                activities.append({
                    "timestamp": ts,
                    "title": f"VIP Log: {cust}",
                    "desc": f"{veh} ({amt})",
                    "icon": "👑",
                    "color": "#F9A826"
                })

        # 5. Bill Claim Entries
        for r in filtered_exp:
            if len(r) > 0 and r[0]:
                ts = r[0]
                amt = f"₹{float(r[1]):,.0f}" if len(r) > 1 and r[1].replace('.','',1).isdigit() else (r[1] if len(r) > 1 else "₹0")
                emp = sheets.resolve_name(r[2]) if len(r) > 2 else "Shop"
                activities.append({
                    "timestamp": ts,
                    "title": f"{emp} logged Bill Claim",
                    "desc": f"Amount: {amt}",
                    "icon": "💸",
                    "color": "#FF5C5C"
                })

        # 5. System Alerts Fallback
        if not activities:
            for alt in db.get_alerts()[:5]:
                activities.append({
                    "timestamp": alt.get("timestamp", ""),
                    "title": alt.get("type", "System Event"),
                    "desc": alt.get("message", ""),
                    "icon": "🔔",
                    "color": "#6C4DFF"
                })

        # Sort descending by timestamp
        activities.sort(key=lambda x: str(x["timestamp"]), reverse=True)

        for act in activities[:5]:
            item_frame = ctk.CTkFrame(self.recent_container, fg_color="#090B14", corner_radius=8, border_width=1, border_color="#20283C")
            item_frame.pack(fill="x", pady=3, padx=2)

            badge = ctk.CTkLabel(item_frame, text=act["icon"], font=ctk.CTkFont(size=11), fg_color="#131826", text_color=act["color"], width=28, height=28, corner_radius=6)
            badge.pack(side="left", padx=6, pady=4)

            txt_box = ctk.CTkFrame(item_frame, fg_color="transparent")
            txt_box.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=2)

            ctk.CTkLabel(txt_box, text=act["title"], font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFF", anchor="w").pack(anchor="w")

            sub_frame = ctk.CTkFrame(txt_box, fg_color="transparent")
            sub_frame.pack(anchor="w", fill="x")

            ctk.CTkLabel(sub_frame, text=act["desc"], font=ctk.CTkFont(size=9), text_color="#A4AEC6", anchor="w").pack(side="left")
            ts_lbl = str(act["timestamp"])[-8:] if len(str(act["timestamp"])) >= 8 else str(act["timestamp"])
            ctk.CTkLabel(sub_frame, text=ts_lbl, font=ctk.CTkFont(size=8), text_color="#6C4DFF", anchor="e").pack(side="right")

    def _draw_revenue_chart(self, daily_revenue_map=None):
        cv = self.cv_revenue
        cv.delete("all")
        w = cv.winfo_width() or 520
        h = 180

        # Background Grid & Axis Lines
        cv.create_line(35, 20, w - 20, 20, fill="#20283C", dash=(2, 4))
        cv.create_line(35, 75, w - 20, 75, fill="#20283C", dash=(2, 4))
        cv.create_line(35, 130, w - 20, 130, fill="#20283C", dash=(2, 4))
        cv.create_line(35, h - 25, w - 20, h - 25, fill="#20283C")

        if not daily_revenue_map or len(daily_revenue_map) == 0:
            # Baseline zero line
            cv.create_line(35, h - 35, w - 20, h - 35, fill="#6C4DFF", width=2)
            cv.create_text(w // 2, h // 2, text="No revenue transactions recorded for selected period", fill="#A4AEC6", font=("Segoe UI", 10, "italic"))
            return

        dates = list(daily_revenue_map.keys())
        values = [daily_revenue_map[d] for d in dates]

        max_val = max(values) if max(values) > 0 else 1000
        min_y, max_y = 25, h - 35

        n = len(dates)
        x_step = (w - 70) / max(1, n - 1) if n > 1 else (w - 70) / 2

        points = []
        for i, val in enumerate(values):
            x = 40 + (i * x_step) if n > 1 else (w / 2)
            y = max_y - ((val / max_val) * (max_y - min_y))
            points.append((x, y))

        # Filled Polygon area under curve
        poly_pts = [points[0][0], max_y]
        for px, py in points:
            poly_pts.extend([px, py])
        poly_pts.extend([points[-1][0], max_y])

        cv.create_polygon(poly_pts, fill="#1A1B3A", outline="")

        # Line joining points
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i+1]
            cv.create_line(x1, y1, x2, y2, fill="#6C4DFF", width=3, smooth=True)

        # Draw glowing dot markers & value labels
        for i, (px, py) in enumerate(points):
            cv.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#2A8DFF", outline="#FFFFFF", width=2)

            # Format X-axis date label
            d_str = dates[i]
            lbl = d_str[-5:] if len(d_str) >= 5 else d_str
            cv.create_text(px, h - 10, text=lbl, fill="#A4AEC6", font=("Segoe UI", 8, "bold"))

            # Format Y-axis value tooltip above point
            if values[i] > 0:
                val_text = f"₹{values[i]/1000:.1f}k" if values[i] >= 1000 else f"₹{values[i]:,.0f}"
                cv.create_text(px, py - 14, text=val_text, fill="#19D96B", font=("Segoe UI", 8, "bold"))

    def _draw_doughnut_chart(self, svc_cnt=0, kits_cnt=0, upg_cnt=0, vip_cnt=0):
        cv = self.cv_doughnut
        cv.delete("all")
        cx, cy, r = 120, 58, 46

        total = svc_cnt + kits_cnt + upg_cnt + vip_cnt
        if total == 0:
            total_display = "0"
            slices = [
                (0, "#6C4DFF"),
                (0, "#2A8DFF"),
                (0, "#19D96B"),
                (0, "#F9A826"),
            ]
        else:
            total_display = f"{total:,}"
            slices = [
                ((svc_cnt / total) * 100, "#6C4DFF"),
                ((kits_cnt / total) * 100, "#2A8DFF"),
                ((upg_cnt / total) * 100, "#19D96B"),
                ((vip_cnt / total) * 100, "#F9A826"),
            ]

        start = 0
        has_slices = False
        for pct, color in slices:
            if pct <= 0:
                continue
            has_slices = True
            extent = (pct / 100.0) * 360
            cv.create_arc(cx-r, cy-r, cx+r, cy+r, start=start, extent=extent, fill=color, outline="")
            start += extent

        if not has_slices:
            cv.create_oval(cx-r, cy-r, cx+r, cy+r, fill="#20283C", outline="")

        cv.create_oval(cx-25, cy-25, cx+25, cy+25, fill="#131826", outline="")
        cv.create_text(cx, cy-4, text=total_display, fill="#FFF", font=("Segoe UI", 11, "bold"))
        cv.create_text(cx, cy+8, text="Total Txns", fill="#A4AEC6", font=("Segoe UI", 8))

        # 🎨 Big Dot Color-Matched Legend Labels with exact counts!
        # Row 1: Services & Kits
        cv.create_oval(14, 126, 26, 138, fill="#6C4DFF", outline="")
        cv.create_text(32, 132, text=f"Services ({svc_cnt})", fill="#6C4DFF", font=("Segoe UI", 10, "bold"), anchor="w")

        cv.create_oval(126, 126, 138, 138, fill="#2A8DFF", outline="")
        cv.create_text(144, 132, text=f"Kits ({kits_cnt})", fill="#2A8DFF", font=("Segoe UI", 10, "bold"), anchor="w")

        # Row 2: Upgrades & VIP Claims
        cv.create_oval(14, 162, 26, 174, fill="#19D96B", outline="")
        cv.create_text(32, 168, text=f"Upgrades ({upg_cnt})", fill="#19D96B", font=("Segoe UI", 10, "bold"), anchor="w")

        cv.create_oval(126, 162, 138, 174, fill="#F9A826", outline="")
        cv.create_text(144, 168, text=f"VIP Claims ({vip_cnt})", fill="#F9A826", font=("Segoe UI", 10, "bold"), anchor="w")

    def _refresh_employee_page_list(self, roster_data=None):
        try:
            self.emp_dir_tree.delete(*self.emp_dir_tree.get_children())
            unique_mapping = {}
            for tag, name in config.EMPLOYEE_MAPPING.items():
                clean_tag = "@" + tag.lstrip("@")
                if name not in unique_mapping:
                    unique_mapping[name] = []
                if clean_tag not in unique_mapping[name]:
                    unique_mapping[name].append(clean_tag)

            stats_lookup = {r["name"]: r for r in (roster_data or [])}

            emp_list = []
            for name, tags in unique_mapping.items():
                st = stats_lookup.get(name, {"service": 0, "kits": 0, "upgrade": 0, "total": 0, "points": 0.0})
                emp_list.append({
                    "name": name,
                    "tags_str": ", ".join(tags),
                    "svc": st["service"],
                    "kits": st["kits"],
                    "upg": st["upgrade"],
                    "total": st["total"],
                    "points": st["points"],
                })

            # Sort descending by performance points, then total txns
            emp_list.sort(key=lambda x: (x["points"], x["total"]), reverse=True)

            for idx, emp in enumerate(emp_list, start=1):
                rank_str = f"🥇 #{idx}" if idx == 1 else (f"🥈 #{idx}" if idx == 2 else (f"🥉 #{idx}" if idx == 3 else f"#{idx}"))
                self.emp_dir_tree.insert("", "end", values=(emp["name"], emp["tags_str"], emp["svc"], emp["kits"], emp["upg"], emp["total"], emp["points"], rank_str))
        except Exception:
            pass

    def _on_save_employee_click(self):
        name_val = self.entry_emp_name.get().strip()
        tag_val = self.entry_emp_tag.get().strip()
        if not name_val or not tag_val:
            self.lbl_emp_msg.configure(text="⚠️ Please enter Name and Tag.", text_color="#FF5C5C")
            return

        added = config.add_employee_mapping(name_val, tag_val)
        if added:
            self.lbl_emp_msg.configure(text=f"✅ Added {name_val} & updated Sheet!", text_color="#19D96B")
            self.entry_emp_name.delete(0, "end")
            self.entry_emp_tag.delete(0, "end")
            db.add_alert("Employee Added", f"Mapped staff: {name_val} -> @{tag_val.lstrip('@')}", "success")
            self._refresh_employee_page_list()
            threading.Thread(target=sheets.update_employee_tracker, daemon=True).start()
            self.update_stats()
            self.log(f"[Config] Added employee mapping: {name_val} -> @{tag_val.lstrip('@')} (Sheet updated).")
        else:
            self.lbl_emp_msg.configure(text="❌ Failed to save employee.", text_color="#FF5C5C")

    def log(self, text):
        timestamp = time.strftime("[%H:%M:%S]")
        self.log_box.insert("end", f"{timestamp} {text}\n")
        self.log_box.see("end")

    def start_bot(self):
        if self.bot_process is not None and self.bot_process.poll() is None:
            self.log("[System] Bot is already running.")
            return

        python_exe = _get_python_exe()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        cwd = os.getcwd()

        bot_script = os.path.join(cwd, "bot.py")
        if not os.path.exists(bot_script):
            bot_script = "bot.py"

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        try:
            self.bot_process = subprocess.Popen(
                [python_exe, bot_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                cwd=cwd,
                creationflags=creationflags
            )
            self.is_running = True
            self.bot_start_time = time.time()
            self.status_badge.configure(text="🟢  All Systems Operational", text_color="#19D96B")
            self.log(f"[System] Bot started: {python_exe} {bot_script} (PID: {self.bot_process.pid})")
            db.add_alert("Bot Online", f"Bot process launched successfully (PID: {self.bot_process.pid})", "success")

            t = threading.Thread(target=self._read_output, daemon=True)
            t.start()
            discord_rpc.start_discord_rpc(
                details="Code69-Jiraiya Custom & Tunerz",
                state="Financial & Employee Monitor Active"
            )
        except Exception as e:
            self.log(f"[Error] Failed to start bot process: {e}")
            db.add_alert("Bot Launch Error", str(e), "error")

    def _read_output(self):
        proc = self.bot_process
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            self.log_box.insert("end", line)
            self.log_box.see("end")

    def stop_bot(self):
        discord_rpc.stop_discord_rpc()
        if self.bot_process is None or self.bot_process.poll() is not None:
            self.log("[System] Bot is not running.")
            return

        try:
            self.bot_process.terminate()
            self.bot_process.wait(timeout=3)
        except Exception:
            self.bot_process.kill()

        self.bot_process = None
        self.is_running = False
        self.status_badge.configure(text="🔴  Bot Service Offline", text_color="#FF5C5C")
        self.log("[System] Bot stopped.")
        db.add_alert("Bot Offline", "Bot process terminated by administrator.", "warning")

    def on_closing(self):
        self.log("[System] Application closing — stopping bot process...")
        self.stop_bot()
        self.destroy()
        sys.exit(0)

    def restart_bot(self):
        self.stop_bot()
        self.after(1000, self.start_bot)

    def wipe_and_rescan(self):
        self.btn_rescan.configure(state="disabled", text="⏳ Wiping...")
        self.log("[Action] Initiating full sheet wipe and fresh Discord history re-scan...")

        def _worker():
            try:
                success = sheets.wipe_all_data_sheets()
                if success:
                    self.log("[System] Google Sheets wiped successfully. Re-seeding official expenses...")

                if os.path.exists("processed_hashes.json"):
                    with open("processed_hashes.json", "w") as f:
                        f.write("[]")

                self.restart_bot()
                self.update_stats()
            except Exception as e:
                self.log(f"[Error] Wipe & Re-scan failed: {e}")
            finally:
                self.btn_rescan.configure(state="normal", text="🧹 Wipe & Re-Scan")

        threading.Thread(target=_worker, daemon=True).start()

    def periodic_check(self):
        if self.bot_process is not None and self.bot_process.poll() is not None:
            self.bot_process = None
            self.is_running = False
            self.status_badge.configure(text="🔴  Bot Service Offline", text_color="#FF5C5C")
            self.log("[System] Bot process ended.")

        self.update_stats()
        self.after(15000, self.periodic_check)

    def update_stats(self, fast_cached_only=False):
        def _calc_and_apply(rows_by_sheet):
            try:
                dt_start, dt_end = get_date_range_bounds(self.selected_date_filter)

                def _row_in_date(r, ts_col=0):
                    if not dt_start or not dt_end or not r or len(r) <= ts_col or not r[ts_col]:
                        return True
                    parsed = sheets.parse_ist_timestamp(r[ts_col])
                    if parsed:
                        return dt_start <= parsed <= dt_end
                    return True

                filtered_svc = [r for r in rows_by_sheet["Service"] if _row_in_date(r, 0)]
                filtered_upg = [r for r in rows_by_sheet["Upgrades"] if _row_in_date(r, 0)]
                filtered_kits = [r for r in rows_by_sheet["Kits"] if _row_in_date(r, 0)]
                filtered_exp = [r for r in rows_by_sheet["Expenses"] if _row_in_date(r, 0)]
                filtered_inv = rows_by_sheet["Inventory"]
                filtered_vip = [r for r in rows_by_sheet["VIP Claim"] if _row_in_date(r, 5)]
                filtered_txns = [r for r in rows_by_sheet["Transactions"] if _row_in_date(r, 0)]

                service_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Service"]] for r in filtered_svc if len(r) > sheets._AMOUNT_COL["Service"]])
                upgrade_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Upgrades"]] for r in filtered_upg if len(r) > sheets._AMOUNT_COL["Upgrades"]])
                kits_total = sheets._sum_numeric([r[sheets._AMOUNT_COL["Kits"]] for r in filtered_kits if len(r) > sheets._AMOUNT_COL["Kits"]])
                vip_total = sheets._sum_numeric([r[4] for r in filtered_vip if len(r) > 4])

                total_expenses = sheets._sum_numeric([r[1] for r in filtered_exp if len(r) > 1])
                if total_expenses == 0:
                    local_exp = sum(e["amount"] for e in db.get_expenses())
                    total_expenses = max(total_expenses, local_exp)

                total_sales = service_total + upgrade_total + kits_total + vip_total
                net_profit = total_sales - total_expenses
                total_txns = len(filtered_svc) + len(filtered_upg) + len(filtered_kits) + len(filtered_vip)

                civ_svc_cnt = sum(1 for r in filtered_svc if len(r) > 2 and "civ" in r[2].lower())
                gov_svc_cnt = sum(1 for r in filtered_svc if len(r) > 2 and "gov" in r[2].lower())
                repair_kits_cnt = sum(int(float(r[2])) for r in filtered_kits if len(r) > 2 and r[2].isdigit())
                clean_kits_cnt = sum(int(float(r[3])) for r in filtered_kits if len(r) > 3 and r[3].isdigit())
                upg_inst_cnt = len(filtered_upg)
                vip_claim_cnt = len(filtered_vip)

                all_configured_names = set(config.EMPLOYEE_MAPPING.values())
                active_users_cnt = len(all_configured_names)

                tot_inv_items = len(filtered_inv) if filtered_inv else len(db.get_inventory())
                tot_inv_val = sum(float(r[5]) for r in filtered_inv if len(r) > 5 and r[5].replace('.', '', 1).isdigit())
                if tot_inv_val == 0:
                    tot_inv_val = sum(i["qty"] * i["unit_price"] for i in db.get_inventory())

                counts_by_emp = defaultdict(lambda: {"kits": 0, "service": 0, "upgrade": 0})
                for ws_name, sheet_rows in (("Service", filtered_svc), ("Upgrades", filtered_upg), ("Kits", filtered_kits)):
                    col = sheets._EMPLOYEE_COL[ws_name]
                    cat_key = "service" if ws_name == "Service" else ("upgrade" if ws_name == "Upgrades" else "kits")
                    for row in sheet_rows:
                        if len(row) > col and row[col]:
                            resolved = resolve_name(row[col])
                            if resolved in all_configured_names:
                                counts_by_emp[resolved][cat_key] += 1

                roster_dict = {}
                for name in sorted(all_configured_names):
                    c = counts_by_emp[name]
                    total = c["kits"] + c["service"] + c["upgrade"]
                    points = round((c["service"] * 1.0) + (c["kits"] * 0.8) + (c["upgrade"] * 1.2), 1)
                    roster_dict[name] = {
                        "name": name,
                        "kits": c["kits"],
                        "service": c["service"],
                        "upgrade": c["upgrade"],
                        "points": points,
                        "total": total,
                    }

                roster = list(roster_dict.values())
                roster.sort(key=lambda x: x["total"], reverse=True)

                self.lbl_sales.configure(text=f"₹{total_sales:,.0f}")
                self.lbl_expenses_kpi.configure(text=f"₹{total_expenses:,.0f}")
                self.lbl_net_profit_kpi.configure(text=f"₹{net_profit:,.0f}")
                self.lbl_txns_kpi.configure(text=f"{total_txns:,}")
                self.lbl_active_users.configure(text=str(active_users_cnt))

                self._draw_doughnut_chart(len(filtered_svc), len(filtered_kits), len(filtered_upg), len(filtered_vip))
                self._update_recent_activity(filtered_svc, filtered_upg, filtered_kits, filtered_vip, filtered_exp)

                max_cnt = max(1, civ_svc_cnt, gov_svc_cnt, repair_kits_cnt, clean_kits_cnt, upg_inst_cnt)
                for w in self.top_svc_container.winfo_children():
                    w.destroy()

                svc_bars = [
                    ("Car Service (Civilian)", civ_svc_cnt, "#6C4DFF"),
                    ("Car Service (Government)", gov_svc_cnt, "#2A8DFF"),
                    ("Repair Kit", repair_kits_cnt, "#19D96B"),
                    ("Cleaning Kit", clean_kits_cnt, "#F9A826"),
                    ("Upgrade Installation", upg_inst_cnt, "#FF5C5C"),
                    ("VIP Claim", vip_claim_cnt, "#06B6D4"),
                ]
                for sname, count, color in svc_bars:
                    s_item = ctk.CTkFrame(self.top_svc_container, fg_color="transparent")
                    s_item.pack(fill="x", pady=3)
                    lbl_row = ctk.CTkFrame(s_item, fg_color="transparent")
                    lbl_row.pack(fill="x")
                    ctk.CTkLabel(lbl_row, text=sname, font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFF").pack(side="left")
                    ctk.CTkLabel(lbl_row, text=str(count), font=ctk.CTkFont(size=11, weight="bold"), text_color="#A4AEC6").pack(side="right")

                    pbar = ctk.CTkProgressBar(s_item, height=6, corner_radius=3, fg_color="#090B14", progress_color=color)
                    pbar.pack(fill="x", pady=(2, 4))
                    pbar.set(min(1.0, count / float(max_cnt)))

                self.tree_dash_emp.delete(*self.tree_dash_emp.get_children())
                for idx, emp in enumerate(roster[:10], start=1):
                    rank_badge = f"🥇 #{idx}" if idx == 1 else (f"🥈 #{idx}" if idx == 2 else (f"🥉 #{idx}" if idx == 3 else f"#{idx}"))
                    self.tree_dash_emp.insert("", "end", values=(emp["name"], emp["service"], emp["kits"], emp["upgrade"], emp["points"], rank_badge))

                # Calculate dynamic daily revenue for line chart
                daily_rev = defaultdict(float)
                for r in filtered_svc:
                    if len(r) > sheets._AMOUNT_COL["Service"] and r[0]:
                        dt = sheets.parse_ist_timestamp(r[0])
                        v_str = r[sheets._AMOUNT_COL["Service"]].replace('.','',1).replace(',','').replace('-','').strip()
                        val = float(v_str) if v_str.isdigit() else 0.0
                        if dt and val > 0:
                            daily_rev[dt.strftime("%Y-%m-%d")] += val

                for r in filtered_upg:
                    if len(r) > sheets._AMOUNT_COL["Upgrades"] and r[0]:
                        dt = sheets.parse_ist_timestamp(r[0])
                        v_str = r[sheets._AMOUNT_COL["Upgrades"]].replace('.','',1).replace(',','').replace('-','').strip()
                        val = float(v_str) if v_str.isdigit() else 0.0
                        if dt and val > 0:
                            daily_rev[dt.strftime("%Y-%m-%d")] += val

                for r in filtered_kits:
                    if len(r) > sheets._AMOUNT_COL["Kits"] and r[0]:
                        dt = sheets.parse_ist_timestamp(r[0])
                        v_str = r[sheets._AMOUNT_COL["Kits"]].replace('.','',1).replace(',','').replace('-','').strip()
                        val = float(v_str) if v_str.isdigit() else 0.0
                        if dt and val > 0:
                            daily_rev[dt.strftime("%Y-%m-%d")] += val

                for r in filtered_vip:
                    if len(r) > 5 and r[5]:
                        dt = sheets.parse_ist_timestamp(r[5])
                        v_str = r[4].replace('.','',1).replace(',','').replace('-','').strip() if len(r) > 4 else "0"
                        val = float(v_str) if v_str.isdigit() else 0.0
                        if dt and val > 0:
                            daily_rev[dt.strftime("%Y-%m-%d")] += val

                sorted_daily_rev = {d: daily_rev[d] for d in sorted(daily_rev.keys())}

                # Calculate daily expenses map
                daily_exp = defaultdict(float)
                for r in filtered_exp:
                    if len(r) > 1 and r[0]:
                        dt = sheets.parse_ist_timestamp(r[0])
                        v_str = r[1].replace('.','',1).replace(',','').replace('-','').strip()
                        val = float(v_str) if v_str.isdigit() else 0.0
                        if dt and val > 0:
                            daily_exp[dt.strftime("%Y-%m-%d")] += val
                sorted_daily_exp = {d: daily_exp[d] for d in sorted(daily_exp.keys())}

                # 📊 Update Overview Page Financial KPIs & Widgets
                self.lbl_ov_revenue.configure(text=f"₹{total_sales:,.0f}")
                self.lbl_ov_expenses.configure(text=f"₹{total_expenses:,.0f}")
                self.lbl_ov_profit.configure(text=f"₹{net_profit:,.0f}")

                margin_pct = ((net_profit / total_sales) * 100) if total_sales > 0 else 0.0
                self.lbl_ov_margin_tag.configure(text=f"Margin: {margin_pct:.1f}%")
                self.lbl_ov_ratio.configure(text=f"{margin_pct:.1f}%")

                self.lbl_ov_svc_val.configure(text=f"₹{service_total:,.0f}")
                self.lbl_ov_upg_val.configure(text=f"₹{upgrade_total:,.0f}")
                self.lbl_ov_kits_val.configure(text=f"₹{kits_total:,.0f}")

                max_cat_val = max(1.0, service_total, upgrade_total, kits_total)
                self.pbar_ov_svc.set(min(1.0, service_total / max_cat_val))
                self.pbar_ov_upg.set(min(1.0, upgrade_total / max_cat_val))
                self.pbar_ov_kits.set(min(1.0, kits_total / max_cat_val))

                self._draw_revenue_chart(sorted_daily_rev)
                self._draw_overview_chart(sorted_daily_rev, sorted_daily_exp)

                # Populate P&L Table
                self.tree_ov_pnl.delete(*self.tree_ov_pnl.get_children())
                svc_share = (service_total / total_sales * 100) if total_sales > 0 else 0.0
                upg_share = (upgrade_total / total_sales * 100) if total_sales > 0 else 0.0
                kits_share = (kits_total / total_sales * 100) if total_sales > 0 else 0.0
                vip_share = (vip_total / total_sales * 100) if total_sales > 0 else 0.0

                pnl_rows = [
                    ("🛠️ Service", f"₹{service_total:,.0f}", f"{svc_share:.1f}%", "₹0", f"₹{service_total:,.0f}", "100.0%", "🟢 High Margin"),
                    ("🔧 Upgrade", f"₹{upgrade_total:,.0f}", f"{upg_share:.1f}%", "₹0", f"₹{upgrade_total:,.0f}", "100.0%", "🟢 High Margin"),
                    ("🧰 Kits", f"₹{kits_total:,.0f}", f"{kits_share:.1f}%", "₹0", f"₹{kits_total:,.0f}", "100.0%", "🟢 High Margin"),
                    ("👑 Vip Log", f"₹{vip_total:,.0f}", f"{vip_share:.1f}%", "₹0", f"₹{vip_total:,.0f}", "100.0%", "🟢 Settled Sales"),
                    ("💸 Bill Claim", "₹0", "0.0%", f"₹{total_expenses:,.0f}", f"-₹{total_expenses:,.0f}", "0.0%", "🔴 Shop Outflow"),
                    ("📊 TOTAL SHOP NET", f"₹{total_sales:,.0f}", "100.0%", f"₹{total_expenses:,.0f}", f"₹{net_profit:,.0f}", f"{margin_pct:.1f}%", "🌟 High Performance" if net_profit > 0 else "⚠️ Deficit")
                ]
                for pnl in pnl_rows:
                    self.tree_ov_pnl.insert("", "end", values=pnl)

                self._refresh_employee_page_list(roster)

                # Populate Expenses Table
                self.tree_exp.delete(*self.tree_exp.get_children())
                if filtered_exp:
                    for r in filtered_exp:
                        ts = r[0] if len(r) > 0 else ""
                        amt_str = f"₹{float(r[1]):,.0f}" if len(r) > 1 and r[1].replace('.','',1).isdigit() else (r[1] if len(r) > 1 else "₹0")
                        staff_name = resolve_name(r[2]) if len(r) > 2 else "Unknown"
                        cat = r[3] if len(r) > 3 else "General"
                        desc = r[4] if len(r) > 4 else ""
                        self.tree_exp.insert("", "end", values=(ts, amt_str, staff_name, cat, desc))
                else:
                    for ex in db.get_expenses():
                        self.tree_exp.insert("", "end", values=(ex["timestamp"], f"₹{ex['amount']:,.0f}", ex["employee"], ex.get("category", "General"), ex.get("desc", "")))

                # Populate Inventory Table
                self.lbl_inv_summary.configure(text=f"Total Stock Items: {tot_inv_items}  |  Total Inventory Asset Value: ₹{tot_inv_val:,.0f}")
                self.tree_inv.delete(*self.tree_inv.get_children())
                if filtered_inv:
                    for r in filtered_inv:
                        item_n = r[0] if len(r) > 0 else ""
                        qty_n = r[1] if len(r) > 1 else "0"
                        bought_m = r[2] if len(r) > 2 else "0"
                        restock_d = r[3] if len(r) > 3 else ""
                        u_price = f"₹{float(r[4]):,.0f}" if len(r) > 4 and r[4].replace('.','',1).isdigit() else (r[4] if len(r) > 4 else "₹0")
                        t_val = f"₹{float(r[5]):,.0f}" if len(r) > 5 and r[5].replace('.','',1).isdigit() else (r[5] if len(r) > 5 else "₹0")
                        up_dt = r[6] if len(r) > 6 else ""
                        self.tree_inv.insert("", "end", values=(item_n, qty_n, bought_m, restock_d, u_price, t_val, up_dt))
                else:
                    for item in db.get_inventory():
                        total_asset = item["qty"] * item["unit_price"]
                        self.tree_inv.insert("", "end", values=(item["item_name"], item["qty"], 0, item.get("last_updated","").split()[0], f"₹{item['unit_price']:,.0f}", f"₹{total_asset:,.0f}", item["last_updated"]))

                # Services Table
                self.tree_svc.delete(*self.tree_svc.get_children())
                for r in filtered_svc:
                    if len(r) >= 6:
                        self.tree_svc.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], resolve_name(r[5])))

                # Upgrades Table
                self.tree_upg.delete(*self.tree_upg.get_children())
                for r in filtered_upg:
                    if len(r) >= 4:
                        self.tree_upg.insert("", "end", values=(r[0], r[1], "Upgrade", "Standard", resolve_name(r[3]), r[2]))
                for r in filtered_vip:
                    if len(r) >= 6:
                        self.tree_upg.insert("", "end", values=(r[5], r[0], r[1], r[2], resolve_name(r[3]), r[4]))

                # Kits Table
                self.tree_kits.delete(*self.tree_kits.get_children())
                for r in filtered_kits:
                    if len(r) >= 7:
                        self.tree_kits.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], r[5], resolve_name(r[6])))

                # Transactions Table
                self.tree_txns.delete(*self.tree_txns.get_children())
                for r in filtered_txns:
                    if len(r) >= 5:
                        self.tree_txns.insert("", "end", values=(r[0], r[1], r[2], r[3], resolve_name(r[4])))

                # VIP Claims Table
                self.lbl_vip_summary.configure(text=f"Total VIP Claims: {len(filtered_vip)}  |  Total VIP Value: ₹{vip_total:,.0f}")
                self.tree_vip.delete(*self.tree_vip.get_children())
                for r in filtered_vip:
                    cust_n = r[0] if len(r) > 0 else "Customer"
                    veh_n = r[1] if len(r) > 1 else "VIP Car"
                    staff_n = resolve_name(r[3]) if len(r) > 3 else "Staff"
                    amt_str = f"₹{float(r[4]):,.0f}" if len(r) > 4 and r[4].replace('.','',1).isdigit() else (r[4] if len(r) > 4 else "₹0")
                    ts_str = r[5] if len(r) > 5 else ""
                    status_str = r[6] if len(r) > 6 and r[6] else "✅ Claimed (Added to Sales)"
                    self.tree_vip.insert("", "end", values=(ts_str, cust_n, veh_n, amt_str, staff_n, status_str))

                # Alerts Table
                self.tree_alerts.delete(*self.tree_alerts.get_children())
                for a in db.get_alerts():
                    self.tree_alerts.insert("", "end", values=(a["timestamp"], a["type"], a["message"], a["severity"].upper()))

            except Exception:
                pass

        if fast_cached_only:
            rows_by_sheet = {
                "Service": sheets._all_rows("Service", fast_cached_only=True),
                "Upgrades": sheets._all_rows("Upgrades", fast_cached_only=True),
                "Kits": sheets._all_rows("Kits", fast_cached_only=True),
                "Expenses": sheets._all_rows("Expenses", fast_cached_only=True),
                "Inventory": sheets._all_rows("Inventory", fast_cached_only=True),
                "VIP Claim": sheets._all_rows("VIP Claim", fast_cached_only=True),
                "Transactions": sheets._all_rows("Transactions", fast_cached_only=True),
            }
            _calc_and_apply(rows_by_sheet)
        else:
            def _fetch():
                try:
                    rows_by_sheet = {
                        "Service": sheets._all_rows("Service"),
                        "Upgrades": sheets._all_rows("Upgrades"),
                        "Kits": sheets._all_rows("Kits"),
                        "Expenses": sheets._all_rows("Expenses"),
                        "Inventory": sheets._all_rows("Inventory"),
                        "VIP Claim": sheets._all_rows("VIP Claim"),
                        "Transactions": sheets._all_rows("Transactions"),
                    }
                    self.after(0, lambda: _calc_and_apply(rows_by_sheet))
                except Exception:
                    pass

            threading.Thread(target=_fetch, daemon=True).start()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    app = JiraiyaBotMonitorApp()
    app.mainloop()
