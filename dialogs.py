"""三个任务编辑对话框：长期任务 / 某日临时任务 / 时期任务。"""

import os

from PyQt6.QtCore import QDate, QTime, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from models import (
    REPEAT_CHOICES,
    REPEAT_DAILY,
    REPEAT_MONTHLY,
    REPEAT_WEEKLY,
    WEEKDAY_NAMES,
)
from sound import (
    AUDIO_FILTER,
    DEFAULT_CHOICE,
    SYSTEM_SOUNDS,
    alias_choice,
    choice_label,
    ensure_sound_dir,
    file_choice,
    list_sound_files,
    play_remind_sound,
)
from hotkey import parse
from storage import (
    DEFAULT_NEW_NOTE_HOTKEY,
    DEFAULT_REMIND_MINUTES,
    NAV_POSITIONS,
    NAV_TOP,
    REMIND_MODES,
    DailyTask,
    OnceTask,
    PeriodTask,
)

DATE_FORMAT = "yyyy-MM-dd"

# Qt 的按键 → 快捷键文本里的主键名：字母、数字、功能键，外加几个常用键
_KEY_NAMES: dict[int, str] = {}
for _code in range(ord("A"), ord("Z") + 1):
    _KEY_NAMES[_code] = chr(_code)
for _code in range(ord("0"), ord("9") + 1):
    _KEY_NAMES[_code] = chr(_code)
for _n in range(1, 25):
    _KEY_NAMES[Qt.Key.Key_F1.value + _n - 1] = f"F{_n}"
_KEY_NAMES.update({
    Qt.Key.Key_Space.value: "Space",
    Qt.Key.Key_Tab.value: "Tab",
    Qt.Key.Key_Return.value: "Enter",
    Qt.Key.Key_Backspace.value: "Backspace",
    Qt.Key.Key_Delete.value: "Delete",
    Qt.Key.Key_Insert.value: "Insert",
    Qt.Key.Key_Home.value: "Home",
    Qt.Key.Key_End.value: "End",
    Qt.Key.Key_PageUp.value: "PageUp",
    Qt.Key.Key_PageDown.value: "PageDown",
    Qt.Key.Key_Left.value: "Left",
    Qt.Key.Key_Up.value: "Up",
    Qt.Key.Key_Right.value: "Right",
    Qt.Key.Key_Down.value: "Down",
})


class HotkeyEdit(QLineEdit):
    """点一下、按一组键，就把这组键记下来的输入框。"""

    def __init__(self, shortcut: str = "", parent=None):
        super().__init__(shortcut, parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点这里，再按下要用的组合键")
        self.setToolTip(
            "至少要有一个 Ctrl / Alt / Shift / Win；单独一个 F1~F24 也认。"
            "按 Esc、退格或 Delete 清空，表示不启用快捷键。"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (
            Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_AltGr,
            Qt.Key.Key_Shift, Qt.Key.Key_Meta, Qt.Key.Key_CapsLock,
        ):
            return          # 只按住修饰键还不算，等真正按下主键
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.setText("")
            return
        name = _KEY_NAMES.get(int(key))
        if name is None:
            return
        mods = event.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("Win")
        # 光秃秃的主键会抢走整机的这个按键，只有功能键可以单独用
        if not parts and not name.startswith("F"):
            return
        parts.append(name)
        self.setText("+".join(parts))


def _to_qdate(day_str: str | None) -> QDate:
    if not day_str:
        return QDate.currentDate()
    parsed = QDate.fromString(day_str, DATE_FORMAT)
    return parsed if parsed.isValid() else QDate.currentDate()


def _date_edit(day_str: str | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat(DATE_FORMAT)
    edit.setDate(_to_qdate(day_str))
    # 上下微调箭头容易误点，去掉；日期靠弹出的日历挑
    edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    edit.setMinimumWidth(132)
    edit.setToolTip("点右侧箭头展开日历挑选日期")
    return edit


def _time_edit(text: str = "") -> QTimeEdit:
    edit = QTimeEdit()
    edit.setDisplayFormat("HH:mm")
    parsed = QTime.fromString(text, "HH:mm") if text else QTime(15, 0)
    edit.setTime(parsed if parsed.isValid() else QTime(15, 0))
    edit.setMinimumWidth(96)
    return edit


def _remind_spin(minutes: int = DEFAULT_REMIND_MINUTES) -> QSpinBox:
    """到点前多少分钟提醒；0 表示不提醒。"""
    spin = QSpinBox()
    spin.setRange(0, 600)
    spin.setSingleStep(5)
    spin.setValue(max(0, int(minutes)))
    spin.setSuffix(" 分钟")
    spin.setMinimumWidth(96)
    spin.setToolTip("到点前多少分钟提醒；填 0 表示不提醒")
    return spin


NO_GROUP = "（不归入分组）"


def _group_combo(groups: list[str] | None, current: str = "") -> QComboBox:
    """归属分组下拉框：可下拉选已有分组，也可手动输入新分组。"""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.addItem(NO_GROUP)
    for name in groups or []:
        combo.addItem(name)
    if current and combo.findText(current) < 0:
        combo.setCurrentText(current)   # 旧数据里的组名已不存在
    elif current:
        combo.setCurrentIndex(combo.findText(current))
    combo.setToolTip("同组的任务在首页折叠成一组显示，点击组名可折叠隐藏")
    return combo


def _group_value(combo: QComboBox) -> str:
    """第一项是「不归入分组」占位；其余取当前文本，手输的新组名也走这里。"""
    text = combo.currentText().strip()
    return "" if text == NO_GROUP else text


class _FormDialog(QDialog):
    """统一的表单对话框外壳：表单区 + 保存/取消 + 错误提示。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.form.setSpacing(10)
        root.addLayout(self.form)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("保存")
        ok.setObjectName("PrimaryButton")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("GhostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_accept(self) -> None:
        problem = self.validate()
        if problem:
            self.error_label.setText(problem)
            self.error_label.show()
            return
        self.accept()

    def validate(self) -> str:
        return ""

    @staticmethod
    def _note_edit(text: str = "") -> QTextEdit:
        edit = QTextEdit()
        edit.setPlainText(text)
        edit.setFixedHeight(62)
        return edit

    @staticmethod
    def _check_row(check: QCheckBox, field: QWidget) -> QWidget:
        """把开关和它控制的输入框并排一行，避免出现空标签的错位。"""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(check, 0)
        row.addWidget(field, 0)
        row.addStretch(1)
        return holder


# ---------------- 时期任务的阶段编辑 ----------------

class StageRow(QWidget):
    """一行阶段：阶段名称 + 截止日期 + 删除。"""

    removed = pyqtSignal(object)

    def __init__(self, title: str = "", deadline: str | None = None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.title_edit = QLineEdit(title)
        self.title_edit.setPlaceholderText("阶段名称，如：完成综述")
        row.addWidget(self.title_edit, 1)

        self.date_edit = _date_edit(deadline)
        row.addWidget(self.date_edit, 0)

        remove = QPushButton("✕")
        remove.setObjectName("IconButton")
        remove.setFixedWidth(30)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("删除该阶段")
        remove.clicked.connect(lambda: self.removed.emit(self))
        row.addWidget(remove)

    def values(self) -> tuple[str, str]:
        return self.title_edit.text().strip(), self.date_edit.date().toString(DATE_FORMAT)


class StageListEditor(QWidget):
    """可增删的阶段列表。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[StageRow] = []

        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)

        self.hint = QLabel("尚未添加阶段。也可只填最终期限，之后再回来拆分。")
        self.hint.setObjectName("FieldHint")
        self.hint.setWordWrap(True)
        self.box.addWidget(self.hint)

        add = QPushButton("+ 添加阶段")
        add.setObjectName("GhostButton")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda: self.add_row())
        self.box.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

    def add_row(self, title: str = "", deadline: str | None = None) -> None:
        row = StageRow(title, deadline)
        row.removed.connect(self._remove_row)
        self.box.insertWidget(len(self.rows), row)
        self.rows.append(row)
        self._refresh_hint()

    def _remove_row(self, row: StageRow) -> None:
        self.rows.remove(row)
        self.box.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh_hint()

    def set_stages(self, stages: list[tuple[str, str]]) -> None:
        for row in list(self.rows):
            self._remove_row(row)
        for title, deadline in stages:
            self.add_row(title, deadline)

    def stages(self) -> list[tuple[str, str]]:
        return [values for values in (row.values() for row in self.rows) if values[0]]

    def _refresh_hint(self) -> None:
        self.hint.setVisible(not self.rows)


# ---------------- 长期任务 ----------------

class DailyTaskDialog(_FormDialog):
    def __init__(self, task: DailyTask | None = None, groups: list[str] | None = None,
                 parent=None, default_remind: int = DEFAULT_REMIND_MINUTES):
        super().__init__("编辑长期任务" if task else "新建长期任务", parent)

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("任务名称，如：俯卧撑")
        self.form.addRow("任务名称", self.title_edit)

        self.group_combo = _group_combo(groups, task.group_name if task else "")
        self.form.addRow("归属分组", self.group_combo)

        # 重复周期：每天 / 每周固定星期几 / 每月固定几号
        self.repeat_combo = QComboBox()
        for value, label in REPEAT_CHOICES:
            self.repeat_combo.addItem(label, value)
        current_repeat = task.repeat if task else REPEAT_DAILY
        repeat_index = self.repeat_combo.findData(current_repeat)
        self.repeat_combo.setCurrentIndex(repeat_index if repeat_index >= 0 else 0)
        self.repeat_combo.setToolTip(
            "每天：天天都出现；每周：只在选定的星期几出现；每月：只在选定的几号出现"
        )
        self.form.addRow("重复周期", self.repeat_combo)

        # 每周的星期几 / 每月的几号：两个控件放进同一行，按周期切换显示
        today = QDate.currentDate()
        self.weekday_combo = QComboBox()
        for index, name in enumerate(WEEKDAY_NAMES):
            self.weekday_combo.addItem(name, index)
        default_weekday = (today.dayOfWeek() - 1) % 7
        if task and task.repeat == REPEAT_WEEKLY:
            default_weekday = int(task.repeat_day) % 7
        self.weekday_combo.setCurrentIndex(default_weekday)
        self.weekday_combo.setToolTip("选它固定在星期几出现")

        self.month_spin = QSpinBox()
        self.month_spin.setRange(1, 31)
        self.month_spin.setSuffix(" 号")
        default_month_day = today.day()
        if task and task.repeat == REPEAT_MONTHLY and 1 <= int(task.repeat_day) <= 31:
            default_month_day = int(task.repeat_day)
        self.month_spin.setValue(default_month_day)
        self.month_spin.setToolTip("选它固定在每月几号出现；当月没有该日时落在当月最后一天")

        self.repeat_hint = QLabel("每天都会出现")
        self.repeat_hint.setObjectName("FieldHint")

        self.repeat_detail = QWidget()
        detail_row = QHBoxLayout(self.repeat_detail)
        detail_row.setContentsMargins(0, 0, 0, 0)
        detail_row.setSpacing(8)
        detail_row.addWidget(self.weekday_combo, 0)
        detail_row.addWidget(self.month_spin, 0)
        detail_row.addWidget(self.repeat_hint, 0)
        detail_row.addStretch(1)
        self.form.addRow("出现于", self.repeat_detail)
        self.repeat_combo.currentIndexChanged.connect(self._sync_repeat_detail)
        self._sync_repeat_detail()

        self.deadline_check = QCheckBox("启用")
        self.deadline_check.setChecked(bool(task and task.has_deadline))
        self.deadline_check.setToolTip("勾选后进入首页「刻不容缓」，否则进入「案无留牍」")
        self.deadline_time = _time_edit(task.deadline_time if task else "15:00")
        self.form.addRow(
            "提醒时间", self._check_row(self.deadline_check, self.deadline_time)
        )
        self.deadline_check.toggled.connect(self.deadline_time.setEnabled)
        self.deadline_time.setEnabled(self.deadline_check.isChecked())

        self.remind_spin = _remind_spin(
            task.remind_minutes if task else default_remind
        )
        self.form.addRow("提前提醒", self.remind_spin)
        self.deadline_check.toggled.connect(self.remind_spin.setEnabled)
        self.remind_spin.setEnabled(self.deadline_check.isChecked())

        self.backlog_check = QCheckBox("进入「陈年旧账」，可事后补勾")
        self.backlog_check.setChecked(task.backlog if task else True)
        self.backlog_check.setToolTip(
            "取消勾选后，漏勾的日子不会出现在首页「陈年旧账」，也就无法补勾"
        )
        self.form.addRow("未完成时", self.backlog_check)

        self.note_edit = self._note_edit(task.note if task else "")
        self.form.addRow("备注", self.note_edit)

        self.title_edit.setFocus()

    def _sync_repeat_detail(self) -> None:
        """按当前周期显示对应的细节控件：每天只留一句说明。"""
        repeat = self.repeat_combo.currentData()
        self.weekday_combo.setVisible(repeat == REPEAT_WEEKLY)
        self.month_spin.setVisible(repeat == REPEAT_MONTHLY)
        self.repeat_hint.setVisible(repeat == REPEAT_DAILY)

    def validate(self) -> str:
        if not self.title_edit.text().strip():
            return "请填写任务名称。"
        return ""

    def values(self) -> dict:
        repeat = self.repeat_combo.currentData()
        if repeat == REPEAT_WEEKLY:
            repeat_day = int(self.weekday_combo.currentData())
        elif repeat == REPEAT_MONTHLY:
            repeat_day = self.month_spin.value()
        else:
            repeat_day = 0
        return {
            "title": self.title_edit.text().strip(),
            "group_name": _group_value(self.group_combo),
            "has_deadline": self.deadline_check.isChecked(),
            "deadline_time": (
                self.deadline_time.time().toString("HH:mm")
                if self.deadline_check.isChecked() else ""
            ),
            "note": self.note_edit.toPlainText().strip(),
            "backlog": self.backlog_check.isChecked(),
            "remind_minutes": self.remind_spin.value(),
            "repeat": repeat,
            "repeat_day": repeat_day,
        }


# ---------------- 某日临时任务 ----------------

class OnceTaskDialog(_FormDialog):
    def __init__(self, task: OnceTask | None = None, groups: list[str] | None = None,
                 parent=None, default_remind: int = DEFAULT_REMIND_MINUTES):
        super().__init__("编辑某日临时任务" if task else "新建某日临时任务", parent)

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("任务名称，如：抢演唱会门票")
        self.form.addRow("任务名称", self.title_edit)

        self.group_combo = _group_combo(groups, task.group_name if task else "")
        self.form.addRow("归属分组", self.group_combo)

        self.date_edit = _date_edit(task.day if task else None)
        self.form.addRow("日期", self.date_edit)

        self.time_check = QCheckBox("启用")
        self.time_check.setChecked(bool(task and task.time))
        self.time_check.setToolTip("勾选后首页会显示具体时刻")
        self.time_edit = _time_edit(task.time if task else "08:00")
        self.form.addRow("具体时间", self._check_row(self.time_check, self.time_edit))
        self.time_check.toggled.connect(self.time_edit.setEnabled)
        self.time_edit.setEnabled(self.time_check.isChecked())

        self.remind_spin = _remind_spin(
            task.remind_minutes if task else default_remind
        )
        self.form.addRow("提前提醒", self.remind_spin)
        self.time_check.toggled.connect(self.remind_spin.setEnabled)
        self.remind_spin.setEnabled(self.time_check.isChecked())

        self.note_edit = self._note_edit(task.note if task else "")
        self.form.addRow("备注", self.note_edit)

        self.always_show_check = QCheckBox("每天都显示在「案无留牍」")
        self.always_show_check.setChecked(bool(task and task.always_show))
        self.always_show_check.setToolTip(
            "勾选后从建好那天起每天都能看到；不勾选则只在设定日期的前 3 天出现"
        )
        self.form.addRow("显示时机", self.always_show_check)

        hint = QLabel(
            "提前显示只是提醒：不勾选时，这条任务从设定日期的前 3 天起出现在"
            "「案无留牍」，到了设定日期当天才转入「刻不容缓」。\n"
            "无论勾选与否，都要等到设定日期当天才能打勾，提前是勾不上的。"
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        self.form.addRow(hint)

        self.title_edit.setFocus()

    def validate(self) -> str:
        if not self.title_edit.text().strip():
            return "请填写任务名称。"
        return ""

    def values(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "group_name": _group_value(self.group_combo),
            "day": self.date_edit.date().toString(DATE_FORMAT),
            "time": self.time_edit.time().toString("HH:mm") if self.time_check.isChecked() else "",
            "note": self.note_edit.toPlainText().strip(),
            "always_show": self.always_show_check.isChecked(),
            "remind_minutes": self.remind_spin.value(),
        }


# ---------------- 时期任务 ----------------

class PeriodTaskDialog(_FormDialog):
    def __init__(self, task: PeriodTask | None = None,
                 stages: list[tuple[str, str]] | None = None,
                 stage_done: list[bool] | None = None,
                 groups: list[str] | None = None, parent=None):
        super().__init__("编辑时期任务" if task else "新建时期任务", parent)
        self.setMinimumWidth(560)
        self._stage_done = list(stage_done or [])

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("任务名称，如：完成毕业论文")
        self.form.addRow("任务名称", self.title_edit)

        self.group_combo = _group_combo(groups, task.group_name if task else "")
        self.form.addRow("归属分组", self.group_combo)

        self.deadline_edit = _date_edit(task.deadline if task else None)
        self.form.addRow("最终期限", self.deadline_edit)

        self.stage_editor = StageListEditor()
        self.stage_editor.set_stages(stages or [])
        self.form.addRow("阶段拆分", self.stage_editor)

        self.note_edit = self._note_edit(task.note if task else "")
        self.form.addRow("备注", self.note_edit)

        self.title_edit.setFocus()

    def validate(self) -> str:
        if not self.title_edit.text().strip():
            return "请填写任务名称。"
        return ""

    def values(self) -> dict:
        stages = self.stage_editor.stages()
        # 阶段数量可能被改动，只保留仍然存在的完成标记
        done_flags = [
            self._stage_done[index] if index < len(self._stage_done) else False
            for index in range(len(stages))
        ]
        return {
            "title": self.title_edit.text().strip(),
            "group_name": _group_value(self.group_combo),
            "deadline": self.deadline_edit.date().toString(DATE_FORMAT),
            "stages": stages,
            "stage_done": done_flags,
            "note": self.note_edit.toPlainText().strip(),
        }


# ---------------- 主页设置 ----------------

class SettingsDialog(_FormDialog):
    """主页设置：默认提前提醒、提醒方式与音频、导航位置、自动更新。"""

    check_update_requested = pyqtSignal()   # 用户点了「检查更新…」

    def __init__(self, default_remind: int = DEFAULT_REMIND_MINUTES,
                 remind_mode: str = "", sound_enabled: bool = True,
                 sound_choice: str = "", sound_files: list[str] | None = None,
                 nav_position: str = NAV_TOP,
                 new_note_hotkey: str = DEFAULT_NEW_NOTE_HOTKEY,
                 app_version: str = "", auto_update: bool = True, parent=None):
        super().__init__("设置", parent)
        self.setMinimumWidth(520)

        self.remind_spin = _remind_spin(default_remind)
        self.form.addRow("默认提前提醒", self.remind_spin)

        self.mode_combo = QComboBox()
        for value, label in REMIND_MODES:
            self.mode_combo.addItem(label, value)
        index = self.mode_combo.findData(remind_mode)
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.mode_combo.setMinimumWidth(260)
        self.form.addRow("提醒方式", self.mode_combo)

        self.sound_check = QCheckBox("提醒时响提示音")
        self.sound_check.setChecked(sound_enabled)
        self.sound_check.setToolTip("关掉后到点只在界面上提示，不出声")
        self.form.addRow("提醒声音", self.sound_check)

        # 提醒音频：系统音在前，用户自己添加的文件排在后
        self.sound_files = list(sound_files or [])
        self.sound_combo = QComboBox()
        self.sound_combo.setMinimumWidth(200)
        self._fill_sound_combo(sound_choice)

        add_audio = QPushButton("添加音频…")
        add_audio.setObjectName("GhostButton")
        add_audio.setCursor(Qt.CursorShape.PointingHandCursor)
        add_audio.setToolTip("从别处挑一个 wav / mp3 音频，之后可以在左侧下拉里选中使用")
        add_audio.clicked.connect(self._add_sound_file)

        preview = QPushButton("试听")
        preview.setObjectName("GhostButton")
        preview.setCursor(Qt.CursorShape.PointingHandCursor)
        preview.setToolTip("听一下当前选中的提醒音")
        preview.clicked.connect(self._preview_sound)

        audio_row = QWidget()
        row = QHBoxLayout(audio_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.sound_combo, 1)
        row.addWidget(add_audio, 0)
        row.addWidget(preview, 0)
        self.form.addRow("提醒音频", audio_row)

        # 铃声文件夹：用户把音乐丢进去，这里扫描出来后即可在下拉里选
        open_folder = QPushButton("打开铃声文件夹")
        open_folder.setObjectName("GhostButton")
        open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder.setToolTip(
            "把 wav / mp3 音乐放进程序目录下的「铃声」文件夹，"
            "回来重开本设置即可在下拉里选中：\n" + str(ensure_sound_dir())
        )
        open_folder.clicked.connect(self._open_sound_folder)
        self.form.addRow(open_folder)

        self.nav_combo = QComboBox()
        for value, label in NAV_POSITIONS:
            self.nav_combo.addItem(label, value)
        index = self.nav_combo.findData(nav_position)
        self.nav_combo.setCurrentIndex(index if index >= 0 else 0)
        self.form.addRow("导航位置", self.nav_combo)

        self.hotkey_edit = HotkeyEdit(new_note_hotkey)
        self.form.addRow("便签快捷键", self.hotkey_edit)

        self.auto_update_check = QCheckBox("启动时自动检查更新")
        self.auto_update_check.setChecked(auto_update)
        self.auto_update_check.setToolTip(
            "每 24 小时最多查一次，发现新版本会先问过你，不会偷偷替换"
        )
        self.form.addRow("自动更新", self.auto_update_check)

        version_label = QLabel(f"当前版本 v{app_version}" if app_version else "当前版本未知")
        version_label.setObjectName("FieldHint")
        check_button = QPushButton("检查更新…")
        check_button.setObjectName("GhostButton")
        check_button.setCursor(Qt.CursorShape.PointingHandCursor)
        check_button.setToolTip("现在就去 GitHub 看看有没有新版本")
        check_button.clicked.connect(self.check_update_requested.emit)

        version_row = QWidget()
        version_layout = QHBoxLayout(version_row)
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(8)
        version_layout.addWidget(version_label, 1)
        version_layout.addWidget(check_button, 0)
        self.form.addRow("版本", version_row)

        hint = QLabel(
            "默认提前提醒是新建有时限任务时提醒输入框的初始值，单条任务里仍可单独改；"
            "填 0 表示默认不提醒。\n"
            "提醒音频支持系统音与 wav / mp3：把音乐放进「铃声」文件夹，"
            "或点「添加音频…」挑一个文件，都能在下拉里选中。\n"
            "导航位置决定「今日一览 / 备忘录」的切换按钮摆在窗口顶部还是左侧。\n"
            "便签快捷键在任何程序里按下都管用：直接在鼠标位置开一张桌面便签。"
            "点一下输入框再按一组键即可记录，按 Esc 清空表示不启用。\n"
            "自动更新只替换程序本身，日程数据与铃声都不会动；"
            "关掉后就只在点「检查更新…」时去查。"
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        self.form.addRow(hint)

    def validate(self) -> str:
        text = self.hotkey_edit.text().strip()
        if text and parse(text) is None:
            return "快捷键至少要有一个 Ctrl / Alt / Shift / Win；单独一个 F1~F24 也可以。"
        return ""

    def _sound_candidates(self) -> list[str]:
        """可选的本地音频：程序目录「铃声」文件夹里的 + 用户另外添加过的，去重。"""
        files: list[str] = []
        for path in list_sound_files() + self.sound_files:
            if path and path not in files:
                files.append(path)
        return files

    def _fill_sound_combo(self, choice: str) -> None:
        """填一遍可选音频：系统音 + 本地音频，并选中当前那一项。"""
        self.sound_combo.clear()
        for alias, label in SYSTEM_SOUNDS:
            self.sound_combo.addItem(label, alias_choice(alias))
        for path in self._sound_candidates():
            self.sound_combo.addItem(choice_label(file_choice(path)), file_choice(path))
        index = self.sound_combo.findData(choice or DEFAULT_CHOICE)
        self.sound_combo.setCurrentIndex(index if index >= 0 else 0)

    def _add_sound_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择提醒音频", str(ensure_sound_dir()), AUDIO_FILTER
        )
        if not path:
            return
        if path not in self.sound_files:
            self.sound_files.append(path)
        self._fill_sound_combo(file_choice(path))

    def _open_sound_folder(self) -> None:
        """打开「铃声」文件夹；用户放完音乐回来，重新扫描一遍供选择。"""
        folder = ensure_sound_dir()
        try:
            os.startfile(str(folder))
        except OSError:
            pass
        self._fill_sound_combo(self.sound_combo.currentData() or DEFAULT_CHOICE)

    def _preview_sound(self) -> None:
        play_remind_sound(self.sound_combo.currentData() or "")

    def values(self) -> dict:
        return {
            "default_remind": self.remind_spin.value(),
            "remind_mode": self.mode_combo.currentData(),
            "sound": self.sound_check.isChecked(),
            "sound_choice": self.sound_combo.currentData() or "",
            "sound_files": list(self.sound_files),
            "nav_position": self.nav_combo.currentData(),
            "new_note_hotkey": self.hotkey_edit.text().strip(),
            "auto_update": self.auto_update_check.isChecked(),
        }
