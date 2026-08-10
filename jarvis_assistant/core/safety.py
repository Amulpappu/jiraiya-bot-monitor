import os
import re
from pathlib import Path
from jarvis_assistant.config import PROTECTED_PATHS

class SafetyChecker:
    """
    Enforces strict security and safety policies for Windows system operations,
    file deletions, registry edits, and command execution.
    """

    DANGEROUS_COMMAND_PATTERNS = [
        r"format\s+[a-z]:",
        r"rmdir\s+/s\s+/q\s+c:\\",
        r"del\s+/f\s+/s\s+/q\s+c:\\windows",
        r"remove-item\s+-recurse\s+-force\s+c:\\",
        r"set-executionpolicy\s+unrestricted",
        r"disable-pnpdevice",
        r"sc\s+config\s+windefend\s+start=\s*disabled",
        r"net\s+stop\s+windefend",
        r"reg\s+delete",
    ]

    RISKY_ACTIONS = {
        "delete_file": "Delete file: '{target}'",
        "delete_folder": "Delete folder and all contents: '{target}'",
        "empty_recycle_bin": "Empty Windows Recycle Bin",
        "kill_process": "Terminate process PID {pid} ({name})",
        "restart_pc": "Restart Windows laptop",
        "shutdown_pc": "Shutdown Windows laptop",
        "uninstall_app": "Uninstall application: '{target}'",
        "modify_registry": "Modify registry key: '{target}'",
        "close_tabs": "Close active browser tabs",
    }

    @classmethod
    def is_path_protected(cls, path_str: str) -> bool:
        """Check if a path falls inside protected Windows system directories."""
        if not path_str:
            return False
        
        try:
            target_path = Path(path_str).resolve()
            for protected in PROTECTED_PATHS:
                prot_path = Path(protected).resolve()
                if target_path == prot_path or prot_path in target_path.parents:
                    return True
        except Exception:
            # If path parsing fails, check substring defensively
            for protected in PROTECTED_PATHS:
                if protected.lower() in path_str.lower():
                    return True
        return False

    @classmethod
    def is_command_safe(cls, cmd: str) -> tuple[bool, str]:
        """Check shell/cmd/powershell command against dangerous pattern signatures."""
        cmd_lower = cmd.lower().strip()

        for pattern in cls.DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False, f"Blocked dangerous command pattern matching '{pattern}'."

        # Check for direct system directory targeting
        for prot in PROTECTED_PATHS:
            if prot.lower() in cmd_lower and any(kw in cmd_lower for kw in ["del", "remove", "rmdir", "format", "erase"]):
                return False, f"Blocked operation targeting protected system directory: {prot}"

        return True, "Command passed security checks."

    @classmethod
    def requires_confirmation(cls, action_type: str, details: dict = None) -> tuple[bool, str]:
        """
        Determines whether an action requires explicit user confirmation.
        Returns (requires_confirm, prompt_message).
        """
        if action_type in cls.RISKY_ACTIONS:
            msg_template = cls.RISKY_ACTIONS[action_type]
            details = details or {}
            prompt_msg = msg_template.format(**details) if details else msg_template
            return True, f"Confirmation Required: {prompt_msg}"

        return False, "Action safe to proceed automatically."
