from datetime import date, timedelta

from models import (
    BACKLOG_SOURCE_ORDER,
    COL_BACKLOG,
    COL_UNSCHEDULED,
    COL_URGENT,
    REPEAT_DAILY,
    REPEAT_MONTHLY,
    REPEAT_WEEKLY,
    SOURCE_DAILY,
    SOURCE_ONCE,
    SOURCE_PERIOD,
    TodayItem,
)

from .helpers import _month_day, _pretty_day, _stamp
from .records import DailyTask
from .schema import BACKLOG_LOOKBACK, BACKLOG_LOOKBACK_DAYS, KIND_BACKLOG, ONCE_LEAD_DAYS


# 今日一览：实时推导各栏内容、完成/撤销与手动排序。
class TodayMixin:
    # ================= 今日视图 =================

    def today_items(self, today: date | None = None) -> dict[str, list[TodayItem]]:
        today = today or date.today()
        day_str = today.isoformat()

        self._settle_once_tasks(day_str)

        items: dict[str, list[TodayItem]] = {
            COL_URGENT: [],
            COL_UNSCHEDULED: [],
            COL_BACKLOG: [],
        }

        self._collect_daily(items, today)
        self._collect_once(items, today)
        self._collect_period(items, today)

        for column_id, column_items in items.items():
            ordered = self._apply_order(column_id, day_str, column_items)
            if column_id == COL_BACKLOG:
                # 旧账按来源归拢：临时任务 → 时期任务 → 每日任务
                ordered.sort(key=lambda item: BACKLOG_SOURCE_ORDER.get(item.source, 99))
            # 勾完的沉到本栏底部，未完成的始终排在看得见的地方；sort 稳定，不打乱上面的顺序
            ordered.sort(key=lambda item: item.done)
            items[column_id] = ordered
        return items

    def _collect_daily(self, items: dict[str, list[TodayItem]], today: date) -> None:
        for task in self.list_daily_tasks():
            # 今天不是它的日子（每周 / 每月任务）：今日栏不露面，
            # 但漏掉的过往日子照旧进「陈年旧账」，可以补勾
            if not self._occurs_on(task, today):
                items[COL_BACKLOG].extend(self._daily_backlog(task, today))
                continue

            record = self._ensure_daily_record(task, today)
            streak, best_streak = self._daily_streaks(task, today)

            item = TodayItem(
                key=f"{SOURCE_DAILY}:{task.id}",
                title=task.title,
                column=COL_URGENT if task.has_deadline else COL_UNSCHEDULED,
                source=SOURCE_DAILY,
                group=task.group_name,
                due_time=task.deadline_time if task.has_deadline else "",
                streak=streak,
                best_streak=best_streak,
                note=task.note,
                done=bool(record["done"]),
                repeat=task.repeat,
                streak_unit="天" if task.repeat == REPEAT_DAILY else "次",
            )
            items[item.column].append(item)

            # 漏勾的日子进积压栏，可在那里补勾（补勾即算那天有效）或移除
            items[COL_BACKLOG].extend(self._daily_backlog(task, today))

    def _occurs_on(self, task: DailyTask, day: date) -> bool:
        """这个任务在指定那天该不该出现（每天任务恒为真）。"""
        if task.repeat == REPEAT_WEEKLY:
            return day.weekday() == int(task.repeat_day) % 7
        if task.repeat == REPEAT_MONTHLY:
            return day.day == _month_day(day, int(task.repeat_day))
        return True

    def _occurrences(self, task: DailyTask, start: date, end: date) -> list[date]:
        """[start, end] 之间任务应当出现的日子，用来算连续次数。"""
        days: list[date] = []
        day = start
        while day <= end:
            if self._occurs_on(task, day):
                days.append(day)
            day += timedelta(days=1)
        return days

    def _daily_streaks(self, task: DailyTask, today: date) -> tuple[int, int]:
        """返回 (最新连续完成次数, 历史最高连续完成次数)。

        每天任务按「天」算；每周/每月任务只看它该出现的那几天，按「次」算。
        """
        done_days = {
            row["day"]
            for row in self.conn.execute(
                "SELECT day FROM daily_records WHERE daily_task_id=? AND day<=? AND done=1",
                (task.id, today.isoformat()),
            ).fetchall()
        }
        if not done_days:
            return 0, 0

        first = date.fromisoformat(task.created_day) if task.created_day else today
        start = min(first, date.fromisoformat(min(done_days)))
        occurrences = self._occurrences(task, start, today)

        best = run = 0
        for day in occurrences:
            if day.isoformat() in done_days:
                run += 1
                best = max(best, run)
            elif day != today:
                # 今天还没勾不算中断，补勾后自然接上
                run = 0

        streak = 0
        for day in reversed(occurrences):
            if day.isoformat() in done_days:
                streak += 1
            elif day != today:
                break
        return streak, best

    def _daily_backlog(self, task: DailyTask, today: date) -> list[TodayItem]:
        """任务已存在、但该出现的那天没完成的日子，逐天列出以便日后补勾。"""
        if not task.backlog:
            return []

        start = today - timedelta(days=BACKLOG_LOOKBACK.get(task.repeat, BACKLOG_LOOKBACK_DAYS))
        if task.created_day:
            start = max(start, date.fromisoformat(task.created_day))

        done_map = {
            row["day"]: row["done"]
            for row in self.conn.execute(
                "SELECT day, done FROM daily_records"
                " WHERE daily_task_id=? AND day>=? AND day<?",
                (task.id, start.isoformat(), today.isoformat()),
            ).fetchall()
        }

        result: list[TodayItem] = []
        day = start
        while day < today:
            day_str = day.isoformat()
            # 每周/每月任务只列它该出现的那几天
            if self._occurs_on(task, day) and not done_map.get(day_str):
                key = f"{SOURCE_DAILY}:{task.id}@{day_str}"
                if not self._is_dismissed(key):
                    result.append(
                        TodayItem(
                            key=key,
                            title=task.title,
                            column=COL_BACKLOG,
                            source=SOURCE_DAILY,
                            group=task.group_name,
                            note=task.note,
                            foot=f"{_pretty_day(day_str)} 未完成",
                            done=False,
                            repeat=task.repeat,
                        )
                    )
            day += timedelta(days=1)
        return result

    def _collect_once(self, items: dict[str, list[TodayItem]], today: date) -> None:
        for task in self.list_once_tasks():
            key = f"{SOURCE_ONCE}:{task.id}"

            if task.status == "discarded":
                if self._is_dismissed(key):
                    continue
                items[COL_BACKLOG].append(
                    TodayItem(
                        key=key,
                        title=task.title,
                        column=COL_BACKLOG,
                        source=SOURCE_ONCE,
                        group=task.group_name,
                        note=task.note,
                        foot=f"{_pretty_day(task.day)} 未完成，临时任务已弃置",
                        done=False,
                    )
                )
                continue

            due_in = (date.fromisoformat(task.day) - today).days

            # 完成过的临时任务只在当天留着（标题画着横线），次日起不再露面
            if task.status == "done" and due_in < 0:
                continue

            if due_in > 0:
                # 还没到期：勾了「每天显示」的马上上桌，没勾的等倒数三天；
                # 提前显示只是提醒，要等到期当天才能打勾
                if not task.always_show and due_in > ONCE_LEAD_DAYS:
                    continue
                column = COL_UNSCHEDULED
                foot = f"{_pretty_day(task.day)} 到期"
            else:
                column = COL_URGENT
                foot = ""

            items[column].append(
                TodayItem(
                    key=key,
                    title=task.title,
                    column=column,
                    source=SOURCE_ONCE,
                    group=task.group_name,
                    locked=due_in > 0,
                    due_time=task.time,
                    note=task.note,
                    foot=foot,
                    done=task.status == "done",
                )
            )

    def _collect_period(self, items: dict[str, list[TodayItem]], today: date) -> None:
        for task in self.list_period_tasks():
            stages = self.list_stages(task.id)
            pending = [s for s in stages if not s.done]

            if not pending:
                self._archive_period_task(task.id)
                continue

            stage = pending[0]
            stage_index = stages.index(stage) + 1
            days = (date.fromisoformat(stage.deadline) - today).days

            if days > 0:
                column = COL_UNSCHEDULED
                time_text = f"剩 {days} 天"
            else:
                column = COL_URGENT
                time_text = "今日截止" if days == 0 else f"已逾期 {-days} 天"

            foot = f"阶段 {stage_index}/{len(stages)}：{stage.title}"
            if len(stages) == 1:
                foot = f"最终期限 {_pretty_day(task.deadline)}"

            items[column].append(
                TodayItem(
                    key=f"{SOURCE_PERIOD}:{task.id}",
                    title=task.title,
                    column=column,
                    source=SOURCE_PERIOD,
                    group=task.group_name,
                    time_text=time_text,
                    note=task.note,
                    foot=foot,
                    done=False,
                    # 已经完成过阶段才谈得上回退
                    step_back=any(s.done for s in stages),
                )
            )

    # ================= 完成 / 撤销 =================

    def set_item_done(self, key: str, done: bool, today: date | None = None) -> None:
        today = today or date.today()
        kind, _, rest = key.partition(":")

        if kind == SOURCE_DAILY:
            task_id, _, day = rest.partition("@")
            target_day = day or today.isoformat()
            if self.get_daily_task(int(task_id)) is None:
                return
            self.conn.execute(
                "INSERT INTO daily_records (daily_task_id, day, done) VALUES (?,?,?)"
                " ON CONFLICT(daily_task_id, day) DO UPDATE SET done=excluded.done",
                (int(task_id), target_day, int(done)),
            )
            self.conn.commit()

        elif kind == SOURCE_ONCE:
            self.conn.execute(
                "UPDATE once_tasks SET status=?, done_at=? WHERE id=?",
                ("done" if done else "pending", _stamp() if done else "", int(rest)),
            )
            self.conn.commit()

        elif kind == SOURCE_PERIOD:
            task_id = int(rest)
            stages = self.list_stages(task_id)
            pending = [s for s in stages if not s.done]
            if done:
                if pending:
                    self.conn.execute(
                        "UPDATE period_stages SET done=1 WHERE id=?", (pending[0].id,)
                    )
            else:
                done_stages = [s for s in stages if s.done]
                if done_stages:
                    self.conn.execute(
                        "UPDATE period_stages SET done=0 WHERE id=?", (done_stages[-1].id,)
                    )
            self.conn.commit()
            self._sync_period_done(task_id)

    def dismiss_item(self, key: str, kind: str = KIND_BACKLOG) -> None:
        """kind 区分「不再提醒的横幅」与「不再保留的积压项」，两者互不影响。"""
        self.conn.execute(
            "INSERT OR REPLACE INTO dismissals (item_key, kind) VALUES (?,?)",
            (key, kind),
        )
        self.conn.commit()

    def _is_dismissed(self, key: str, kind: str = KIND_BACKLOG) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM dismissals WHERE item_key=? AND kind=?", (key, kind)
        ).fetchone()
        return row is not None

    # ================= 排序 =================

    def save_order(self, column_id: str, keys: list[str], today: date | None = None) -> None:
        day_str = (today or date.today()).isoformat()
        self.conn.execute(
            "DELETE FROM today_order WHERE day=? AND column_id=?", (day_str, column_id)
        )
        for position, key in enumerate(keys):
            self.conn.execute(
                "INSERT INTO today_order (day, column_id, item_key, position)"
                " VALUES (?,?,?,?)",
                (day_str, column_id, key, position),
            )
        self.conn.commit()

    def _apply_order(self, column_id: str, day_str: str,
                     items: list[TodayItem]) -> list[TodayItem]:
        rows = self.conn.execute(
            "SELECT item_key FROM today_order WHERE day=? AND column_id=? ORDER BY position",
            (day_str, column_id),
        ).fetchall()
        if not rows:
            return items

        index = {r["item_key"]: i for i, r in enumerate(rows)}
        fallback = len(index)
        return sorted(items, key=lambda item: index.get(item.key, fallback))
