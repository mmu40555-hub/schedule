"""便签相关的小控件：合并预览框、便签编辑框、画布、拾取提示条。"""

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from theme import APP_QSS


class _MergePreview(QDialog):
    """合并前的最终效果预览：正文只读，点「确认合并」才真正并成一张。"""

    def __init__(self, contents: list[str], merged: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("合并便签预览")
        self.setMinimumSize(460, 360)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        tip = QLabel(
            f"将按页签顺序把 {len(contents)} 张便签合并成一整张，"
            f"中间用分割线隔开。合并后原来的几张会并进来，"
            f"分割线就在正文里，想删随手删掉即可。"
        )
        tip.setObjectName("PageDate")
        tip.setWordWrap(True)
        box.addWidget(tip)

        view = QTextEdit()
        view.setObjectName("MergePreview")
        view.setReadOnly(True)
        view.setPlainText(merged)
        box.addWidget(view, 1)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        confirm = buttons.addButton("确认合并", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        box.addWidget(buttons)


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
