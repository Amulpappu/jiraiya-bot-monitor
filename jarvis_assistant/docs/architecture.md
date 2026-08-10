# Jarvis Personal AI Assistant - Project Architecture & Workflow

## Overview
Jarvis is a fully local, privacy-focused, multi-agent AI assistant designed for Windows 11 using Google Antigravity Agent Architecture. It combines natural conversational intelligence, voice interaction, deep laptop management, system optimization, file organization, and browser intelligence.

```
                               ┌───────────────────────────┐
                               │     User Interface        │
                               │  (PySide6 Qt / CLI Mode)  │
                               └─────────────┬─────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │   Main Coordinator Agent  │
                               └──────┬─────┬─────┬────┬───┘
                                      │     │     │    │
          ┌───────────────────────────┘     │     │    └───────────────────────────┐
          │                                 │     │                                │
          ▼                                 ▼     ▼                                ▼
┌──────────────────┐               ┌─────────────────┐                    ┌──────────────────┐
│   Chat Agent     │               │ Windows Control │                    │ Optimization     │
│ (Local Ollama)   │               │      Agent      │                    │     Agent        │
└──────────────────┘               └─────────────────┘                    └──────────────────┘
          │                                 │                                      │
          ▼                                 ▼                                      ▼
┌──────────────────┐               ┌─────────────────┐                    ┌──────────────────┐
│ Browser Intel    │               │   File Agent    │                    │  Memory Agent    │
│    Agent         │               │ (Docs / Search) │                    │ (SQLite Database)│
└──────────────────┘               └─────────────────┘                    └──────────────────┘
```

---

## Agent Modules & Responsibilities

### 1. Main Coordinator Agent (`jarvis_assistant/core/coordinator.py`)
- Central dispatcher evaluating user query intent.
- Routes queries to specialized agents.
- Enforces strict safety validation via `SafetyChecker`.
- Persists all conversation turns to SQLite local memory.

### 2. Chat Agent (`jarvis_assistant/agents/chat_agent.py`)
- Interfaces with local Ollama service (`http://localhost:11434/api/chat`).
- Supports local LLMs (`gemma2`, `qwen2.5-coder`, `llama3.2`).
- Gracefully handles offline fallback responses when Ollama is not active.

### 3. Voice Agent (`jarvis_assistant/agents/voice_agent.py`)
- Handles microphone speech recognition (via Whisper / SpeechRecognition).
- Provides text-to-speech feedback using local TTS (via pyttsx3 / Piper).

### 4. Windows Control Agent (`jarvis_assistant/agents/windows_agent.py`)
- Launches and closes Windows applications (Chrome, VS Code, Discord, Steam, FiveM, etc.).
- Adjusts master volume and display brightness.
- Controls power states (Lock, Sleep, Scheduled Shutdown, Cancel Shutdown).
- Opens Windows 11 Settings pages directly via `ms-settings:` protocol.

### 5. Optimization Agent (`jarvis_assistant/agents/optimization_agent.py`)
- Gathers hardware metrics (CPU %, RAM GB/%, Disk free/used, Battery status, Active process count).
- Identifies memory-heavy background processes.
- Safe temporary cache cleaner (`%TEMP%`, Windows Temp).
- Flushes DNS cache (`ipconfig /flushdns`).
- Recommends laptop gaming optimizations.

### 6. File Agent (`jarvis_assistant/agents/file_agent.py`)
- Searches local files by keyword or file extension.
- Discovers large files (>100 MB).
- Reads and extracts text from TXT, Markdown, PDF (`pypdf`), and DOCX (`python-docx`).
- Creates folders, moves/renames files.
- Executes safe deletions with mandatory confirmation popups.

### 7. Browser Intelligence Agent (`jarvis_assistant/agents/browser_agent.py`)
- Searches local browsing history across Chrome, Edge, Firefox, and Brave.
- Measures browser RAM and process usage.
- Extracts technical tips, commands, and shortcuts from guides and tutorials.

### 8. Memory Agent (`jarvis_assistant/core/memory.py`)
- Manages persistent SQLite database (`jarvis_memory.db`).
- Stores conversation history, user preferences, app shortcuts, and research notes.
