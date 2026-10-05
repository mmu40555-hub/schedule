from datetime import datetime

from models import SOURCE_DAILY, SOURCE_ONCE

from .helpers import _in_window, _moment
from .records import Reminder


# 到点提醒：挑选进入提醒窗口的任务并记录已弹过。
class RemindMixin:
    # ================= 到点提醒 =================

    def due_reminders(self, now: datetime | None = None) -> list[Reminder]:
        """进入提醒窗口、且今天还没提醒过的未完成时限任务。

        每日任务看「截止时间」，临时任务看当天「具体时间」；
        各自的提前量由 remind_minutes 决定（默认 10 分钟）。
        """
        now = now or datetime.now()
        today = now.date()
        day_str = today.isoformat()

        fired = {
            row["item_key"]
            for row in self.conn.execute(
                "SELECT item_key FROM reminder_log WHERE day=?", (day_str,)
            ).fetchall()
        }

        result: list[Reminder] = []
        for task in self.list_daily_tasks():
            if not task.has_deadline or not task.deadline_time:
                continue
            key = f"{SOURCE_DAILY}:{task.id}"
            if key in fired:
                continue
            record = self._get_daily_record(task.id, day_str)
            if record is not None and record["done"]:
                continue
            due_at = _moment(day_str, task.deadline_time)
            if _in_window(now, due_at, task.remind_minutes):
                result.append(
                    Reminder(key, task.title, due_at, SOURCE_DAILY,
                             task.remind_minutes, task.group_name, task.note)
                )

        for task in self.list_once_tasks():
            if task.status != "pending" or task.day != day_str or not task.time:
                continue
            key = f"{SOURCE_ONCE}:{task.id}"
            if key in fired:
                continue
            due_at = _moment(day_str, task.time)
            if _in_window(now, due_at, task.remind_minutes):
                result.append(
                    Reminder(key, task.title, due_at, SOURCE_ONCE,
                             task.remind_minutes, task.group_name, task.note)
                )

        result.sort(key=lambda item: item.due_at)
        return result

    def mark_reminded(self, keys: list[str], now: datetime | None = None) -> None:
        """记下今天已经弹过提醒的任务，避免反复打扰。"""
        day_str = (now or datetime.now()).date().isoformat()
        for key in keys:
            self.conn.execute(
                "INSERT OR IGNORE INTO reminder_log (item_key, day) VALUES (?,?)",
                (key, day_str),
            )
        # 顺手清掉过期记录，表不会无限长大
        self.conn.execute("DELETE FROM reminder_log WHERE day < ?", (day_str,))
        self.conn.commit()
