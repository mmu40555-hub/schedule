"""废弃栏：丢掉便签的收容所。

左边是「子页栏」，一张丢掉的便签算一个子页，按丢弃时间排（最近丢的在最前）；
可以多选，选中的子页会置顶到子页栏最上面，取消选中才落回原位。
右边同时铺开选中的那几张的内容 —— 这里只看内容，不再是桌面上的便签窗。

上面一个搜索框按关键词筛子页；工具栏对选中的子页做「还原」或「彻底丢弃」。
彻底丢弃是唯一真正删掉便签的地方，所以要再确认一次。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from storage import Memo, Store


def _preview(text: str, limit: int = 28) -> str:
    """把便签内容压成一行摘要，给子页栏当标题。"""
    flat = " ".join((text or "").split())
    if not flat:
        return "（空白便签）"
    return flat[:limit] + ("…" if len(flat) > limit else "")


class _SubPageItem(QFrame):
    """子页栏里的一个子页：点一下切换选中。"""

    clicked = pyqtSignal(int)

    def __init__(self, memo: Memo, parent=None):
        super().__init__(parent)
        self.memo_id = memo.id
        self.setObjectName("SubPageItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"丢弃于 {memo.discarded_at}\n{memo.content}")

        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)

        self.title = QLabel(_preview(memo.content))
        self.title.setObjectName("SubPageTitle")
        box.addWidget(self.title)

        when = QLabel(memo.discarded_at[:16])
        when.setObjectName("SubPageTime")
        box.addWidget(when)

    def set_selected(self, selected: bool) -> None:
        name = "SubPageItemOn" if selected else "SubPageItem"
        if self.objectName() == name:
            return
        self.setObjectName(name)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.memo_id)
        super().mousePressEvent(event)


class TrashView(QWidget):
    """废弃栏页面。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setObjectName("TrashPage")
        self.store = store
        self._keyword = ""
        self._selected: list[int] = []      # 选中的子页 id，按选中的先后排
        self._memos: list[Memo] = []
        self._items: dict[int, _SubPageItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addWidget(self._build_search())
        root.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("TrashSplitter")
        splitter.addWidget(self._build_bar())
        splitter.addWidget(self._build_content())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 720])
        root.addWidget(splitter, 1)

        self.reload()

    # ---------- 骨架 ----------

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("废弃栏")
        title.setObjectName("PageTitle")
        left.addWidget(title)
        hint = QLabel("丢掉便签的收容所；可以多选几页一起看，也能还原回备忘录或彻底删除")
        hint.setObjectName("PageDate")
        left.addWidget(hint)
        row.addLayout(left)
        row.addStretch(1)

        self.count_label = QLabel()
        self.count_label.setObjectName("StatText")
        row.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignBottom)
        return row

    def _build_search(self) -> QWidget:
        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("搜索丢弃的便签内容…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        return self.search

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.select_hint = QLabel("在左边点子页选中，可多选")
        self.select_hint.setObjectName("FieldHint")
        row.addWidget(self.select_hint)
        row.addStretch(1)

        self.restore_button = QPushButton("还原选中")
        self.restore_button.setObjectName("GhostButton")
        self.restore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_button.clicked.connect(self._on_restore)
        row.addWidget(self.restore_button)

        self.purge_button = QPushButton("彻底丢弃选中")
        self.purge_button.setObjectName("DangerButton")
        self.purge_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.purge_button.setToolTip("删掉就找不回来了")
        self.purge_button.clicked.connect(self._on_purge)
        row.addWidget(self.purge_button)
        return row

    def _build_bar(self) -> QWidget:
        self.bar = QWidget()
        self.bar.setObjectName("TrashBar")
        self.bar_box = QVBoxLayout(self.bar)
        self.bar_box.setContentsMargins(8, 8, 8, 8)
        self.bar_box.setSpacing(6)

        scroll = QScrollArea()
        scroll.setObjectName("TrashBarScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.bar)
        scroll.setMinimumWidth(220)
        return scroll

    def _build_content(self) -> QWidget:
        self.content = QWidget()
        self.content.setObjectName("TrashContent")
        self.content_box = QVBoxLayout(self.content)
        self.content_box.setContentsMargins(12, 12, 12, 12)
        self.content_box.setSpacing(12)

        scroll = QScrollArea()
        scroll.setObjectName("TrashContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.content)
        return scroll

    # ---------- 数据 ----------

    def reload(self) -> None:
        """重新问一次库，重建子页栏。"""
        self._memos = self.store.list_discarded_memos()
        alive = {memo.id for memo in self._memos}
        self._selected = [item for item in self._selected if item in alive]

        for item in self._items.values():
            item.setParent(None)
            item.deleteLater()
        self._items = {}
        for memo in self._memos:
            item = _SubPageItem(memo)
            item.clicked.connect(self._on_toggle)
            self._items[memo.id] = item

        self._refresh_bar()
        self._refresh_content()
        self._refresh_count()

    def _visible(self) -> list[Memo]:
        if not self._keyword:
            return self._memos
        return [memo for memo in self._memos if self._keyword in (memo.content or "").lower()]

    def _bar_order(self) -> list[Memo]:
        """选中的子页置顶，其余按丢弃时间跟在后头。"""
        visible = self._visible()
        chosen = [memo for memo in visible if memo.id in self._selected]
        rest = [memo for memo in visible if memo.id not in self._selected]
        return chosen + rest

    def _selected_memos(self) -> list[Memo]:
        """选中的便签，顺序跟子页栏一致。"""
        ordered = self._bar_order()
        return [memo for memo in ordered if memo.id in self._selected]

    def _refresh_bar(self) -> None:
        # 清布局不能只 takeAt：控件还挂在 bar 上照样显示，旧的空提示会一直赖着。
        # 子页留着复用（下面再挂回去），空提示这类临时控件直接销毁。
        reusable = {id(widget) for widget in self._items.values()}
        while self.bar_box.count():
            entry = self.bar_box.takeAt(0)
            widget = entry.widget()
            if widget is None:
                continue
            widget.setParent(None)
            if id(widget) not in reusable:
                widget.deleteLater()
        ordered = self._bar_order()
        if not ordered:
            label = QLabel("没有匹配的便签" if self._memos else "废弃栏还是空的")
            label.setObjectName("EmptyHint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bar_box.addWidget(label)
        else:
            for memo in ordered:
                item = self._items[memo.id]
                item.set_selected(memo.id in self._selected)
                self.bar_box.addWidget(item)
        self.bar_box.addStretch(1)

    def _refresh_content(self) -> None:
        while self.content_box.count():
            item = self.content_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        chosen = self._selected_memos()
        if not chosen:
            label = QLabel("在左边点一个子页，这里就摊开它的内容；可以同时选好几页")
            label.setObjectName("EmptyHint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_box.addWidget(label)
        else:
            for memo in chosen:
                self.content_box.addWidget(self._content_card(memo))
        self.content_box.addStretch(1)

    def _content_card(self, memo: Memo) -> QFrame:
        card = QFrame()
        card.setObjectName("TrashCard")

        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(_preview(memo.content, 40))
        title.setObjectName("TrashCardTitle")
        head.addWidget(title, 1)
        when = QLabel(f"丢弃于 {memo.discarded_at[:16]}")
        when.setObjectName("EntryTime")
        head.addWidget(when, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(head)

        body = QLabel(memo.content or "（这张便签是空的）")
        body.setObjectName("TrashCardBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(body)
        return card

    def _refresh_count(self) -> None:
        total = len(self._memos)
        picked = len(self._selected)
        if self._keyword:
            self.count_label.setText(f"{len(self._visible())} / {total} 张便签")
        else:
            self.count_label.setText(f"共 {total} 张便签")
        self.select_hint.setText(
            f"已选中 {picked} 页" if picked else "在左边点子页选中，可多选"
        )
        self.restore_button.setEnabled(bool(picked))
        self.purge_button.setEnabled(bool(picked))

    # ---------- 交互 ----------

    def _on_search(self, text: str) -> None:
        keyword = text.strip().lower()
        if keyword == self._keyword:
            return
        self._keyword = keyword
        self._refresh_bar()
        self._refresh_count()

    def _on_toggle(self, memo_id: int) -> None:
        """点一下子页：选中就置顶，再点一下取消，落回原来的位置。"""
        if memo_id in self._selected:
            self._selected.remove(memo_id)
        else:
            self._selected.append(memo_id)
        self._refresh_bar()
        self._refresh_content()
        self._refresh_count()

    def _on_restore(self) -> None:
        chosen = self._selected_memos()
        if not chosen:
            return
        for memo in chosen:
            self.store.restore_memo(memo.id)
        self._selected = []
        self.reload()

    def _on_purge(self) -> None:
        chosen = self._selected_memos()
        if not chosen:
            return
        confirmed = QMessageBox.question(
            self,
            "彻底丢弃",
            f"确定彻底丢弃选中的 {len(chosen)} 张便签吗？\n\n"
            f"{'、'.join(_preview(memo.content, 14) for memo in chosen[:5])}"
            f"{' …' if len(chosen) > 5 else ''}\n\n删掉就找不回来了。",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.purge_memos([memo.id for memo in chosen])
        self._selected = []
        self.reload()
