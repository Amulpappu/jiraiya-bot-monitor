try:
    from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from jarvis_assistant.ui.sidebar import SidebarNav
from jarvis_assistant.ui.chat_view import ChatView
from jarvis_assistant.ui.dashboard_view import DashboardView
from jarvis_assistant.ui.styles import Styles

class MainWindow(QMainWindow if PYSIDE_AVAILABLE else object):
    """
    Main Application Window combining Sidebar Navigation, Chat View,
    and Dashboard View into a single responsive layout.
    """

    def __init__(self):
        if PYSIDE_AVAILABLE:
            super().__init__()
            self.setWindowTitle("Jarvis Personal AI Assistant (Windows 11)")
            self.resize(1150, 750)
            self.is_dark_theme = True
            
            self._init_ui()
            self.setStyleSheet(Styles.DARK_THEME)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self.sidebar = SidebarNav()
        self.sidebar.page_changed.connect(self._on_navigation)
        main_layout.addWidget(self.sidebar)

        # Stacked Views Widget
        self.stacked_widget = QStackedWidget()
        
        self.chat_view = ChatView()
        self.dashboard_view = DashboardView()

        self.stacked_widget.addWidget(self.chat_view)       # Index 0
        self.stacked_widget.addWidget(self.dashboard_view)  # Index 1

        main_layout.addWidget(self.stacked_widget)

    def _on_navigation(self, page_key: str):
        if page_key == "chat":
            self.stacked_widget.setCurrentIndex(0)
        elif page_key == "dashboard":
            self.stacked_widget.setCurrentIndex(1)
            self.dashboard_view.update_metrics()
        elif page_key == "toggle_theme":
            self.is_dark_theme = not self.is_dark_theme
            theme = Styles.DARK_THEME if self.is_dark_theme else Styles.LIGHT_THEME
            self.setStyleSheet(theme)
