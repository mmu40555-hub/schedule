"""任务栏：栏头（标题 / 计数 / 宽度锁定）+ 组别分区 + 可滚动卡片区 + 栏内拖拽排序。

栏内先按组别分区，组别标题可点击折叠；拖拽仍然只在本栏内排序。
"""

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models import COL_BACKLOG, COLUMN_SUBTITLE, COLUMN_TITLE, UNGROUPED_LABEL, TodayItem
from task_card import MIME_TYPE, TaskCard
from theme import ACCENT


class GroupHeader(QFrame):
    """组别标题行：折叠箭头 + 组名 + 条数 + 组别设定的「⋯」。"""

    toggled = pyqtSignal(str)
    menu_requested = pyqtSignal(str, object)

    def __init__(self, name: str, count: int, collapsed: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(6)

        arrow = "▸" if collapsed else "▾"
        self.toggle = QPushButton(f"{arrow} {name or UNGROUPED_LABEL}")
        self.toggle.setObjectName("GroupToggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("点击折叠 / 展开这一组")
        self.toggle.clicked.connect(lambda: self.toggled.emit(name))
        row.addWidget(self.toggle)

        count_label = QLabel(str(count))
        count_label.setObjectName("ColumnSub")
        row.addWidget(count_label)
        row.addStretch(1)

        # 「未归组」不是登记过的组别，没有可管理的内容
        if name:
            more = QPushButton("⋯")
            more.setObjectName("MoreButton")
            more.setFixedSize(28, 22)
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.setToolTip("组别设定：重命名 / 删除")
            more.clicked.connect(
                lambda: self.menu_requested.emit(
                    name, more.mapToGlobal(more.rect().bottomLeft())
                )
            )
            row.addWidget(more)


class BacklogHeader(QFrame):
    """陈年旧账里的一批同名任务：折叠箭头 + 任务名 + 条数 + 「统一消去」。"""

    toggled = pyqtSignal(str)
    purge_requested = pyqtSignal(str)

    def __init__(self, title: str, count: int, collapsed: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(6)

        arrow = "▸" if collapsed else "▾"
        self.toggle = QPushButton(f"{arrow} {title}")
        self.toggle.setObjectName("GroupToggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("点击折叠 / 展开这一批同名旧账")
        self.toggle.clicked.connect(lambda: self.toggled.emit(title))
        row.addWidget(self.toggle)

        count_label = QLabel(str(count))
        count_label.setObjectName("ColumnSub")
        row.addWidget(count_label)
        row.addStretch(1)

        purge = QPushButton("统一消去")
        purge.setObjectName("GhostButton")
        purge.setCursor(Qt.CursorShape.PointingHandCursor)
        purge.setToolTip("把这一批同名旧账一起消去，之后不再保留")
        purge.clicked.connect(lambda: self.purge_requested.emit(title))
        row.addWidget(purge)


class _DropHost(QWidget):
    """卡片容器。只接受同栏卡片的拖拽，跨栏一律拒绝。"""

    dropped = pyqtSignal(str, str, int)  # column_id, task_id, 目标索引
    group_toggled = pyqtSignal(str)
    group_menu_requested = pyqtSignal(str, object)
    backlog_purge_requested = pyqtSignal(str)

    def __init__(self, column_id: str, parent=None):
        super().__init__(parent)
        self.column_id = column_id
        self.setAcceptDrops(True)
        # 折叠起来的卡片不参与落点计算，但序号仍是它在整栏里的真实位置
        self._visible: list[tuple[TaskCard, int]] = []
        self._total = 0
        self._line_y: float | None = None

        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(12, 6, 12, 12)
        self.box.setSpacing(8)
        self.box.addStretch(1)

    # ---------- 卡片管理 ----------

    def set_rows(self, rows: list[tuple], total: int) -> None:
        """rows 元素形如 ("group", 组名, 条数, 折叠?) 或 ("card", 卡片, 序号, 折叠?)。"""
        self.clear_rows()
        self._total = total
        if not total:
            hint = QLabel("暂无任务")
            hint.setObjectName("ColumnSub")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setContentsMargins(0, 20, 0, 0)
            self.box.addWidget(hint)

        for row in rows:
            if row[0] == "group":
                _, name, count, collapsed = row
                header = GroupHeader(name, count, collapsed)
                header.toggled.connect(self.group_toggled)
                header.menu_requested.connect(self.group_menu_requested)
                self.box.addWidget(header)
                continue

            if row[0] == "purge_group":
                _, title, count, collapsed = row
                header = BacklogHeader(title, count, collapsed)
                header.toggled.connect(self.group_toggled)
                header.purge_requested.connect(self.backlog_purge_requested)
                self.box.addWidget(header)
                continue

            _, card, index, collapsed = row
            self.box.addWidget(card)
            card.setVisible(not collapsed)
            if not collapsed:
                self._visible.append((card, index))
        self.box.addStretch(1)

    def clear_rows(self) -> None:
        while self.box.count():
            item = self.box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._visible = []
        self._total = 0

    # ---------- 拖拽 ----------

    def _payload(self, event) -> str | None:
        data = event.mimeData().data(MIME_TYPE)
        if data.isEmpty():
            return None
        text = bytes(data).decode("utf-8")
        if ":" not in text:
            return None
        column_id, task_id = text.split(":", 1)
        if column_id != self.column_id:
            return None
        return task_id

    def dragEnterEvent(self, event):
        if self._payload(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self._payload(event) is None:
            return
        event.acceptProposedAction()
        self._line_y = self._line_position(self._drop_index(event.position().toPoint()))
        self.update()

    def dragLeaveEvent(self, event):
        self._line_y = None
        self.update()

    def dropEvent(self, event):
        task_id = self._payload(event)
        index = self._drop_index(event.position().toPoint())
        self._line_y = None
        self.update()
        if task_id is None:
            return
        event.acceptProposedAction()
        self.dropped.emit(self.column_id, task_id, index)

    def _drop_index(self, pos) -> int:
        y = pos.y()
        for card, index in self._visible:
            if y < card.y() + card.height() / 2:
                return index
        return self._total

    def _line_position(self, index: int) -> float:
        spacing = self.box.spacing()
        if not self._visible:
            return float(self.box.contentsMargins().top())
        for card, card_index in self._visible:
            if card_index >= index:
                return card.y() - spacing / 2
        last = self._visible[-1][0]
        return last.y() + last.height() + spacing / 2

    def paintEvent(self, event):
        if self._line_y is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT[self.column_id]))
        painter.drawRoundedRect(
            QRectF(12, self._line_y - 1.5, self.width() - 24, 3), 1.5, 1.5
        )


class TaskColumn(QFrame):
    """首页的一栏。"""

    state_changed = pyqtSignal(str, bool)
    order_changed = pyqtSignal(str, str, int)
    dismiss_requested = pyqtSignal(str)
    step_back_requested = pyqtSignal(str)
    menu_requested = pyqtSignal(str, object)
    group_menu_requested = pyqtSignal(str, object)
    backlog_purge_requested = pyqtSignal(str)

    def __init__(self, column_id: str, parent=None):
        super().__init__(parent)
        self.column_id = column_id
        self.tasks: list[TodayItem] = []
        self.collapsed: set[str] = set()   # 本栏里被折叠起来的组别名

        self.setMinimumWidth(180)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        root.addLayout(self._build_head())
        root.addWidget(self._build_scroll(), 1)

    def _build_head(self) -> QVBoxLayout:
        head = QVBoxLayout()
        head.setContentsMargins(12, 0, 12, 0)
        head.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(7)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {ACCENT[self.column_id]}; font-size: 11px;")
        top.addWidget(dot)

        title = QLabel(COLUMN_TITLE[self.column_id])
        title.setObjectName("ColumnTitle")
        top.addWidget(title)

        self.count_label = QLabel("0/0")
        self.count_label.setObjectName("ColumnSub")
        top.addWidget(self.count_label)
        top.addStretch(1)

        head.addLayout(top)

        sub = QLabel(COLUMN_SUBTITLE[self.column_id])
        sub.setObjectName("ColumnSub")
        head.addWidget(sub)

        return head

    def _build_scroll(self) -> QScrollArea:
        self.host = _DropHost(self.column_id)
        self.host.dropped.connect(self.order_changed)
        self.host.group_toggled.connect(self._on_group_toggled)
        self.host.group_menu_requested.connect(self.group_menu_requested)
        self.host.backlog_purge_requested.connect(self.backlog_purge_requested)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.host)
        return scroll

    # ---------- 数据 ----------

    def set_tasks(self, tasks: list[TodayItem]) -> None:
        self.tasks = tasks

        # 陈年旧账只按任务名折叠：同名积压项收进一组，组头可「统一消去」；
        # 其余栏按归属分组折叠，组别之间按首次出现的顺序排列。
        group_by_title = self.column_id == COL_BACKLOG
        sections: dict[str, list[tuple[int, TaskCard]]] = {}
        for index, item in enumerate(tasks):
            card = TaskCard(item)
            card.state_changed.connect(self.state_changed)
            card.dismiss_requested.connect(self.dismiss_requested)
            card.step_back_requested.connect(self.step_back_requested)
            card.menu_requested.connect(self.menu_requested)
            key = item.title if group_by_title else item.group
            sections.setdefault(key, []).append((index, card))

        rows: list[tuple] = []
        header_kind = "purge_group" if group_by_title else "group"
        for key, entries in sections.items():
            collapsed = key in self.collapsed
            rows.append((header_kind, key, len(entries), collapsed))
            rows.extend(("card", card, index, collapsed) for index, card in entries)

        self.host.set_rows(rows, len(tasks))
        self.refresh_count()

    def _on_group_toggled(self, group: str) -> None:
        if group in self.collapsed:
            self.collapsed.discard(group)
        else:
            self.collapsed.add(group)
        self.set_tasks(self.tasks)

    def refresh_count(self) -> None:
        done = sum(1 for item in self.tasks if item.done)
        self.count_label.setText(f"{done}/{len(self.tasks)}")
