import json
import urllib.request
import urllib.error
from jarvis_assistant.config import OLLAMA_HOST, DEFAULT_LLM_MODEL

class ChatAgent:
    """
    Handles natural conversation, reasoning, summaries, coding assistance,
    and markdown responses using local LLMs (Ollama) or local fallback.
    """

    SYSTEM_PROMPT = (
        "You are Jarvis, a helpful, highly intelligent, privacy-focused Windows AI Assistant. "
        "Provide direct, concise, natural, and helpful answers formatted in markdown."
    )

    def __init__(self, model_name: str = DEFAULT_LLM_MODEL, host: str = OLLAMA_HOST):
        self.model_name = model_name
        self.host = host.rstrip("/")

    def generate_response(self, prompt: str, conversation_context: list[dict] = None) -> str:
        """
        Sends request to local Ollama service.
        Falls back to a structured offline response if Ollama service is unreachable.
        """
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]

        if conversation_context:
            for msg in conversation_context[-6:]:  # include last 6 turns context
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": prompt})

        active_model = self._get_active_model()
        url = f"{self.host}/api/chat"
        payload = {
            "model": active_model,
            "messages": messages,
            "stream": False
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    content = data.get("message", {}).get("content", "").strip()
                    if content:
                        return content
        except Exception as e:
            print(f"[Ollama LLM Error]: {e}")
            return self._offline_fallback_response(prompt)

        return self._offline_fallback_response(prompt)

    def _get_active_model(self) -> str:
        """Queries local Ollama tags API to resolve available installed models."""
        try:
            url = f"{self.host}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    if self.model_name in models:
                        return self.model_name
                    if models:
                        return models[0]  # Return first installed model
        except Exception:
            pass
        return self.model_name

    def _offline_fallback_response(self, prompt: str) -> str:
        """Fallback response generator when Ollama service is not running locally."""
        p_lower = prompt.lower()
        if "who are you" in p_lower or "what is your name" in p_lower:
            return (
                "### I am **Jarvis**\n\n"
                "Your local, privacy-focused Windows AI Assistant powered by Google Antigravity Agent Architecture. "
                "I can control your Windows laptop, monitor & optimize performance, manage files, search browsing history, and process voice commands."
            )
        elif "help" in p_lower or "what can you do" in p_lower:
            return (
                "### Jarvis Capabilities Overview\n\n"
                "- **Windows Control**: Open apps (Chrome, VS Code, Steam), adjust volume/brightness, lock/sleep/restart PC.\n"
                "- **System Optimization**: Show CPU/GPU/RAM usage, clean Windows temp files, recommend gaming settings.\n"
                "- **File Management**: Search files, summarize PDFs/DOCX/Markdown, organize folders, delete with safety check.\n"
                "- **Browser Intelligence**: Search history across Chrome/Edge/Firefox/Brave, list tabs, extract tips from guides.\n"
                "- **Local AI Chat**: Fully local privacy-focused LLM chat via Ollama (Gemma2 / Qwen2.5)."
            )

        # Quick Web / Knowledge Lookup for general questions
        web_summary = self._quick_web_lookup(prompt)
        if web_summary:
            return web_summary

        return (
            f"**Jarvis Assistant**\n\n"
            f"Received your query: *\"{prompt}\"*\n\n"
            f"> [!IMPORTANT]\n"
            f"> **Ollama is not yet installed on this PC.**\n"
            f"> To enable full offline AI reasoning:\n"
            f"> 1. Open PowerShell and run: `winget install Ollama.Ollama` (or download from [ollama.com](https://ollama.com/download))\n"
            f"> 2. Run: `ollama run gemma2`\n\n"
            f"All Windows device control, system optimization, file tools, and browser history features remain fully active!"
        )

    def _quick_web_lookup(self, query: str) -> str | None:
        """Attempts a quick Wikipedia API lookup for general knowledge questions."""
        clean_q = query.lower().replace("what is", "").replace("who is", "").replace("explain", "").replace("?", "").strip()
        if not clean_q:
            return None

        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_q)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JarvisAssistant/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    title = data.get("title", clean_q.capitalize())
                    extract = data.get("extract", "")
                    if extract:
                        return (
                            f"### 🌐 {title}\n\n"
                            f"{extract}\n\n"
                            f"> [!NOTE]\n"
                            f"> *Retrieved via Jarvis Quick Web Lookup.*"
                        )
        except Exception:
            pass
        return None
