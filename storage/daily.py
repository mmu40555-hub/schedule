import sqlite3
from datetime import date

from models import REPEAT_DAILY

from .helpers import _clean_repeat
from .records import DailyTask, _daily
from .schema import DEFAULT_REMIND_MINUTES


# 长期每日任务：定义、增删改与单日完成记录的读写。
class DailyMixin:
    # ================= 长期每日任务 =================

    def list_daily_tasks(self) -> list[DailyTask]:
        rows = self.conn.execute(
            "SELECT * FROM daily_tasks ORDER BY sort_order, id"
        ).fetchall()
        return [_daily(r) for r in rows]

    def create_daily_task(self, title: str, group_name: str = "", has_deadline: bool = False,
                          deadline_time: str = "", note: str = "",
                          created_day: str | None = None, backlog: bool = True,
                          remind_minutes: int = DEFAULT_REMIND_MINUTES,
                          repeat: str = REPEAT_DAILY, repeat_day: int = 0) -> int:
        order = self._next_order("daily_tasks")
        cursor = self.conn.execute(
            "INSERT INTO daily_tasks (title, group_name, has_deadline, deadline_time,"
            " remind_minutes, note, created_day, backlog, repeat, repeat_day, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (title, group_name, int(has_deadline), deadline_time,
             int(remind_minutes), note, created_day or date.today().isoformat(),
             int(backlog), _clean_repeat(repeat), int(repeat_day), order),
        )
        self._ensure_group(group_name)
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_daily_task(self, task_id: int, title: str, group_name: str = "",
                          has_deadline: bool = False, deadline_time: str = "",
                          note: str = "", backlog: bool = True,
                          remind_minutes: int = DEFAULT_REMIND_MINUTES,
                          repeat: str = REPEAT_DAILY, repeat_day: int = 0) -> None:
        self.conn.execute(
            "UPDATE daily_tasks SET title=?, group_name=?, has_deadline=?, deadline_time=?,"
            " remind_minutes=?, note=?, backlog=?, repeat=?, repeat_day=? WHERE id=?",
            (title, group_name, int(has_deadline), deadline_time, int(remind_minutes),
             note, int(backlog), _clean_repeat(repeat), int(repeat_day), task_id),
        )
        self._ensure_group(group_name)
        self.conn.commit()

    def delete_daily_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM daily_tasks WHERE id=?", (task_id,))
        self.conn.execute("DELETE FROM daily_records WHERE daily_task_id=?", (task_id,))
        self.conn.commit()

    # ================= 内部工具 =================

    def get_daily_task(self, task_id: int) -> DailyTask | None:
        row = self.conn.execute(
            "SELECT * FROM daily_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return _daily(row) if row else None

    def _get_daily_record(self, task_id: int, day_str: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM daily_records WHERE daily_task_id=? AND day=?",
            (task_id, day_str),
        ).fetchone()

    def _ensure_daily_record(self, task: DailyTask, today: date) -> sqlite3.Row:
        day_str = today.isoformat()
        record = self._get_daily_record(task.id, day_str)
        if record is not None:
            return record

        self.conn.execute(
            "INSERT INTO daily_records (daily_task_id, day, done) VALUES (?,?,0)",
            (task.id, day_str),
        )
        self.conn.commit()
        return self._get_daily_record(task.id, day_str)
