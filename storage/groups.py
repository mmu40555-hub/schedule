# 组别：三类任务共用的分组名登记与增删改。
class GroupMixin:
    def groups(self) -> list[str]:
        """全部组别名（不含未归组）：已登记的组别在前，任务里出现过但未登记的补在后面。"""
        names = [r["name"] for r in self.conn.execute(
            "SELECT name FROM task_groups ORDER BY sort_order, name"
        ).fetchall()]
        known = set(names)
        for name in self._used_groups():
            if name and name not in known:
                known.add(name)
                names.append(name)
        return names

    def _used_groups(self) -> list[str]:
        """三类任务里被实际使用过的组名。"""
        names: list[str] = []
        for table in ("daily_tasks", "once_tasks", "period_tasks"):
            rows = self.conn.execute(
                f"SELECT DISTINCT group_name FROM {table} WHERE group_name <> ''"
            ).fetchall()
            names.extend(r["group_name"] for r in rows)
        return names

    def create_group(self, name: str) -> None:
        """新建一个组别（暂时没有任务也可以存在）。"""
        self._ensure_group(name)
        self.conn.commit()

    def rename_group(self, old: str, new: str) -> None:
        """改组名；新名字已被占用时，两组并成一组。"""
        if not old or not new or old == new:
            return
        self._move_group(old, new)
        self.conn.execute("DELETE FROM task_groups WHERE name=?", (old,))
        self._ensure_group(new)
        self.conn.commit()

    def delete_group(self, name: str) -> None:
        """删除组别，组内任务移到「未归组」，任务本身与完成记录都保留。"""
        self._move_group(name, "")
        self.conn.execute("DELETE FROM task_groups WHERE name=?", (name,))
        self.conn.commit()

    def purge_group(self, name: str) -> int:
        """删除组别并连带删掉组内的所有任务（含完成记录、阶段），返回删掉的任务数。"""
        if not name:
            return 0
        removed = 0
        for table, delete in (
            ("daily_tasks", self.delete_daily_task),
            ("once_tasks", self.delete_once_task),
            ("period_tasks", self.delete_period_task),
        ):
            rows = self.conn.execute(
                f"SELECT id FROM {table} WHERE group_name=?", (name,)
            ).fetchall()
            for row in rows:
                delete(row["id"])
                removed += 1
        self.conn.execute("DELETE FROM task_groups WHERE name=?", (name,))
        self.conn.commit()
        return removed

    def _move_group(self, old: str, new: str) -> None:
        for table in ("daily_tasks", "once_tasks", "period_tasks"):
            self.conn.execute(
                f"UPDATE {table} SET group_name=? WHERE group_name=?", (new, old)
            )

    def _ensure_group(self, name: str) -> None:
        """把任务里出现的组名登记成正式组别，便于排序与删除。"""
        if not name:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO task_groups (name, sort_order) VALUES (?,?)",
            (name, self._next_order("task_groups")),
        )
