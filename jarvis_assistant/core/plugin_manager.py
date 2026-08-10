import importlib
import inspect
from pathlib import Path
from typing import Callable, Dict, Any

class JarvisPlugin:
    """Base class for custom Jarvis plugins."""
    name: str = "base_plugin"
    description: str = "Base Plugin"

    def get_commands(self) -> Dict[str, Callable]:
        """Returns mapping of command names/keywords to handler functions."""
        return {}


class PluginManager:
    """
    Extensible Plugin System allowing external features, MCP tools,
    or custom Python scripts to register with Jarvis Coordinator.
    """

    def __init__(self):
        self.plugins: Dict[str, JarvisPlugin] = {}
        self.registered_commands: Dict[str, Callable] = {}

    def register_plugin(self, plugin: JarvisPlugin):
        """Registers a plugin instance into Jarvis."""
        self.plugins[plugin.name] = plugin
        commands = plugin.get_commands()
        for cmd_trigger, handler in commands.items():
            self.registered_commands[cmd_trigger.lower()] = handler

    def handle_command(self, trigger: str, *args, **kwargs) -> Any:
        """Executes a registered plugin command if present."""
        trigger_clean = trigger.lower().strip()
        if trigger_clean in self.registered_commands:
            handler = self.registered_commands[trigger_clean]
            return handler(*args, **kwargs)
        return None

    def list_plugins(self) -> list[dict]:
        """Returns details of all loaded plugins."""
        return [
            {"name": p.name, "description": p.description, "commands": list(p.get_commands().keys())}
            for p in self.plugins.values()
        ]
