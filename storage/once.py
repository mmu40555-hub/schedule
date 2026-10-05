from models import SOURCE_ONCE

from .records import OnceTask, _once
from .schema import DEFAULT_REMIND_MINUTES, KIND_BANNER


# 某日临时任务：临期/过期弃置与增删改。
class OnceMixin:
    # ================= 某日临时任务 =================

    def list_once_tasks(self) -> list[OnceTask]:
        rows = self.conn.execute(
            "SELECT * FROM once_tasks ORDER BY day, time, id"
        ).fetchall()
        return [_once(r) for r in rows]

    def create_once_task(self, title: str, day: str, time_text: str = "",
                         note: str = "", always_show: bool = False,
                         group_name: str = "",
                         remind_minutes: int = DEFAULT_REMIND_MINUTES) -> int:
        order = self._next_order("once_tasks")
        cursor = self.conn.execute(
            "INSERT INTO once_tasks (title, group_name, day, time, remind_minutes, note,"
            " status, always_show, sort_order) VALUES (?,?,?,?,?,?, 'pending', ?, ?)",
            (title, group_name, day, time_text, int(remind_minutes), note,
             int(always_show), order),
        )
        self._ensure_group(group_name)
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_once_task(self, task_id: int, title: str, day: str, time_text: str = "",
                         note: str = "", always_show: bool = False,
                         group_name: str = "",
                         remind_minutes: int = DEFAULT_REMIND_MINUTES) -> None:
        self.conn.execute(
            "UPDATE once_tasks SET title=?, group_name=?, day=?, time=?, remind_minutes=?,"
            " note=?, always_show=? WHERE id=?",
            (title, group_name, day, time_text, int(remind_minutes), note,
             int(always_show), task_id),
        )
        self._ensure_group(group_name)
        self.conn.commit()

    def delete_once_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM once_tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def discarded_once_tasks(self) -> list[OnceTask]:
        """被弃置、且用户还没处理过的临时任务，用于首页横幅提醒。"""
        rows = self.conn.execute(
            "SELECT * FROM once_tasks WHERE status='discarded' ORDER BY day DESC"
        ).fetchall()
        result = []
        for row in rows:
            task = _once(row)
            if self._is_dismissed(f"{SOURCE_ONCE}:{task.id}", KIND_BANNER):
                continue
            result.append(task)
        return result

    def _settle_once_tasks(self, day_str: str) -> None:
        """过期未完成的临时任务按设计直接弃置。"""
        self.conn.execute(
            "UPDATE once_tasks SET status='discarded'"
            " WHERE status='pending' AND day < ?",
            (day_str,),
        )
        self.conn.commit()
