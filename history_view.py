"""历史汇总：把做完的任务按时间倒序摊开看，长期任务不算在内。

只读一页：上面一个搜索框，下面一条条完成记录。数据全部现查现铺，
所以切进来时调一次 reload() 就能看到最新的。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models import SOURCE_LABEL
from storage import Store
from theme import SOURCE_COLOR, rgba


def _time_text(entry) -> str:
    """有完成时刻就显示到分钟；老数据没有，就标明用的是计划日期。"""
    if entry.done_at:
        return entry.done_at[:16]
    if entry.plan:
        return f"计划 {entry.plan}"
    return "时间不详"


class HistoryView(QWidget):
    """历史汇总页面。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.setObjectName("HistoryPage")
        self.store = store
        self._keyword = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())
        root.addWidget(self._build_search())

        self.body = QWidget()
        self.body.setObjectName("HistoryBody")
        self.body_box = QVBoxLayout(self.body)
        self.body_box.setContentsMargins(0, 0, 0, 0)
        self.body_box.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("HistoryScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        self.reload()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("历史汇总")
        title.setObjectName("PageTitle")
        left.addWidget(title)
        hint = QLabel("所有做完的任务按完成时间倒序排列，长期任务不进这里")
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
        self.search.setPlaceholderText("搜索任务名、归属或备注…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        return self.search

    def _on_search(self, text: str) -> None:
        keyword = text.strip().lower()
        if keyword == self._keyword:
            return
        self._keyword = keyword
        self._fill()

    # ---------- 铺内容 ----------

    def reload(self) -> None:
        """重新问一次库；页面不常开，整体重建最省心。"""
        self.entries = self.store.completed_history()
        self._fill()

    def _fill(self) -> None:
        while self.body_box.count():
            item = self.body_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        shown = [entry for entry in self.entries if self._match(entry)]
        if not shown:
            self.body_box.addWidget(self._placeholder())
        else:
            for entry in shown:
                self.body_box.addWidget(self._entry_card(entry))
        self.body_box.addStretch(1)

        if self._keyword:
            self.count_label.setText(f"{len(shown)} / {len(self.entries)} 条记录")
        else:
            self.count_label.setText(f"共 {len(self.entries)} 条记录")

    def _match(self, entry) -> bool:
        if not self._keyword:
            return True
        haystack = f"{entry.title} {entry.group} {entry.note}".lower()
        return self._keyword in haystack

    def _placeholder(self) -> QLabel:
        text = "没有匹配的完成记录" if self.entries else "还没有完成的记录"
        label = QLabel(text)
        label.setObjectName("EmptyHint")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _entry_card(self, entry) -> QFrame:
        card = QFrame()
        card.setObjectName("HistoryEntry")

        box = QVBoxLayout(card)
        box.setContentsMargins(14, 11, 14, 11)
        box.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)

        color = SOURCE_COLOR.get(entry.source, "#94A3B8")
        chip = QLabel(SOURCE_LABEL.get(entry.source, "任务"))
        chip.setObjectName("EntryChip")
        chip.setStyleSheet(
            f"color: {color}; background: {rgba(color, 0.12)};"
            " border-radius: 4px; padding: 1px 7px; font-size: 12px;"
        )
        top.addWidget(chip, 0)

        title = QLabel(entry.title)
        title.setObjectName("EntryTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)

        when = QLabel(_time_text(entry))
        when.setObjectName("EntryTime")
        top.addWidget(when, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(top)

        if entry.group or entry.note:
            meta = QLabel(" · ".join(part for part in (entry.group, entry.note) if part))
            meta.setObjectName("EntryMeta")
            meta.setWordWrap(True)
            box.addWidget(meta)
        return card
