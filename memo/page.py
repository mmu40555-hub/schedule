"""备忘录页面：一块可滚动的自由画布，外加摊在桌面上的那几张便签。

- 画布空白处右键 → 新建便签，便签大小随内容自适应
- 便签上单击就地编辑，点别处自动保存；按住拖动则是挪位置
- 允许简单重叠；与另一张重叠面积过大时松手，两张就叠成一摞
- 叠起来后画布上只留一张，右侧一列小页签切换浏览，一摞最多五张
- 页签右键能把某张移出这一摞，便签右键可以拆开整摞或删掉
- 便签右键「合并成一整张…」可按页签序号把整摞并成一张：先弹出最终效果预览确认，
  合并后各段之间垫一条分割线，分割线就是普通文字，想删随手删掉即可
- 便签可以直接拖出主窗口：一出窗口边沿就当场变成桌面浮窗、一路跟手走；
  松手时压在哪个程序窗口上，就钉在哪个窗口上（浏览器、游戏启动器都行），
  底下要是光秃秃的桌面，那就只是浮在桌面最上层
- 钉在窗口上的便签跟那个窗口联动：窗口挪它跟着挪，窗口最小化它一并藏起来，
  窗口关掉它自己收回备忘录页面；拖得离那个窗口足够远，就自动改回普通浮窗
- 便签右键「钉到某个窗口…」也可以先指定再贴：选完点一下目标窗口即可
- 便签右上角的「钉」也能把它钉到桌面上（会挪到主窗口右边），再点一下收回页面
"""

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from storage import MAX_MEMO_STACK, Memo, Store

from .consts import (
    CANVAS_MARGIN,
    CANVAS_MIN_HEIGHT,
    CANVAS_MIN_WIDTH,
    DESK_GAP,
    MERGE_RATIO,
    NOTE_MIN_HEIGHT,
    NOTE_WIDTH,
    PICK_TICK_MS,
    STRIP_GAP,
    TAB_WIDTH,
)
from .helpers import _merge_texts, _overlap_ratio, _preview
from .sticky_note import StickyNote
from .tab_strip import TabStrip
from .widgets import _Canvas, _MergePreview, _PickHint
from .win32 import (
    VK_ESCAPE,
    VK_LBUTTON,
    VK_RBUTTON,
    find_window,
    hwnd_at,
    is_desktop,
    key_down,
    own_windows,
    window_alive,
    window_class,
    window_rect,
    window_title,
    window_under,
)


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
            note.discard_requested.connect(self._on_discard)
            note.detach_requested.connect(self._detach)
            note.split_requested.connect(self._on_split)
            note.merge_requested.connect(self._on_merge)
            note.show()
            self.notes.append(note)
            self.note_of[host.id] = note

            if len(members) > 1:
                strip = TabStrip(host.stack_id, members, host.id, self.canvas)
                strip.selected.connect(self._on_stack_selected)
                strip.detach_requested.connect(self._detach)
                strip.split_requested.connect(self._on_split)
                strip.merge_requested.connect(self._on_merge)
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
        note.discard_requested.connect(self._on_discard)
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

    def _on_merge(self, stack_id: int) -> None:
        """把一摞便签按页签序号合并成一整张：先给用户看一眼最终效果再落定。"""
        members = self.store.stack_members(stack_id)
        if len(members) < 2:
            return
        contents = [member.content for member in members]
        merged = _merge_texts(contents)
        if _MergePreview(contents, merged, self).exec() != QDialog.DialogCode.Accepted:
            return
        if self.store.merge_stack_into_one(stack_id, merged) is None:
            return
        self.reload()

    def _on_discard(self, memo_id: int) -> None:
        """把便签丢进「废弃栏」：从备忘录收起来，内容留着随时能翻回来。"""
        memo = self.store.get_memo(memo_id)
        if memo is None:
            return
        confirmed = QMessageBox.question(
            self,
            "丢弃便签",
            f"丢弃后这张便签就从备忘录收起来了，可以随时到「废弃栏」页面找回。\n\n"
            f"{_preview(memo.content, 40)}",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.discard_memo(memo_id)
        self.reload()
