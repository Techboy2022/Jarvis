"""SQLite persistence for chats, messages and user preferences.

sqlite3 is synchronous, so every public helper is an ``async def`` that hops
onto a worker thread. That keeps the event loop free while streaming.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'New chat',
    model         TEXT,
    system_prompt TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    pinned        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    thinking   TEXT,
    model      TEXT,
    stats      TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);

CREATE TABLE IF NOT EXISTS prefs (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    # ---------------------------------------------------------------- chats

    async def create_chat(self, title: str = "New chat", model: str | None = None,
                          system_prompt: str | None = None) -> dict[str, Any]:
        chat_id = uuid.uuid4().hex

        def _create() -> dict[str, Any]:
            now = time.time()
            self._conn.execute(
                "INSERT INTO chats (id, title, model, system_prompt, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, title, model, system_prompt, now, now),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            return _chat_row(row, 0)

        return await self._run(_create)

    async def list_chats(self) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS n"
                " FROM chats c ORDER BY c.pinned DESC, c.updated_at DESC"
            ).fetchall()
            return [_chat_row(r, r["n"]) for r in rows]

        return await self._run(_list)

    async def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        def _get() -> dict[str, Any] | None:
            row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            if row is None:
                return None
            msgs = self._conn.execute(
                "SELECT * FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)
            ).fetchall()
            chat = _chat_row(row, len(msgs))
            chat["messages"] = [_message_row(m) for m in msgs]
            return chat

        return await self._run(_get)

    async def update_chat(self, chat_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"title", "model", "system_prompt", "pinned"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_chat_meta(chat_id)

        def _update() -> dict[str, Any] | None:
            assignments = ", ".join(f"{k} = ?" for k in updates)
            self._conn.execute(
                f"UPDATE chats SET {assignments}, updated_at = ? WHERE id = ?",
                (*updates.values(), time.time(), chat_id),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            return _chat_row(row, 0) if row else None

        return await self._run(_update)

    async def get_chat_meta(self, chat_id: str) -> dict[str, Any] | None:
        def _get() -> dict[str, Any] | None:
            row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            return _chat_row(row, 0) if row else None

        return await self._run(_get)

    async def delete_chat(self, chat_id: str) -> bool:
        def _delete() -> bool:
            cur = self._conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            self._conn.commit()
            return cur.rowcount > 0

        return await self._run(_delete)

    async def delete_all_chats(self) -> int:
        def _delete() -> int:
            cur = self._conn.execute("DELETE FROM chats")
            self._conn.commit()
            return cur.rowcount

        return await self._run(_delete)

    # ------------------------------------------------------------- messages

    async def add_message(self, chat_id: str, role: str, content: str,
                          thinking: str | None = None, model: str | None = None,
                          stats: dict[str, Any] | None = None) -> dict[str, Any]:
        def _add() -> dict[str, Any]:
            now = time.time()
            cur = self._conn.execute(
                "INSERT INTO messages (chat_id, role, content, thinking, model, stats, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, role, content, thinking, model,
                 json.dumps(stats) if stats else None, now),
            )
            self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return _message_row(row)

        return await self._run(_add)

    async def history(self, chat_id: str, limit: int) -> list[dict[str, str]]:
        """Last ``limit`` messages, oldest first, as Ollama chat messages."""

        def _history() -> list[dict[str, str]]:
            rows = self._conn.execute(
                "SELECT role, content FROM (SELECT * FROM messages WHERE chat_id = ?"
                " ORDER BY id DESC LIMIT ?) ORDER BY id",
                (chat_id, limit),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows]

        return await self._run(_history)

    async def delete_message(self, message_id: int) -> bool:
        def _delete() -> bool:
            cur = self._conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            self._conn.commit()
            return cur.rowcount > 0

        return await self._run(_delete)

    async def truncate_from_last_user(self, chat_id: str) -> str | None:
        """Drop the trailing assistant reply (and its user turn) for a regenerate.

        Returns the removed user prompt, or ``None`` when there is nothing to
        regenerate.
        """

        def _truncate() -> str | None:
            rows = self._conn.execute(
                "SELECT id, role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 2",
                (chat_id,),
            ).fetchall()
            if not rows:
                return None
            prompt: str | None = None
            doomed: list[int] = []
            for row in rows:
                doomed.append(row["id"])
                if row["role"] == "user":
                    prompt = row["content"]
                    break
            if prompt is None:
                return None
            self._conn.executemany(
                "DELETE FROM messages WHERE id = ?", [(i,) for i in doomed]
            )
            self._conn.commit()
            return prompt

        return await self._run(_truncate)

    async def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        def _search() -> list[dict[str, Any]]:
            like = f"%{query}%"
            rows = self._conn.execute(
                "SELECT DISTINCT c.id, c.title, c.updated_at FROM chats c"
                " JOIN messages m ON m.chat_id = c.id"
                " WHERE c.title LIKE ? OR m.content LIKE ?"
                " ORDER BY c.updated_at DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
            return [{"id": r["id"], "title": r["title"], "updated_at": r["updated_at"]} for r in rows]

        return await self._run(_search)

    # ---------------------------------------------------------------- prefs

    async def get_prefs(self) -> dict[str, Any]:
        def _get() -> dict[str, Any]:
            rows = self._conn.execute("SELECT key, value FROM prefs").fetchall()
            return {r["key"]: json.loads(r["value"]) for r in rows}

        return await self._run(_get)

    async def set_prefs(self, values: dict[str, Any]) -> None:
        def _set() -> None:
            self._conn.executemany(
                "INSERT INTO prefs (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, json.dumps(v)) for k, v in values.items()],
            )
            self._conn.commit()

        await self._run(_set)


def _chat_row(row: sqlite3.Row, message_count: int) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pinned": bool(row["pinned"]),
        "message_count": message_count,
    }


def _message_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "thinking": row["thinking"],
        "model": row["model"],
        "stats": json.loads(row["stats"]) if row["stats"] else None,
        "created_at": row["created_at"],
    }
