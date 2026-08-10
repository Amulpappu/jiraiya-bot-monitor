try:
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
    from PySide6.QtCore import Qt
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

class SafetyConfirmDialog:
    """
    Modal confirmation dialog displayed when a requested operation is risky
    (e.g., file deletion, PC shutdown/restart, process termination).
    """

    def __init__(self, parent=None, title: str = "Safety Confirmation Required", message: str = ""):
        self.title = title
        self.message = message
        self.confirmed = False

    def exec_(self) -> bool:
        if not PYSIDE_AVAILABLE:
            print(f"Safety Dialog (CLI fallback): {self.title}\n{self.message}")
            choice = input("Confirm action (y/n): ").strip().lower()
            return choice in ["y", "yes"]

        dialog = QDialog()
        dialog.setWindowTitle(self.title)
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        title_label = QLabel(f"<b>⚠️ {self.title}</b>")
        title_label.setStyleSheet("font-size: 16px; color: #f59e0b;")
        layout.addWidget(title_label)

        msg_label = QLabel(self.message)
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_confirm = QPushButton("Confirm Action")
        btn_confirm.setStyleSheet("background-color: #ef4444; color: white;")

        btn_cancel.clicked.connect(dialog.reject)
        btn_confirm.clicked.connect(dialog.accept)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_confirm)
        layout.addLayout(btn_layout)

        result = dialog.exec_()
        return result == QDialog.Accepted
