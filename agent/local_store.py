from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Tuple


@dataclass(slots=True)
class PendingMessage:
    id: int
    session_id: str
    source: str | None
    text: str
    captured_at: datetime


class AgentStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    source TEXT,
                    text TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def save_message(self, session_id: str, source: str | None, text: str, captured_at: datetime) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, source, text, captured_at, synced) VALUES (?, ?, ?, ?, 0)",
                (session_id, source, text, captured_at.isoformat()),
            )
            conn.commit()

    def load_pending(self, limit: int) -> List[PendingMessage]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, session_id, source, text, captured_at FROM messages WHERE synced = 0 ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            PendingMessage(
                id=row["id"],
                session_id=row["session_id"],
                source=row["source"],
                text=row["text"],
                captured_at=datetime.fromisoformat(row["captured_at"]),
            )
            for row in rows
        ]

    def mark_synced(self, message_ids: Iterable[int]) -> None:
        ids = list(message_ids)
        if not ids:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                "UPDATE messages SET synced = 1 WHERE id = ?",
                ((msg_id,) for msg_id in ids),
            )
            conn.commit()
