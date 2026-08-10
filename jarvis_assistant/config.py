import os
import sys
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "jarvis_memory.db"
LOG_PATH = DATA_DIR / "jarvis.log"

# Local AI Configuration (Ollama)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_LLM_MODEL = os.getenv("JARVIS_LLM_MODEL", "gemma2:2b") # gemma2:2b, qwen2.5, llama3.2

# Speech Configuration
STT_MODEL = os.getenv("JARVIS_STT_MODEL", "base") # whisper model size: tiny, base, small
TTS_ENGINE = os.getenv("JARVIS_TTS_ENGINE", "pyttsx3") # pyttsx3, piper

# Safety Settings
SAFETY_CONFIRMATION_REQUIRED = True
PROTECTED_PATHS = [
    r"C:\Windows",
    r"C:\Windows\System32",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
]

# Supported Browsers for History / Tab / Bookmark Access
SUPPORTED_BROWSERS = ["Chrome", "Edge", "Firefox", "Brave"]
