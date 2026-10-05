"""一摞便签右侧的竖排小页签：点谁就显示谁。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QMenu, QPushButton, QVBoxLayout, QWidget

from storage import Memo

from .consts import TAB_HEIGHT, TAB_SPACING, TAB_WIDTH
from .helpers import _preview


class TabStrip(QWidget):
    """一摞便签右侧的竖排小页签：点谁就显示谁。"""

    selected = pyqtSignal(int, int)      # stack_id, memo_id
    detach_requested = pyqtSignal(int)   # memo_id
    split_requested = pyqtSignal(int)    # stack_id
    merge_requested = pyqtSignal(int)    # stack_id

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
        menu.addAction("合并成一整张…", lambda: self.merge_requested.emit(self.stack_id))
        menu.exec(button.mapToGlobal(pos))
