"""SQLite 存储层：任务定义、每日完成记录、今日视图生成。

三类任务定义分别存放在 daily_tasks / once_tasks / period_tasks，
首页的「今日一览」不落库，而是每次根据定义 + 当天日期实时推导。
"""

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
    SOURCE_DAILY,
    SOURCE_ONCE,
    SOURCE_PERIOD,
    TodayItem,
)


def _app_dir() -> Path:
    """打包成 exe 后 __file__ 指向临时解包目录，数据文件要落在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DB_PATH = _app_dir() / "schedule.db"

# 历史未完成记录最多回溯多少天（避免积压栏被陈年数据淹没）
BACKLOG_LOOKBACK_DAYS = 7

# 没勾「每天显示」的临时任务，只在到期前这几天开始出现在首页
ONCE_LEAD_DAYS = 3

# 有时限的任务默认提前多久提醒（分钟），可逐条改
DEFAULT_REMIND_MINUTES = 10

# 忽略记录的类型：不再保留的积压项 / 不再提醒的横幅
KIND_BACKLOG = "backlog"
KIND_BANNER = "banner"

# 悬浮窗透明度（0.30 ~ 1.0）持久化用的设置键
SETTING_FLOAT_OPACITY = "float_opacity"
DEFAULT_FLOAT_OPACITY = 0.9
# 再低就找不着那个调整按钮了，所以卡在 30%
MIN_FLOAT_OPACITY = 0.30

# 设置项：新任务默认提前多久提醒 / 到点提醒的弹出方式
SETTING_DEFAULT_REMIND = "default_remind_minutes"
SETTING_REMIND_MODE = "remind_mode"

# 到点提醒要不要响一声系统提示音
SETTING_REMIND_SOUND = "remind_sound"

# 用哪个音频提醒："alias:系统音别名" 或 "file:本地音频路径"
SETTING_REMIND_SOUND_CHOICE = "remind_sound_choice"
# 用户添加过的本地音频文件，换行分隔
SETTING_REMIND_SOUND_FILES = "remind_sound_files"

# 主导航放顶部还是左侧
SETTING_NAV_POSITION = "nav_position"
NAV_TOP = "top"
NAV_LEFT = "left"
NAV_POSITIONS = [
    (NAV_TOP, "顶部横向导航"),
    (NAV_LEFT, "左侧竖向导航"),
]

# 一摞便签最多叠几张
MAX_MEMO_STACK = 5

REMIND_AUTO = "auto"     # 有悬浮窗就在悬浮窗内提示，否则弹置底小窗
REMIND_POPUP = "popup"   # 只用置底小窗
REMIND_BOTH = "both"     # 两处都提示

REMIND_MODES = [
    (REMIND_AUTO, "自动：有悬浮窗就在窗内提示，否则弹置底小窗"),
    (REMIND_POPUP, "只用置底小窗"),
    (REMIND_BOTH, "两处都提示：悬浮窗 + 置底小窗"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    group_name    TEXT    NOT NULL DEFAULT '',
    has_deadline  INTEGER NOT NULL DEFAULT 0,
    deadline_time TEXT    NOT NULL DEFAULT '',
    remind_minutes INTEGER NOT NULL DEFAULT 10,
    note          TEXT    NOT NULL DEFAULT '',
    backlog       INTEGER NOT NULL DEFAULT 1,
    created_day   TEXT    NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_records (
    daily_task_id INTEGER NOT NULL,
    day           TEXT    NOT NULL,
    done          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (daily_task_id, day)
);

CREATE TABLE IF NOT EXISTS once_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    group_name TEXT    NOT NULL DEFAULT '',
    day        TEXT    NOT NULL,
    time       TEXT    NOT NULL DEFAULT '',
    remind_minutes INTEGER NOT NULL DEFAULT 10,
    note       TEXT    NOT NULL DEFAULT '',
    status     TEXT    NOT NULL DEFAULT 'pending',
    always_show INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS period_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    group_name TEXT    NOT NULL DEFAULT '',
    deadline   TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS period_stages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    period_task_id INTEGER NOT NULL,
    title          TEXT    NOT NULL,
    deadline       TEXT    NOT NULL,
    done           INTEGER NOT NULL DEFAULT 0,
    sort_order     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dismissals (
    item_key TEXT NOT NULL,
    kind     TEXT NOT NULL,
    PRIMARY KEY (item_key, kind)
);

CREATE TABLE IF NOT EXISTS today_order (
    day      TEXT    NOT NULL,
    column_id TEXT   NOT NULL,
    item_key TEXT    NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (day, column_id, item_key)
);

CREATE TABLE IF NOT EXISTS task_groups (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS reminder_log (
    item_key TEXT NOT NULL,
    day      TEXT NOT NULL,
    PRIMARY KEY (item_key, day)
);

CREATE TABLE IF NOT EXISTS memos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL DEFAULT '',
    x           INTEGER NOT NULL DEFAULT 0,
    y           INTEGER NOT NULL DEFAULT 0,
    stack_id    INTEGER NOT NULL DEFAULT 0,
    stack_order INTEGER NOT NULL DEFAULT 0,
    stack_active INTEGER NOT NULL DEFAULT 1,
    pinned      INTEGER NOT NULL DEFAULT 0,
    updated_day TEXT    NOT NULL DEFAULT ''
);
"""


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


@dataclass
class PeriodTask:
    id: int
    title: str
    deadline: str
    note: str = ""
    archived: bool = False
    sort_order: int = 0
    group_name: str = ""


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
    updated_day: str = ""


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
        updated_day=row["updated_day"],
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


class Store:
    """所有读写都经过这里。UI 层不直接接触 SQL。"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()
        self._seed_if_empty()

    def _migrate(self) -> None:
        """给旧库补上后来新增的列与表（CREATE TABLE IF NOT EXISTS 不会改已有表）。"""
        self._add_column("daily_tasks", "backlog", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("once_tasks", "always_show", "INTEGER NOT NULL DEFAULT 0")
        self._add_column("once_tasks", "group_name", "TEXT NOT NULL DEFAULT ''")
        self._add_column("period_tasks", "group_name", "TEXT NOT NULL DEFAULT ''")
        self._add_column(
            "daily_tasks", "remind_minutes",
            f"INTEGER NOT NULL DEFAULT {DEFAULT_REMIND_MINUTES}",
        )
        self._add_column(
            "once_tasks", "remind_minutes",
            f"INTEGER NOT NULL DEFAULT {DEFAULT_REMIND_MINUTES}",
        )
        self._add_column("memos", "stack_active", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("memos", "pinned", "INTEGER NOT NULL DEFAULT 0")

        # 组别早期只服务于每日任务，表名 daily_groups，现在三类任务共用
        tables = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "daily_groups" in tables:
            self.conn.execute(
                "INSERT OR IGNORE INTO task_groups (name, sort_order)"
                " SELECT name, sort_order FROM daily_groups"
            )
            self.conn.execute("DROP TABLE daily_groups")
        self.conn.commit()

    def _add_column(self, table: str, column: str, spec: str) -> None:
        columns = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")

    def close(self) -> None:
        self.conn.close()

    # ================= 长期每日任务 =================

    def list_daily_tasks(self) -> list[DailyTask]:
        rows = self.conn.execute(
            "SELECT * FROM daily_tasks ORDER BY sort_order, id"
        ).fetchall()
        return [_daily(r) for r in rows]

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

    def create_daily_task(self, title: str, group_name: str = "", has_deadline: bool = False,
                          deadline_time: str = "", note: str = "",
                          created_day: str | None = None, backlog: bool = True,
                          remind_minutes: int = DEFAULT_REMIND_MINUTES) -> int:
        order = self._next_order("daily_tasks")
        cursor = self.conn.execute(
            "INSERT INTO daily_tasks (title, group_name, has_deadline, deadline_time,"
            " remind_minutes, note, created_day, backlog, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (title, group_name, int(has_deadline), deadline_time,
             int(remind_minutes), note, created_day or date.today().isoformat(),
             int(backlog), order),
        )
        self._ensure_group(group_name)
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_daily_task(self, task_id: int, title: str, group_name: str = "",
                          has_deadline: bool = False, deadline_time: str = "",
                          note: str = "", backlog: bool = True,
                          remind_minutes: int = DEFAULT_REMIND_MINUTES) -> None:
        self.conn.execute(
            "UPDATE daily_tasks SET title=?, group_name=?, has_deadline=?, deadline_time=?,"
            " remind_minutes=?, note=?, backlog=? WHERE id=?",
            (title, group_name, int(has_deadline), deadline_time, int(remind_minutes),
             note, int(backlog), task_id),
        )
        self._ensure_group(group_name)
        self.conn.commit()

    def delete_daily_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM daily_tasks WHERE id=?", (task_id,))
        self.conn.execute("DELETE FROM daily_records WHERE daily_task_id=?", (task_id,))
        self.conn.commit()

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
            )
            items[item.column].append(item)

            # 漏勾的日子进积压栏，可在那里补勾（补勾即算那天有效）或移除
            items[COL_BACKLOG].extend(self._daily_backlog(task, today))

    def _daily_streaks(self, task: DailyTask, today: date) -> tuple[int, int]:
        """返回 (最新连续完成次数, 历史最高连续完成次数)，单位是天。"""
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

        best = run = 0
        day = start
        while day <= today:
            if day.isoformat() in done_days:
                run += 1
                best = max(best, run)
            else:
                run = 0
            day += timedelta(days=1)

        # 今天还没勾不算中断，从昨天往回数；补勾后自然接上
        cursor = today if today.isoformat() in done_days else today - timedelta(days=1)
        streak = 0
        while cursor >= start and cursor.isoformat() in done_days:
            streak += 1
            cursor -= timedelta(days=1)
        return streak, best

    def _daily_backlog(self, task: DailyTask, today: date) -> list[TodayItem]:
        """任务已存在、但那一天没完成的日子，逐天列出以便日后补勾。"""
        if not task.backlog:
            return []

        start = today - timedelta(days=BACKLOG_LOOKBACK_DAYS)
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
            if not done_map.get(day_str):
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
                "UPDATE once_tasks SET status=? WHERE id=?",
                ("done" if done else "pending", int(rest)),
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

    # ================= 备忘录便签 =================

    def list_memos(self) -> list[Memo]:
        """全部便签：按摞聚合，摞内按页签序号排。"""
        rows = self.conn.execute(
            "SELECT * FROM memos ORDER BY stack_id, stack_order, id"
        ).fetchall()
        return [_memo(r) for r in rows]

    def get_memo(self, memo_id: int) -> Memo | None:
        row = self.conn.execute(
            "SELECT * FROM memos WHERE id=?", (int(memo_id),)
        ).fetchone()
        return _memo(row) if row else None

    def create_memo(self, content: str = "", x: int = 0, y: int = 0) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memos (content, x, y, stack_id, stack_order, updated_day)"
            " VALUES (?,?,?,0,0,?)",
            (content, int(x), int(y), date.today().isoformat()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_memo_content(self, memo_id: int, content: str) -> None:
        self.conn.execute(
            "UPDATE memos SET content=?, updated_day=? WHERE id=?",
            (content, date.today().isoformat(), int(memo_id)),
        )
        self.conn.commit()

    def save_memo_pos(self, memo_id: int, x: int, y: int) -> None:
        """记住便签落在哪儿；是一摞的话整摞一起走，换页签看时不会跳。"""
        memo = self.get_memo(memo_id)
        if memo is None:
            return
        if memo.stack_id:
            self.conn.execute(
                "UPDATE memos SET x=?, y=? WHERE stack_id=?",
                (int(x), int(y), memo.stack_id),
            )
        else:
            self.conn.execute(
                "UPDATE memos SET x=?, y=? WHERE id=?", (int(x), int(y), memo.id)
            )
        self.conn.commit()

    def set_memo_pinned(self, memo_id: int, pinned: bool) -> None:
        """钉到桌面 / 收回页面。

        钉出去之前先脱离那一摞：半张在桌面、半张在页面里没法看。
        """
        memo = self.get_memo(memo_id)
        if memo is None:
            return
        if pinned and memo.stack_id:
            self.detach_memo(memo_id)
        self.conn.execute(
            "UPDATE memos SET pinned=? WHERE id=?", (1 if pinned else 0, memo.id)
        )
        self.conn.commit()

    def delete_memo(self, memo_id: int) -> None:
        """删掉一张便签；摞里只剩一张时自动散掉。"""
        row = self.conn.execute(
            "SELECT stack_id FROM memos WHERE id=?", (int(memo_id),)
        ).fetchone()
        if row is None:
            return
        stack_id = int(row["stack_id"])
        self.conn.execute("DELETE FROM memos WHERE id=?", (int(memo_id),))
        if stack_id:
            self._settle_stack(stack_id)
        self.conn.commit()

    def stack_members(self, stack_id: int) -> list[Memo]:
        """某一摞里的便签，按页签序号排（序号由 stack_order 固定下来）。"""
        rows = self.conn.execute(
            "SELECT * FROM memos WHERE stack_id=? ORDER BY stack_order, id",
            (int(stack_id),),
        ).fetchall()
        return [_memo(r) for r in rows]

    def merge_memos(self, host_id: int, guest_id: int) -> bool:
        """把 guest 那一摞叠到 host 这一摞上；超过上限就不合并，返回 False。"""
        host = self.get_memo(host_id)
        guest = self.get_memo(guest_id)
        if host is None or guest is None or host.id == guest.id:
            return False
        if host.stack_id and host.stack_id == guest.stack_id:
            return False

        host_stack = host.stack_id or host.id
        total = self._stack_size(host_stack) + self._stack_size(guest.stack_id)
        if total > MAX_MEMO_STACK:
            return False

        # host 原本单独一张时，先把自己立成一摞的摞主，并继续露在最上面
        if not host.stack_id:
            self.conn.execute(
                "UPDATE memos SET stack_id=?, stack_order=0, stack_active=1 WHERE id=?",
                (host_stack, host.id),
            )

        order = self._next_stack_order(host_stack)
        members = self.stack_members(guest.stack_id) if guest.stack_id else [guest]
        for member in members:
            # 位置对齐到 host：一摞就是同一处，换页签看时不会整个跳走
            self.conn.execute(
                "UPDATE memos SET stack_id=?, stack_order=?, stack_active=0, x=?, y=?"
                " WHERE id=?",
                (host_stack, order, host.x, host.y, member.id),
            )
            order += 1
        self.conn.commit()
        return True

    def promote_in_stack(self, stack_id: int, memo_id: int) -> None:
        """把摞里某一张翻到最上面：只换显示的那张，页签序号原地不动。"""
        members = self.stack_members(stack_id)
        if len(members) < 2 or memo_id not in {member.id for member in members}:
            return
        self.conn.execute(
            "UPDATE memos SET stack_active=0 WHERE stack_id=?", (int(stack_id),)
        )
        self.conn.execute("UPDATE memos SET stack_active=1 WHERE id=?", (int(memo_id),))
        self.conn.commit()

    def detach_memo(self, memo_id: int) -> None:
        """把一张便签从摞里拿出来，变回单独一张。"""
        memo = self.get_memo(memo_id)
        if memo is None or not memo.stack_id:
            return
        self.conn.execute(
            "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE id=?",
            (memo.id,),
        )
        self._settle_stack(memo.stack_id)
        self.conn.commit()

    def split_stack(self, stack_id: int) -> None:
        """整摞拆开，每张都变回单独一张。"""
        self.conn.execute(
            "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE stack_id=?",
            (int(stack_id),),
        )
        self.conn.commit()

    def _stack_size(self, stack_id: int) -> int:
        """某一摞的张数；stack_id 为 0 时就是单独一张。"""
        if not stack_id:
            return 1
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memos WHERE stack_id=?", (int(stack_id),)
        ).fetchone()
        return int(row["n"])

    def _next_stack_order(self, stack_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(stack_order), -1) + 1 AS n FROM memos WHERE stack_id=?",
            (int(stack_id),),
        ).fetchone()
        return int(row["n"])

    def _settle_stack(self, stack_id: int) -> None:
        """摞里只剩一张就散掉，否则把编号收紧，并保证总有一张露在外面。"""
        members = self.stack_members(stack_id)
        if not members:
            return
        if len(members) == 1:
            self.conn.execute(
                "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE id=?",
                (members[0].id,),
            )
            return
        # 本来露在外面那张被移走或删掉了，由编号最靠前的那张顶上
        if not any(member.stack_active for member in members):
            self.conn.execute(
                "UPDATE memos SET stack_active=1 WHERE id=?", (members[0].id,)
            )
        for order, member in enumerate(members):
            if member.stack_order != order:
                self.conn.execute(
                    "UPDATE memos SET stack_order=? WHERE id=?", (order, member.id)
                )

    # ================= 应用设置 =================

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def default_remind_minutes(self) -> int:
        """新建任务时提醒量输入框的默认值。"""
        raw = self.get_setting(SETTING_DEFAULT_REMIND, "")
        try:
            return max(0, min(600, int(raw)))
        except ValueError:
            return DEFAULT_REMIND_MINUTES

    def remind_mode(self) -> str:
        """到点提醒怎么弹：自动 / 只用置底小窗 / 两处都提示。"""
        mode = self.get_setting(SETTING_REMIND_MODE, REMIND_AUTO)
        return mode if mode in {value for value, _ in REMIND_MODES} else REMIND_AUTO

    def remind_sound_enabled(self) -> bool:
        """到点提醒要不要响一声。默认响，只有明确存过 "0" 才静音。"""
        return self.get_setting(SETTING_REMIND_SOUND, "1") != "0"

    def remind_sound_choice(self) -> str:
        """当前选的提醒音：alias:xxx 是系统音，file:xxx 是本地音频；空串表示用默认。"""
        choice = self.get_setting(SETTING_REMIND_SOUND_CHOICE, "")
        return choice if choice.startswith(("alias:", "file:")) else ""

    def set_remind_sound_choice(self, choice: str) -> None:
        self.set_setting(SETTING_REMIND_SOUND_CHOICE, str(choice))

    def remind_sound_files(self) -> list[str]:
        """用户添加过的本地音频文件，按添加顺序去重。"""
        files: list[str] = []
        for line in self.get_setting(SETTING_REMIND_SOUND_FILES, "").splitlines():
            path = line.strip()
            if path and path not in files:
                files.append(path)
        return files

    def set_remind_sound_files(self, paths: list[str]) -> None:
        files: list[str] = []
        for path in paths:
            path = str(path).strip()
            if path and path not in files:
                files.append(path)
        self.set_setting(SETTING_REMIND_SOUND_FILES, "\n".join(files))

    def nav_position(self) -> str:
        """主导航在顶部还是左侧。"""
        position = self.get_setting(SETTING_NAV_POSITION, NAV_TOP)
        return position if position in {value for value, _ in NAV_POSITIONS} else NAV_TOP

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

    # ================= 内部工具 =================

    def get_daily_task(self, task_id: int) -> DailyTask | None:
        row = self.conn.execute(
            "SELECT * FROM daily_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return _daily(row) if row else None

    def _get_daily_record(self, task_id: int, day_str: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM daily_records WHERE daily_task_id=? AND day=?",
            (task_id, day_str),
        ).fetchone()

    def _ensure_daily_record(self, task: DailyTask, today: date) -> sqlite3.Row:
        day_str = today.isoformat()
        record = self._get_daily_record(task.id, day_str)
        if record is not None:
            return record

        self.conn.execute(
            "INSERT INTO daily_records (daily_task_id, day, done) VALUES (?,?,0)",
            (task.id, day_str),
        )
        self.conn.commit()
        return self._get_daily_record(task.id, day_str)

    def _settle_once_tasks(self, day_str: str) -> None:
        """过期未完成的临时任务按设计直接弃置。"""
        self.conn.execute(
            "UPDATE once_tasks SET status='discarded'"
            " WHERE status='pending' AND day < ?",
            (day_str,),
        )
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

    def _archive_period_task(self, task_id: int) -> None:
        self.conn.execute("UPDATE period_tasks SET archived=1 WHERE id=?", (task_id,))
        self.conn.commit()

    def _next_order(self, table: str) -> int:
        row = self.conn.execute(f"SELECT COALESCE(MAX(sort_order), 0) + 1 FROM {table}").fetchone()
        return int(row[0])

    # ================= 首次运行的演示数据 =================

    def _seed_if_empty(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM daily_tasks").fetchone()
        if row["n"]:
            return

        today = date.today()
        yesterday = today - timedelta(days=1)

        daily_specs = [
            ("俯卧撑", "每日健身", False, "", ""),
            ("跑步 5 km", "每日健身", False, "", ""),
            ("背单词", "学习", False, "", ""),
            ("阅读 30 分钟", "学习", False, "", ""),
            ("给绿植浇水", "生活", False, "", ""),
            ("整理本周会议纪要", "", False, "", ""),
            ("完成今日工作周报", "", True, "15:00", "按时提交到周报系统"),
        ]
        daily_ids: dict[str, int] = {}
        for title, group, has_deadline, time_text, note in daily_specs:
            # 创建日设为前天，这样能演示「最新连续」与「最高连续」的差别
            daily_ids[title] = self.create_daily_task(
                title, group, has_deadline, time_text, note,
                created_day=(today - timedelta(days=2)).isoformat(),
            )

        # 前天：背单词完成，其余漏勾
        self._insert_record(daily_ids["背单词"], today - timedelta(days=2), done=True)
        # 昨天：俯卧撑、背单词、跑步完成 → 背单词连续 2 天
        self._insert_record(daily_ids["俯卧撑"], yesterday, done=True)
        self._insert_record(daily_ids["背单词"], yesterday, done=True)
        self._insert_record(daily_ids["跑步 5 km"], yesterday, done=True)
        # 阅读、整理会议纪要、给绿植浇水 昨天未勾，会出现在陈年旧账里

        self.create_once_task(
            "抢演唱会门票", today.isoformat(), "08:00", "提前登录账号", group_name="娱乐"
        )
        self.create_once_task(
            "给客户回电话确认排期", today.isoformat(), "17:30", "", group_name="工作"
        )
        self.create_once_task(
            "回复张老师关于课题的邮件", yesterday.isoformat(), "", "", group_name="工作"
        )
        # 远期任务两种显示时机各来一个：前者每天都挂在首页，后者等到倒数三天才出现
        self.create_once_task(
            "预约下周体检", (today + timedelta(days=10)).isoformat(), "", "每天都提醒，别忘了",
            always_show=True, group_name="生活",
        )
        self.create_once_task(
            "续费域名", (today + timedelta(days=12)).isoformat(), "", "到期前三天才会冒出来",
            group_name="工作",
        )

        self.create_period_task(
            "完成毕业论文",
            (today + timedelta(days=45)).isoformat(),
            "分三个阶段推进，每个阶段完成后再进入下一阶段",
            [
                ("综述章节", (today + timedelta(days=12)).isoformat()),
                ("正文初稿", (today + timedelta(days=30)).isoformat()),
                ("终稿定稿并上传", (today + timedelta(days=45)).isoformat()),
            ],
            group_name="学业",
        )
        report_id = self.create_period_task(
            "提交项目结题报告",
            today.isoformat(),
            "最终期限就是今天",
            [
                ("整理实验数据", (today - timedelta(days=10)).isoformat()),
                ("撰写报告正文", today.isoformat()),
            ],
            group_name="工作",
        )
        first_stage = self.list_stages(report_id)[0]
        self.conn.execute(
            "UPDATE period_stages SET done=1 WHERE id=?", (first_stage.id,)
        )
        self.conn.commit()

    def _insert_record(self, task_id: int, day: date, done: bool) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO daily_records (daily_task_id, day, done) VALUES (?,?,?)",
            (task_id, day.isoformat(), int(done)),
        )
        self.conn.commit()


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
