from models import SOURCE_ONCE, SOURCE_PERIOD

from .records import HistoryEntry


# 历史汇总：列出完成过的临时任务与时期任务。
class HistoryMixin:
    # ================= 历史汇总 =================

    def completed_history(self) -> list[HistoryEntry]:
        """完成过的任务，按时间倒序（最近完成的排最前）。

        长期每日任务不进这里；时期任务要所有阶段都做完才算完成。
        老数据的完成时刻是空的，那时就退回任务自己的日期 / 期限参与排序。
        """
        entries: list[HistoryEntry] = []
        for row in self.conn.execute(
            "SELECT id, title, group_name, note, day AS plan, done_at"
            " FROM once_tasks WHERE status='done'"
        ).fetchall():
            entries.append(HistoryEntry(
                key=f"{SOURCE_ONCE}:{row['id']}",
                title=row["title"],
                source=SOURCE_ONCE,
                group=row["group_name"],
                note=row["note"],
                done_at=row["done_at"],
                plan=row["plan"],
            ))
        for row in self.conn.execute(
            "SELECT id, title, group_name, note, deadline AS plan, done_at"
            " FROM period_tasks WHERE archived=1"
        ).fetchall():
            entries.append(HistoryEntry(
                key=f"{SOURCE_PERIOD}:{row['id']}",
                title=row["title"],
                source=SOURCE_PERIOD,
                group=row["group_name"],
                note=row["note"],
                done_at=row["done_at"],
                plan=row["plan"],
            ))
        entries.sort(key=lambda item: item.sort_key, reverse=True)
        return entries
