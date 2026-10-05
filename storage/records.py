import sqlite3
from dataclasses import dataclass
from datetime import datetime

from models import REPEAT_DAILY

from .schema import DEFAULT_REMIND_MINUTES


# ---------------- 实体 ----------------

@dataclass
class DailyTask:
    id: int
    title: str
    group_name: str = ""
    has_deadline: bool = False
    deadline_time: str = ""
    note: str = ""
    backlog: bool = True          # 未完成时是否进「陈年旧账」
    created_day: str = ""
    sort_order: int = 0
    remind_minutes: int = DEFAULT_REMIND_MINUTES   # 截止前几分钟提醒
    repeat: str = REPEAT_DAILY    # 重复周期：每天 / 每周 / 每月
    repeat_day: int = 0           # 每周→星期几(0~6)，每月→几号(1~31)，每天忽略


@dataclass
class OnceTask:
    id: int
    title: str
    day: str
    time: str = ""
    note: str = ""
    status: str = "pending"
    always_show: bool = False     # 每天都显示；否则只在到期前三天出现
    sort_order: int = 0
    group_name: str = ""
    remind_minutes: int = DEFAULT_REMIND_MINUTES   # 到点前几分钟提醒
    done_at: str = ""             # 完成时刻，形如 2026-07-07 15:04:05；没完成是空串


@dataclass
class PeriodTask:
    id: int
    title: str
    deadline: str
    note: str = ""
    archived: bool = False
    sort_order: int = 0
    group_name: str = ""
    done_at: str = ""             # 所有阶段做完才算完成，记下那一刻


@dataclass
class PeriodStage:
    id: int
    period_task_id: int
    title: str
    deadline: str
    done: bool = False
    sort_order: int = 0


@dataclass
class Reminder:
    """一条待提醒的时限任务。"""

    key: str              # 与今日一览一致的 item_key，用于去重与联动
    title: str
    due_at: datetime      # 到点时刻
    source: str
    remind_minutes: int   # 提前量，用于文案「N 分钟后」
    group_name: str = ""
    note: str = ""

    @property
    def minutes_left(self) -> int:
        delta = (self.due_at - datetime.now()).total_seconds()
        return max(0, int(delta // 60))


@dataclass
class HistoryEntry:
    """历史汇总里的一条：一个完成过的任务。

    长期每日任务不进历史，所以这里只有临时任务与时期任务。
    """

    key: str            # 与今日一览一致的 item_key
    title: str
    source: str
    group: str = ""
    note: str = ""
    done_at: str = ""   # 完成时刻；老数据没这个字段，为空
    plan: str = ""      # 任务的计划日期 / 最终期限，完成时刻缺失时拿它排序

    @property
    def sort_key(self) -> str:
        """排序用的时间：优先真实的完成时刻，老数据退回计划日期。"""
        return self.done_at or self.plan


@dataclass
class Memo:
    """一张便签：位置自由，内容即文本，同摞的共享一个 stack_id。"""

    id: int
    content: str = ""
    x: int = 0
    y: int = 0
    stack_id: int = 0       # 0 表示单独一张；同号的叠成一摞
    stack_order: int = 0    # 摞内编号，页签序号就按它排，进摞后不再变动
    stack_active: int = 1   # 1 表示这一摞当前露在外面的就是这张
    pinned: int = 0         # 1 表示钉在桌面上（独立小窗），0 表示躺在备忘录页面里
    # 钉在某个程序窗口上时，记下那个窗口是谁：类名 + 标题用于下次开程序时把它找回来，
    # dx / dy 是便签左上角相对该窗口左上角的距离，窗口一动就照这个把它带过去
    host_class: str = ""
    host_title: str = ""
    host_dx: int = 0
    host_dy: int = 0
    updated_day: str = ""
    discarded_at: str = ""   # 丢弃时刻；非空表示躺在「废弃栏」里，不再出现在备忘录页面


def _memo(row: sqlite3.Row) -> Memo:
    return Memo(
        id=row["id"],
        content=row["content"],
        x=row["x"],
        y=row["y"],
        stack_id=row["stack_id"],
        stack_order=row["stack_order"],
        stack_active=row["stack_active"],
        pinned=row["pinned"],
        host_class=row["host_class"],
        host_title=row["host_title"],
        host_dx=row["host_dx"],
        host_dy=row["host_dy"],
        updated_day=row["updated_day"],
        discarded_at=row["discarded_at"],
    )


def _daily(row: sqlite3.Row) -> DailyTask:
    return DailyTask(
        id=row["id"],
        title=row["title"],
        group_name=row["group_name"],
        has_deadline=bool(row["has_deadline"]),
        deadline_time=row["deadline_time"],
        note=row["note"],
        backlog=bool(row["backlog"]),
        created_day=row["created_day"],
        sort_order=row["sort_order"],
        remind_minutes=row["remind_minutes"],
        repeat=row["repeat"],
        repeat_day=row["repeat_day"],
    )


def _once(row: sqlite3.Row) -> OnceTask:
    return OnceTask(
        id=row["id"],
        title=row["title"],
        day=row["day"],
        time=row["time"],
        note=row["note"],
        status=row["status"],
        always_show=bool(row["always_show"]),
        sort_order=row["sort_order"],
        group_name=row["group_name"],
        remind_minutes=row["remind_minutes"],
        done_at=row["done_at"],
    )


def _period(row: sqlite3.Row) -> PeriodTask:
    return PeriodTask(
        id=row["id"],
        title=row["title"],
        deadline=row["deadline"],
        note=row["note"],
        archived=bool(row["archived"]),
        sort_order=row["sort_order"],
        group_name=row["group_name"],
        done_at=row["done_at"],
    )


def _stage(row: sqlite3.Row) -> PeriodStage:
    return PeriodStage(
        id=row["id"],
        period_task_id=row["period_task_id"],
        title=row["title"],
        deadline=row["deadline"],
        done=bool(row["done"]),
        sort_order=row["sort_order"],
    )
