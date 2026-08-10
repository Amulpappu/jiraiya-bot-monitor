try:
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QProgressBar
    from PySide6.QtCore import QTimer, Qt
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from jarvis_assistant.agents.optimization_agent import OptimizationAgent

class DashboardView(QWidget if PYSIDE_AVAILABLE else object):
    """
    Live Laptop System Performance Dashboard displaying CPU, RAM, Storage,
    Battery metrics, active processes, and quick optimization trigger buttons.
    """

    def __init__(self, parent=None):
        if PYSIDE_AVAILABLE:
            super().__init__(parent)
            self.opt_agent = OptimizationAgent()
            self._init_ui()
            
            # Setup periodic stats update timer (every 2 seconds)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update_metrics)
            self.timer.start(2000)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("💻 System Performance Dashboard")
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Metrics Cards Row
        metrics_layout = QHBoxLayout()

        # CPU Card
        self.cpu_card, self.cpu_val, self.cpu_bar = self._create_card("CPU Utilization", "0%")
        metrics_layout.addWidget(self.cpu_card)

        # RAM Card
        self.ram_card, self.ram_val, self.ram_bar = self._create_card("Memory (RAM)", "0 GB")
        metrics_layout.addWidget(self.ram_card)

        # Disk Card
        self.disk_card, self.disk_val, self.disk_bar = self._create_card("Storage (C:)", "0 GB")
        metrics_layout.addWidget(self.disk_card)

        layout.addLayout(metrics_layout)

        # Additional Info Panel
        info_card = QFrame()
        info_card.setObjectName("Card")
        info_layout = QVBoxLayout(info_card)

        self.lbl_battery = QLabel("Battery Status: Loading...")
        self.lbl_processes = QLabel("Running Processes: Loading...")
        info_layout.addWidget(self.lbl_battery)
        info_layout.addWidget(self.lbl_processes)

        layout.addWidget(info_card)

        # Quick Optimization Buttons
        btn_layout = QHBoxLayout()
        btn_clean_temp = QPushButton("🧹 Clean Temp Cache")
        btn_flush_dns = QPushButton("🌐 Flush DNS Cache")
        btn_game_mode = QPushButton("🎮 Gaming Recommendations")

        btn_clean_temp.clicked.connect(self._on_clean_temp)
        btn_flush_dns.clicked.connect(self._on_flush_dns)
        btn_game_mode.clicked.connect(self._on_game_mode)

        btn_layout.addWidget(btn_clean_temp)
        btn_layout.addWidget(btn_flush_dns)
        btn_layout.addWidget(btn_game_mode)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self.update_metrics()

    def _create_card(self, title_text: str, default_val: str):
        card = QFrame()
        card.setObjectName("Card")
        l = QVBoxLayout(card)
        
        t_label = QLabel(title_text)
        t_label.setObjectName("MetricTitle")
        
        v_label = QLabel(default_val)
        v_label.setObjectName("MetricValue")

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)

        l.addWidget(t_label)
        l.addWidget(v_label)
        l.addWidget(bar)

        return card, v_label, bar

    def update_metrics(self):
        if not PYSIDE_AVAILABLE:
            return

        stats = self.opt_agent.get_system_stats()
        self.cpu_val.setText(f"{stats['cpu_usage']}%")
        self.cpu_bar.setValue(int(stats['cpu_usage']))

        self.ram_val.setText(f"{stats['ram_used_gb']} / {stats['ram_total_gb']} GB")
        self.ram_bar.setValue(int(stats['ram_pct']))

        self.disk_val.setText(f"{stats['disk_used_gb']} / {stats['disk_total_gb']} GB")
        self.disk_bar.setValue(int(stats['disk_pct']))

        self.lbl_battery.setText(f"🔋 Battery Status: {stats['battery']}")
        self.lbl_processes.setText(f"⚙️ Active Processes: {stats['running_processes']}")

    def _on_clean_temp(self):
        msg = self.opt_agent.clean_temp_files()
        print(msg)

    def _on_flush_dns(self):
        msg = self.opt_agent.flush_dns_cache()
        print(msg)

    def _on_game_mode(self):
        msg = self.opt_agent.recommend_gaming_mode()
        print(msg)
