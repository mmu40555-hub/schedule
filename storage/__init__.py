"""SQLite 存储层：任务定义、每日完成记录、今日视图生成。

三类任务定义分别存放在 daily_tasks / once_tasks / period_tasks，
首页的「今日一览」不落库，而是每次根据定义 + 当天日期实时推导。
"""

import calendar
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

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

from .helpers import (
    _app_dir,
    _clean_repeat,
    _in_window,
    _moment,
    _month_day,
    _pretty_day,
    _stamp,
)
from .records import (
    DailyTask,
    HistoryEntry,
    Memo,
    OnceTask,
    PeriodStage,
    PeriodTask,
    Reminder,
    _daily,
    _memo,
    _once,
    _period,
    _stage,
)
from .schema import (
    BACKLOG_LOOKBACK,
    BACKLOG_LOOKBACK_DAYS,
    DB_PATH,
    DEFAULT_FLOAT_OPACITY,
    DEFAULT_NEW_NOTE_HOTKEY,
    DEFAULT_REMIND_MINUTES,
    KIND_BACKLOG,
    KIND_BANNER,
    MAX_MEMO_STACK,
    MIN_FLOAT_OPACITY,
    NAV_LEFT,
    NAV_POSITIONS,
    NAV_TOP,
    ONCE_LEAD_DAYS,
    REMIND_AUTO,
    REMIND_BOTH,
    REMIND_MODES,
    REMIND_POPUP,
    SCHEMA,
    SETTING_AUTO_UPDATE,
    SETTING_DEFAULT_REMIND,
    SETTING_FLOAT_OPACITY,
    SETTING_NAV_POSITION,
    SETTING_NEW_NOTE_HOTKEY,
    SETTING_REMIND_MODE,
    SETTING_REMIND_SOUND,
    SETTING_REMIND_SOUND_CHOICE,
    SETTING_REMIND_SOUND_FILES,
    SETTING_UPDATE_LAST,
    SETTING_UPDATE_SKIP,
)
from .store import Store
