"""全局快捷键：程序不在前台时，按下组合键也能收到通知。

注册走 Win32 的 RegisterHotKey，消息落在主窗口上，由 Qt 的原生事件过滤器
（WM_HOTKEY）转成 activated 信号。不依赖键盘钩子，所以不会拦截别的程序的按键。

快捷键文本形如 "Ctrl+Alt+N"：解析成「修饰键 + 主键」交给系统，也负责把两者
拼回同一种文本，供设置界面显示。
"""

import ctypes
import time
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

# RegisterHotKey 的修饰键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# 按住不放时不重复触发（Windows 7 起可用）
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

# 修饰键的名字与顺序：显示成 Ctrl+Alt+N 这种惯用写法
_MOD_ORDER = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT),
              ("Shift", MOD_SHIFT), ("Win", MOD_WIN))
_MOD_BY_NAME = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN,
}

# 支持作主键的按键：字母、数字、功能键，外加几个常用的符号与编辑键
_VK_BY_NAME: dict[str, int] = {}
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _VK_BY_NAME[_ch] = ord(_ch)
for _i in range(1, 25):
    _VK_BY_NAME[f"F{_i}"] = 0x70 + _i - 1
_VK_BY_NAME.update({
    "Space": 0x20, "Tab": 0x09, "Enter": 0x0D, "Backspace": 0x08,
    "Delete": 0x2E, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
    "PageUp": 0x21, "PageDown": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
})
_NAME_BY_VK = {vk: name for name, vk in _VK_BY_NAME.items()}

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                   ctypes.c_uint, ctypes.c_uint]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL


def _canonical_key(text: str) -> str | None:
    """把用户写的主键名规整成表里的标准写法；认不出来返回 None。"""
    stripped = text.strip()
    if not stripped:
        return None
    upper = stripped.upper()
    if upper in _VK_BY_NAME:
        return upper
    for name in _VK_BY_NAME:
        if name.lower() == stripped.lower():
            return name
    return None


def parse(shortcut: str) -> tuple[int, int] | None:
    """把 "Ctrl+Alt+N" 解析成 (修饰键, 主键)；不合法或太霸道就返回 None。

    不做修饰键的裸键（功能键除外）也拒掉：全局热键会抢走整机的这个按键，
    只按一个字母当热键会把别处打字也搅乱。
    """
    if not shortcut:
        return None
    parts = [part.strip() for part in shortcut.split("+") if part.strip()]
    if not parts:
        return None
    mods = 0
    for part in parts[:-1]:
        mask = _MOD_BY_NAME.get(part.lower())
        if mask is None:
            return None
        mods |= mask
    key = _canonical_key(parts[-1])
    if key is None:
        return None
    if not mods and not key.startswith("F"):
        return None
    return mods, _VK_BY_NAME[key]


def format_shortcut(mods: int, vk: int) -> str:
    """(修饰键, 主键) 拼回 "Ctrl+Alt+N" 这样的文本。"""
    parts = [name for name, mask in _MOD_ORDER if mods & mask]
    key = _NAME_BY_VK.get(vk)
    if key:
        parts.append(key)
    return "+".join(parts)


class _HotkeyFilter(QAbstractNativeEventFilter):
    """真正接系统消息的过滤器。

    单独一个对象，不跟 QObject 混在一个类里：PyQt6 里 QObject 与
    QAbstractNativeEventFilter 多继承会让虚拟派发失效，过滤器收不到任何消息。
    """

    # 一次按键 Windows 偶尔会连投两条 WM_HOTKEY（合成的输入尤其如此），
    # 这个间隔内的重复消息只当一次，免得一下开出两张便签。
    REPEAT_GUARD = 0.25

    def __init__(self, owner: "GlobalHotkey"):
        super().__init__()
        self._owner = owner
        self._last = 0.0

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY and int(msg.wParam) == GlobalHotkey.HOTKEY_ID:
                now = time.monotonic()
                if now - self._last >= self.REPEAT_GUARD:
                    self._last = now
                    self._owner.activated.emit()
        return False, 0


class GlobalHotkey(QObject):
    """把一套组合键注册到系统，任何程序在前台时按下都会发出 activated。"""

    activated = pyqtSignal()

    # 进程内唯一即可；WM_HOTKEY 靠它认出是不是自己注册的那个
    HOTKEY_ID = 0x5A17

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window          # 注册挂在它的窗口上，消息也落到它这儿
        self._hwnd = 0
        self._active = False
        # 过滤器交给全局，这里留一份引用免得被回收
        self._filter = _HotkeyFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    @property
    def active(self) -> bool:
        return self._active

    def register(self, shortcut: str) -> bool:
        """按快捷键文本注册；文本不合法或系统里已被占用就返回 False。"""
        self.unregister()
        parsed = parse(shortcut)
        if parsed is None:
            return False
        mods, vk = parsed
        hwnd = int(self._window.winId())
        if not _user32.RegisterHotKey(wintypes.HWND(hwnd), self.HOTKEY_ID,
                                      mods | MOD_NOREPEAT, vk):
            return False
        self._hwnd = hwnd
        self._active = True
        return True

    def unregister(self) -> None:
        if not self._active:
            return
        _user32.UnregisterHotKey(wintypes.HWND(self._hwnd), self.HOTKEY_ID)
        self._active = False
        self._hwnd = 0
