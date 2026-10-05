import calendar
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from models import REPEAT_DAILY, REPEAT_MONTHLY, REPEAT_WEEKLY


def _app_dir() -> Path:
    """打包成 exe 后 __file__ 指向临时解包目录，数据文件要落在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 本文件在 storage/ 包内，往上退一级才是程序目录
    return Path(__file__).resolve().parent.parent


def _clean_repeat(repeat: str) -> str:
    """校验重复周期，非法的落回「每天」。"""
    if repeat in (REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_MONTHLY):
        return repeat
    return REPEAT_DAILY


def _stamp() -> str:
    """当前时刻，形如 2026-07-07 15:04:05；完成时间与丢弃时间都用它。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _month_day(day: date, repeat_day: int) -> int:
    """每月任务的「几号」：超过当月天数就落到当月最后一天（如 2 月记 31 号时算 28/29 号）。"""
    last = calendar.monthrange(day.year, day.month)[1]
    return min(max(1, int(repeat_day)), last)


def _pretty_day(day_str: str) -> str:
    """把 2026-07-08 变成 7/8。"""
    try:
        parsed = date.fromisoformat(day_str)
    except ValueError:
        return day_str
    return f"{parsed.month}/{parsed.day}"


def _moment(day_str: str, hhmm: str) -> datetime:
    """把 2026-09-22 与 15:00 合成一个 datetime。"""
    hour, minute = (int(part) for part in hhmm.split(":")[:2])
    return datetime.combine(date.fromisoformat(day_str), time(hour, minute))


def _in_window(now: datetime, due_at: datetime, lead_minutes: int) -> bool:
    """是否已进入「到点前 lead_minutes 分钟」的提醒窗口；0 表示不提醒。"""
    if lead_minutes <= 0:
        return False
    return due_at - timedelta(minutes=lead_minutes) <= now <= due_at
