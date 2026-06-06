"""Хранилище виденных проектов (антидубли) на SQLite.

Помнит id уже обработанных проектов между перезапусками — чтобы не слать
повторных уведомлений.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


class Storage:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            "  project_id INTEGER PRIMARY KEY,"
            "  first_seen TEXT DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        self._conn.commit()

    def is_seen(self, project_id: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen WHERE project_id = ?", (project_id,)
        )
        return cur.fetchone() is not None

    def add(self, project_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen(project_id) VALUES (?)", (project_id,)
        )
        self._conn.commit()

    def add_many(self, project_ids: Iterable[int]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen(project_id) VALUES (?)",
            [(pid,) for pid in project_ids],
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
