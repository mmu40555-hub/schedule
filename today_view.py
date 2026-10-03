"""首页：今日一览。

三栏结构 —— 刻不容缓 / 案无留牍 / 陈年旧账，内容全部由 storage 按当天日期实时推导。
- 归属由任务属性决定，拖拽只允许栏内排序
- 栏宽由两条分隔条随手拖动，勾选「悬浮窗」还能把单个栏目常驻到桌面上
- 有时限的任务快到点时提醒：开了悬浮窗就在窗内提示，否则弹一个置底小窗
"""

from datetime import date

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dialogs import (
    DailyTaskDialog,
    OnceTaskDialog,
    PeriodTaskDialog,
    SettingsDialog,
)
from floating import (
    FloatingBoard,
    OpacityPopup,
    RemindPopup,
    clamp_opacity,
    load_opacity,
)
from models import COL_BACKLOG, COLUMN_ORDER, SOURCE_DAILY, SOURCE_ONCE, SOURCE_PERIOD, TodayItem
from sound import play_remind_sound
from storage import (
    KIND_BANNER,
    REMIND_AUTO,
    REMIND_BOTH,
    REMIND_POPUP,
    SETTING_DEFAULT_REMIND,
    SETTING_FLOAT_OPACITY,
    SETTING_NAV_POSITION,
    SETTING_REMIND_MODE,
    SETTING_REMIND_SOUND,
    SETTING_REMIND_SOUND_FILES,
    Store,
)
from task_column import TaskColumn

WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MAX_BANNER_NAMES = 3

# 到点提醒的轮询间隔（毫秒）：半分钟足够准，又不至于一直占着 CPU
REMIND_POLL_MS = 30_000


def _task_id(item_key: str) -> int:
    """daily:3@2026-09-17 / period:2 → 3 / 2。"""
    return int(item_key.split(":", 1)[1].split("@", 1)[0])


class TodayView(QWidget):
    settings_saved = pyqtSignal()   # 设置改完了，主窗口据此决定要不要重搭导航

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setObjectName("TodayView")
        self.store = store
        self.data: dict[str, list[TodayItem]] = {}
        self.columns: dict[str, TaskColumn] = {}
        self.board: FloatingBoard | None = None
        self.popup: RemindPopup | None = None
        self.opacity_popup: OpacityPopup | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        self.banner_holder = QVBoxLayout()
        self.banner_holder.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.banner_holder)
        root.addLayout(self._build_header())
        root.addWidget(self._build_splitter(), 1)

        self.reload()

        self.remind_timer = QTimer(self)
        self.remind_timer.setInterval(REMIND_POLL_MS)
        self.remind_timer.timeout.connect(self._check_reminders)
        self.remind_timer.start()
        # 界面铺好后再查一次，免得启动时正好处在提醒窗口里却漏掉
        QTimer.singleShot(1500, self._check_reminders)

    # ---------- 顶部区域 ----------

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("今日一览")
        title.setObjectName("PageTitle")
        left.addWidget(title)

        today = date.today()
        subtitle = QLabel(
            f"{today.year} 年 {today.month} 月 {today.day} 日 · {WEEKDAY[today.weekday()]}"
        )
        subtitle.setObjectName("PageDate")
        left.addWidget(subtitle)
        row.addLayout(left)
        row.addStretch(1)

        self.stat_label = QLabel()
        self.stat_label.setObjectName("StatText")
        row.addWidget(self.stat_label, 0, Qt.AlignmentFlag.AlignBottom)

        self.float_check = QCheckBox("悬浮窗")
        self.float_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.float_check.setToolTip(
            "勾选后桌面上常驻一个小窗口，只显示一个栏目，\n"
            "窗内三个页签可以切换刻不容缓 / 案无留牍 / 陈年旧账"
        )
        self.float_check.toggled.connect(self._on_float_toggled)
        row.addWidget(self.float_check, 0, Qt.AlignmentFlag.AlignBottom)

        # 找不到悬浮窗时，这里是最后的透明度调整入口
        self.page_opacity_button = QPushButton("◐")
        self.page_opacity_button.setObjectName("GhostButton")
        self.page_opacity_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_opacity_button.clicked.connect(self._show_page_opacity_popup)
        self._refresh_page_opacity_tip()
        row.addWidget(self.page_opacity_button, 0, Qt.AlignmentFlag.AlignBottom)

        settings = QPushButton("设置")
        settings.setObjectName("GhostButton")
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.setToolTip("修改默认提前提醒时间与提醒方式")
        settings.clicked.connect(self._open_settings)
        row.addWidget(settings, 0, Qt.AlignmentFlag.AlignBottom)

        add_group = QPushButton("+ 新建组别")
        add_group.setObjectName("GhostButton")
        add_group.setCursor(Qt.CursorShape.PointingHandCursor)
        add_group.setToolTip("新建组别，三类任务共用")
        add_group.clicked.connect(self._new_group)
        row.addWidget(add_group, 0, Qt.AlignmentFlag.AlignBottom)

        self.add_button = QPushButton("+ 新建任务")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setToolTip("选择任务类型后新建")
        self.add_button.clicked.connect(self._show_add_menu)
        row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignBottom)

        return row

    # ---------- 悬浮窗 ----------

    def _on_float_toggled(self, checked: bool) -> None:
        if checked:
            if self.board is None:
                self.board = FloatingBoard(self.store)
                self.board.closed.connect(
                    lambda: self.float_check.setChecked(False)
                )
                for column_id, column in self.board.columns.items():
                    self._connect_column(column)
                    column.set_tasks(self.data[column_id])
            self.board.move_to_default_spot()
            self.board.show()
            self.board.raise_()
        elif self.board is not None:
            self.board.hide_board()
        self._refresh_page_opacity_tip()

    def close_floating(self) -> None:
        """主窗口关闭时顺带收掉悬浮窗与提醒小窗，否则程序退不干净。"""
        if self.board is not None:
            self.board.close()
        if self.popup is not None:
            self.popup.close()
        if self.opacity_popup is not None:
            self.opacity_popup.close()

    # ---------- 主页上的透明度入口 ----------

    def _current_float_opacity(self) -> float:
        if self.board is not None:
            return self.board.opacity
        return load_opacity(self.store)

    def _refresh_page_opacity_tip(self) -> None:
        self.page_opacity_button.setToolTip(
            f"调整悬浮窗透明度（当前 {int(round(self._current_float_opacity() * 100))}%）\n"
            "悬浮窗被拖到看不见的地方时，也可以先用这里把透明度调回来"
        )

    def _set_float_opacity(self, value: float) -> None:
        """悬浮窗开着就交给它（顺带记住），没开就只写设置，下次打开生效。"""
        if self.board is not None:
            self.board.set_opacity(value)
        else:
            self.store.set_setting(
                SETTING_FLOAT_OPACITY, f"{clamp_opacity(value):.2f}"
            )
        self._refresh_page_opacity_tip()

    def _show_page_opacity_popup(self) -> None:
        self._refresh_page_opacity_tip()
        if self.opacity_popup is None:
            self.opacity_popup = OpacityPopup(self._current_float_opacity(), self)
            self.opacity_popup.opacity_changed.connect(self._set_float_opacity)
        else:
            self.opacity_popup.slider.setValue(
                int(round(self._current_float_opacity() * 100))
            )
        self.opacity_popup.popup_at(self.page_opacity_button)

    # ---------- 主页设置 ----------

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.store.default_remind_minutes(),
            self.store.remind_mode(),
            self.store.remind_sound_enabled(),
            self.store.remind_sound_choice(),
            self.store.remind_sound_files(),
            self.store.nav_position(),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.store.set_setting(SETTING_DEFAULT_REMIND, str(values["default_remind"]))
        self.store.set_setting(SETTING_REMIND_MODE, str(values["remind_mode"]))
        self.store.set_setting(SETTING_REMIND_SOUND, "1" if values["sound"] else "0")
        self.store.set_remind_sound_choice(values["sound_choice"])
        self.store.set_remind_sound_files(values["sound_files"])
        self.store.set_setting(SETTING_NAV_POSITION, str(values["nav_position"]))
        self.settings_saved.emit()

    def _default_remind(self) -> int:
        """新建任务时提醒输入框的初始值。"""
        return self.store.default_remind_minutes()

    # ---------- 到点提醒 ----------

    def _check_reminders(self) -> None:
        """时限任务进入提醒窗口就提示一次；同一条当天只打扰一次。"""
        reminders = self.store.due_reminders()
        if not reminders:
            return

        if self.store.remind_sound_enabled():
            play_remind_sound(self.store.remind_sound_choice())

        mode = self.store.remind_mode()
        # 悬浮窗开着才谈得上在窗内提示；没开时无论哪种方式都要有小窗兜底
        floating = self.board is not None and self.board.isVisible()
        in_float = floating and mode in (REMIND_AUTO, REMIND_BOTH)
        in_popup = not floating or mode in (REMIND_POPUP, REMIND_BOTH)

        if in_float:
            self.board.show_reminder(reminders)
        if in_popup:
            if self.popup is None:
                self.popup = RemindPopup()
            self.popup.show_reminders(reminders)

        self.store.mark_reminded([item.key for item in reminders])

    # ---------- 首页里直接做任务设定 ----------

    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("长期每日任务", self._new_daily_task)
        menu.addAction("某日临时任务", self._new_once_task)
        menu.addAction("时期任务", self._new_period_task)
        menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))

    def _new_daily_task(self) -> None:
        dialog = DailyTaskDialog(
            groups=self.store.groups(), parent=self,
            default_remind=self._default_remind(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.store.create_daily_task(**dialog.values())
        self.reload()

    def _new_group(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建组别", "组别名称")
        if not accepted:
            return
        name = name.strip()
        if not name:
            return
        if name in self.store.groups():
            QMessageBox.information(self, "组别已存在", f"组别「{name}」已经存在。")
            return
        self.store.create_group(name)
        self.reload()

    def _new_once_task(self) -> None:
        dialog = OnceTaskDialog(
            groups=self.store.groups(), parent=self,
            default_remind=self._default_remind(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.store.create_once_task(
            values["title"], values["day"], values["time"], values["note"],
            values["always_show"], values["group_name"], values["remind_minutes"],
        )
        self.reload()

    def _new_period_task(self) -> None:
        dialog = PeriodTaskDialog(groups=self.store.groups(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.store.create_period_task(
            values["title"], values["deadline"], values["note"], values["stages"],
            values["group_name"],
        )
        self.reload()

    # ---------- 组别设定 ----------

    def _on_group_menu(self, group: str, position) -> None:
        """组别标题上的「⋯」：重命名或删除这个组别。"""
        menu = QMenu(self)
        menu.addAction("重命名这个组别", lambda: self._rename_group(group))
        menu.addAction("删除这个组别", lambda: self._delete_group(group))
        menu.exec(position)

    def _rename_group(self, group: str) -> None:
        name, accepted = QInputDialog.getText(
            self, "重命名组别", "组别名称", text=group
        )
        if not accepted:
            return
        name = name.strip()
        if not name or name == group:
            return
        if name in self.store.groups():
            QMessageBox.information(self, "组别已存在", f"组别「{name}」已经存在。")
            return
        self.store.rename_group(group, name)
        self.reload()

    def _delete_group(self, group: str) -> None:
        confirmed = QMessageBox.question(
            self,
            "删除组别",
            f"确定删除组别「{group}」吗？",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        # 第二步单独问：组里的任务是一起删掉，还是留到「未归组」
        box = QMessageBox(self)
        box.setWindowTitle("组内的任务")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"组别「{group}」里的任务怎么处理？")
        box.setInformativeText(
            "仅删除组别：任务移到「未归组」，任务本身与完成记录都保留。\n"
            "组别和任务一起删除：组内所有任务连同完成记录一并删除，无法恢复。"
        )
        keep = box.addButton("仅删除组别", QMessageBox.ButtonRole.AcceptRole)
        purge = box.addButton("组别和任务一起删除", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.exec()

        clicked = box.clickedButton()
        if clicked is cancel:
            return
        if clicked is purge:
            removed = self.store.purge_group(group)
            QMessageBox.information(
                self, "已删除", f"组别「{group}」及其 {removed} 条任务已删除。"
            )
        else:
            self.store.delete_group(group)
        self.reload()

    def _on_menu(self, item_key: str, position) -> None:
        """卡片上的「⋯」：弹出这条任务能做的设定操作。"""
        item = self._find_item(item_key)
        if item is None:
            return

        menu = QMenu(self)
        if item.source == SOURCE_DAILY:
            menu.addAction("编辑这个每日任务", lambda: self._edit_daily(item))
            menu.addAction("删除这个每日任务", lambda: self._delete_daily(item))
        elif item.source == SOURCE_ONCE:
            menu.addAction("编辑这条临时任务", lambda: self._edit_once(item))
            menu.addAction("删除这条临时任务", lambda: self._delete_once(item))
        else:
            menu.addAction("编辑这个时期任务", lambda: self._edit_period(item))
            menu.addAction("删除这个时期任务", lambda: self._delete_period(item))
        if item.column == COL_BACKLOG:
            menu.addSeparator()
            menu.addAction("不再保留这一条", lambda: self._on_dismiss(item.key))
        menu.exec(position)

    def _edit_daily(self, item: TodayItem) -> None:
        task = self._daily_task(item)
        if task is None:
            return
        dialog = DailyTaskDialog(task, self.store.groups(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.store.update_daily_task(task.id, **dialog.values())
        self._after_edit()

    def _delete_daily(self, item: TodayItem) -> None:
        task = self._daily_task(item)
        if task is None:
            return
        confirmed = QMessageBox.question(
            self,
            "删除每日任务",
            f"确定删除「{task.title}」吗？该任务的历史完成记录也会一并清除。",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_daily_task(task.id)
        self._after_edit()

    def _edit_once(self, item: TodayItem) -> None:
        task = self._once_task(item)
        if task is None:
            return
        dialog = OnceTaskDialog(task, self.store.groups(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.store.update_once_task(
            task.id, values["title"], values["day"], values["time"], values["note"],
            values["always_show"], values["group_name"], values["remind_minutes"],
        )
        self._after_edit()

    def _delete_once(self, item: TodayItem) -> None:
        task = self._once_task(item)
        if task is None:
            return
        confirmed = QMessageBox.question(
            self, "删除临时任务", f"确定删除「{task.title}」吗？"
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_once_task(task.id)
        self._after_edit()

    def _edit_period(self, item: TodayItem) -> None:
        task = self._period_task(item)
        if task is None:
            return
        stages = self.store.list_stages(task.id)
        stage_pairs = [(s.title, s.deadline) for s in stages]
        done_flags = [s.done for s in stages]

        dialog = PeriodTaskDialog(
            task, stage_pairs, done_flags, self.store.groups(), parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.store.update_period_task(
            task.id, values["title"], values["deadline"], values["note"],
            values["stages"], values["stage_done"], values["group_name"],
        )
        self._after_edit()

    def _delete_period(self, item: TodayItem) -> None:
        task = self._period_task(item)
        if task is None:
            return
        confirmed = QMessageBox.question(
            self, "删除时期任务", f"确定删除「{task.title}」及其全部阶段吗？"
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_period_task(task.id)
        self._after_edit()

    def _daily_task(self, item: TodayItem):
        task_id = _task_id(item.key)
        return next((t for t in self.store.list_daily_tasks() if t.id == task_id), None)

    def _once_task(self, item: TodayItem):
        task_id = _task_id(item.key)
        return next((t for t in self.store.list_once_tasks() if t.id == task_id), None)

    def _period_task(self, item: TodayItem):
        task_id = _task_id(item.key)
        tasks = self.store.list_period_tasks(include_archived=True)
        return next((t for t in tasks if t.id == task_id), None)

    def _after_edit(self) -> None:
        self.reload()

    def _refresh_banner(self) -> None:
        while self.banner_holder.count():
            item = self.banner_holder.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        tasks = self.store.discarded_once_tasks()
        if not tasks:
            return

        banner = QFrame()
        banner.setObjectName("Banner")
        banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(10)

        icon = QLabel("⏰")
        icon.setFont(QFont("Segoe UI Emoji", 12))
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(2)

        title = QLabel(f"有 {len(tasks)} 个临时任务昨日未完成，已自动弃置")
        title.setObjectName("BannerTitle")
        texts.addWidget(title)

        names = "」「".join(t.title for t in tasks[:MAX_BANNER_NAMES])
        suffix = " 等" if len(tasks) > MAX_BANNER_NAMES else ""
        body = QLabel(f"「{names}」{suffix} —— 请重新安排时间，或确认放弃。")
        body.setObjectName("BannerText")
        body.setWordWrap(True)
        texts.addWidget(body)
        row.addLayout(texts, 1)

        recreate = QPushButton("重新创建")
        recreate.setObjectName("PrimaryButton")
        recreate.setCursor(Qt.CursorShape.PointingHandCursor)
        recreate.clicked.connect(self._on_recreate)
        row.addWidget(recreate, 0, Qt.AlignmentFlag.AlignVCenter)

        ignore = QPushButton("忽略")
        ignore.setObjectName("GhostButton")
        ignore.setCursor(Qt.CursorShape.PointingHandCursor)
        ignore.clicked.connect(self._on_ignore_banner)
        row.addWidget(ignore, 0, Qt.AlignmentFlag.AlignVCenter)

        self.banner_holder.addWidget(banner)

    def _on_recreate(self) -> None:
        tasks = self.store.discarded_once_tasks()
        if not tasks:
            return

        source = tasks[0]
        dialog = OnceTaskDialog(
            groups=self.store.groups(), parent=self,
            default_remind=self._default_remind(),
        )
        dialog.title_edit.setText(source.title)
        if source.note:
            dialog.note_edit.setPlainText(source.note)
        if source.group_name:
            dialog.group_combo.setCurrentText(source.group_name)
        dialog.date_edit.setDate(QDate.currentDate())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.values()
        self.store.create_once_task(
            values["title"], values["day"], values["time"], values["note"],
            values["always_show"], values["group_name"], values["remind_minutes"],
        )
        self.store.dismiss_item(f"once:{source.id}", KIND_BANNER)
        self.reload()

    def _on_ignore_banner(self) -> None:
        for task in self.store.discarded_once_tasks():
            self.store.dismiss_item(f"once:{task.id}", KIND_BANNER)
        self._refresh_banner()

    # ---------- 三栏 ----------

    def _build_splitter(self) -> QSplitter:
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(10)
        self.splitter.setChildrenCollapsible(False)

        for index, column_id in enumerate(COLUMN_ORDER):
            column = TaskColumn(column_id)
            self._connect_column(column)
            self.columns[column_id] = column
            self.splitter.addWidget(column)
            # 两条分隔条随手可拖，但不允许把某一栏拖没
            self.splitter.setCollapsible(index, False)

        return self.splitter

    def _connect_column(self, column: TaskColumn) -> None:
        """主界面和悬浮窗里的同一栏，行为完全一致。"""
        column.state_changed.connect(self._on_task_state)
        column.order_changed.connect(self._on_reorder)
        column.dismiss_requested.connect(self._on_dismiss)
        column.step_back_requested.connect(self._on_step_back)
        column.menu_requested.connect(self._on_menu)
        column.group_menu_requested.connect(self._on_group_menu)

    # ---------- 数据 ----------

    def reload(self) -> None:
        """重新推导今日视图并刷新界面。"""
        self.data = self.store.today_items()
        for column_id, column in self.columns.items():
            column.set_tasks(self.data[column_id])
        self._refresh_stat()
        self._refresh_banner()
        if self.board is not None:
            for column_id, column in self.board.columns.items():
                column.set_tasks(self.data[column_id])

    def _on_task_state(self, item_key: str, done: bool) -> None:
        item = self._find_item(item_key)
        # 有些任务勾一下影响不小，都得先问一句；否定就把勾选框还原
        message = self._done_prompt(item) if done else None
        if message is not None:
            if not self._confirm(*message):
                self.reload()
                return

        self.store.set_item_done(item_key, done)
        self.reload()

    def _done_prompt(self, item: TodayItem | None) -> tuple[str, str, str] | None:
        """勾选前要确认的任务，给出（标题、正文、肯定键文案）。"""
        if item is None:
            return None
        # 时期任务勾一下就会推进阶段
        if item.source == SOURCE_PERIOD:
            return (
                "确认完成阶段",
                f"确定完成「{item.title}」的这一阶段吗？\n"
                f"当前：{item.foot}\n"
                "确认后该阶段记为已完成并进入下一阶段；若这已是最后一阶段，任务会归档。",
                "完成本阶段",
            )
        # 临时任务勾完当天画横线、次日不再出现
        if item.source == SOURCE_ONCE:
            return (
                "确认完成临时任务",
                f"确定完成「{item.title}」吗？\n"
                "完成后今天会画上横线留着，明天起就不再显示了。",
                "完成",
            )
        return None

    def _on_step_back(self, item_key: str) -> None:
        """时期任务退回上一个阶段，最近完成的那个阶段重新变成待完成。"""
        item = self._find_item(item_key)
        if item is None:
            return
        if not self._confirm(
            "返回上一阶段",
            f"确定把「{item.title}」退回上一个阶段吗？\n"
            f"当前：{item.foot}\n"
            "退回后最近完成的那个阶段会重新变成待完成。",
            "返回上一阶段",
        ):
            return

        self.store.set_item_done(item_key, False)
        self.reload()

    def _find_item(self, item_key: str) -> TodayItem | None:
        for tasks in self.data.values():
            for item in tasks:
                if item.key == item_key:
                    return item
        return None

    def _confirm(self, title: str, text: str, ok_text: str) -> bool:
        """一问一答的确认框：肯定键用 ok_text，否定键固定为「取消」。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Question)
        accept = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(accept)
        box.exec()
        return box.clickedButton() is accept

    def _on_dismiss(self, item_key: str) -> None:
        self.store.dismiss_item(item_key)
        self.reload()

    def _on_reorder(self, column_id: str, item_key: str, index: int) -> None:
        tasks = self.data[column_id]
        current = next((i for i, t in enumerate(tasks) if t.key == item_key), None)
        if current is None:
            return

        item = tasks.pop(current)
        if index > current:
            index -= 1
        tasks.insert(index, item)

        self.store.save_order(column_id, [t.key for t in tasks])
        self.columns[column_id].set_tasks(tasks)
        if self.board is not None:
            self.board.columns[column_id].set_tasks(tasks)

    def _refresh_stat(self) -> None:
        total = sum(len(tasks) for tasks in self.data.values())
        done = sum(
            1 for tasks in self.data.values() for item in tasks if item.done
        )
        self.stat_label.setText(f"已完成 {done} / {total}")
