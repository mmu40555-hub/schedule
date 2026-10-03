"""桌面悬浮窗：常驻桌面，一次只显示一个栏目，顶上三个小页签切换。

勾选首页的「悬浮窗」后出现；无边框、始终置顶，拖标题栏移动，右下角可拉伸。
另有：
- 透明度拉条（档位写进 app_settings，下次打开照旧）
- 窗内到点提醒条
- 上沿拖到屏幕顶部会自动收起，只留一条小横条，鼠标碰到再滑下来
"""

from PyQt6.QtCore import (
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from models import COLUMN_ORDER, COLUMN_TITLE
from storage import (
    DEFAULT_FLOAT_OPACITY,
    MIN_FLOAT_OPACITY,
    SETTING_FLOAT_OPACITY,
    Store,
)
from task_column import TaskColumn
from theme import APP_QSS

# 窗口上沿离屏幕顶部多近算「贴顶」
EDGE_TOLERANCE = 12
# 收起后留在屏幕顶上的小横条高度 / 鼠标判定高度
EDGE_STRIP_HEIGHT = 6
EDGE_HIT_HEIGHT = 12
# 收起与展开的滑行时长，以及盯着鼠标位置的轮询间隔
EDGE_ANIM_MS = 150
EDGE_POLL_MS = 200


def clamp_opacity(value: float) -> float:
    """透明度卡在 30% ~ 100%：再低就找不着调整按钮了。"""
    return max(MIN_FLOAT_OPACITY, min(1.0, float(value)))


def load_opacity(store: Store) -> float:
    """读回上次记住的透明度，没存过或存坏了就用默认值。"""
    raw = store.get_setting(SETTING_FLOAT_OPACITY, "")
    try:
        value = float(raw)
    except ValueError:
        value = DEFAULT_FLOAT_OPACITY
    return clamp_opacity(value)


class EdgeHandle(QWidget):
    """悬浮窗贴顶收起后留下的那条小横条，鼠标碰它就展开。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("EdgeHandle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(APP_QSS)
        self.setFixedHeight(EDGE_STRIP_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("鼠标移过来展开悬浮窗")


class OpacityPopup(QWidget):
    """拉条调透明度的浮层：拖动即时生效，点别处自动收起。"""

    opacity_changed = pyqtSignal(float)

    def __init__(self, value: float, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("OpacityPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 独立顶层浮层，样式表要自己挂一份
        self.setStyleSheet(APP_QSS)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        icon = QLabel("◐")
        icon.setObjectName("OpacityIcon")
        row.addWidget(icon)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("OpacitySlider")
        self.slider.setRange(int(round(MIN_FLOAT_OPACITY * 100)), 100)
        self.slider.setFixedWidth(160)
        self.slider.setToolTip(
            f"左右拖动调整悬浮窗透明度（最低 {int(round(MIN_FLOAT_OPACITY * 100))}%）"
        )
        row.addWidget(self.slider)

        self.value_label = QLabel()
        self.value_label.setObjectName("OpacityValue")
        self.value_label.setFixedWidth(40)
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(self.value_label)

        self.slider.setValue(int(round(clamp_opacity(value) * 100)))
        self._sync_label(self.slider.value())
        self.slider.valueChanged.connect(self._on_changed)

    def _on_changed(self, value: int) -> None:
        self._sync_label(value)
        self.opacity_changed.emit(value / 100)

    def _sync_label(self, value: int) -> None:
        self.value_label.setText(f"{value}%")

    def popup_at(self, button: QPushButton) -> None:
        """贴着按钮下沿弹出；靠屏幕右边时往回收一点，免得露到屏幕外。"""
        self.adjustSize()
        pos = button.mapToGlobal(button.rect().bottomLeft())
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(pos.x(), area.right() - self.width() - 8))
            pos.setX(x)
        self.move(pos)
        self.show()


class FloatingBoard(QWidget):
    """一次只显示一个栏目的悬浮窗。"""

    closed = pyqtSignal()

    def __init__(self, store: Store, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.store = store
        self.setObjectName("FloatingBoard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 独立的顶层窗口，样式表要自己挂一份
        self.setStyleSheet(APP_QSS)
        self.setWindowTitle("今日一览 · 悬浮窗")
        self.resize(340, 470)
        self.setMinimumSize(260, 300)
        self._drag_offset = None

        self.opacity = load_opacity(store)
        self.setWindowOpacity(self.opacity)
        self.opacity_popup: OpacityPopup | None = None

        # 贴顶自动收起：edge_mode 开着时，鼠标不在窗口里就只剩一条小横条
        self.edge_mode = False
        self.edge_collapsed = False
        self.edge_handle = EdgeHandle()
        self.edge_anim: QPropertyAnimation | None = None
        # 收起动画里自己藏的窗口，不算「外面把它关了」
        self._internal_hide = False
        self.edge_timer = QTimer(self)
        self.edge_timer.setInterval(EDGE_POLL_MS)
        self.edge_timer.timeout.connect(self._watch_edge)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.tabs: dict[str, QPushButton] = {}
        self.columns: dict[str, TaskColumn] = {}
        root.addWidget(self._build_header())
        root.addWidget(self._build_remind_bar())

        self.stack = QStackedWidget()
        for column_id in COLUMN_ORDER:
            column = TaskColumn(column_id)
            self.columns[column_id] = column
            self.stack.addWidget(column)
        root.addWidget(self.stack, 1)
        root.addWidget(self._build_footer())

        self.show_column(COLUMN_ORDER[0])

    # ---------- 构建 ----------

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("FloatHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header = header

        row = QHBoxLayout(header)
        row.setContentsMargins(8, 6, 6, 6)
        row.setSpacing(2)

        for column_id in COLUMN_ORDER:
            tab = QPushButton(COLUMN_TITLE[column_id])
            tab.setObjectName("FloatTab")
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setToolTip(f"只看「{COLUMN_TITLE[column_id]}」")
            tab.clicked.connect(lambda _checked=False, cid=column_id: self.show_column(cid))
            self.tabs[column_id] = tab
            row.addWidget(tab)
        row.addStretch(1)

        self.opacity_button = QPushButton("◐")
        self.opacity_button.setObjectName("FloatIcon")
        self.opacity_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_opacity_tip()
        self.opacity_button.clicked.connect(self._show_opacity_popup)
        row.addWidget(self.opacity_button)

        close = QPushButton("✕")
        close.setObjectName("FloatClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("关闭悬浮窗")
        close.clicked.connect(self.close)
        row.addWidget(close)
        return header

    def _build_remind_bar(self) -> QFrame:
        """窗内提醒条：有时限的任务快到点时在这里冒出来。"""
        bar = QFrame()
        bar.setObjectName("RemindBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(6)

        self.remind_label = QLabel()
        self.remind_label.setObjectName("RemindText")
        self.remind_label.setWordWrap(True)
        row.addWidget(self.remind_label, 1)

        dismiss = QPushButton("✕")
        dismiss.setObjectName("FloatClose")
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setToolTip("收起提醒")
        dismiss.clicked.connect(bar.hide)
        row.addWidget(dismiss, 0, Qt.AlignmentFlag.AlignTop)

        self.remind_bar = bar
        bar.hide()
        return bar

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        row = QHBoxLayout(footer)
        row.setContentsMargins(0, 0, 2, 2)
        row.addStretch(1)
        row.addWidget(QSizeGrip(self), 0)
        return footer

    # ---------- 透明度 ----------

    def set_opacity(self, value: float) -> None:
        self.opacity = clamp_opacity(value)
        self.setWindowOpacity(self.opacity)
        self.store.set_setting(SETTING_FLOAT_OPACITY, f"{self.opacity:.2f}")
        self._refresh_opacity_tip()

    def _refresh_opacity_tip(self) -> None:
        self.opacity_button.setToolTip(
            f"调整悬浮窗透明度（当前 {int(round(self.opacity * 100))}%）"
        )

    def _show_opacity_popup(self) -> None:
        if self.opacity_popup is None:
            self.opacity_popup = OpacityPopup(self.opacity, self)
            self.opacity_popup.opacity_changed.connect(self.set_opacity)
        else:
            self.opacity_popup.slider.setValue(int(round(self.opacity * 100)))
        self.opacity_popup.popup_at(self.opacity_button)

    # ---------- 窗内提醒 ----------

    def show_reminder(self, reminders: list) -> None:
        if not reminders:
            return
        lines = [
            f"「{item.title}」{item.due_at.strftime('%H:%M')} 到点，"
            f"还剩 {item.minutes_left} 分钟"
            for item in reminders
        ]
        self.remind_label.setText("⏰ 快到点了\n" + "\n".join(lines))
        self.remind_bar.show()

    # ---------- 页签 ----------

    def show_column(self, column_id: str) -> None:
        self.stack.setCurrentWidget(self.columns[column_id])
        for cid, tab in self.tabs.items():
            tab.setObjectName("FloatTabActive" if cid == column_id else "FloatTab")
            tab.style().unpolish(tab)
            tab.style().polish(tab)

    def current_column(self) -> TaskColumn:
        return self.stack.currentWidget()

    # ---------- 位置 ----------

    def board_area(self) -> QRect:
        """悬浮窗所在的屏幕可用区域（已避开任务栏）。"""
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect()

    def move_to_default_spot(self) -> None:
        """首次出现时贴着桌面右上角，尽量不挡首页内容。"""
        self._leave_edge_mode()
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.top() + 60)

    # ---------- 贴顶自动收起 ----------

    def _watch_edge(self) -> None:
        """贴顶状态下盯着鼠标：碰小横条就滑下来，离开窗口就收回去。"""
        if not self.edge_mode:
            return
        cursor = QCursor.pos()
        if self.edge_collapsed:
            if self._handle_rect().contains(cursor):
                self._expand_from_edge()
        elif not self.frameGeometry().contains(cursor):
            self._collapse_to_edge()

    def _handle_rect(self) -> QRect:
        """小横条的鼠标判定区，比看上去略高一点，方便够着。"""
        return QRect(self.x(), self.board_area().top(), self.width(), EDGE_HIT_HEIGHT)

    def _update_edge_mode(self) -> None:
        """松手后看窗口上沿有没有贴到屏幕顶。"""
        area = self.board_area()
        if not area.isValid():
            return
        if self.y() - area.top() <= EDGE_TOLERANCE:
            self.move(self.x(), area.top())
            self.edge_mode = True
            # 鼠标还在窗里就先别收，等它移出去再收
            if not self.frameGeometry().contains(QCursor.pos()):
                self._collapse_to_edge()
            self.edge_timer.start()
        else:
            self._leave_edge_mode()

    def _leave_edge_mode(self) -> None:
        """拖离顶部时退出贴顶：顺带把窗口拉回屏幕里。"""
        collapsed = self.edge_collapsed
        self._clear_edge()
        if collapsed:
            self.move(self.x(), self.board_area().top())
            self.show()

    def _clear_edge(self) -> None:
        """撤掉贴顶状态：停轮询、收小横条、把几个标记复位。"""
        self.edge_mode = False
        self.edge_collapsed = False
        self._stop_edge_anim()
        self.edge_timer.stop()
        self.edge_handle.hide()

    def hide_board(self) -> None:
        """从外面收起悬浮窗（取消勾选时用）。

        已经收起的窗口再 hide() 不会再发 hideEvent，所以这里得自己把小横条清掉。
        """
        self._clear_edge()
        self.hide()

    def _collapse_to_edge(self) -> None:
        if self.edge_collapsed:
            return
        self.edge_collapsed = True
        self._slide(self.board_area().top() - self.height(), self._finish_collapse)

    def _finish_collapse(self) -> None:
        if not self.edge_mode:
            return
        self._internal_hide = True
        self.hide()
        self._internal_hide = False
        area = self.board_area()
        self.edge_handle.setGeometry(self.x(), area.top(), self.width(),
                                     EDGE_STRIP_HEIGHT)
        self.edge_handle.show()
        self.edge_handle.raise_()

    def _expand_from_edge(self) -> None:
        if not self.edge_collapsed:
            return
        self.edge_collapsed = False
        self.edge_handle.hide()
        top = self.board_area().top()
        # 先从屏幕外就位，再滑下来
        self.move(self.x(), top - self.height())
        self.show()
        self.raise_()
        self._slide(top)

    def _slide(self, y: int, on_done=None) -> None:
        self._stop_edge_anim()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(EDGE_ANIM_MS)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(self.x(), y))
        if on_done is not None:
            anim.finished.connect(on_done)
        self.edge_anim = anim
        anim.start()

    def _stop_edge_anim(self) -> None:
        if self.edge_anim is not None:
            self.edge_anim.stop()
            self.edge_anim = None

    def hideEvent(self, event):
        # 外头把悬浮窗收起来了（比如取消勾选），别再把小横条留在桌面上
        if not self._internal_hide:
            self._clear_edge()
        super().hideEvent(event)

    # ---------- 无边框窗口的拖动 ----------

    def _in_header(self, event) -> bool:
        point = self.header.mapFrom(self, event.position().toPoint())
        return self.header.rect().contains(point)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._in_header(event):
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        dragged = self._drag_offset is not None
        self._drag_offset = None
        super().mouseReleaseEvent(event)
        if dragged and event.button() == Qt.MouseButton.LeftButton:
            self._update_edge_mode()

    def closeEvent(self, event):
        self._clear_edge()
        self.edge_handle.close()
        self.closed.emit()
        super().closeEvent(event)


class RemindPopup(QWidget):
    """没开悬浮窗时的置底小窗提醒。

    不抢焦点、垫在其它窗口下面，点「知道了」或 ✕ 收起。
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnBottomHint,
        )
        self.setObjectName("RemindPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 弹出来但不打断手头操作
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(APP_QSS)
        self.setFixedWidth(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 12, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("⏰ 快到点了")
        title.setObjectName("RemindTitle")
        head.addWidget(title, 1)

        close = QPushButton("✕")
        close.setObjectName("FloatClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("收起这条提醒")
        close.clicked.connect(self.close)
        head.addWidget(close)
        root.addLayout(head)

        self.body = QLabel()
        self.body.setObjectName("RemindText")
        self.body.setWordWrap(True)
        root.addWidget(self.body)

        ok = QPushButton("知道了")
        ok.setObjectName("PrimaryButton")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.close)
        root.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)

    def show_reminders(self, reminders: list) -> None:
        lines = [
            f"「{item.title}」{item.due_at.strftime('%H:%M')} 到点，"
            f"还剩 {item.minutes_left} 分钟"
            for item in reminders
        ]
        self.body.setText("\n".join(lines))
        self.adjustSize()
        self._move_to_corner()
        self.show()
        self.raise_()

    def _move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 24, area.bottom() - self.height() - 24)

