"""首页栏目常量、任务来源常量与今日卡片数据结构。

这里只放纯数据描述，不碰数据库，也不碰 UI。
"""

from dataclasses import dataclass

# ---------------- 首页三栏 ----------------

COL_URGENT = "urgent"            # 刻不容缓：有明确截止时间
COL_UNSCHEDULED = "unscheduled"  # 案无留牍：无截止时间，今日须完成
COL_BACKLOG = "backlog"          # 陈年旧账：历史未完成

COLUMN_ORDER = [COL_URGENT, COL_UNSCHEDULED, COL_BACKLOG]

COLUMN_TITLE = {
    COL_URGENT: "刻不容缓",
    COL_UNSCHEDULED: "案无留牍",
    COL_BACKLOG: "陈年旧账",
}

COLUMN_SUBTITLE = {
    COL_URGENT: "有截止时间，到点必交付",
    COL_UNSCHEDULED: "无固定时点，今日须了结",
    COL_BACKLOG: "往期未竟之事，可清可留",
}

# ---------------- 任务来源 ----------------

SOURCE_DAILY = "daily"    # 长期每日任务
SOURCE_ONCE = "once"      # 某日临时任务
SOURCE_PERIOD = "period"  # 时期任务

SOURCE_LABEL = {
    SOURCE_DAILY: "每日",
    SOURCE_ONCE: "临时",
    SOURCE_PERIOD: "时期",
}

# 「陈年旧账」栏里按来源归拢：临时任务 → 时期任务 → 每日任务
BACKLOG_SOURCE_ORDER = {
    SOURCE_ONCE: 0,
    SOURCE_PERIOD: 1,
    SOURCE_DAILY: 2,
}

# 没有归属分组的任务，在首页归到这一组里显示
UNGROUPED_LABEL = "未归组"

# ---------------- 临时任务状态 ----------------

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_DISCARDED = "discarded"

STATUS_LABEL = {
    STATUS_PENDING: "待办",
    STATUS_DONE: "已完成",
    STATUS_DISCARDED: "已弃置",
}


@dataclass
class TodayItem:
    """首页卡片的数据快照。由 storage 按当天日期实时推导。"""

    key: str                        # 形如 daily:3 或 daily:3@2026-07-07
    title: str
    column: str
    source: str
    group: str = ""                 # 归属分组，空串表示未归组
    locked: bool = False            # 到期前不允许打勾（临时任务）
    due_time: str = ""              # 具体截止时点，如 15:00
    time_text: str = ""             # 倒计时类文案，如「剩 12 天」
    streak: int = 0                 # 最新连续完成次数
    best_streak: int = 0            # 历史最高连续完成次数
    note: str = ""
    foot: str = ""                  # 卡片底部小字
    done: bool = False
    step_back: bool = False         # 时期任务已完成过阶段时，卡片上给出「返回上一阶段」

    @property
    def time_display(self) -> str:
        if self.due_time:
            return f"截止 {self.due_time}"
        return self.time_text

    @property
    def streak_text(self) -> str:
        """只有今天的每日任务卡片展示连续次数，积压项不展示。"""
        if self.source != SOURCE_DAILY or self.column == COL_BACKLOG:
            return ""
        return f"连续 {self.streak} 天 · 最长 {self.best_streak} 天"
