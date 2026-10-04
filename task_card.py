"""任务卡片：自绘勾选框 + 内容自适应高度 + 拖拽发起。

卡片只负责发出「我被勾选了」「我被拖走了」，跨栏是否接受由任务栏判断。
"""

from PyQt6.QtCore import QMimeData, QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models import COL_BACKLOG, TodayItem
from theme import ACCENT, SOURCE_COLOR, TEXT_DONE, TEXT_PRIMARY, rgba

# 拖拽携带的数据："{column_id}:{item_key}"，item_key 形如 daily:3
MIME_TYPE = "application/x-schedule-task"


class CircleCheck(QWidget):
    """圆形勾选框，选中后填充蓝底白勾。"""

    toggled = pyqtSignal(bool)

    SIZE = 18

    def __init__(self, checked: bool = False, locked: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._checked = checked
        self._locked = locked        # 到期前不允许打勾
        self._hover = False
        if locked:
            self.setToolTip("还没到设定日期，到期当天才能打勾")
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if self._checked != value:
            self._checked = value
            self.update()

    def enterEvent(self, event):
        if self._locked:
            return
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._locked:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1.0, 1.0, self.SIZE - 2.0, self.SIZE - 2.0)

        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#2F80ED"))
            painter.drawEllipse(rect)

            pen = QPen(QColor("#FFFFFF"), 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            path = QPainterPath()
            path.moveTo(self.SIZE * 0.28, self.SIZE * 0.52)
            path.lineTo(self.SIZE * 0.44, self.SIZE * 0.68)
            path.lineTo(self.SIZE * 0.73, self.SIZE * 0.34)
            painter.drawPath(path)
        else:
            if self._locked:
                painter.setPen(QPen(QColor("#DFE3E8"), 1.5))
                painter.setBrush(QColor("#F4F5F7"))
            else:
                border = QColor("#2F80ED") if self._hover else QColor("#C6CCD3")
                painter.setPen(QPen(border, 1.5))
                painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(rect)


class TaskCard(QFrame):
    """首页的单条任务卡片。"""

    state_changed = pyqtSignal(str, bool)   # item_key, 是否完成
    dismiss_requested = pyqtSignal(str)     # item_key
    step_back_requested = pyqtSignal(str)   # item_key，时期任务回退一个阶段
    menu_requested = pyqtSignal(str, object)  # item_key, 弹出菜单的全局坐标

    def __init__(self, item: TodayItem, parent=None):
        super().__init__(parent)
        self.item = item
        self._press_pos = QPoint()

        self.setObjectName("TaskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumWidth(160)
        if item.note:
            self.setToolTip(item.note)

        self._build()
        self._apply_state()

    # ---------- 构建 ----------

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.bar = QFrame()
        self.bar.setFixedWidth(4)
        self.bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.bar)

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 10, 11)
        body.setSpacing(6)
        outer.addLayout(body, 1)

        head = QHBoxLayout()
        head.setSpacing(9)
        self.check = CircleCheck(self.item.done, self.item.locked)
        self.check.toggled.connect(self._on_check)
        head.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        self.title = QLabel(self.item.title)
        self.title.setObjectName("TaskTitle")
        self.title.setWordWrap(True)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        head.addWidget(self.title, 1)

        if self.item.column == COL_BACKLOG:
            dismiss = QPushButton("✕")
            dismiss.setObjectName("IconButton")
            dismiss.setFixedWidth(24)
            dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
            dismiss.setToolTip("不再保留这条积压任务")
            dismiss.clicked.connect(lambda: self.dismiss_requested.emit(self.item.key))
            head.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)

        if self.item.step_back:
            step_back = QPushButton("↩")
            step_back.setObjectName("IconButton")
            step_back.setFixedWidth(24)
            step_back.setCursor(Qt.CursorShape.PointingHandCursor)
            step_back.setToolTip("返回上一阶段")
            step_back.clicked.connect(
                lambda: self.step_back_requested.emit(self.item.key)
            )
            head.addWidget(step_back, 0, Qt.AlignmentFlag.AlignTop)

        more = QPushButton("⋯")
        more.setObjectName("MoreButton")
        more.setFixedSize(30, 26)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setToolTip("任务设定：编辑 / 删除")
        more.clicked.connect(
            lambda: self.menu_requested.emit(
                self.item.key, more.mapToGlobal(more.rect().bottomLeft())
            )
        )
        head.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)

        body.addLayout(head)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(27, 0, 0, 0)
        meta_row.addWidget(self._source_chip())

        meta_text = self._meta_text()
        if meta_text:
            label = QLabel(meta_text)
            label.setObjectName("TaskMeta")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            meta_row.addWidget(label)
        meta_row.addStretch(1)
        body.addLayout(meta_row)

        if self.item.foot:
            foot = QLabel(self.item.foot)
            foot.setObjectName("TaskFoot")
            foot.setWordWrap(True)
            foot.setContentsMargins(27, 0, 0, 0)
            foot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            body.addWidget(foot)

    def _source_chip(self) -> QLabel:
        color = SOURCE_COLOR[self.item.source]
        # 每日任务按周期显示每日 / 每周 / 每月，其余按来源显示
        chip = QLabel(self.item.source_label)
        chip.setStyleSheet(
            f"background: {rgba(color, 0.12)}; color: {color};"
            "border-radius: 4px; padding: 1px 6px; font-size: 11px;"
        )
        chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return chip

    def _meta_text(self) -> str:
        parts: list[str] = []
        time_text = self.item.time_display
        if time_text:
            parts.append(time_text)
        if self.item.streak_text:
            parts.append(self.item.streak_text)
        return " · ".join(parts)

    # ---------- 状态 ----------

    def _on_check(self, checked: bool) -> None:
        self.item.done = checked
        self._apply_state()
        self.state_changed.emit(self.item.key, checked)

    def _apply_state(self) -> None:
        done = self.item.done

        self.setObjectName("TaskCardDone" if done else "TaskCard")
        self.style().unpolish(self)
        self.style().polish(self)

        font = self.title.font()
        font.setStrikeOut(done)
        self.title.setFont(font)
        self.title.setStyleSheet(f"color: {TEXT_DONE if done else TEXT_PRIMARY};")

        bar_color = ACCENT[self.item.column]
        self.bar.setStyleSheet(
            f"background: {rgba(bar_color, 0.3) if done else bar_color};"
            "border-top-left-radius: 10px; border-bottom-left-radius: 10px;"
        )

    # ---------- 拖拽发起 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        payload = f"{self.item.column}:{self.item.key}"
        mime.setData(MIME_TYPE, payload.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self._press_pos)

        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.MoveAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
