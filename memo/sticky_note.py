"""一张便签：单击编辑、拖动挪位置、大面积重叠就并摞。

也能当桌面小窗用（desk=True）：这时候它自己是顶层窗口，钉在别的窗口上面。
"""

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFontMetrics, QPainter, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOption,
    QVBoxLayout,
)

from storage import Memo
from theme import APP_QSS

from .consts import (
    CLICK_SLOP,
    HOST_TICK_MS,
    NOTE_MAX_HEIGHT,
    NOTE_MIN_HEIGHT,
    NOTE_PAD,
    NOTE_WIDTH,
    PIN_GAP,
    PIN_SIZE,
    PLACEHOLDER,
    TEXT_WIDTH,
)
from .helpers import _repolish
from .widgets import _NoteEditor
from .win32 import (
    is_desktop,
    put_above,
    set_topmost,
    window_alive,
    window_class,
    window_minimized,
    window_rect,
    window_title,
)


class StickyNote(QFrame):
    """一张便签：单击编辑、拖动挪位置、大面积重叠就并摞。

    也能当桌面小窗用（desk=True）：这时候它自己是顶层窗口，钉在别的窗口上面。
    """

    moved = pyqtSignal(int)               # 拖动过程中位置变了
    drag_finished = pyqtSignal(int)       # 松手了，可以看看要不要并摞
    edited = pyqtSignal(int, str)         # 内容改完了
    click_edit = pyqtSignal(int)          # 想进入编辑
    create_requested = pyqtSignal()       # 右键里的「新建便签」
    pin_requested = pyqtSignal(int, QPoint)    # 钉到桌面，附带落点（屏幕坐标）
    unpin_requested = pyqtSignal(int)          # 从桌面收回页面
    dragged_out = pyqtSignal(int)              # 拖着拖着出了主窗口，该转成桌面浮窗
    host_changed = pyqtSignal(int)             # 贴上了 / 摘下了宿主窗口
    host_lost = pyqtSignal(int)                # 宿主窗口没了，请把它收回页面
    pick_requested = pyqtSignal(int)           # 右键选了「钉到某个窗口…」
    discard_requested = pyqtSignal(int)   # 丢进「废弃栏」
    detach_requested = pyqtSignal(int)    # 从这一摞里拿出来
    split_requested = pyqtSignal(int)     # 拆开整摞
    merge_requested = pyqtSignal(int)     # 按页签序号合并成一整张

    def __init__(self, memo: Memo, stack_size: int = 1, parent=None, desk: bool = False):
        super().__init__(parent)
        self.memo = memo
        self.stack_size = stack_size
        self.desk = desk                # True：这是一张摊在桌面上的独立小窗
        self._press_at: QPoint | None = None
        self._dragging = False
        self._editing = False
        self._hopped_out = False        # 这次拖动是从画布上跳出去的
        self._grabbed = False           # 为了拖动不断线，临时抓了鼠标
        self._host = 0                  # 贴在哪个窗口上（0 就是块普通浮窗）
        self._host_dx = 0               # 便签左上角与宿主左上角的横距
        self._host_dy = 0
        self._tick: QTimer | None = None    # 盯着宿主看的心跳
        self._parked = False            # 主窗口缩到后台，被页面收起来了

        # 名字要赶在挂样式表之前定下来：样式表按 objectName 匹配，晚了就对不上
        self.setObjectName("StickyNote")
        if desk:
            self._become_desk_window()

        box = QVBoxLayout(self)
        box.setContentsMargins(NOTE_PAD, NOTE_PAD, NOTE_PAD, NOTE_PAD)
        box.setSpacing(0)

        self.label = QLabel()
        self.label.setObjectName("StickyLabel")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        box.addWidget(self.label)

        self.editor = _NoteEditor()
        self.editor.setObjectName("StickyEdit")
        self.editor.hide()
        self.editor.focus_lost.connect(self._finish_edit)
        self.editor.escape_pressed.connect(self._finish_edit)
        self.editor.textChanged.connect(self._grow_while_editing)
        box.addWidget(self.editor)

        # 钉住按钮钉在右上角，正文给它让出一条，免得字压在按钮底下
        self.pin_button = QPushButton("钉", self)
        self.pin_button.setFixedSize(PIN_SIZE, PIN_SIZE)
        self.pin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_button.clicked.connect(self._on_pin_clicked)
        self._refresh_pin()

        self._refresh_tip()
        self.set_content(memo.content)

    # ---------- 桌面小窗 ----------

    def _become_desk_window(self) -> None:
        """把自己变形成桌面浮窗：无边框、始终置顶，浮在别的窗口上面。"""
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # 窗口整体透明，只为让四角露出 QSS 画的圆角，便签本身不透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(APP_QSS)         # 独立顶层窗口，样式表要自己挂一份
        self.setWindowTitle("便签")

    def _refresh_tip(self) -> None:
        if not self.desk:
            self.setToolTip(
                "单击改内容，按住拖动挪位置；拖到别的便签上大面积重叠会叠成一摞"
            )
            return
        if self._host:
            self.setToolTip(
                f"已贴在「{window_title(self._host) or window_class(self._host)}」上："
                "它挪窝便签跟着挪，它缩下去便签也藏起来。"
                "拖离这个窗口就不贴了，点右上角的钉收回备忘录页面"
            )
            return
        self.setToolTip(
            "单击改内容，按住拖动挪位置；拖到别的程序窗口上松手就贴住它，"
            "点右上角的钉收回备忘录页面"
        )

    def go_desk(self) -> None:
        """从画布上的便签就地变成桌面浮窗。

        刻意不重建控件：正在拖便签的那只手还按着它，换了控件拖动就断了。
        """
        if self.desk:
            return
        self.desk = True
        self._hopped_out = True         # 松手时要是又回了窗口里，还收得回来
        self.setParent(None)
        self._become_desk_window()
        self._refresh_pin()
        self._refresh_tip()
        self.show()
        self.raise_()
        # 换过原生窗口，系统那边的鼠标抓取会失效，得抢回来才拖得动
        self.grabMouse()
        self._grabbed = True

    def take_hop(self) -> bool:
        """取走「这次是从画布上跳出去的」标记。"""
        hopped, self._hopped_out = self._hopped_out, False
        return hopped

    # ---------- 贴在别的程序窗口上 ----------

    @property
    def host(self) -> int:
        """当前贴着的宿主窗口；0 表示没贴，就是块普通浮窗。"""
        return self._host

    @property
    def host_offset(self) -> tuple[int, int]:
        return self._host_dx, self._host_dy

    def attach_to(self, hwnd: int, dx: int | None = None, dy: int | None = None) -> bool:
        """把便签贴到某个程序窗口上，从此跟它一条心。

        dx / dy 不传就照便签眼下压的位置算，也就是「就贴在这儿」。
        """
        if not self.desk or not window_alive(hwnd) or is_desktop(hwnd):
            return False
        rect = window_rect(hwnd)
        if rect is None:
            return False
        self._host = hwnd
        self._host_dx = self.x() - rect.x() if dx is None else int(dx)
        self._host_dy = self.y() - rect.y() if dy is None else int(dy)
        # 摘掉「整屏置顶」，接下来靠 put_above 插到宿主的 Z 序正上方
        set_topmost(self, False)
        self._sync_with_host(force=True)
        self._start_tick()
        self._refresh_tip()
        self.host_changed.emit(self.memo.id)
        return True

    def detach_host(self) -> None:
        """从宿主窗口上摘下来，变回一块普通浮窗。"""
        if not self._host:
            return
        self._host = 0
        self._stop_tick()
        # 不再跟谁一条心了，恢复成整屏置顶的普通浮窗
        set_topmost(self, True)
        self._refresh_tip()
        self.host_changed.emit(self.memo.id)

    def _start_tick(self) -> None:
        if self._tick is None:
            self._tick = QTimer(self)
            self._tick.setInterval(HOST_TICK_MS)
            self._tick.timeout.connect(self._sync_with_host)
        self._tick.start()

    def _stop_tick(self) -> None:
        if self._tick is not None:
            self._tick.stop()

    def _sync_with_host(self, force: bool = False) -> None:
        """看一眼宿主：还在不在、挪没挪窝、有没有缩到任务栏去。"""
        if not self._host:
            return
        if not window_alive(self._host):
            # 人家关掉了：这张便签回备忘录页面去
            self._host = 0
            self._stop_tick()
            self.host_lost.emit(self.memo.id)
            return
        if self._parked:
            return
        if not force and (self._dragging or self._press_at is not None or self._editing):
            # 正拖着或正写着：这会儿便签听手的，不听宿主的
            return
        if window_minimized(self._host):
            if self.isVisible():
                self.hide()
            return
        rect = window_rect(self._host)
        if rect is None:
            return
        target = QPoint(rect.x() + self._host_dx, rect.y() + self._host_dy)
        if not self.isVisible():
            self.move(target)
            self.show()
        elif self.pos() != target:
            self.move(target)
        # 露面的动作可能又把「整屏置顶」带回来，插队之前先确认摘干净了
        set_topmost(self, False)
        put_above(self, self._host)

    def _still_on_host(self) -> bool:
        """便签中心还压在宿主窗口上吗；拖出去之后中心就露到外面了。"""
        rect = window_rect(self._host)
        if rect is None:
            return False
        return rect.contains(QRect(self.pos(), self.size()).center())

    def park(self) -> None:
        """主窗口缩到后台：先把便签收起来，宿主那边别急着叫醒它。"""
        self._parked = True
        self.hide()

    def unpark(self) -> None:
        self._parked = False
        if self._host and window_minimized(self._host):
            return          # 宿主还缩着，等它还原再露面
        self.show()
        self.raise_()

    def shutdown(self) -> None:
        """这张便签要销毁了：先把盯着宿主看的心跳停掉。"""
        self._stop_tick()
        self._host = 0

    # ---------- 内容与尺寸 ----------

    def paintEvent(self, event):
        """桌面便签是整体透明的窗口，Qt 会跳过样式表那套底色绘制，得自己喊一声。

        呼的是 PE_Widget：样式表里 #StickyNote / :hover / #StickyNoteEditing
        那几条规则照样管用，底色与圆角跟画布上的一模一样。
        """
        if not self.desk:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, option, painter, self
        )

    def set_content(self, text: str) -> None:
        empty = not text.strip()
        self.label.setText(PLACEHOLDER if empty else text)
        name = "StickyPlaceholder" if empty else "StickyLabel"
        if self.label.objectName() != name:
            self.label.setObjectName(name)
            _repolish(self.label)
        self._autosize()

    def _autosize(self) -> None:
        """按文字量算高度：内容多了就长高，到上限为止。

        不用 QLabel.heightForWidth()：它按宽度缓存结果，改完文字再问会拿到旧高度。
        """
        box = QFontMetrics(self.label.font()).boundingRect(
            QRect(0, 0, TEXT_WIDTH, 10_000),
            int(Qt.TextFlag.TextWordWrap),
            self.label.text(),
        )
        self._apply_size(box.height() + NOTE_PAD * 2)

    def _apply_size(self, height: int) -> None:
        height = max(NOTE_MIN_HEIGHT, min(NOTE_MAX_HEIGHT, int(height)))
        inner = height - NOTE_PAD * 2
        self.label.setFixedSize(TEXT_WIDTH, inner)
        self.editor.setFixedSize(TEXT_WIDTH, inner)
        self.setFixedSize(NOTE_WIDTH, height)
        self.pin_button.move(NOTE_WIDTH - NOTE_PAD - PIN_SIZE, NOTE_PAD)

    def _grow_while_editing(self) -> None:
        """边写边长，写到上限为止。"""
        if not self._editing:
            return
        needed = int(self.editor.document().size().height()) + 6 + NOTE_PAD * 2
        self._apply_size(needed)

    # ---------- 钉住 ----------

    def _refresh_pin(self) -> None:
        """钉住时按钮变灰底，一眼能看出这张已经摊在桌面上了。"""
        name = "StickyPinOn" if self.memo.pinned else "StickyPin"
        if self.pin_button.objectName() != name:
            self.pin_button.setObjectName(name)
            _repolish(self.pin_button)
        self.pin_button.setToolTip(
            "收回备忘录页面" if self.memo.pinned else "钉在桌面上，浮在别的窗口上面"
        )

    def _on_pin_clicked(self) -> None:
        # 编辑到一半先收工，免得拖着一半的内容搬来搬去
        if self._editing:
            self._finish_edit()
        if self.desk:
            self.unpin_requested.emit(self.memo.id)
        else:
            self.pin_requested.emit(self.memo.id, self.mapToGlobal(QPoint(0, 0)))

    def screen_pos(self, x: int, y: int) -> QPoint:
        """把左上角收进所在屏幕的可用区域，别让便签跑到屏幕外找不着。"""
        point = QPoint(int(x), int(y))
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is None:
            return point
        area = screen.availableGeometry()
        return QPoint(
            max(area.left(), min(point.x(), area.right() - self.width() + 1)),
            max(area.top(), min(point.y(), area.bottom() - self.height() + 1)),
        )

    # ---------- 编辑 ----------

    def begin_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        self.label.hide()
        self.editor.setPlainText(self.memo.content)
        self.editor.show()
        self.editor.setFocus()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._grow_while_editing()
        if self.objectName() != "StickyNoteEditing":
            self.setObjectName("StickyNoteEditing")
            _repolish(self)

    def _finish_edit(self) -> None:
        # 先摘掉标记：hide() 会再触发一次 focusOut，靠这个标记挡住重入
        if not self._editing:
            return
        self._editing = False
        text = self.editor.toPlainText()
        self.editor.hide()
        self.label.show()
        if self.objectName() != "StickyNote":
            self.setObjectName("StickyNote")
            _repolish(self)
        self.set_content(text)
        if text != self.memo.content:
            self.memo.content = text
            self.edited.emit(self.memo.id, text)

    # ---------- 拖动与点击 ----------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._editing:
            super().mousePressEvent(event)
            return
        self._press_at = event.position().toPoint()
        self._dragging = False
        self.raise_()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press_at is None:
            return
        position = event.position().toPoint()
        if not self._dragging:
            if (position - self._press_at).manhattanLength() < CLICK_SLOP:
                return
            self._dragging = True

        if not self.desk and self._dragged_out():
            # 拖着拖着出了主窗口：就地转成桌面浮窗，接着跟手走
            self.dragged_out.emit(self.memo.id)

        self._follow(position)
        if self._host and not self._still_on_host():
            # 拖得离开了宿主窗口：这张就不贴着了，变回普通浮窗
            self.detach_host()
        self.moved.emit(self.memo.id)
        event.accept()

    def _dragged_out(self) -> bool:
        """鼠标现在是不是已经在主窗口外面了。"""
        window = self.window()
        if window is None or not window.isVisible():
            return False
        return not window.frameGeometry().contains(QCursor.pos())

    def _follow(self, position: QPoint) -> None:
        """照鼠标当前位置把便签挪过去：桌面浮窗走屏幕坐标，画布便签走画布坐标。"""
        if self.desk:
            target = self.mapToGlobal(position) - self._press_at
            self.move(self.screen_pos(target.x(), target.y()))
            return
        canvas = self.parentWidget()
        target = self.mapToParent(position) - self._press_at
        self.move(
            max(0, min(target.x(), max(0, canvas.width() - self.width()))),
            max(0, min(target.y(), max(0, canvas.height() - self.height()))),
        )

    def mouseReleaseEvent(self, event):
        if self._grabbed:
            # 拖动途中变身桌面浮窗时抓过鼠标，用完得还回去
            self._grabbed = False
            self.releaseMouse()
        if self._press_at is None:
            super().mouseReleaseEvent(event)
            return
        pressed_at = self._press_at
        self._press_at = None
        if self._dragging:
            self._dragging = False
            if self._host:
                # 还贴在人家身上：位置动了，相对位置跟着更新一下
                rect = window_rect(self._host)
                if rect is not None:
                    self._host_dx = self.x() - rect.x()
                    self._host_dy = self.y() - rect.y()
            dropped = self._drop_outside(pressed_at)
            if dropped is None:
                self.drag_finished.emit(self.memo.id)
            else:
                # 松手时人已经在主窗口外面了：这张该搬到桌面上
                self.pin_requested.emit(self.memo.id, dropped)
        else:
            self.click_edit.emit(self.memo.id)
        event.accept()

    def _drop_outside(self, pressed_at: QPoint) -> QPoint | None:
        """松手时鼠标已经跑到主窗口外面：返回该落到屏幕上的位置，否则 None。"""
        if self.desk:
            return None
        window = self.window()
        if window is None or not window.isVisible():
            return None
        cursor = QCursor.pos()
        if window.frameGeometry().contains(cursor):
            return None
        return cursor - pressed_at

    # ---------- 右键菜单 ----------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("编辑内容", lambda: self.click_edit.emit(self.memo.id))
        if self.desk:
            if self._host:
                menu.addAction("不贴在窗口上", self.detach_host)
            else:
                menu.addAction(
                    "钉到某个窗口…", lambda: self.pick_requested.emit(self.memo.id)
                )
            menu.addAction("收回备忘录页面", self._on_pin_clicked)
        else:
            menu.addAction("新建便签", lambda: self.create_requested.emit())
            if self.stack_size > 1:
                menu.addAction(
                    "从这摞里移出", lambda: self.detach_requested.emit(self.memo.id)
                )
                menu.addAction(
                    "拆开这一摞", lambda: self.split_requested.emit(self.memo.id)
                )
                menu.addAction(
                    "合并成一整张…", lambda: self.merge_requested.emit(self.memo.stack_id)
                )
        menu.addSeparator()
        discard = menu.addAction(
            "丢弃便签", lambda: self.discard_requested.emit(self.memo.id)
        )
        discard.setToolTip("从备忘录里收进「废弃栏」，内容留着随时能找回")
        menu.exec(event.globalPos())
