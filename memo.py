"""备忘录：一块自由画布，便签随手拖、随手写，大面积重叠就叠成一摞。

- 画布空白处右键 → 新建便签，便签大小随内容自适应
- 便签上单击就地编辑，点别处自动保存；按住拖动则是挪位置
- 允许简单重叠；与另一张重叠面积过大时松手，两张就叠成一摞
- 叠起来后画布上只留一张，右侧一列小页签切换浏览，一摞最多五张
- 页签右键能把某张移出这一摞，便签右键可以拆开整摞或删掉
- 便签可以直接拖出主窗口：一出窗口边沿就当场变成桌面浮窗、一路跟手走；
  松手时压在哪个程序窗口上，就钉在哪个窗口上（浏览器、游戏启动器都行），
  底下要是光秃秃的桌面，那就只是浮在桌面最上层
- 钉在窗口上的便签跟那个窗口联动：窗口挪它跟着挪，窗口最小化它一并藏起来，
  窗口关掉它自己收回备忘录页面；拖得离那个窗口足够远，就自动改回普通浮窗
- 便签右键「钉到某个窗口…」也可以先指定再贴：选完点一下目标窗口即可
- 便签右上角的「钉」也能把它钉到桌面上（会挪到主窗口右边），再点一下收回页面
"""

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFontMetrics, QPainter, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOption,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from storage import MAX_MEMO_STACK, Memo, Store
from theme import APP_QSS

# 便签宽度固定，高度随内容长；超过上限就截住，免得一张便签占满整屏
NOTE_WIDTH = 220
NOTE_PAD = 12
NOTE_MIN_HEIGHT = 88
NOTE_MAX_HEIGHT = 460

# 右上角钉住按钮的尺寸，以及正文为它让出来的宽度
PIN_SIZE = 16
PIN_GAP = 6
TEXT_WIDTH = NOTE_WIDTH - NOTE_PAD * 2 - PIN_SIZE - PIN_GAP

# 钉到桌面时，便签跟主窗口边沿留出的空当
DESK_GAP = 24

# 重叠面积占到较小一张的这个比例，就算「高度重叠」，该叠成一摞
MERGE_RATIO = 0.55

# 按下后位移不超过这个像素算点击（进入编辑），超过才算拖动
CLICK_SLOP = 4

# 画布最小尺寸与四周留白
CANVAS_MIN_WIDTH = 2200
CANVAS_MIN_HEIGHT = 1400
CANVAS_MARGIN = 320

# 右侧小页签的尺寸与便签跟它的间隙
TAB_WIDTH = 26
TAB_HEIGHT = 26
TAB_SPACING = 2
STRIP_GAP = 6

PLACEHOLDER = "点一下写点什么…"

# 便签盯着宿主窗口看的间隔；窗口一挪便签就跟上，靠的就是这个心跳
HOST_TICK_MS = 60
# 拾取宿主窗口时，查鼠标左右键的间隔
PICK_TICK_MS = 40

# ---------------- 和别的程序窗口打交道 ----------------
#
# 「钉在某个程序窗口上」全靠下面这几个原生调用实现。这里刻意不去设窗口的
# owner：owner 关系下宿主一关，便签会被系统连带销毁，Qt 那边会留下一个
# 自己都不知道已经没了的窗口。改成自己盯着宿主，四条联动都由自己拿主意：
#   位置跟着走、最小化一并藏、关掉就收回、Z 序压在宿主之上

GA_ROOT = 2
GW_HWNDNEXT = 2
GW_HWNDPREV = 3
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_ESCAPE = 0x1B

# 桌面本身不算「别的程序窗口」：钉在桌面上就该是普通浮窗
DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "SysListView32"}

_user32 = ctypes.windll.user32
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
# 32 位系统上这两个叫 ...LongW，64 位上是 ...LongPtrW；按位宽选对的那个
_GetWindowLong = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
_SetWindowLong = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
_GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLong.restype = ctypes.c_ssize_t
_SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_SetWindowLong.restype = ctypes.c_ssize_t


def hwnd_of(widget: QWidget) -> int:
    """Qt 控件的原生窗口句柄。"""
    return int(widget.winId())


def top_hwnd(hwnd: int) -> int:
    """从一个子窗口往上找到它所属的顶层窗口。"""
    if not hwnd:
        return 0
    return int(_user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or hwnd)


def hwnd_at(x: int, y: int) -> int:
    """屏幕上这一点压着哪个顶层窗口；没有就是 0。"""
    found = _user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return top_hwnd(int(found or 0))


def window_under(widget: QWidget) -> int:
    """便签正盖着的那个别人家的窗口；盖着的是桌面或自家窗口就返回 0。

    便签自己就压在这一点上，直接问系统只会问回自己。先把便签设成「鼠标穿透」，
    系统就会跳过它、告诉底下压着谁；问完马上恢复，外观与手感都不变。
    """
    hwnd = wintypes.HWND(hwnd_of(widget))
    style = int(_GetWindowLong(hwnd, GWL_EXSTYLE))
    _SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT)
    try:
        center = widget.mapToGlobal(QPoint(0, 0)) + QPoint(
            widget.width() // 2, widget.height() // 2
        )
        found = hwnd_at(center.x(), center.y())
    finally:
        _SetWindowLong(hwnd, GWL_EXSTYLE, style)
    if not found or found in own_windows() or is_desktop(found):
        return 0
    return found


def own_windows() -> set[int]:
    """本程序自己的所有顶层窗口，找宿主时都要跳过。"""
    ids = set()
    for widget in QApplication.topLevelWidgets():
        if widget.isVisible():
            ids.add(int(widget.winId()))
    return ids


def window_rect(hwnd: int) -> QRect | None:
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def window_alive(hwnd: int) -> bool:
    return bool(hwnd) and bool(_user32.IsWindow(wintypes.HWND(hwnd)))


def window_minimized(hwnd: int) -> bool:
    return bool(_user32.IsIconic(wintypes.HWND(hwnd)))


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def is_desktop(hwnd: int) -> bool:
    """是不是系统桌面 / 任务栏本身；这种不算「别的程序窗口」。"""
    return bool(hwnd) and window_class(hwnd) in DESKTOP_CLASSES


def window_title(hwnd: int) -> str:
    length = int(_user32.GetWindowTextLengthW(wintypes.HWND(hwnd)))
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(wintypes.HWND(hwnd), buf, length + 1)
    return buf.value


def find_window(cls: str, title: str) -> int:
    """照类名 + 标题把宿主窗口找回来（下次开程序时接着贴）。"""
    if not cls and not title:
        return 0
    found = _user32.FindWindowW(cls or None, title or None)
    return int(found or 0)


def put_above(widget: QWidget, host: int) -> None:
    """把便签插到宿主的 Z 序正上方：压在它上头，但不盖住别的程序。

    当心 SetWindowPos 的第二个参数是「排在便签前面（也就是压在便签上）的那个
    窗口」，直接传宿主会把便签塞到宿主下面去。所以要取宿主上面贴着的那一个，
    把便签插在它后头；宿主本身就是最上层时就干脆摆到顶层。
    前提是便签自己没有 WS_EX_TOPMOST——带着它这套插队会被系统直接忽略。
    """
    hwnd = wintypes.HWND(hwnd_of(widget))
    preceding = int(_user32.GetWindow(wintypes.HWND(host), GW_HWNDPREV) or 0)
    if preceding and not (
        _GetWindowLong(wintypes.HWND(preceding), GWL_EXSTYLE) & WS_EX_TOPMOST
    ):
        after = wintypes.HWND(preceding)
    else:
        after = wintypes.HWND(HWND_TOP)
    _user32.SetWindowPos(
        hwnd, after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )


def set_topmost(widget: QWidget, on: bool) -> None:
    """给便签窗口加 / 去 WS_EX_TOPMOST。

    Qt 的 WindowStaysOnTopHint 设出来的就是这个样式。贴到宿主窗口上时要摘掉，
    否则便签永远是整屏最上层，谈不上「压在宿主之上、但不盖住别的程序」。
    已经是想要的样式就直接返回，这样可以放心地按心跳反复喊。
    """
    hwnd = wintypes.HWND(hwnd_of(widget))
    style = int(_GetWindowLong(hwnd, GWL_EXSTYLE))
    if bool(style & WS_EX_TOPMOST) == on:
        return
    new = (style | WS_EX_TOPMOST) if on else (style & ~WS_EX_TOPMOST)
    _SetWindowLong(hwnd, GWL_EXSTYLE, new)
    # 光改样式不够，还得让系统重新排一次 Z 序才会生效
    _user32.SetWindowPos(hwnd, wintypes.HWND(HWND_TOPMOST if on else HWND_NOTOPMOST),
                         0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _repolish(widget: QWidget) -> None:
    """objectName 变了要重新走一遍样式，否则界面不会立即刷新。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _preview(content: str, limit: int = 24) -> str:
    """把便签内容压成一行短摘要，给页签提示与删除确认用。"""
    text = " ".join(content.split())
    if not text:
        return "（空白便签）"
    return text if len(text) <= limit else text[:limit] + "…"


def _overlap_ratio(a: QRect, b: QRect) -> float:
    """重叠面积占较小一张的比例：0 是没碰上，1 是完全盖住。"""
    overlap = a.intersected(b)
    if overlap.isEmpty():
        return 0.0
    smaller = min(a.width() * a.height(), b.width() * b.height())
    if smaller <= 0:
        return 0.0
    return overlap.width() * overlap.height() / smaller


class _NoteEditor(QTextEdit):
    """便签里的多行输入框：失焦或按 Esc 就通知外面收工。"""

    focus_lost = pyqtSignal()
    escape_pressed = pyqtSignal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_lost.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """自己搭一份中文菜单：Qt 自带的那份是英文的。"""
        has_selection = self.textCursor().hasSelection()
        menu = QMenu(self)

        cut = menu.addAction("剪切", self.cut)
        cut.setEnabled(has_selection)
        copy = menu.addAction("复制", self.copy)
        copy.setEnabled(has_selection)
        paste = menu.addAction("粘贴", self.paste)
        paste.setEnabled(self.canPaste())

        menu.addSeparator()
        select_all = menu.addAction("全选", self.selectAll)
        select_all.setEnabled(bool(self.toPlainText()))
        remove = menu.addAction("删除选中", self._remove_selection)
        remove.setEnabled(has_selection)

        menu.exec(event.globalPos())

    def _remove_selection(self) -> None:
        self.textCursor().removeSelectedText()


class _Canvas(QWidget):
    """便签画布：空白处右键就是新建。"""

    create_requested = pyqtSignal(object)   # 画布内的落点

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("新建便签", lambda: self.create_requested.emit(event.pos()))
        menu.exec(event.globalPos())


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
    delete_requested = pyqtSignal(int)
    detach_requested = pyqtSignal(int)    # 从这一摞里拿出来
    split_requested = pyqtSignal(int)     # 拆开整摞

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
        menu.addSeparator()
        menu.addAction("删除便签", lambda: self.delete_requested.emit(self.memo.id))
        menu.exec(event.globalPos())


class _PickHint(QLabel):
    """挑宿主窗口时跟着鼠标跑的小提示条。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("PickHint")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(APP_QSS)         # 独立顶层浮层，样式表要自己挂一份
        self.setText("点一下要钉住的窗口（按 Esc 取消）")
        self.adjustSize()

    def follow(self, point: QPoint) -> None:
        self.move(point.x() + 18, point.y() + 20)


class TabStrip(QWidget):
    """一摞便签右侧的竖排小页签：点谁就显示谁。"""

    selected = pyqtSignal(int, int)      # stack_id, memo_id
    detach_requested = pyqtSignal(int)   # memo_id
    split_requested = pyqtSignal(int)    # stack_id

    def __init__(self, stack_id: int, members: list[Memo], active_id: int, parent=None):
        super().__init__(parent)
        self.setObjectName("TabStrip")
        self.stack_id = stack_id

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(TAB_SPACING)

        for index, memo in enumerate(members):
            # 页签上只放序号：内容首字常常是空白或标点，认不出哪张是哪张
            tab = QPushButton(str(index + 1))
            tab.setObjectName("StackTabActive" if memo.id == active_id else "StackTab")
            tab.setFixedSize(TAB_WIDTH, TAB_HEIGHT)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setToolTip(
                f"第 {index + 1} 张（共 {len(members)} 张）：{_preview(memo.content)}\n"
                "点这里切换显示这张，右键可以拆开"
            )
            tab.clicked.connect(
                lambda _, memo_id=memo.id: self.selected.emit(self.stack_id, memo_id)
            )
            tab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tab.customContextMenuRequested.connect(
                lambda pos, memo_id=memo.id, button=tab: self._tab_menu(memo_id, button, pos)
            )
            box.addWidget(tab)

        self.setFixedSize(
            TAB_WIDTH, len(members) * TAB_HEIGHT + (len(members) - 1) * TAB_SPACING
        )

    def _tab_menu(self, memo_id: int, button: QPushButton, pos) -> None:
        menu = QMenu(self)
        menu.addAction("从这摞里移出", lambda: self.detach_requested.emit(memo_id))
        menu.addAction("拆开这一摞", lambda: self.split_requested.emit(self.stack_id))
        menu.exec(button.mapToGlobal(pos))


class MemoPage(QWidget):
    """备忘录页面：一块可滚动的自由画布，外加摊在桌面上的那几张便签。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setObjectName("MemoPage")
        self.store = store
        self.notes: list[StickyNote] = []
        # 便签是一摞一个控件，键就是当前露在外面那张的 id（切页签时会跟着换）
        self.note_of: dict[int, StickyNote] = {}
        self.strip_of: dict[int, TabStrip] = {}
        # 钉到桌面的便签：一张一个独立小窗，键是便签 id
        self.desk: dict[int, StickyNote] = {}
        self._desk_hidden = False
        # 挑宿主窗口：_picking 是正在挑的那张便签，_pick_armed 是等上一次按下的手抬起来
        self._picking = 0
        self._pick_armed = False
        self._pick_timer: QTimer | None = None
        self._pick_hint: _PickHint | None = None
        self._reloading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        self.canvas = _Canvas()
        self.canvas.setObjectName("MemoCanvas")
        self.canvas.create_requested.connect(self.create_note)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("MemoScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        self.empty_hint = QLabel("在空白处右键 → 新建便签", self.canvas)
        self.empty_hint.setObjectName("CanvasHint")
        self.empty_hint.move(28, 28)

        self.reload()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("备忘录")
        title.setObjectName("PageTitle")
        left.addWidget(title)
        hint = QLabel("右键空白处新建便签；拖到另一张上大面积重叠，两张就叠成一摞")
        hint.setObjectName("PageDate")
        left.addWidget(hint)
        row.addLayout(left)
        row.addStretch(1)

        self.count_label = QLabel()
        self.count_label.setObjectName("StatText")
        row.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignBottom)
        return row

    # ---------- 铺画布 ----------

    def reload(self) -> None:
        """按库里的数据重铺一遍画布；便签数量不大，整体重建最省心。"""
        self._reloading = True
        for note in self.notes:
            note.setParent(None)
            note.deleteLater()
        for strip in self.strip_of.values():
            strip.setParent(None)
            strip.deleteLater()
        self.notes = []
        self.note_of = {}
        self.strip_of = {}

        memos = self.store.list_memos()
        # 钉在桌面上的不在画布上露面，免得同一张便签两处都有
        stacks: dict[int, list[Memo]] = {}
        for memo in memos:
            if memo.pinned:
                continue
            # 同摞的共享 stack_id；单个便签自己算一组
            stacks.setdefault(memo.stack_id or memo.id, []).append(memo)

        for members in stacks.values():
            # 页签序号由 stack_order 固定，露在外面的那张另行标记
            host = next((m for m in members if m.stack_active), members[0])
            note = StickyNote(host, len(members), self.canvas)
            note.move(host.x, host.y)
            note.moved.connect(self._on_note_moved)
            note.drag_finished.connect(self._on_drag_finished)
            note.edited.connect(self._on_note_edited)
            note.click_edit.connect(self._on_note_clicked)
            note.create_requested.connect(lambda memo_id=host.id: self._create_beside(memo_id))
            note.pin_requested.connect(self._on_pin)
            note.dragged_out.connect(self._on_dragged_out)
            note.delete_requested.connect(self._on_delete)
            note.detach_requested.connect(self._detach)
            note.split_requested.connect(self._on_split)
            note.show()
            self.notes.append(note)
            self.note_of[host.id] = note

            if len(members) > 1:
                strip = TabStrip(host.stack_id, members, host.id, self.canvas)
                strip.selected.connect(self._on_stack_selected)
                strip.detach_requested.connect(self._detach)
                strip.split_requested.connect(self._on_split)
                strip.show()
                self.strip_of[host.id] = strip
                self._place_strip(note)

        self._sync_desk([memo for memo in memos if memo.pinned])
        self._resize_canvas()
        self.empty_hint.setVisible(not self.notes)
        self.empty_hint.raise_()
        self.count_label.setText(f"共 {len(memos)} 张便签")
        self._reloading = False

    def _resize_canvas(self) -> None:
        """画布只增不减：便签拖到哪儿都留得下，不会出现无处可放的边角。"""
        width, height = CANVAS_MIN_WIDTH, CANVAS_MIN_HEIGHT
        for note in self.notes:
            width = max(width, note.x() + note.width() + CANVAS_MARGIN)
            height = max(height, note.y() + note.height() + CANVAS_MARGIN)
        self.canvas.setFixedSize(width, height)

    def _place_strip(self, note: StickyNote) -> None:
        """页签条贴着便签右边站好，跟着它一起走。"""
        strip = self.strip_of.get(note.memo.id)
        if strip is None:
            return
        x = min(note.x() + NOTE_WIDTH + STRIP_GAP,
                max(0, self.canvas.width() - TAB_WIDTH))
        strip.move(x, note.y())

    # ---------- 钉在桌面上的便签 ----------

    def _sync_desk(self, pinned: list[Memo]) -> None:
        """让桌面上的便签窗与库里的记录对齐：多退少补。"""
        wanted = {memo.id: memo for memo in pinned}
        for memo_id in list(self.desk):
            if memo_id not in wanted:
                self._close_desk(memo_id)
        for memo_id, memo in wanted.items():
            if memo_id not in self.desk:
                self._open_desk(memo)

    def _open_desk(self, memo: Memo) -> None:
        """把一张便签摊到桌面上：独立小窗、浮在别的窗口上面。"""
        note = StickyNote(memo, 1, None, desk=True)
        note.move(note.screen_pos(memo.x, memo.y))   # 钉住时存的就是屏幕坐标
        note.drag_finished.connect(self._on_desk_drag_finished)
        note.edited.connect(self._on_note_edited)
        note.click_edit.connect(self._on_desk_clicked)
        note.unpin_requested.connect(self._on_unpin)
        note.host_changed.connect(self._on_host_changed)
        note.host_lost.connect(self._on_host_lost)
        note.pick_requested.connect(self._begin_pick)
        note.delete_requested.connect(self._on_delete)
        self.desk[memo.id] = note
        if self._desk_hidden:
            note.park()
        else:
            note.show()
        self._restore_host(note, memo)

    def _restore_host(self, note: StickyNote, memo: Memo) -> None:
        """上次贴着的那个窗口要是还开着，就把便签重新贴回去。"""
        if not memo.host_class and not memo.host_title:
            return
        host = find_window(memo.host_class, memo.host_title)
        if host and window_alive(host) and not is_desktop(host):
            note.attach_to(host, memo.host_dx, memo.host_dy)

    def _close_desk(self, memo_id: int) -> None:
        note = self.desk.pop(memo_id, None)
        if note is None:
            return
        note.shutdown()
        note.hide()
        note.setParent(None)
        note.deleteLater()

    def _on_desk_drag_finished(self, memo_id: int) -> None:
        note = self.desk.get(memo_id)
        if note is None:
            return
        window = self.window()
        if (
            note.take_hop()
            and window is not None
            and window.isVisible()
            and window.frameGeometry().contains(note.frameGeometry())
        ):
            # 拖出去又拖回了主窗口里面：那不钉了，收回页面
            self._on_unpin(memo_id)
            return
        self.store.save_memo_pos(memo_id, note.x(), note.y())
        if note.host:
            # 还贴在原来那个窗口上：位置挪了，相对位置存一下
            self._on_host_changed(memo_id)
        else:
            # 松手时便签压在哪个程序窗口上，就此贴住它
            self._attach_under(note)

    def _on_dragged_out(self, memo_id: int) -> None:
        """便签被拖出了主窗口：就地转成桌面浮窗，接着跟手走。

        这里刻意不重建控件：正在拖的那只手还按着它，换了控件拖动就断了。
        """
        note = self.note_of.pop(memo_id, None)
        if note is None or memo_id in self.desk:
            return
        if note in self.notes:
            self.notes.remove(note)
        strip = self.strip_of.pop(memo_id, None)
        if strip is not None:
            strip.setParent(None)
            strip.deleteLater()
        self.store.set_memo_pinned(memo_id, True)     # 会顺手把它从原来那摞里摘出来
        note.memo.pinned = 1
        note.unpin_requested.connect(self._on_unpin)  # 转过去之后，钉按钮得能收回来
        note.host_changed.connect(self._on_host_changed)
        note.host_lost.connect(self._on_host_lost)
        note.pick_requested.connect(self._begin_pick)
        self.desk[memo_id] = note
        note.go_desk()
        # 同摞剩下的、页签序号要重排；这张已经不在画布名单里，重建时不会被删掉
        self.reload()

    def _on_desk_clicked(self, memo_id: int) -> None:
        note = self.desk.get(memo_id)
        if note is not None:
            note.begin_edit()

    def _on_pin(self, memo_id: int, spot: QPoint) -> None:
        """钉到桌面：从点「钉」按钮来的，就把便签挪到主窗口外面去。

        原地浮起来看着跟没动一样，挪出窗口才一眼看得出它脱离程序了；
        本来就是拖到窗口外松手的，落点按鼠标位置原样用。
        """
        if self.store.get_memo(memo_id) is None:
            return
        self.store.set_memo_pinned(memo_id, True)
        landing = self._desk_spot(spot)
        self.store.save_memo_pos(memo_id, landing.x(), landing.y())
        self.store.save_memo_host(memo_id)      # 新钉出来的先算没贴着谁，贴不贴看落点
        self.reload()
        note = self.desk.get(memo_id)
        if note is not None:
            self._attach_under(note)

    def _desk_spot(self, spot: QPoint) -> QPoint:
        """钉住后的落点：主窗口右边优先，右边挤不下就摆到下边。"""
        window = self.window()
        if window is None or not window.isVisible() or not window.frameGeometry().contains(spot):
            return spot
        frame = window.frameGeometry()
        screen = QApplication.screenAt(frame.center()) or QApplication.primaryScreen()
        if screen is None:
            return spot
        area = screen.availableGeometry()
        if frame.right() + DESK_GAP + NOTE_WIDTH <= area.right() + 1:
            return QPoint(frame.right() + DESK_GAP, spot.y())
        if frame.bottom() + DESK_GAP + NOTE_MIN_HEIGHT <= area.bottom() + 1:
            return QPoint(spot.x(), frame.bottom() + DESK_GAP)
        # 窗口几乎占满屏幕：就往右下角摆，出界由便签窗自己拉回来
        return QPoint(area.right() - NOTE_WIDTH + 1, area.bottom() - NOTE_MIN_HEIGHT + 1)

    def _on_unpin(self, memo_id: int) -> None:
        """收回页面：屏幕上落在哪儿就摆到画布对应的那一格。"""
        note = self.desk.get(memo_id)
        if note is None:
            return
        spot = self.canvas_pos(note.pos())
        self.store.set_memo_pinned(memo_id, False)
        self.store.save_memo_pos(memo_id, spot.x(), spot.y())
        self.store.save_memo_host(memo_id)      # 回页面了，就不再贴着谁的窗口
        self.reload()

    # ---------- 贴着的是哪个窗口 ----------

    def _on_host_changed(self, memo_id: int) -> None:
        """便签贴上了谁、或者从谁身上摘下来了，把这件事记进库。"""
        note = self.desk.get(memo_id)
        if note is None:
            return
        if not note.host:
            self.store.save_memo_host(memo_id)
            return
        rect = window_rect(note.host)
        if rect is None:
            self.store.save_memo_host(memo_id)
            return
        dx, dy = note.host_offset
        self.store.save_memo_host(
            memo_id, window_class(note.host), window_title(note.host), dx, dy
        )

    def _on_host_lost(self, memo_id: int) -> None:
        """贴着的那个窗口关掉了：便签自己回备忘录页面去。"""
        self._on_unpin(memo_id)

    def _attach_under(self, note: StickyNote) -> bool:
        """便签正盖着别人家的窗口就贴上去；盖着的是桌面或自家窗口就不贴。"""
        host = window_under(note)
        return bool(host) and note.attach_to(host)

    # ---------- 挑一个窗口贴上去 ----------

    def _begin_pick(self, memo_id: int) -> None:
        """右键选了「钉到某个窗口…」：接下来点哪个窗口，便签就贴上去。"""
        note = self.desk.get(memo_id)
        if note is None:
            return
        self._picking = memo_id
        self._pick_armed = False        # 菜单点完那只手可能还按着，先等它抬起来
        if self._pick_hint is None:
            self._pick_hint = _PickHint()
        self._pick_hint.follow(QCursor.pos())
        self._pick_hint.show()
        if self._pick_timer is None:
            self._pick_timer = QTimer(self)
            self._pick_timer.setInterval(PICK_TICK_MS)
            self._pick_timer.timeout.connect(self._poll_pick)
        self._pick_timer.start()

    def _poll_pick(self) -> None:
        """等用户去点一下目标窗口。"""
        note = self.desk.get(self._picking)
        if note is None:
            self._end_pick()
            return
        point = QCursor.pos()
        if self._pick_hint is not None:
            self._pick_hint.follow(point)
        if key_down(VK_ESCAPE) or key_down(VK_RBUTTON):
            self._end_pick()
            return
        if not self._pick_armed:
            self._pick_armed = not key_down(VK_LBUTTON)
            return
        if not key_down(VK_LBUTTON):
            return
        host = hwnd_at(point.x(), point.y())
        if not host or is_desktop(host) or host in own_windows():
            return          # 点在自己身上或桌面上：这次不算，接着挑
        note.attach_to(host)
        self._end_pick()

    def _end_pick(self) -> None:
        self._picking = 0
        self._pick_armed = False
        if self._pick_timer is not None:
            self._pick_timer.stop()
        if self._pick_hint is not None:
            self._pick_hint.hide()

    def canvas_pos(self, screen_point: QPoint) -> QPoint:
        """屏幕上这点对应画布里的哪一格。

        桌面上的便签通常飘在窗口外面，直接换算会落到画布边角上，
        这时就摆到当前视野的左上角，收回来一眼能看见。
        """
        viewport = self.scroll.viewport()
        visible = QRect(viewport.mapToGlobal(QPoint(0, 0)), viewport.size())
        if not visible.contains(screen_point):
            screen_point = visible.topLeft() + QPoint(24, 24)
        local = viewport.mapFromGlobal(screen_point)
        x = local.x() + self.scroll.horizontalScrollBar().value()
        y = local.y() + self.scroll.verticalScrollBar().value()
        return QPoint(
            max(0, min(x, max(0, self.canvas.width() - NOTE_WIDTH))),
            max(0, min(y, max(0, self.canvas.height() - NOTE_MIN_HEIGHT))),
        )

    def hide_desktop_notes(self) -> None:
        """主窗口缩到后台：桌面上的便签跟着一起收起来。"""
        self._desk_hidden = True
        self._end_pick()
        for note in self.desk.values():
            note.park()

    def show_desktop_notes(self) -> None:
        if not self._desk_hidden:
            return
        self._desk_hidden = False
        for note in self.desk.values():
            note.unpark()

    def close_desktop_notes(self) -> None:
        self._end_pick()
        for memo_id in list(self.desk):
            self._close_desk(memo_id)

    # ---------- 新建、编辑 ----------

    def create_note(self, point: QPoint) -> None:
        """在画布落点新建一张便签，并直接进入编辑状态。"""
        x = max(0, min(point.x(), max(0, self.canvas.width() - NOTE_WIDTH)))
        y = max(0, min(point.y(), max(0, self.canvas.height() - NOTE_MIN_HEIGHT)))
        memo_id = self.store.create_memo("", x, y)
        self.reload()
        note = self.note_of.get(memo_id)
        if note is not None:
            note.begin_edit()

    def _on_note_clicked(self, memo_id: int) -> None:
        # 拖出窗口的那张归到桌面那边了，两处都得找一下
        note = self.note_of.get(memo_id) or self.desk.get(memo_id)
        if note is not None:
            note.begin_edit()

    def _create_beside(self, memo_id: int) -> None:
        """在某张便签旁边新起一张，省得从画布另一头拖过来。"""
        memo = self.store.get_memo(memo_id)
        if memo is None:
            return
        x = min(memo.x + NOTE_WIDTH + 24, max(0, self.canvas.width() - NOTE_WIDTH))
        y = min(memo.y + 24, max(0, self.canvas.height() - NOTE_MIN_HEIGHT))
        new_id = self.store.create_memo("", x, y)
        self.reload()
        note = self.note_of.get(new_id)
        if note is not None:
            note.begin_edit()

    def create_desk_note(self, spot: QPoint) -> None:
        """在屏幕上的某点直接摊一张桌面便签（全局快捷键走的就是这里）。

        主窗口可能正缩在托盘里、桌面便签被一并藏着，所以这一张要单独露面：
        是用户主动叫出来的，总得让人看见、能接着写。
        """
        x, y = int(spot.x()), int(spot.y())
        memo_id = self.store.create_memo("", x, y)
        self.store.set_memo_pinned(memo_id, True)
        self.store.save_memo_pos(memo_id, x, y)
        self.store.save_memo_host(memo_id)      # 刚开出来的，还没贴在谁身上
        self.reload()
        note = self.desk.get(memo_id)
        if note is None:
            return
        note.unpark()
        note.activateWindow()
        note.begin_edit()

    def _on_note_edited(self, memo_id: int, text: str) -> None:
        self.store.update_memo_content(memo_id, text)
        if not self._reloading:
            self._resize_canvas()

    def _on_note_moved(self, memo_id: int) -> None:
        note = self.note_of.get(memo_id)
        if note is None:
            return
        note.raise_()
        strip = self.strip_of.get(memo_id)
        if strip is not None:
            strip.raise_()
        self._place_strip(note)

    # ---------- 并摞 ----------

    def _on_drag_finished(self, memo_id: int) -> None:
        note = self.note_of.get(memo_id)
        if note is None:
            # 拖到一半变身桌面浮窗了，松手就是落定位置
            self._on_desk_drag_finished(memo_id)
            return
        self.store.save_memo_pos(memo_id, note.x(), note.y())

        target = self._merge_target(note)
        if target is None:
            return
        if self.store.merge_memos(target.memo.id, memo_id):
            self.reload()
        else:
            QMessageBox.information(
                self,
                "一摞最多五张",
                f"这一摞已经叠了 {MAX_MEMO_STACK} 张，这张先放在旁边吧。",
            )

    def _merge_target(self, note: StickyNote) -> StickyNote | None:
        """找与刚放下的便签大面积重叠的那一张；没有就返回 None。"""
        mine = note.memo.stack_id or note.memo.id
        for other in self.notes:
            if other is note:
                continue
            # 单独一张的 stack_id 是 0，拿它比会误判成「同一摞」，得先归一化
            theirs = other.memo.stack_id or other.memo.id
            if theirs == mine:
                continue
            if _overlap_ratio(note.geometry(), other.geometry()) >= MERGE_RATIO:
                return other
        return None

    def _on_stack_selected(self, stack_id: int, memo_id: int) -> None:
        self.store.promote_in_stack(stack_id, memo_id)
        self.reload()

    # ---------- 拆开与删除 ----------

    def _detach(self, memo_id: int) -> None:
        """把一张便签从摞里拿出来，挪到旁边，免得跟原来的摞叠在一起分不清。"""
        memo = self.store.get_memo(memo_id)
        if memo is None or not memo.stack_id:
            return
        self.store.detach_memo(memo_id)
        x = min(memo.x + NOTE_WIDTH + 24, max(0, self.canvas.width() - NOTE_WIDTH))
        y = min(memo.y + 24, max(0, self.canvas.height() - NOTE_MIN_HEIGHT))
        self.store.save_memo_pos(memo_id, x, y)
        self.reload()

    def _on_split(self, memo_id: int) -> None:
        """整摞拆开：扇形铺开，一眼能看出刚才叠在一起的是哪几张。"""
        memo = self.store.get_memo(memo_id)
        if memo is None or not memo.stack_id:
            return
        members = self.store.stack_members(memo.stack_id)
        self.store.split_stack(memo.stack_id)
        for index, member in enumerate(members):
            self.store.save_memo_pos(
                member.id,
                memo.x + index * (NOTE_WIDTH + 16),
                memo.y + index * 26,
            )
        self.reload()

    def _on_delete(self, memo_id: int) -> None:
        memo = self.store.get_memo(memo_id)
        if memo is None:
            return
        confirmed = QMessageBox.question(
            self,
            "删除便签",
            f"确定删除这张便签吗？\n\n{_preview(memo.content, 40)}",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_memo(memo_id)
        self.reload()
