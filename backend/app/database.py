import os
import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import settings

def get_db_path() -> str:
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:////"):
        path = "/" + db_url[11:].lstrip("/")
    elif db_url.startswith("sqlite:///"):
        path = db_url[10:]
    elif db_url.startswith("sqlite://"):
        path = db_url[9:]
    else:
        path = db_url
    
    # Ensure directory exists if needed
    dirname = os.path.dirname(path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname, exist_ok=True)
    return path

def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    path = get_db_path()
    dirname = os.path.dirname(path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname, exist_ok=True)
    
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);")
    finally:
        conn.close()

def check_db_health() -> bool:
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            return cursor.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False

def get_session_messages(session_id: str) -> Optional[List[Dict[str, Any]]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        
        result = []
        for r in rows:
            item: Dict[str, Any] = {
                "role": r["role"],
                "content": r["content"]
            }
            if r["role"] == "assistant" and r["metadata"]:
                try:
                    item["metadata"] = json.loads(r["metadata"])
                except Exception:
                    item["metadata"] = {}
            result.append(item)
        return result
    finally:
        conn.close()

def save_message_turn(session_id: str, user_content: str, assistant_content: str, assistant_metadata: Dict[str, Any]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        with conn:
            # 1. Insert user message
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, "user", user_content, None, now_iso)
            )
            # 2. Insert assistant message
            meta_json = json.dumps(assistant_metadata)
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, "assistant", assistant_content, meta_json, now_iso)
            )
    finally:
        conn.close()
