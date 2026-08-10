# Jarvis Personal AI Assistant - Installation & Configuration Guide

## Prerequisites
- **Operating System**: Windows 11 or Windows 10 (64-bit)
- **Python**: Python 3.10, 3.11, 3.12, or 3.14
- **Local LLM Engine (Optional but Recommended)**: [Ollama](https://ollama.com/)

---

## Quick Start Installation

1. **Clone or Download Repository**:
   ```cmd
   cd c:\Users\lohit\Downloads\files\jarvis_assistant
   ```

2. **Install Python Dependencies**:
   ```cmd
   pip install -r requirements.txt
   ```

3. **Install & Start Ollama (Optional for Local AI Chat)**:
   - Download Ollama from [ollama.com](https://ollama.com/)
   - Pull your preferred model in terminal:
     ```cmd
     ollama pull gemma2
     ```

4. **Launch Jarvis Assistant**:
   - **GUI Mode (PySide6 Desktop Application)**:
     ```cmd
     python main.py
     ```
   - **CLI Mode (Interactive Terminal)**:
     ```cmd
     python main.py --cli
     ```
   - **Single Command Execution**:
     ```cmd
     python main.py --cmd "Show CPU usage"
     ```

---

## Configuration Settings

Global configuration values can be adjusted in `jarvis_assistant/config.py` or set via environment variables:

| Environment Variable | Default Value | Description |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | URL of local Ollama instance |
| `JARVIS_LLM_MODEL` | `gemma2` | Preferred LLM model (`gemma2`, `qwen2.5-coder`) |
| `JARVIS_STT_MODEL` | `base` | Whisper STT model size |
| `JARVIS_TTS_ENGINE` | `pyttsx3` | Text-to-speech driver engine |
