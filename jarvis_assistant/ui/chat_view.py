try:
    from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
                               QLineEdit, QPushButton, QScrollArea, QLabel, QFrame, QFileDialog)
    from PySide6.QtCore import Qt, Signal, QThread
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from jarvis_assistant.core.coordinator import CoordinatorAgent
from jarvis_assistant.agents.voice_agent import VoiceAgent
from jarvis_assistant.ui.confirm_dialog import SafetyConfirmDialog

class ChatView(QWidget if PYSIDE_AVAILABLE else object):
    """
    ChatGPT/Claude style conversation interface featuring markdown message bubbles,
    input field, microphone voice input button, file attachment picker,
    and integrated safety confirmation popups.
    """

    def __init__(self, parent=None):
        if PYSIDE_AVAILABLE:
            super().__init__(parent)
            self.coordinator = CoordinatorAgent()
            self.voice_agent = VoiceAgent()
            self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header Title
        header = QLabel("🤖 Jarvis AI Assistant")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px;")
        layout.addWidget(header)

        # Chat History Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.addStretch()
        
        self.scroll_area.setWidget(self.chat_container)
        layout.addWidget(self.scroll_area)

        # Input Area Controls
        input_layout = QHBoxLayout()

        self.btn_attach = QPushButton("📎")
        self.btn_attach.setToolTip("Attach File / Document")
        self.btn_attach.setMaximumWidth(40)
        self.btn_attach.clicked.connect(self._on_attach_file)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask Jarvis anything or give a Windows command... (e.g. 'Show CPU usage', 'Open Chrome')")
        self.input_field.returnPressed.connect(self._on_send_message)

        self.btn_voice = QPushButton("🎙️")
        self.btn_voice.setToolTip("Voice Command Input")
        self.btn_voice.setMaximumWidth(40)
        self.btn_voice.clicked.connect(self._on_voice_input)

        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self._on_send_message)

        input_layout.addWidget(self.btn_attach)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.btn_voice)
        input_layout.addWidget(self.btn_send)

        layout.addLayout(input_layout)

        # Initial Welcome Message
        self.add_message("assistant", "Hello! I am **Jarvis**, your local Windows AI Assistant. How can I help you today?")

    def add_message(self, role: str, content: str):
        if not PYSIDE_AVAILABLE:
            return

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)

        sender_label = QLabel("<b>You</b>" if role == "user" else "<b>Jarvis Agent</b>")
        sender_label.setStyleSheet("color: #3b82f6;" if role == "user" else "color: #10b981;")

        msg_box = QTextEdit()
        msg_box.setReadOnly(True)
        msg_box.setMarkdown(content)
        msg_box.setStyleSheet("border: none; background: transparent; padding: 4px;")
        
        # Calculate dynamic height based on document layout
        doc_height = int(msg_box.document().size().height()) + 15
        msg_box.setFixedHeight(max(45, min(doc_height, 450)))
        if doc_height <= 450:
            msg_box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        card_layout.addWidget(sender_label)
        card_layout.addWidget(msg_box)

        self.chat_layout.addWidget(card)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        if PYSIDE_AVAILABLE:
            self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            )

    def _on_send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self.add_message("user", text)
        self._process_user_input(text)

    def _process_user_input(self, text: str, confirm_token: bool = False):
        response_md, agent_used, requires_confirm, details = self.coordinator.process_request(text, confirm_token=confirm_token)

        if requires_confirm:
            # Trigger safety dialog
            dlg = SafetyConfirmDialog(self, title="Security Confirmation", message=response_md)
            if dlg.exec_():
                # Re-process with confirm_token = True
                self._process_user_input(text, confirm_token=True)
            else:
                self.add_message("assistant", "❌ Operation cancelled by user.")
            return

        self.add_message("assistant", response_md)
        self.voice_agent.speak(response_md)

    def _on_voice_input(self):
        self.add_message("assistant", "*Listening for voice input...*")
        speech_text = self.voice_agent.listen_speech(timeout=5)
        if speech_text:
            self.add_message("user", speech_text)
            self._process_user_input(speech_text)
        else:
            self.add_message("assistant", "Could not capture voice audio or microphone not detected.")

    def _on_attach_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Analyze", "", "All Files (*.*)")
        if file_path:
            cmd = f"Summarize document {file_path}"
            self.input_field.setText(cmd)
