"""三个任务编辑对话框：长期每日任务 / 某日临时任务 / 时期任务。"""

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

from sound import (
    AUDIO_FILTER,
    DEFAULT_CHOICE,
    SYSTEM_SOUNDS,
    alias_choice,
    choice_label,
    file_choice,
    play_remind_sound,
)
from storage import (
    DEFAULT_REMIND_MINUTES,
    NAV_POSITIONS,
    NAV_TOP,
    REMIND_MODES,
    DailyTask,
    OnceTask,
    PeriodTask,
)

DATE_FORMAT = "yyyy-MM-dd"


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


# ---------------- 长期每日任务 ----------------

class DailyTaskDialog(_FormDialog):
    def __init__(self, task: DailyTask | None = None, groups: list[str] | None = None,
                 parent=None, default_remind: int = DEFAULT_REMIND_MINUTES):
        super().__init__("编辑长期每日任务" if task else "新建长期每日任务", parent)

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("任务名称，如：俯卧撑")
        self.form.addRow("任务名称", self.title_edit)

        self.group_combo = _group_combo(groups, task.group_name if task else "")
        self.form.addRow("归属分组", self.group_combo)

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

    def validate(self) -> str:
        if not self.title_edit.text().strip():
            return "请填写任务名称。"
        return ""

    def values(self) -> dict:
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
    """主页设置：默认提前提醒、提醒方式与音频、导航位置。"""

    def __init__(self, default_remind: int = DEFAULT_REMIND_MINUTES,
                 remind_mode: str = "", sound_enabled: bool = True,
                 sound_choice: str = "", sound_files: list[str] | None = None,
                 nav_position: str = NAV_TOP, parent=None):
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
        add_audio.setToolTip("添加本地 wav 音频，之后可以在左侧下拉里选中使用")
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

        self.nav_combo = QComboBox()
        for value, label in NAV_POSITIONS:
            self.nav_combo.addItem(label, value)
        index = self.nav_combo.findData(nav_position)
        self.nav_combo.setCurrentIndex(index if index >= 0 else 0)
        self.form.addRow("导航位置", self.nav_combo)

        hint = QLabel(
            "默认提前提醒是新建有时限任务时提醒输入框的初始值，单条任务里仍可单独改；"
            "填 0 表示默认不提醒。\n"
            "导航位置决定「今日一览 / 备忘录」的切换按钮摆在窗口顶部还是左侧。"
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        self.form.addRow(hint)

    def _fill_sound_combo(self, choice: str) -> None:
        """填一遍可选音频：系统音 + 已添加的本地文件，并选中当前那一项。"""
        self.sound_combo.clear()
        for alias, label in SYSTEM_SOUNDS:
            self.sound_combo.addItem(label, alias_choice(alias))
        for path in self.sound_files:
            self.sound_combo.addItem(choice_label(file_choice(path)), file_choice(path))
        index = self.sound_combo.findData(choice or DEFAULT_CHOICE)
        self.sound_combo.setCurrentIndex(index if index >= 0 else 0)

    def _add_sound_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择提醒音频", "", AUDIO_FILTER)
        if not path:
            return
        if path not in self.sound_files:
            self.sound_files.append(path)
        self._fill_sound_combo(file_choice(path))

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
        }
