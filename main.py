"""日程计划表 · 程序入口。

运行： python main.py
数据： 首次运行会在同目录生成 schedule.db 并写入一份演示数据
说明： 程序只允许开一个窗口，重复运行会把已有窗口唤到最前，不会多开
       关掉主窗口不会退出程序，而是收进系统托盘继续后台运行（到点提醒照常），
       要真正结束得从托盘图标右键菜单里选「退出程序」
"""

import sys

from PyQt6.QtCore import QEvent, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from hotkey import GlobalHotkey
from memo import MemoPage
from sound import ensure_sound_dir
from storage import NAV_LEFT, Store
from theme import APP_QSS, FONT_FAMILY
from today_view import TodayView
from updater import run_check, schedule_startup_check

# 单实例用的本地套接字名，同一台机器上唯一
SERVER_NAME = "schedule-single-instance"

# 图标主色跟界面保持一致
ICON_BLUE = "#2F80ED"

# 一整套尺寸，托盘、任务栏、窗口角标各取所需
ICON_SIZES = (16, 24, 32, 48, 64, 128)


def _app_icon() -> QIcon:
    """程序图标：项目里没有图片资源，直接画一个蓝底白勾。"""
    icon = QIcon()
    for size in ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        inset = size * 0.08
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ICON_BLUE))
        painter.drawRoundedRect(
            QRectF(inset, inset, size - inset * 2, size - inset * 2),
            size * 0.24,
            size * 0.24,
        )

        pen = QPen(QColor("#FFFFFF"), max(1.4, size * 0.1))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        path.moveTo(size * 0.28, size * 0.52)
        path.lineTo(size * 0.44, size * 0.68)
        path.lineTo(size * 0.74, size * 0.33)
        painter.drawPath(path)
        painter.end()

        icon.addPixmap(pixmap)
    return icon


class MainWindow(QMainWindow):
    # 主导航上的两页：键、按钮文字
    PAGES = (("today", "今日一览"), ("memo", "备忘录"))

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.tray = None          # 托盘不可用时保持 None，关窗即退出
        self._quitting = False    # 托盘菜单点了「退出」，这次关窗要动真格
        self.setWindowTitle("日程计划表")
        self.setWindowIcon(_app_icon())
        self.resize(1280, 840)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(APP_QSS)

        self.today_view = TodayView(store)
        self.memo_view = MemoPage(store)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.today_view)
        self.stack.addWidget(self.memo_view)

        self._page = "today"
        self._nav_position = store.nav_position()
        self.nav_buttons: dict[str, QPushButton] = {}

        # 设置里换了导航位置，主窗口得重搭一次骨架
        self.today_view.settings_saved.connect(self._on_settings_saved)
        self._build_layout()
        self._refresh_nav()

        # 全局快捷键：程序不在前台时，按下也能在鼠标处开一张桌面便签
        self.hotkey = GlobalHotkey(self, self)
        self.hotkey.activated.connect(
            self._on_hotkey, Qt.ConnectionType.QueuedConnection
        )
        self.apply_hotkey()

    # ---------- 页面导航 ----------

    def _build_layout(self) -> None:
        """按设置搭骨架：导航在上方横排，或在左侧竖排。"""
        self._nav_position = self.store.nav_position()
        left = self._nav_position == NAV_LEFT

        container = QWidget()
        if left:
            root = QHBoxLayout(container)
        else:
            root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_nav(left))
        root.addWidget(self.stack, 1)

        old = self.centralWidget()
        self.setCentralWidget(container)
        if old is not None:
            old.deleteLater()

    def _build_nav(self, left: bool) -> QWidget:
        bar = QWidget()
        bar.setObjectName("NavRail" if left else "NavBar")

        box = QVBoxLayout(bar) if left else QHBoxLayout(bar)
        if left:
            box.setContentsMargins(10, 14, 10, 14)
            bar.setFixedWidth(160)
        else:
            box.setContentsMargins(20, 10, 20, 10)
        box.setSpacing(6)

        self.nav_buttons = {}
        for key, title in self.PAGES:
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _, page=key: self.show_page(page))
            box.addWidget(button)
            self.nav_buttons[key] = button
        box.addStretch(1)
        return bar

    def show_page(self, key: str) -> None:
        index = [page for page, _ in self.PAGES].index(key)
        self.stack.setCurrentIndex(index)
        self._page = key
        if key == "memo":
            # 别处可能动过便签，切进来时按库里的数据重铺一遍
            self.memo_view.reload()
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        for key, button in self.nav_buttons.items():
            name = "NavButtonActive" if key == self._page else "NavButton"
            if button.objectName() == name:
                continue
            button.setObjectName(name)
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_settings_saved(self) -> None:
        self.apply_hotkey()
        if self.store.nav_position() == self._nav_position:
            return
        # 先把页面栈摘出来，免得随旧骨架一起被回收
        self.stack.setParent(None)
        self._build_layout()
        self._refresh_nav()

    # ---------- 全局快捷键 ----------

    def apply_hotkey(self) -> None:
        """按设置里的组合键重新注册；注册不上就通过托盘说一声。"""
        shortcut = self.store.new_note_hotkey()
        if not shortcut:
            self.hotkey.unregister()
            return
        if self.hotkey.register(shortcut):
            return
        if self.tray is not None:
            self.tray.showMessage(
                "便签快捷键没能启用",
                f"{shortcut} 可能已被别的程序占用，到设置里换一个组合试试。",
                QSystemTrayIcon.MessageIcon.Warning,
                4000,
            )

    def _on_hotkey(self) -> None:
        """快捷键对应的动作：在鼠标位置直接摊一张桌面便签。"""
        self.memo_view.create_desk_note(QCursor.pos())

    # ---------- 托盘与退出 ----------

    def attach_tray(self, tray: "TrayIcon") -> None:
        self.tray = tray
        # 这会儿才有托盘可以报信，补注册一次
        self.apply_hotkey()

    def changeEvent(self, event):
        """最小化 / 还原时，钉在桌面上的便签跟着一起收起、露面。"""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.memo_view.hide_desktop_notes()
            else:
                self.memo_view.show_desktop_notes()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.tray is not None and not self._quitting:
            # 收进托盘接着跑：悬浮窗和到点提醒都不受影响
            event.ignore()
            self.hide()
            self.memo_view.hide_desktop_notes()
            self.tray.note_hidden()
            return
        # 真退出：悬浮窗和桌面便签都是独立顶层窗口，不收掉程序会留在后台
        self.today_view.close_floating()
        self.memo_view.close_desktop_notes()
        super().closeEvent(event)

    def quit_app(self) -> None:
        """托盘菜单里的「退出程序」。"""
        self._quitting = True
        self.close()
        QApplication.quit()

    def bring_to_front(self) -> None:
        """被第二个实例唤醒时调用：从最小化或托盘里恢复并抢到最前。"""
        if self.windowState() & Qt.WindowState.WindowMinimized:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.memo_view.show_desktop_notes()
        self.raise_()
        self.activateWindow()


class TrayIcon(QSystemTrayIcon):
    """系统托盘图标：主窗口收起来后程序就待在这里，也只有这里能真的退出。"""

    def __init__(self, window: MainWindow):
        super().__init__(_app_icon(), window)
        self.window_ref = window
        self.setToolTip("日程计划表")
        self._tip_shown = False

        menu = QMenu()
        open_action = menu.addAction("打开主窗口")
        open_action.triggered.connect(window.bring_to_front)
        update_action = menu.addAction("检查更新…")
        update_action.triggered.connect(self._check_update)
        menu.addSeparator()
        quit_action = menu.addAction("退出程序")
        quit_action.triggered.connect(window.quit_app)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _check_update(self) -> None:
        """托盘里手动查一次更新；结果会直接弹窗告知。"""
        run_check(self.window_ref, self.window_ref.store, silent=False)

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.window_ref.bring_to_front()

    def note_hidden(self) -> None:
        """第一次收进托盘时提示一句，免得以为程序被关掉了。"""
        if self._tip_shown:
            return
        self._tip_shown = True
        self.showMessage(
            "日程计划表仍在后台运行",
            "到点提醒照常工作。双击托盘图标可以重新打开主窗口，"
            "右键菜单里可以退出程序。",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )


def _wake_existing_instance() -> bool:
    """已有实例在跑就唤醒它的窗口并返回 True。"""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def _listen_single_instance(window: MainWindow) -> QLocalServer:
    """占用套接字名；之后每次有实例连上来，就把窗口唤到最前。"""
    server = QLocalServer(window)
    if not server.listen(SERVER_NAME):
        # 上次异常退出可能留下了同名套接字，清掉再试一次
        QLocalServer.removeServer(SERVER_NAME)
        server.listen(SERVER_NAME)

    def on_new_connection() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.readyRead.connect(connection.readAll)
            connection.disconnected.connect(connection.deleteLater)
            connection.disconnectFromServer()
        window.bring_to_front()

    server.newConnection.connect(on_new_connection)
    return server


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont(FONT_FAMILY, 10))
    app.setWindowIcon(_app_icon())

    # 已经有窗口在跑就不再开第二个
    if _wake_existing_instance():
        return

    # 提醒音自定义用的「铃声」文件夹：启动时就摆出来，用户可以直接把音乐丢进去
    ensure_sound_dir()

    store = Store()
    window = MainWindow(store)
    server = _listen_single_instance(window)  # noqa: F841 需存活到程序退出

    # 有托盘就常驻：主窗口关掉只是收起来，程序继续在后台跑
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(window)
        window.attach_tray(tray)
        tray.show()
        app.setQuitOnLastWindowClosed(False)

    window.show()

    # 启动后悄悄看一眼有没有新版本（每 24 小时最多一次，可以在设置里关掉）
    schedule_startup_check(window, store)

    exit_code = app.exec()
    store.close()
    server.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
