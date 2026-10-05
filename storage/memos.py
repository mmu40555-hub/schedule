from datetime import date

from .helpers import _stamp
from .records import Memo, _memo
from .schema import MAX_MEMO_STACK


# 备忘录便签：位置、摞（stack）组织与废弃栏。
class MemoMixin:
    # ================= 备忘录便签 =================

    def list_memos(self) -> list[Memo]:
        """备忘录页面上的全部便签：按摞聚合，摞内按页签序号排。

        丢进「废弃栏」的不在此列。
        """
        rows = self.conn.execute(
            "SELECT * FROM memos WHERE discarded_at='' ORDER BY stack_id, stack_order, id"
        ).fetchall()
        return [_memo(r) for r in rows]

    def get_memo(self, memo_id: int) -> Memo | None:
        row = self.conn.execute(
            "SELECT * FROM memos WHERE id=?", (int(memo_id),)
        ).fetchone()
        return _memo(row) if row else None

    def create_memo(self, content: str = "", x: int = 0, y: int = 0) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memos (content, x, y, stack_id, stack_order, updated_day)"
            " VALUES (?,?,?,0,0,?)",
            (content, int(x), int(y), date.today().isoformat()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_memo_content(self, memo_id: int, content: str) -> None:
        self.conn.execute(
            "UPDATE memos SET content=?, updated_day=? WHERE id=?",
            (content, date.today().isoformat(), int(memo_id)),
        )
        self.conn.commit()

    def save_memo_pos(self, memo_id: int, x: int, y: int) -> None:
        """记住便签落在哪儿；是一摞的话整摞一起走，换页签看时不会跳。"""
        memo = self.get_memo(memo_id)
        if memo is None:
            return
        if memo.stack_id:
            self.conn.execute(
                "UPDATE memos SET x=?, y=? WHERE stack_id=?",
                (int(x), int(y), memo.stack_id),
            )
        else:
            self.conn.execute(
                "UPDATE memos SET x=?, y=? WHERE id=?", (int(x), int(y), memo.id)
            )
        self.conn.commit()

    def set_memo_pinned(self, memo_id: int, pinned: bool) -> None:
        """钉到桌面 / 收回页面。

        钉出去之前先脱离那一摞：半张在桌面、半张在页面里没法看。
        """
        memo = self.get_memo(memo_id)
        if memo is None:
            return
        if pinned and memo.stack_id:
            self.detach_memo(memo_id)
        self.conn.execute(
            "UPDATE memos SET pinned=? WHERE id=?", (1 if pinned else 0, memo.id)
        )
        self.conn.commit()

    def save_memo_host(
        self,
        memo_id: int,
        host_class: str = "",
        host_title: str = "",
        dx: int = 0,
        dy: int = 0,
    ) -> None:
        """记住这张便签贴在哪个窗口上、贴在窗口的哪个位置。

        什么都不传就是忘掉这个宿主（便签重新变回一块普通浮窗）。
        """
        self.conn.execute(
            "UPDATE memos SET host_class=?, host_title=?, host_dx=?, host_dy=? WHERE id=?",
            (host_class, host_title, int(dx), int(dy), int(memo_id)),
        )
        self.conn.commit()

    def delete_memo(self, memo_id: int) -> None:
        """删掉一张便签；摞里只剩一张时自动散掉。"""
        row = self.conn.execute(
            "SELECT stack_id FROM memos WHERE id=?", (int(memo_id),)
        ).fetchone()
        if row is None:
            return
        stack_id = int(row["stack_id"])
        self.conn.execute("DELETE FROM memos WHERE id=?", (int(memo_id),))
        if stack_id:
            self._settle_stack(stack_id)
        self.conn.commit()

    # ---------- 废弃栏 ----------

    def discard_memo(self, memo_id: int) -> None:
        """把便签丢进废弃栏：内容留着，只是从备忘录页面收起来。"""
        self.conn.execute(
            "UPDATE memos SET discarded_at=?, pinned=0 WHERE id=?",
            (_stamp(), int(memo_id)),
        )
        self.conn.commit()

    def list_discarded_memos(self) -> list[Memo]:
        """废弃栏里的便签：按丢弃时间排，最近丢的排最前。"""
        rows = self.conn.execute(
            "SELECT * FROM memos WHERE discarded_at!=''"
            " ORDER BY discarded_at DESC, id DESC"
        ).fetchall()
        return [_memo(r) for r in rows]

    def restore_memo(self, memo_id: int) -> None:
        """把便签从废弃栏捞回备忘录页面。"""
        self.conn.execute(
            "UPDATE memos SET discarded_at='' WHERE id=?", (int(memo_id),)
        )
        self.conn.commit()

    def purge_memos(self, memo_ids: list[int]) -> int:
        """彻底删除：从废弃栏里删掉就真没了，返回删掉的张数。"""
        ids = [int(item) for item in memo_ids]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        cursor = self.conn.execute(
            f"DELETE FROM memos WHERE id IN ({marks}) AND discarded_at!=''", ids
        )
        self.conn.commit()
        return int(cursor.rowcount)

    def stack_members(self, stack_id: int) -> list[Memo]:
        """某一摞里的便签，按页签序号排（序号由 stack_order 固定下来）。"""
        rows = self.conn.execute(
            "SELECT * FROM memos WHERE stack_id=? ORDER BY stack_order, id",
            (int(stack_id),),
        ).fetchall()
        return [_memo(r) for r in rows]

    def merge_memos(self, host_id: int, guest_id: int) -> bool:
        """把 guest 那一摞叠到 host 这一摞上；超过上限就不合并，返回 False。"""
        host = self.get_memo(host_id)
        guest = self.get_memo(guest_id)
        if host is None or guest is None or host.id == guest.id:
            return False
        if host.stack_id and host.stack_id == guest.stack_id:
            return False

        host_stack = host.stack_id or host.id
        total = self._stack_size(host_stack) + self._stack_size(guest.stack_id)
        if total > MAX_MEMO_STACK:
            return False

        # host 原本单独一张时，先把自己立成一摞的摞主，并继续露在最上面
        if not host.stack_id:
            self.conn.execute(
                "UPDATE memos SET stack_id=?, stack_order=0, stack_active=1 WHERE id=?",
                (host_stack, host.id),
            )

        order = self._next_stack_order(host_stack)
        members = self.stack_members(guest.stack_id) if guest.stack_id else [guest]
        for member in members:
            # 位置对齐到 host：一摞就是同一处，换页签看时不会整个跳走
            self.conn.execute(
                "UPDATE memos SET stack_id=?, stack_order=?, stack_active=0, x=?, y=?"
                " WHERE id=?",
                (host_stack, order, host.x, host.y, member.id),
            )
            order += 1
        self.conn.commit()
        return True

    def promote_in_stack(self, stack_id: int, memo_id: int) -> None:
        """把摞里某一张翻到最上面：只换显示的那张，页签序号原地不动。"""
        members = self.stack_members(stack_id)
        if len(members) < 2 or memo_id not in {member.id for member in members}:
            return
        self.conn.execute(
            "UPDATE memos SET stack_active=0 WHERE stack_id=?", (int(stack_id),)
        )
        self.conn.execute("UPDATE memos SET stack_active=1 WHERE id=?", (int(memo_id),))
        self.conn.commit()

    def detach_memo(self, memo_id: int) -> None:
        """把一张便签从摞里拿出来，变回单独一张。"""
        memo = self.get_memo(memo_id)
        if memo is None or not memo.stack_id:
            return
        self.conn.execute(
            "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE id=?",
            (memo.id,),
        )
        self._settle_stack(memo.stack_id)
        self.conn.commit()

    def split_stack(self, stack_id: int) -> None:
        """整摞拆开，每张都变回单独一张。"""
        self.conn.execute(
            "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE stack_id=?",
            (int(stack_id),),
        )
        self.conn.commit()

    def merge_stack_into_one(self, stack_id: int, content: str) -> int | None:
        """把整摞按页签序号合并成一整张，返回留下来的那张 id。

        合并后的正文由调用方拼好传进来。留下来的那张沿用序号最靠前那张的位置，
        其余几张并入后删掉，整张也就散成一摞之外的单独一张。
        """
        members = self.stack_members(stack_id)
        if len(members) < 2:
            return None
        survivor = members[0]
        for member in members[1:]:
            self.conn.execute("DELETE FROM memos WHERE id=?", (member.id,))
        self.conn.execute(
            "UPDATE memos SET content=?, updated_day=?, stack_id=0, stack_order=0,"
            " stack_active=1 WHERE id=?",
            (content, date.today().isoformat(), survivor.id),
        )
        self.conn.commit()
        return survivor.id

    def _stack_size(self, stack_id: int) -> int:
        """某一摞的张数；stack_id 为 0 时就是单独一张。"""
        if not stack_id:
            return 1
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memos WHERE stack_id=?", (int(stack_id),)
        ).fetchone()
        return int(row["n"])

    def _next_stack_order(self, stack_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(stack_order), -1) + 1 AS n FROM memos WHERE stack_id=?",
            (int(stack_id),),
        ).fetchone()
        return int(row["n"])

    def _settle_stack(self, stack_id: int) -> None:
        """摞里只剩一张就散掉，否则把编号收紧，并保证总有一张露在外面。"""
        members = self.stack_members(stack_id)
        if not members:
            return
        if len(members) == 1:
            self.conn.execute(
                "UPDATE memos SET stack_id=0, stack_order=0, stack_active=1 WHERE id=?",
                (members[0].id,),
            )
            return
        # 本来露在外面那张被移走或删掉了，由编号最靠前的那张顶上
        if not any(member.stack_active for member in members):
            self.conn.execute(
                "UPDATE memos SET stack_active=1 WHERE id=?", (members[0].id,)
            )
        for order, member in enumerate(members):
            if member.stack_order != order:
                self.conn.execute(
                    "UPDATE memos SET stack_order=? WHERE id=?", (order, member.id)
                )
