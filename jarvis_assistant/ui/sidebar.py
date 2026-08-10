try:
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QFrame, QSpacerItem, QSizePolicy
    from PySide6.QtCore import Signal
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

class SidebarNav(QWidget if PYSIDE_AVAILABLE else object):
    """
    Sidebar Navigation component with links for Chat, Performance Dashboard,
    Local Memory Inspector, Plugin Manager, and Theme Switcher.
    """
    
    # Custom signals for page switching
    page_changed = Signal(str) if PYSIDE_AVAILABLE else None

    def __init__(self, parent=None):
        if PYSIDE_AVAILABLE:
            super().__init__(parent)
            self.setObjectName("Sidebar")
            self.setFixedWidth(200)
            self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("⚙️ JARVIS")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px 5px;")
        layout.addWidget(title)

        btn_chat = QPushButton("💬 Assistant Chat")
        btn_chat.setObjectName("NavButton")
        btn_chat.clicked.connect(lambda: self.page_changed.emit("chat"))

        btn_dash = QPushButton("📊 Dashboard")
        btn_dash.setObjectName("NavButton")
        btn_dash.clicked.connect(lambda: self.page_changed.emit("dashboard"))

        btn_memory = QPushButton("🧠 Memory Agent")
        btn_memory.setObjectName("NavButton")
        btn_memory.clicked.connect(lambda: self.page_changed.emit("memory"))

        btn_plugins = QPushButton("🔌 Plugins")
        btn_plugins.setObjectName("NavButton")
        btn_plugins.clicked.connect(lambda: self.page_changed.emit("plugins"))

        layout.addWidget(btn_chat)
        layout.addWidget(btn_dash)
        layout.addWidget(btn_memory)
        layout.addWidget(btn_plugins)

        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        btn_theme = QPushButton("🌓 Toggle Theme")
        btn_theme.setObjectName("NavButton")
        btn_theme.clicked.connect(lambda: self.page_changed.emit("toggle_theme"))
        layout.addWidget(btn_theme)
