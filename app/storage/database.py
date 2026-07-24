from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.serialization import finite_number, json_safe, strict_json_dumps

T = TypeVar("T")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_time REAL NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    importance REAL NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    sim_time REAL NOT NULL,
                    seed INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS model_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sim_time REAL NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    response_json TEXT NOT NULL,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    sim_time REAL NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(model_responses)").fetchall()}
            if "metadata_json" not in columns:
                self._conn.execute("ALTER TABLE model_responses ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def _retry(self, operation: Callable[[], T]) -> T:
        last: Exception | None = None
        for attempt in range(4):
            try:
                with self._lock:
                    return operation()
            except sqlite3.OperationalError as exc:
                last = exc
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                time.sleep(0.03 * (attempt + 1))
        assert last is not None
        raise last

    def set_metadata(self, key: str, value: Any) -> None:
        payload = strict_json_dumps(value, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000)

        def op() -> None:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, payload),
                )

        self._retry(op)

    def get_metadata(self, key: str) -> Any | None:
        row = self._retry(lambda: self._conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone())
        return json.loads(row["value"]) if row else None

    def clear_memories(self) -> None:
        def op() -> None:
            with self._conn:
                self._conn.execute("DELETE FROM memories")

        self._retry(op)

    def clear_experiment(self) -> None:
        """Clear world-specific history while preserving application/runtime configuration."""

        def op() -> None:
            with self._conn:
                self._conn.executescript(
                    """
                    DELETE FROM events;
                    DELETE FROM snapshots;
                    DELETE FROM model_responses;
                    DELETE FROM memories;
                    DELETE FROM metadata WHERE key IN ('current_state', 'run_id', 'world_generation_id');
                    """
                )

        self._retry(op)

    def add_event(self, event: dict[str, Any]) -> int:
        def op() -> int:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO events(sim_time, kind, message, importance, data_json) VALUES(?,?,?,?,?)",
                    (
                        finite_number(event.get("sim_time"), 0.0) or 0.0,
                        str(event.get("kind") or "unknown")[:120],
                        str(event.get("message") or "")[:4000],
                        finite_number(event.get("importance"), 0.3, minimum=0.0, maximum=1.0) or 0.3,
                        strict_json_dumps(event.get("data", {}), max_depth=10, max_items=1000, max_text=4000, max_nodes=50000),
                    ),
                )
                return int(cursor.lastrowid)

        return self._retry(op)

    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._retry(
            lambda: self._conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        )
        return [
            {
                "id": row["id"],
                "sim_time": row["sim_time"],
                "kind": row["kind"],
                "message": row["message"],
                "importance": row["importance"],
                "data": json.loads(row["data_json"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def save_snapshot(self, name: str, state: dict[str, Any]) -> None:
        world = state["world"]
        payload = strict_json_dumps(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000)

        def op() -> None:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO snapshots(name, sim_time, seed, state_json) VALUES(?,?,?,?)
                    ON CONFLICT(name) DO UPDATE SET sim_time=excluded.sim_time, seed=excluded.seed,
                    state_json=excluded.state_json, created_at=CURRENT_TIMESTAMP
                    """,
                    (name, world["sim_time"], world["seed"], payload),
                )

        self._retry(op)

    def load_snapshot(self, name: str) -> dict[str, Any] | None:
        row = self._retry(lambda: self._conn.execute("SELECT state_json FROM snapshots WHERE name=?", (name,)).fetchone())
        return json.loads(row["state_json"]) if row else None

    def list_snapshots(self) -> list[dict[str, Any]]:
        rows = self._retry(
            lambda: self._conn.execute(
                "SELECT name, sim_time, seed, created_at FROM snapshots ORDER BY created_at DESC"
            ).fetchall()
        )
        return [dict(row) for row in rows]

    def add_model_response(self, sim_time: float, result: Any) -> int:
        response_value = result.value.model_dump() if hasattr(result.value, "model_dump") else result.value
        response_json = strict_json_dumps(response_value, max_depth=8, max_items=512, max_text=4000, max_nodes=50000)
        provider_metadata = {
            "finish_reason": getattr(result, "finish_reason", None),
            "provider_response_id": getattr(result, "provider_response_id", None),
            "request_attempts": getattr(result, "request_attempts", None),
        }

        def op() -> int:
            with self._conn:
                cursor = self._conn.execute(
                    """INSERT INTO model_responses(sim_time, source, status, latency_ms, prompt_tokens,
                    completion_tokens, response_json, error, metadata_json) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        sim_time,
                        result.source,
                        result.status,
                        result.latency_ms,
                        result.prompt_tokens,
                        result.completion_tokens,
                        response_json,
                        result.error,
                        strict_json_dumps(provider_metadata, max_depth=4, max_items=64, max_text=1000, max_nodes=1000),
                    ),
                )
                return int(cursor.lastrowid)

        return self._retry(op)

    def list_model_responses(self, limit: int = 2000) -> list[dict[str, Any]]:
        rows = self._retry(
            lambda: self._conn.execute(
                "SELECT * FROM model_responses ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        )
        return [
            {
                "id": row["id"],
                "sim_time": row["sim_time"],
                "source": row["source"],
                "status": row["status"],
                "latency_ms": row["latency_ms"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "response": json.loads(row["response_json"]),
                "error": row["error"],
                "provider": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def add_memory(self, record: Any) -> None:
        payload = record.to_dict()

        def op() -> None:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO memories(id, sim_time, category, title, path, metadata_json) VALUES(?,?,?,?,?,?)",
                    (record.id, record.sim_time, record.category, record.title, record.path, strict_json_dumps(payload, max_depth=8, max_items=512, max_text=4000, max_nodes=50000)),
                )

        self._retry(op)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
