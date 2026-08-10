import os
import shutil
import subprocess
import psutil
from pathlib import Path
from jarvis_assistant.core.safety import SafetyChecker

class OptimizationAgent:
    """
    Monitors Windows performance stats (CPU, GPU, RAM, Storage, Battery),
    identifies resource bottlenecks, safely cleans temporary caches,
    and provides gaming & memory optimization suggestions.
    """

    def get_system_stats(self) -> dict:
        """Collects current hardware metrics."""
        cpu_pct = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('C:\\')
        
        battery_info = "N/A (Desktop / AC Power)"
        if hasattr(psutil, "sensors_battery"):
            batt = psutil.sensors_battery()
            if batt:
                plugged = "Plugged In" if batt.power_plugged else "On Battery"
                battery_info = f"{batt.percent}% ({plugged})"

        return {
            "cpu_usage": cpu_pct,
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_pct": mem.percent,
            "ram_available_gb": round(mem.available / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "disk_pct": disk.percent,
            "battery": battery_info,
            "running_processes": len(psutil.pids()),
        }

    def format_stats_summary(self) -> str:
        """Formats current system metrics into clean Markdown."""
        stats = self.get_system_stats()
        return (
            "### 🖥️ Windows Laptop System Performance\n\n"
            f"- **CPU Utilization**: `{stats['cpu_usage']}%`\n"
            f"- **Memory Usage**: `{stats['ram_used_gb']} GB / {stats['ram_total_gb']} GB` (`{stats['ram_pct']}%` used, `{stats['ram_available_gb']} GB free)\n"
            f"- **System Drive (C:)**: `{stats['disk_used_gb']} GB / {stats['disk_total_gb']} GB` (`{stats['disk_pct']}%` used)\n"
            f"- **Battery Health**: `{stats['battery']}`\n"
            f"- **Active Processes**: `{stats['running_processes']}`\n"
        )

    def analyze_resource_hogs(self) -> str:
        """Identifies top processes consuming RAM and CPU."""
        processes = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
            try:
                info = p.info
                ram_mb = round(info['memory_info'].rss / (1024 * 1024), 1)
                processes.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "cpu": info['cpu_percent'],
                    "ram_mb": ram_mb
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by RAM consumption
        top_ram = sorted(processes, key=lambda x: x['ram_mb'], reverse=True)[:5]
        
        summary = "### 📊 Top RAM Consuming Background Processes\n\n"
        summary += "| Process Name | PID | RAM Usage (MB) |\n| --- | --- | --- |\n"
        for proc in top_ram:
            summary += f"| `{proc['name']}` | `{proc['pid']}` | `{proc['ram_mb']} MB` |\n"

        summary += "\n> [!TIP]\n> If your laptop feels slow, closing unused heavy applications listed above will free up memory immediately."
        return summary

    def calculate_temp_files_size(self) -> dict:
        """Calculates size of user temp and Windows temp folders."""
        temp_paths = [
            os.environ.get("TEMP"),
            r"C:\Windows\Temp",
        ]
        
        total_bytes = 0
        details = {}

        for tpath in temp_paths:
            if tpath and os.path.exists(tpath):
                folder_bytes = 0
                try:
                    for root, _, files in os.walk(tpath):
                        for f in files:
                            try:
                                fp = os.path.join(root, f)
                                folder_bytes += os.path.getsize(fp)
                            except Exception:
                                pass
                except Exception:
                    pass
                total_bytes += folder_bytes
                details[tpath] = round(folder_bytes / (1024 * 1024), 2)

        total_mb = round(total_bytes / (1024 * 1024), 2)
        return {"total_mb": total_mb, "details": details}

    def clean_temp_files(self) -> str:
        """Cleans temporary files from User Temp folder safely."""
        user_temp = os.environ.get("TEMP")
        if not user_temp or not os.path.exists(user_temp):
            return "User Temp folder not found."

        deleted_count = 0
        freed_bytes = 0

        for item in os.listdir(user_temp):
            item_path = os.path.join(user_temp, item)
            # Skip protected path check
            if SafetyChecker.is_path_protected(item_path):
                continue

            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    size = os.path.getsize(item_path)
                    os.unlink(item_path)
                    deleted_count += 1
                    freed_bytes += size
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                    deleted_count += 1
            except Exception:
                continue

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        return f"Successfully cleaned **{deleted_count}** temporary items, freeing **{freed_mb} MB** of disk space."

    def flush_dns_cache(self) -> str:
        """Flushes Windows DNS resolver cache."""
        try:
            res = subprocess.run("ipconfig /flushdns", shell=True, capture_output=True, text=True)
            return f"**DNS Cache Flushed**:\n```\n{res.stdout.strip()}\n```"
        except Exception as e:
            return f"Failed to flush DNS cache: {e}"

    def recommend_gaming_mode(self) -> str:
        """Provides gaming performance recommendations."""
        return (
            "### 🎮 Recommended Windows Gaming Optimizations\n\n"
            "1. **Enable Windows Game Mode**: Open `ms-settings:gaming-gamemode` and turn on Game Mode.\n"
            "2. **Set Power Plan to High Performance**: Optimizes CPU frequency scaling.\n"
            "3. **Close Background Browsers**: Web browsers with multi-tabs consume 2-4 GB of RAM.\n"
            "4. **Update GPU Drivers**: Ensure NVIDIA/AMD/Intel graphics drivers are up to date.\n"
            "5. **Disable Startup Apps**: Check Task Manager (`Ctrl+Shift+Esc`) -> Startup Apps tab."
        )
