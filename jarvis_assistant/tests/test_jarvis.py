import unittest
import os
import shutil
import tempfile
from pathlib import Path

from jarvis_assistant.core.safety import SafetyChecker
from jarvis_assistant.core.memory import MemoryManager
from jarvis_assistant.core.coordinator import CoordinatorAgent
from jarvis_assistant.agents.optimization_agent import OptimizationAgent
from jarvis_assistant.agents.file_agent import FileAgent
from jarvis_assistant.agents.browser_agent import BrowserIntelligenceAgent

class TestJarvisAssistant(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_memory.db"
        self.memory = MemoryManager(db_path=self.db_path)
        self.coordinator = CoordinatorAgent(session_id="test_session")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_safety_checker_protected_paths(self):
        self.assertTrue(SafetyChecker.is_path_protected(r"C:\Windows"))
        self.assertTrue(SafetyChecker.is_path_protected(r"C:\Windows\System32\drivers"))
        self.assertFalse(SafetyChecker.is_path_protected(r"C:\Users\Public\Documents"))

    def test_safety_checker_dangerous_commands(self):
        safe, msg = SafetyChecker.is_command_safe("format c:")
        self.assertFalse(safe)
        safe, msg = SafetyChecker.is_command_safe("del /f /s /q c:\\windows")
        self.assertFalse(safe)
        safe, msg = SafetyChecker.is_command_safe("echo Hello World")
        self.assertTrue(safe)

    def test_memory_manager(self):
        self.memory.add_message("test_s", "user", "Hello Jarvis", "chat")
        history = self.memory.get_recent_history("test_s")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "Hello Jarvis")

        self.memory.set_preference("theme", "dark")
        self.assertEqual(self.memory.get_preference("theme"), "dark")

    def test_coordinator_routing(self):
        # Optimization routing
        res, agent_used, _, _ = self.coordinator.process_request("Show CPU usage")
        self.assertEqual(agent_used, "optimization")
        self.assertIn("CPU Utilization", res)

        # Windows control routing
        res, agent_used, _, _ = self.coordinator.process_request("Open notepad")
        self.assertEqual(agent_used, "windows")

        # Browser routing
        res, agent_used, _, _ = self.coordinator.process_request("Show browser ram usage")
        self.assertEqual(agent_used, "browser")

    def test_file_agent_search(self):
        fa = FileAgent()
        # Create dummy file inside temp_dir
        dummy_file = os.path.join(self.temp_dir, "my_sample_test_doc.txt")
        with open(dummy_file, "w") as f:
            f.write("Test content")

        result = fa.search_files("my_sample_test_doc", start_directory=self.temp_dir)
        self.assertIn("my_sample_test_doc.txt", result)

    def test_file_agent_safe_delete_protection(self):
        fa = FileAgent()
        res = fa.safe_delete(r"C:\Windows\System32", confirmed=True)
        self.assertIn("SECURITY BLOCK", res)

if __name__ == "__main__":
    unittest.main()
