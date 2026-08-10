import logging
from jarvis_assistant.core.memory import MemoryManager
from jarvis_assistant.core.safety import SafetyChecker
from jarvis_assistant.core.plugin_manager import PluginManager
from jarvis_assistant.agents.chat_agent import ChatAgent
from jarvis_assistant.agents.windows_agent import WindowsControlAgent
from jarvis_assistant.agents.optimization_agent import OptimizationAgent
from jarvis_assistant.agents.file_agent import FileAgent
from jarvis_assistant.agents.browser_agent import BrowserIntelligenceAgent

class CoordinatorAgent:
    """
    Main Coordinator Agent orchestrating specialized agents:
    - Intent parsing & task routing
    - Security validation via SafetyChecker
    - SQLite memory persistence
    - Plugin command execution
    - Combined response synthesis
    """

    def __init__(self, session_id: str = "default_session"):
        self.session_id = session_id
        self.memory = MemoryManager()
        self.plugins = PluginManager()

        # Instantiate specialized agents
        self.chat_agent = ChatAgent()
        self.windows_agent = WindowsControlAgent()
        self.optimization_agent = OptimizationAgent()
        self.file_agent = FileAgent()
        self.browser_agent = BrowserIntelligenceAgent()

    def process_request(self, user_input: str, confirm_token: bool = False) -> tuple[str, str, bool, dict]:
        """
        Processes user query and routes to the appropriate agent.
        Returns tuple: (response_markdown, agent_name, requires_confirmation, confirmation_details)
        """
        query = user_input.strip()
        q_lower = query.lower()

        if not query:
            return "Please state a command or question.", "coordinator", False, {}

        # 1. Check Plugin Manager
        plugin_result = self.plugins.handle_command(query)
        if plugin_result:
            self.memory.add_message(self.session_id, "user", query)
            self.memory.add_message(self.session_id, "assistant", str(plugin_result), "plugin")
            return str(plugin_result), "plugin", False, {}

        # 2. Browser Intelligence Agent Intents
        if any(kw in q_lower for kw in ["history", "browser", "browsing", "tab", "tips", "bookmark", "chrome", "edge", "firefox", "brave"]):
            if "ram" in q_lower or "memory" in q_lower or "usage" in q_lower:
                res = self.browser_agent.get_browser_ram_usage()
            elif "tip" in q_lower or "extract" in q_lower:
                res = self.browser_agent.extract_tips_and_tricks(query)
            else:
                kw = query.replace("history", "").replace("search", "").replace("for", "").strip()
                res = self.browser_agent.search_history(kw if kw else "a")

            self._save_interaction(query, res, "browser")
            return res, "browser", False, {}

        # 3. Optimization Agent Intents
        if any(kw in q_lower for kw in ["cpu", "gpu", "ram", "memory", "battery", "performance", "system stats", "laptop stats", "slow"]):
            if "clean" in q_lower or "temp" in q_lower:
                res = self.optimization_agent.clean_temp_files()
            elif "dns" in q_lower or "flush" in q_lower:
                res = self.optimization_agent.flush_dns_cache()
            elif "game" in q_lower or "gaming" in q_lower:
                res = self.optimization_agent.recommend_gaming_mode()
            elif "hog" in q_lower or "heavy" in q_lower or "top" in q_lower or "slow" in q_lower:
                res = self.optimization_agent.analyze_resource_hogs()
            else:
                res = self.optimization_agent.format_stats_summary()
            
            self._save_interaction(query, res, "optimization")
            return res, "optimization", False, {}

        # 4. Windows Control Agent Intents
        if any(kw in q_lower for kw in ["open", "launch", "close", "restart", "shutdown", "lock", "sleep", "volume", "mute"]):
            if "volume" in q_lower or "mute" in q_lower:
                if "mute" in q_lower: action = "mute"
                elif "up" in q_lower or "increase" in q_lower: action = "up"
                else: action = "down"
                res = self.windows_agent.adjust_volume(action)
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

            elif "lock" in q_lower and "pc" in q_lower:
                res = self.windows_agent.lock_pc()
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

            elif "sleep" in q_lower and ("pc" in q_lower or "laptop" in q_lower):
                res = self.windows_agent.sleep_pc()
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

            elif "shutdown" in q_lower or "restart" in q_lower:
                action_type = "shutdown_pc" if "shutdown" in q_lower else "restart_pc"
                if not confirm_token:
                    req, prompt = SafetyChecker.requires_confirmation(action_type)
                    return prompt, "windows", True, {"action": action_type}
                
                if "shutdown" in q_lower:
                    res = self.windows_agent.schedule_shutdown(delay_minutes=1)
                else:
                    res = "Restart initiated."
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

            elif "open" in q_lower or "launch" in q_lower:
                target = q_lower.replace("open", "").replace("launch", "").strip()
                res = self.windows_agent.launch_app(target)
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

            elif "close" in q_lower:
                target = q_lower.replace("close", "").strip()
                res = self.windows_agent.close_app(target)
                self._save_interaction(query, res, "windows")
                return res, "windows", False, {}

        # 4. File Agent Intents
        if any(kw in q_lower for kw in ["file", "folder", "directory", "pdf", "docx", "document", "find", "search file", "large file", "delete"]):
            if "delete" in q_lower or "remove" in q_lower:
                target = query.replace("delete", "").replace("remove", "").strip()
                if not confirm_token:
                    return f"⚠️ Confirmation required to delete file/folder: `{target}`", "file", True, {"action": "delete_file", "target": target}
                res = self.file_agent.safe_delete(target, confirmed=True)
            elif "large" in q_lower:
                res = self.file_agent.find_large_files()
            elif "read" in q_lower or "summarize" in q_lower:
                parts = query.split()
                target_path = parts[-1]
                res = self.file_agent.read_document(target_path)
            elif "create folder" in q_lower:
                folder_name = query.lower().replace("create folder", "").strip()
                res = self.file_agent.create_folder(folder_name)
            else:
                kw = query.replace("search", "").replace("find", "").replace("file", "").strip()
                res = self.file_agent.search_files(kw)

            self._save_interaction(query, res, "file")
            return res, "file", False, {}

        # 5. Browser Intelligence Agent Intents
        if any(kw in q_lower for kw in ["history", "browser", "browsing", "tab", "tips", "bookmark", "chrome", "edge"]):
            if "ram" in q_lower or "memory" in q_lower or "usage" in q_lower:
                res = self.browser_agent.get_browser_ram_usage()
            elif "tip" in q_lower or "extract" in q_lower:
                res = self.browser_agent.extract_tips_and_tricks(query)
            else:
                kw = query.replace("history", "").replace("search", "").replace("for", "").strip()
                res = self.browser_agent.search_history(kw if kw else "a")

            self._save_interaction(query, res, "browser")
            return res, "browser", False, {}

        # 6. Fallback to Conversational Chat Agent (LLM)
        history = self.memory.get_recent_history(self.session_id, limit=6)
        res = self.chat_agent.generate_response(query, conversation_context=history)
        self._save_interaction(query, res, "chat")
        return res, "chat", False, {}

    def _save_interaction(self, query: str, response: str, agent_used: str):
        self.memory.add_message(self.session_id, "user", query)
        self.memory.add_message(self.session_id, "assistant", response, agent_used)
