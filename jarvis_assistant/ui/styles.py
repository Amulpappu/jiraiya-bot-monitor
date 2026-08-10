class Styles:
    """Modern Dark and Light Theme QSS Stylesheets for Jarvis Assistant."""

    DARK_THEME = """
    QMainWindow {
        background-color: #0f172a;
        color: #f8fafc;
        font-family: 'Segoe UI', Roboto, sans-serif;
    }

    QWidget {
        background-color: #0f172a;
        color: #f8fafc;
        font-size: 14px;
    }

    /* Sidebar */
    #Sidebar {
        background-color: #1e293b;
        border-right: 1px solid #334155;
    }

    QPushButton {
        background-color: #3b82f6;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
    }

    QPushButton:hover {
        background-color: #2563eb;
    }

    QPushButton:pressed {
        background-color: #1d4ed8;
    }

    QPushButton#NavButton {
        background-color: transparent;
        color: #94a3b8;
        text-align: left;
        padding: 10px 14px;
        border-radius: 6px;
    }

    QPushButton#NavButton:hover {
        background-color: #334155;
        color: #f8fafc;
    }

    QPushButton#NavButton:checked {
        background-color: #3b82f6;
        color: #ffffff;
    }

    /* Chat Messages */
    QTextEdit, QPlainTextEdit, QLineEdit {
        background-color: #1e293b;
        color: #f8fafc;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 8px;
    }

    QTextEdit:focus, QLineEdit:focus {
        border: 1px solid #3b82f6;
    }

    /* Cards & Widgets */
    QFrame#Card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
    }

    QLabel#MetricTitle {
        color: #94a3b8;
        font-size: 12px;
        font-weight: bold;
    }

    QLabel#MetricValue {
        color: #38bdf8;
        font-size: 22px;
        font-weight: bold;
    }

    QProgressBar {
        border: none;
        background-color: #334155;
        border-radius: 6px;
        height: 10px;
        text-align: center;
    }

    QProgressBar::chunk {
        background-color: #3b82f6;
        border-radius: 6px;
    }
    """

    LIGHT_THEME = """
    QMainWindow {
        background-color: #f8fafc;
        color: #0f172a;
        font-family: 'Segoe UI', Roboto, sans-serif;
    }

    QWidget {
        background-color: #f8fafc;
        color: #0f172a;
        font-size: 14px;
    }

    #Sidebar {
        background-color: #ffffff;
        border-right: 1px solid #e2e8f0;
    }

    QPushButton {
        background-color: #2563eb;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
    }

    QPushButton#NavButton {
        background-color: transparent;
        color: #64748b;
        text-align: left;
        padding: 10px 14px;
    }

    QPushButton#NavButton:hover {
        background-color: #f1f5f9;
        color: #0f172a;
    }

    QFrame#Card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
    }
    """
