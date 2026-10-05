from models import REPEAT_DAILY, REPEAT_MONTHLY, REPEAT_WEEKLY

from .helpers import _app_dir


DB_PATH = _app_dir() / "schedule.db"

# 历史未完成记录最多回溯多少天（避免积压栏被陈年数据淹没）
BACKLOG_LOOKBACK_DAYS = 7

# 陈年旧账的回溯天数：每周/每月任务的漏勾日子间隔更远，得多看一阵子
BACKLOG_LOOKBACK = {
    REPEAT_DAILY: BACKLOG_LOOKBACK_DAYS,
    REPEAT_WEEKLY: 14,
    REPEAT_MONTHLY: 62,
}

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

# 全局快捷键：在任何程序里按下就能在鼠标处新建一张桌面便签
SETTING_NEW_NOTE_HOTKEY = "new_note_hotkey"
DEFAULT_NEW_NOTE_HOTKEY = "Ctrl+Alt+N"

# 自动更新：开不开自动检查、上次检查的时间戳、用户说过要跳过的版本
SETTING_AUTO_UPDATE = "auto_update_check"
SETTING_UPDATE_LAST = "update_last_check"
SETTING_UPDATE_SKIP = "update_skip_version"

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
    repeat        TEXT    NOT NULL DEFAULT 'daily',
    repeat_day    INTEGER NOT NULL DEFAULT 0,
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
    sort_order INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS period_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    group_name TEXT    NOT NULL DEFAULT '',
    deadline   TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT    NOT NULL DEFAULT ''
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
    host_class  TEXT    NOT NULL DEFAULT '',
    host_title  TEXT    NOT NULL DEFAULT '',
    host_dx     INTEGER NOT NULL DEFAULT 0,
    host_dy     INTEGER NOT NULL DEFAULT 0,
    updated_day TEXT    NOT NULL DEFAULT '',
    discarded_at TEXT   NOT NULL DEFAULT ''
);
"""
