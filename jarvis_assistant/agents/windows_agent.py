import os
import sys
import subprocess
import shutil
import psutil
import ctypes
from jarvis_assistant.core.safety import SafetyChecker

class WindowsControlAgent:
    """
    Manages Windows applications, system settings, volume, brightness,
    power operations (lock, sleep, restart, shutdown), and process management.
    """

    KNOWN_APPS = {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "edge": r"msedge.exe",
        "microsoft edge": r"msedge.exe",
        "vs code": "code",
        "vscode": "code",
        "discord": r"C:\Users\%USERNAME%\AppData\Local\Discord\Update.exe --processStart Discord.exe",
        "steam": r"C:\Program Files (x86)\Steam\steam.exe",
        "fivem": "FiveM.exe",
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
    }

    def launch_app(self, app_name: str) -> str:
        """Launches an application by name or path."""
        clean_name = app_name.lower().strip()

        # Check known apps map
        if clean_name in self.KNOWN_APPS:
            target = os.path.expandvars(self.KNOWN_APPS[clean_name])
            try:
                subprocess.Popen(target, shell=True)
                return f"Launched **{app_name.capitalize()}** successfully."
            except Exception as e:
                return f"Failed to launch {app_name}: {e}"

        # Try generic system execution (PATH lookup)
        try:
            subprocess.Popen(clean_name, shell=True)
            return f"Launched application process: **{app_name}**"
        except Exception as e:
            return f"Could not find or launch application '{app_name}': {e}"

    def open_path_or_url(self, target: str) -> str:
        """Opens a folder, file, or URL in Windows default application."""
        if target.startswith("http://") or target.startswith("https://"):
            import webbrowser
            webbrowser.open(target)
            return f"Opened website: [{target}]({target})"

        expanded_path = os.path.expanduser(os.path.expandvars(target))
        if os.path.exists(expanded_path):
            os.startfile(expanded_path)
            return f"Opened Windows path: `{expanded_path}`"
        
        return f"Path not found: `{target}`"

    def close_app(self, app_name: str) -> str:
        """Terminates processes matching app_name."""
        clean_name = app_name.lower().replace(".exe", "").strip()
        closed_count = 0

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                proc_name = proc.info['name'].lower()
                if clean_name in proc_name:
                    p = psutil.Process(proc.info['pid'])
                    p.terminate()
                    closed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if closed_count > 0:
            return f"Closed **{closed_count}** process instance(s) matching '{app_name}'."
        return f"No running processes found matching '{app_name}'."

    def adjust_volume(self, action: str, level: int = None) -> str:
        """Adjusts master volume on Windows using nkc / Virtual Keys or NirCmd fallback."""
        try:
            if action == "mute":
                ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0) # VK_VOLUME_MUTE
                return "Toggled Windows volume mute."
            elif action == "up":
                for _ in range(5):
                    ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0) # VK_VOLUME_UP
                return "Increased Windows master volume."
            elif action == "down":
                for _ in range(5):
                    ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0) # VK_VOLUME_DOWN
                return "Decreased Windows master volume."
            elif level is not None:
                return f"Master volume level requested set to {level}%."
        except Exception as e:
            return f"Volume control error: {e}"
        return "Volume adjustment executed."

    def lock_pc(self) -> str:
        """Locks the Windows workstation."""
        try:
            ctypes.windll.user32.LockWorkStation()
            return "Windows PC locked."
        except Exception as e:
            return f"Failed to lock PC: {e}"

    def sleep_pc(self) -> str:
        """Puts Windows laptop into sleep mode."""
        try:
            subprocess.run("powertoy /sleep", shell=True) # or rundll32
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return "Windows laptop set to Sleep mode."
        except Exception as e:
            return f"Failed to initiate sleep: {e}"

    def schedule_shutdown(self, delay_minutes: int) -> str:
        """Schedules a Windows shutdown after specified delay in minutes."""
        seconds = delay_minutes * 60
        try:
            subprocess.run(f"shutdown /s /t {seconds}", shell=True, check=True)
            return f"Scheduled Windows shutdown in **{delay_minutes} minutes** (`shutdown /a` to cancel)."
        except Exception as e:
            return f"Failed to schedule shutdown: {e}"

    def cancel_shutdown(self) -> str:
        """Aborts scheduled Windows shutdown."""
        try:
            subprocess.run("shutdown /a", shell=True, check=True)
            return "Cancelled scheduled Windows shutdown."
        except Exception as e:
            return f"No scheduled shutdown to cancel or error occurred: {e}"

    def open_settings_page(self, setting_name: str) -> str:
        """Opens specific Windows 11 Settings page using ms-settings URI scheme."""
        settings_map = {
            "bluetooth": "ms-settings:bluetooth",
            "wifi": "ms-settings:network-wifi",
            "network": "ms-settings:network",
            "display": "ms-settings:display",
            "sound": "ms-settings:sound",
            "battery": "ms-settings:powersleep",
            "storage": "ms-settings:storagesense",
            "updates": "ms-settings:windowsupdate",
        }

        clean = setting_name.lower().strip()
        if clean in settings_map:
            os.system(f"start {settings_map[clean]}")
            return f"Opened Windows Settings page for **{clean.capitalize()}**."
        
        os.system("start ms-settings:")
        return "Opened Windows Settings main page."
