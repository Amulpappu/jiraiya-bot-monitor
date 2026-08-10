import sqlite3
import json
import time
from pathlib import Path
from jarvis_assistant.config import DB_PATH

class MemoryManager:
    """
    SQLite-backed local persistent memory manager for Jarvis Assistant.
    Stores chat history, user preferences, favorite paths, app mappings,
    and extracted research tips without cloud dependency.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Chat History table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_used TEXT DEFAULT 'chat',
                timestamp REAL NOT NULL
            );
            """)

            # User Preferences table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                pref_key TEXT PRIMARY KEY,
                pref_value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            # App Shortcuts & Favorite Paths
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_shortcuts (
                app_name TEXT PRIMARY KEY,
                exe_path TEXT NOT NULL,
                launch_count INTEGER DEFAULT 1
            );
            """)

            # Research Notes & Tips
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_url TEXT,
                tags TEXT,
                created_at REAL NOT NULL
            );
            """)

            conn.commit()

    # Conversation History
    def add_message(self, session_id: str, role: str, content: str, agent_used: str = "chat"):
        with self._get_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO conversation_history (session_id, role, content, agent_used, timestamp) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, agent_used, time.time())
            )
            conn.commit()

    def get_recent_history(self, session_id: str, limit: int = 15) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.cursor().execute(
                "SELECT role, content, agent_used, timestamp FROM conversation_history WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def search_history(self, query: str, limit: int = 10) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.cursor().execute(
                "SELECT session_id, role, content, timestamp FROM conversation_history WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # User Preferences
    def set_preference(self, key: str, value: any):
        val_str = json.dumps(value)
        with self._get_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO user_preferences (pref_key, pref_value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(pref_key) DO UPDATE SET pref_value = excluded.pref_value, updated_at = excluded.updated_at",
                (key, val_str, time.time())
            )
            conn.commit()

    def get_preference(self, key: str, default: any = None) -> any:
        with self._get_connection() as conn:
            row = conn.cursor().execute(
                "SELECT pref_value FROM user_preferences WHERE pref_key = ?", (key,)
            ).fetchone()
            if row:
                try:
                    return json.loads(row["pref_value"])
                except json.JSONDecodeError:
                    return row["pref_value"]
            return default

    # App Shortcuts
    def register_app_shortcut(self, app_name: str, exe_path: str):
        with self._get_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO app_shortcuts (app_name, exe_path, launch_count) VALUES (?, ?, 1) "
                "ON CONFLICT(app_name) DO UPDATE SET exe_path = excluded.exe_path, launch_count = launch_count + 1",
                (app_name.lower(), exe_path)
            )
            conn.commit()

    def get_app_shortcut(self, app_name: str) -> str | None:
        with self._get_connection() as conn:
            row = conn.cursor().execute(
                "SELECT exe_path FROM app_shortcuts WHERE app_name = ?", (app_name.lower(),)
            ).fetchone()
            return row["exe_path"] if row else None

    # Research Notes & Tips
    def save_research_note(self, title: str, content: str, source_url: str = None, tags: list[str] = None):
        tags_str = ",".join(tags) if tags else ""
        with self._get_connection() as conn:
            conn.cursor().execute(
                "INSERT INTO research_notes (title, content, source_url, tags, created_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, source_url, tags_str, time.time())
            )
            conn.commit()

    def search_research_notes(self, query: str) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.cursor().execute(
                "SELECT title, content, source_url, tags, created_at FROM research_notes "
                "WHERE title LIKE ? OR content LIKE ? ORDER BY created_at DESC",
                (f"%{query}%", f"%{query}%")
            ).fetchall()
            return [dict(r) for r in rows]
