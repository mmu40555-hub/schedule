"""重构差异比对：同一批种子数据、同一串操作，两份工作副本各跑一遍再逐行比对。

重构前先跑一次拿到基线；重构后在新副本里再跑一次，两份摘要一字不差，就说明
行为没变。摘要里的「今天」和「此刻」都冻成了固定值，所以跨天、跨机器跑也一致。

用法（在仓库目录里跑）：
    python diff_check.py                          # 打印当前目录代码的行为摘要
    python diff_check.py --compare <另一份副本目录>  # 两边的摘要直接比对
退出码：0 = 一致，1 = 有差异，2 = 有一边跑不起来。
"""

import dataclasses
import difflib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

# 摘要里的「今天」与「此刻」都钉在这个固定时刻，保证输出可复现
FROZEN_DAY = date(2026, 3, 15)
FROZEN_STAMP = "2026-03-15 09:00:00"


def _freeze(storage) -> None:
    """把 storage 里跟「现在」有关的东西钉死，否则两次运行差几秒就对不上。

    storage 眼下是单个文件；将来拆成包以后，date 与 _stamp 会散到各个子模块里，
    所以这里按名字把 storage 名下的每个模块都铺一遍，拆不拆都照样管用。
    """

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(FROZEN_DAY.year, FROZEN_DAY.month, FROZEN_DAY.day)

    for name, module in list(sys.modules.items()):
        if name != "storage" and not name.startswith("storage."):
            continue
        if getattr(module, "_stamp", None) is not None:
            module._stamp = lambda: FROZEN_STAMP
        if getattr(module, "date", None) is date:
            module.date = FrozenDate


def _run_operations(store, storage) -> None:
    """一串覆盖各类功能的操作：建、改、勾、退回、排序、丢弃、还原、彻底删。"""
    day = FROZEN_DAY.isoformat()

    # 组别：新建一个再改名，两个操作都得落到库里
    store.create_group("重构测试")
    store.rename_group("重构测试", "重构后的组")

    # 每日任务：三种周期各来一个，再勾掉一个
    daily_id = store.create_daily_task("每天散步", "重构后的组")
    store.create_daily_task(
        "每周复盘", "重构后的组", has_deadline=True, deadline_time="20:00",
        note="周五晚上写", repeat=storage.REPEAT_WEEKLY, repeat_day=5,
    )
    store.create_daily_task(
        "每月体检", "重构后的组", repeat=storage.REPEAT_MONTHLY, repeat_day=15,
    )
    store.set_item_done(f"{storage.SOURCE_DAILY}:{daily_id}@{day}", True)

    # 临时任务：一个留成已完成（要进历史汇总），一个勾了又撤
    done_once = store.create_once_task(
        "已完成的临时任务", day, "10:00", "备注甲", group_name="重构后的组"
    )
    store.set_item_done(f"{storage.SOURCE_ONCE}:{done_once}", True)

    undo_once = store.create_once_task("勾了又撤的临时任务", day, group_name="重构后的组")
    store.set_item_done(f"{storage.SOURCE_ONCE}:{undo_once}", True)
    store.set_item_done(f"{storage.SOURCE_ONCE}:{undo_once}", False)
    store.dismiss_item(f"{storage.SOURCE_ONCE}:{undo_once}", storage.KIND_BACKLOG)

    # 时期任务：全阶段完成 → 归档并记下完成时刻；再退回一步 → 复活；再做完
    period_id = store.create_period_task(
        "重构期任务", "2026-03-20", "分两步走",
        stages=[("第一步", "2026-03-16"), ("第二步", "2026-03-20")],
        group_name="重构后的组",
    )
    period_key = f"{storage.SOURCE_PERIOD}:{period_id}"
    store.set_item_done(period_key, True)   # 完成第一步
    store.set_item_done(period_key, True)   # 完成第二步 → 归档
    store.set_item_done(period_key, False)  # 退回一步 → 复活、清掉完成时刻
    store.set_item_done(period_key, True)   # 再做完 → 重新归档

    # 便签：叠成一摞再拆开，然后丢弃、还原、彻底删
    memo_a = store.create_memo("便签甲", 10, 20)
    memo_b = store.create_memo("便签乙", 12, 22)
    store.update_memo_content(memo_a, "便签甲（改过内容）")
    store.set_memo_pinned(memo_a, True)
    store.merge_memos(memo_a, memo_b)
    store.stack_members(memo_a)
    store.split_stack(memo_a)
    store.discard_memo(memo_b)
    store.restore_memo(memo_b)

    memo_c = store.create_memo("要彻底删掉的便签", 0, 0)
    store.discard_memo(memo_c)
    store.purge_memos([memo_c])

    # 设置：几项会被落库的偏好
    store.set_new_note_hotkey("Ctrl+Alt+N")
    store.set_auto_update_check(False)
    store.set_update_last_check(1234567890.0)
    store.set_remind_sound_choice("默认铃声")
    store.set_setting("daily_goal", "3")

    # 手动排序：把积压栏倒过来存一遍
    items = store.today_items(FROZEN_DAY)
    backlog_keys = [item.key for item in items.get(storage.COL_BACKLOG, [])]
    store.save_order(storage.COL_BACKLOG, list(reversed(backlog_keys)), FROZEN_DAY)


def _derived(store, storage) -> dict:
    """上层真正拿到手的东西：各栏内容、历史、便签、废弃栏。"""

    def dump(rows):
        return [dataclasses.asdict(row) for row in rows]

    items = store.today_items(FROZEN_DAY)
    data = {
        f"column:{column}": dump(rows) for column, rows in items.items()
    }
    data["daily_tasks"] = dump(store.list_daily_tasks())
    data["once_tasks"] = dump(store.list_once_tasks())
    data["period_tasks"] = dump(store.list_period_tasks(include_archived=True))
    data["groups"] = store.groups()
    data["history"] = dump(store.completed_history())
    data["memos"] = dump(store.list_memos())
    data["discarded_memos"] = dump(store.list_discarded_memos())
    data["discarded_once"] = dump(store.discarded_once_tasks())
    data["today_order"] = [
        dict(row)
        for row in store.conn.execute(
            "SELECT day, column_id, item_key, position FROM today_order"
            " ORDER BY day, column_id, position"
        ).fetchall()
    ]
    return data


def _snapshot(store, storage) -> dict:
    """整库快照 + 上层推导结果，两层都记，重构动哪一层都能看出来。"""
    conn = store.conn
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    snapshot = {
        # 数据文件必须落在程序目录里。拆包很容易把 _app_dir() 指到子目录去，
        # 而下面的快照都是显式传库路径的，抓不到这种偏差，所以单独盯一眼。
        "db_path_ok": storage.DB_PATH.parent == Path(__file__).resolve().parent,
        "schema": [
            row["sql"]
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
            ).fetchall()
        ],
    }
    for name in tables:
        snapshot[f"table:{name}"] = [
            dict(row) for row in conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
        ]
    snapshot["derived"] = _derived(store, storage)
    return snapshot


def build_digest() -> str:
    """当前目录这份代码的行为摘要（JSON 文本）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import storage as storage_module

    _freeze(storage_module)

    workdir = Path(tempfile.mkdtemp(prefix="schedule_diff_"))
    db_path = workdir / "check.db"
    store = storage_module.Store(db_path)
    try:
        _run_operations(store, storage_module)
        snapshot = _snapshot(store, storage_module)
    finally:
        store.close()

    return json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)


def _compare(other_dir: str) -> int:
    """拿另一份副本的摘要跟本目录比，逐行比对差异。"""
    other_script = Path(other_dir).resolve() / "diff_check.py"
    if not other_script.exists():
        print(f"找不到 {other_script}")
        return 2

    # 别让子进程在另一份副本里写 __pycache__，保持那份工作区干净
    env = dict(
        os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1"
    )
    result = subprocess.run(
        [sys.executable, str(other_script), "--dump"],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(other_script.parent),
    )
    if result.returncode != 0:
        print("另一份副本没跑起来，stderr 末尾：")
        print(result.stderr[-2000:])
        return 2

    mine = build_digest()
    # 子进程经管道输出时行尾会变成 \r\n、末尾还多个换行，统一成行列表再比
    theirs = result.stdout.replace("\r\n", "\n").replace("\r", "\n")
    mine_lines = mine.splitlines()
    their_lines = theirs.splitlines()
    if mine_lines == their_lines:
        print(f"行为一致：本目录与 {other_script.parent} 的摘要逐行相同")
        return 0

    diff = difflib.unified_diff(
        their_lines, mine_lines,
        fromfile=str(other_script.parent), tofile="本目录", lineterm="",
    )
    lines = list(diff)
    print("\n".join(lines[:300]))
    if len(lines) > 300:
        print(f"...（差异还有 {len(lines) - 300} 行）")
    print("\n行为有差异：from = 另一份副本，to = 本目录")
    return 1


def main() -> int:
    if "--compare" in sys.argv:
        index = sys.argv.index("--compare")
        if index + 1 >= len(sys.argv):
            print("用法：python diff_check.py --compare <另一份副本目录>")
            return 2
        return _compare(sys.argv[index + 1])
    print(build_digest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
