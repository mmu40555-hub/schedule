"""和别的程序窗口打交道：「钉在某个程序窗口上」全靠这里的原生调用实现。

这里刻意不去设窗口的 owner：owner 关系下宿主一关，便签会被系统连带销毁，
Qt 那边会留下一个自己都不知道已经没了的窗口。改成自己盯着宿主，四条联动
都由自己拿主意：位置跟着走、最小化一并藏、关掉就收回、Z 序压在宿主之上。
"""

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QWidget

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
