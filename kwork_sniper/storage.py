"""Хранилище виденных проектов (антидубли) на SQLite.

Помнит id уже обработанных проектов между перезапусками — чтобы не слать
повторных уведомлений. Для отправленных проектов хранит ещё и JSON их данных,
чтобы кнопка «Обновить» могла перерисовать сообщение (в т.ч. как «удалён»).
"""

from __future__ import annotations

import json
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
        # Миграция: добавляем колонку data, если её ещё нет (старые БД).
        try:
            self._conn.execute("ALTER TABLE seen ADD COLUMN data TEXT")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
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

    def save_project(self, project_id: int, data: dict) -> None:
        """Сохраняет/обновляет JSON данных отправленного проекта."""
        self._conn.execute(
            "INSERT INTO seen(project_id, data) VALUES(?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET data = excluded.data",
            (project_id, json.dumps(data, ensure_ascii=False)),
        )
        self._conn.commit()

    def get_project(self, project_id: int) -> dict | None:
        """Возвращает сохранённые данные проекта или None."""
        row = self._conn.execute(
            "SELECT data FROM seen WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
