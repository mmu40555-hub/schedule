import sqlite3
from pathlib import Path

from .daily import DailyMixin
from .groups import GroupMixin
from .history import HistoryMixin
from .memos import MemoMixin
from .once import OnceMixin
from .period import PeriodMixin
from .remind import RemindMixin
from .schema import DB_PATH, DEFAULT_REMIND_MINUTES, SCHEMA
from .seed import SeedMixin
from .settings import SettingsMixin
from .today import TodayMixin


class Store(GroupMixin, DailyMixin, OnceMixin, PeriodMixin, TodayMixin, MemoMixin, SettingsMixin, RemindMixin, HistoryMixin, SeedMixin):
    """所有读写都经过这里。UI 层不直接接触 SQL。"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()
        self._seed_if_empty()

    def _migrate(self) -> None:
        """给旧库补上后来新增的列与表（CREATE TABLE IF NOT EXISTS 不会改已有表）。"""
        self._add_column("daily_tasks", "backlog", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("once_tasks", "always_show", "INTEGER NOT NULL DEFAULT 0")
        self._add_column("once_tasks", "group_name", "TEXT NOT NULL DEFAULT ''")
        self._add_column("period_tasks", "group_name", "TEXT NOT NULL DEFAULT ''")
        self._add_column(
            "daily_tasks", "remind_minutes",
            f"INTEGER NOT NULL DEFAULT {DEFAULT_REMIND_MINUTES}",
        )
        self._add_column(
            "once_tasks", "remind_minutes",
            f"INTEGER NOT NULL DEFAULT {DEFAULT_REMIND_MINUTES}",
        )
        self._add_column("memos", "stack_active", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("memos", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self._add_column("memos", "host_class", "TEXT NOT NULL DEFAULT ''")
        self._add_column("memos", "host_title", "TEXT NOT NULL DEFAULT ''")
        self._add_column("memos", "host_dx", "INTEGER NOT NULL DEFAULT 0")
        self._add_column("memos", "host_dy", "INTEGER NOT NULL DEFAULT 0")
        # 每日任务后来支持了每周 / 每月周期
        self._add_column("daily_tasks", "repeat", "TEXT NOT NULL DEFAULT 'daily'")
        self._add_column("daily_tasks", "repeat_day", "INTEGER NOT NULL DEFAULT 0")
        # 历史汇总要知道「什么时候完成的」，废弃栏要知道「什么时候丢的」
        self._add_column("once_tasks", "done_at", "TEXT NOT NULL DEFAULT ''")
        self._add_column("period_tasks", "done_at", "TEXT NOT NULL DEFAULT ''")
        self._add_column("memos", "discarded_at", "TEXT NOT NULL DEFAULT ''")

        # 组别早期只服务于每日任务，表名 daily_groups，现在三类任务共用
        tables = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "daily_groups" in tables:
            self.conn.execute(
                "INSERT OR IGNORE INTO task_groups (name, sort_order)"
                " SELECT name, sort_order FROM daily_groups"
            )
            self.conn.execute("DROP TABLE daily_groups")
        self.conn.commit()

    def _add_column(self, table: str, column: str, spec: str) -> None:
        columns = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")

    def close(self) -> None:
        self.conn.close()
