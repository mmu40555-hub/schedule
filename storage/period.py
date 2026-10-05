from .helpers import _stamp
from .records import PeriodStage, PeriodTask, _period, _stage


# 时期任务：阶段列表与整体完成归档。
class PeriodMixin:
    # ================= 时期任务 =================

    def list_period_tasks(self, include_archived: bool = False) -> list[PeriodTask]:
        sql = "SELECT * FROM period_tasks"
        if not include_archived:
            sql += " WHERE archived=0"
        sql += " ORDER BY deadline, id"
        return [_period(r) for r in self.conn.execute(sql).fetchall()]

    def list_stages(self, period_task_id: int) -> list[PeriodStage]:
        rows = self.conn.execute(
            "SELECT * FROM period_stages WHERE period_task_id=?"
            " ORDER BY deadline, sort_order, id",
            (period_task_id,),
        ).fetchall()
        return [_stage(r) for r in rows]

    def create_period_task(self, title: str, deadline: str, note: str = "",
                           stages: list[tuple[str, str]] | None = None,
                           group_name: str = "") -> int:
        order = self._next_order("period_tasks")
        cursor = self.conn.execute(
            "INSERT INTO period_tasks (title, group_name, deadline, note, archived,"
            " sort_order) VALUES (?,?,?,?,0,?)",
            (title, group_name, deadline, note, order),
        )
        task_id = int(cursor.lastrowid)
        self._insert_stages(task_id, stages or [])
        self._ensure_group(group_name)
        self.conn.commit()
        return task_id

    def update_period_task(self, task_id: int, title: str, deadline: str, note: str = "",
                           stages: list[tuple[str, str]] | None = None,
                           stage_done: list[bool] | None = None,
                           group_name: str = "") -> None:
        self.conn.execute(
            "UPDATE period_tasks SET title=?, group_name=?, deadline=?, note=? WHERE id=?",
            (title, group_name, deadline, note, task_id),
        )
        self.conn.execute("DELETE FROM period_stages WHERE period_task_id=?", (task_id,))
        self._insert_stages(task_id, stages or [], stage_done)
        self._ensure_group(group_name)
        self.conn.commit()

    def delete_period_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM period_tasks WHERE id=?", (task_id,))
        self.conn.execute("DELETE FROM period_stages WHERE period_task_id=?", (task_id,))
        self.conn.commit()

    def _insert_stages(self, period_task_id: int, stages: list[tuple[str, str]],
                       done_flags: list[bool] | None = None) -> None:
        for index, (title, deadline) in enumerate(stages):
            done = bool(done_flags[index]) if done_flags and index < len(done_flags) else False
            self.conn.execute(
                "INSERT INTO period_stages (period_task_id, title, deadline, done, sort_order)"
                " VALUES (?,?,?,?,?)",
                (period_task_id, title, deadline, int(done), index),
            )

    def _archive_period_task(self, task_id: int) -> None:
        """推导今日一览时发现阶段都做完了：归档并补上完成时刻。"""
        self._sync_period_done(task_id)

    def _sync_period_done(self, task_id: int) -> None:
        """时期任务的完成与否看阶段：全做完就归档并记下完成时刻，退回一步就复活。

        完成时刻只在第一次完成时写下，之后来回勾不会把历史里的时间改来改去。
        """
        stages = self.list_stages(task_id)
        complete = all(stage.done for stage in stages)
        row = self.conn.execute(
            "SELECT done_at FROM period_tasks WHERE id=?", (int(task_id),)
        ).fetchone()
        if row is None:
            return
        if complete:
            if not row["done_at"]:
                self.conn.execute(
                    "UPDATE period_tasks SET archived=1, done_at=? WHERE id=?",
                    (_stamp(), int(task_id)),
                )
        else:
            # 退回阶段后任务重新变成未完成，得让它回到今日一览，也别留在历史里
            self.conn.execute(
                "UPDATE period_tasks SET archived=0, done_at='' WHERE id=?",
                (int(task_id),),
            )
        self.conn.commit()
