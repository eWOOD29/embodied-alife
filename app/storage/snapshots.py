from __future__ import annotations

from app.storage.database import Database


class SnapshotStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, name: str, state: dict) -> None:
        if not name or len(name) > 80 or any(ch in name for ch in "/\\\x00"):
            raise ValueError("invalid_snapshot_name")
        self.database.save_snapshot(name, state)

    def load(self, name: str) -> dict | None:
        return self.database.load_snapshot(name)

    def list(self) -> list[dict]:
        return self.database.list_snapshots()
