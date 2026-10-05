"""废弃栏回归测试。

子页栏刷新时若只把控件移出布局、不销毁控件，旧的「废弃栏还是空的」会一直
挂在界面上——有废弃便签了也不消失。这个测试盯住这件事。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SCHEDULE_TEST_MODE", "1")

# 让测试能 import 到程序模块（仓库根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from storage import Store  # noqa: E402
from trash_view import TrashView, _SubPageItem  # noqa: E402

EMPTY_HINT = "废弃栏还是空的"


class TrashViewEmptyHintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.view = TrashView(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _hint_texts(self) -> list[str]:
        return [w.text() for w in self.view.bar.findChildren(QLabel)]

    def _bar_items(self) -> list[_SubPageItem]:
        return self.view.bar.findChildren(_SubPageItem)

    def test_discarded_memo_replaces_empty_hint(self):
        """丢一张进废弃栏后，空提示必须消失、子页要露面。"""
        self.assertEqual(self._hint_texts(), [EMPTY_HINT])

        memo_id = self.store.create_memo("一张会被丢的便签", 0, 0)
        self.store.discard_memo(memo_id)
        self.view.reload()

        self.assertNotIn(EMPTY_HINT, self._hint_texts())
        self.assertEqual(len(self._bar_items()), 1)

    def test_restored_memo_brings_empty_hint_back(self):
        """还原回去后，子页要收起、空提示要重新出现。"""
        memo_id = self.store.create_memo("又被捡回来的便签", 0, 0)
        self.store.discard_memo(memo_id)
        self.view.reload()
        self.assertEqual(len(self._bar_items()), 1)

        self.store.restore_memo(memo_id)
        self.view.reload()

        self.assertEqual(self._bar_items(), [])
        self.assertIn(EMPTY_HINT, self._hint_texts())


if __name__ == "__main__":
    unittest.main()
