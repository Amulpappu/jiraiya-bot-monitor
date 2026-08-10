import os
import sqlite3
import shutil
import tempfile
import psutil
import urllib.request
import re
from pathlib import Path
from jarvis_assistant.config import SUPPORTED_BROWSERS

class BrowserIntelligenceAgent:
    """
    Interacts safely with local Windows browsers (Chrome, Edge, Firefox, Brave).
    Searches browsing history, manages active session tabs, extracts technical tips
    from documentation/tutorials, monitors browser RAM usage, and organizes downloads.
    """

    BROWSER_HISTORY_PATHS = {
        "Chrome": r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\User Data\Default\History",
        "Edge": r"C:\Users\%USERNAME%\AppData\Local\Microsoft\Edge\User Data\Default\History",
        "Brave": r"C:\Users\%USERNAME%\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History",
    }

    def search_history(self, keyword: str, limit: int = 10) -> str:
        """Queries local SQLite history files for supported Chromium browsers."""
        results = []
        kw_lower = keyword.lower()

        for browser, rel_path in self.BROWSER_HISTORY_PATHS.items():
            db_path = os.path.expandvars(rel_path)
            if not os.path.exists(db_path):
                continue

            # Copy history DB to temp file because active browser locks DB file
            temp_db = tempfile.NamedTemporaryFile(delete=False)
            temp_db.close()

            try:
                shutil.copy2(db_path, temp_db.name)
                conn = sqlite3.connect(temp_db.name)
                cursor = conn.cursor()
                
                query = "SELECT title, url, visit_count, last_visit_time FROM urls WHERE title LIKE ? OR url LIKE ? ORDER BY last_visit_time DESC LIMIT ?"
                cursor.execute(query, (f"%{keyword}%", f"%{keyword}%", limit))
                rows = cursor.fetchall()
                
                for title, url, visit_count, _ in rows:
                    if title and url:
                        results.append({
                            "browser": browser,
                            "title": title,
                            "url": url,
                            "visits": visit_count
                        })
                conn.close()
            except Exception:
                pass
            finally:
                if os.path.exists(temp_db.name):
                    try:
                        os.unlink(temp_db.name)
                    except Exception:
                        pass

        if not results:
            return f"No browsing history found matching **\"{keyword}\"**."

        output = f"### 🌐 Browsing History Results for \"{keyword}\":\n\n"
        output += "| Browser | Title | URL | Visits |\n| --- | --- | --- | --- |\n"
        for r in results[:limit]:
            title_clean = r['title'].replace("|", "-")[:45]
            output += f"| `{r['browser']}` | `{title_clean}` | [{r['url'][:40]}...]({r['url']}) | `{r['visits']}` |\n"

        return output

    def get_browser_ram_usage(self) -> str:
        """Calculates RAM and CPU usage of active browsers."""
        browser_processes = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"]
        metrics = {}

        for p in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                name = p.info['name'].lower()
                if name in browser_processes:
                    b_name = name.split(".")[0].capitalize()
                    if b_name not in metrics:
                        metrics[b_name] = {"count": 0, "ram_mb": 0.0}
                    
                    ram = p.info['memory_info'].rss / (1024 * 1024)
                    metrics[b_name]["count"] += 1
                    metrics[b_name]["ram_mb"] += ram
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not metrics:
            return "No active web browsers currently running."

        summary = "### 🌐 Active Browser Memory Usage\n\n"
        summary += "| Browser | Running Processes / Tabs | Total RAM Usage (MB) |\n| --- | --- | --- |\n"
        for bname, data in metrics.items():
            ram_mb = round(data['ram_mb'], 2)
            summary += f"| **{bname}** | `{data['count']}` | `{ram_mb} MB` |\n"

        summary += "\n> [!TIP]\n> Closing unused browser tabs or windows frees significant laptop RAM."
        return summary

    def extract_tips_and_tricks(self, url_or_text: str) -> str:
        """
        Parses text/webpage from tutorials or documentation to extract key commands,
        shortcuts, best practices, and optimization tips.
        """
        content = url_or_text

        # Fetch URL content if URL passed
        if url_or_text.startswith("http://") or url_or_text.startswith("https://"):
            try:
                req = urllib.request.Request(url_or_text, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                    # Strip basic HTML tags
                    content = re.sub(r'<[^>]+>', ' ', html)
            except Exception as e:
                return f"Failed to fetch webpage content from `{url_or_text}`: {e}"

        # Extract tips using regex heuristics
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        tips = []
        commands = []

        for line in lines:
            if any(kw in line.lower() for kw in ["tip:", "note:", "shortcut:", "recommend", "best practice", "warning:", "step"]):
                tips.append(line[:120])
            elif re.search(r"(`[^`]+`|\b(pip|git|npm|powershell|gcloud|bcdedit|reg|sfc|dism)\b)", line, re.I):
                commands.append(line[:120])

        summary = "### 💡 Extracted Tips & Best Practices\n\n"
        if tips:
            summary += "#### Key Insights:\n"
            for t in tips[:6]:
                summary += f"- {t}\n"
        
        if commands:
            summary += "\n#### Extracted Commands / Code Snippets:\n"
            for c in commands[:6]:
                summary += f"- `{c}`\n"

        if not tips and not commands:
            summary += "No explicit tip or command keywords detected in provided text snippet."

        return summary
