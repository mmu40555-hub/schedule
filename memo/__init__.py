"""备忘录：一块自由画布，便签随手拖、随手写，大面积重叠就叠成一摞。

模块按领域拆开，这里只做门面：对外仍然 `from memo import MemoPage`。

- 便签本体：sticky_note.StickyNote
- 一摞的页签：tab_strip.TabStrip
- 页面统筹：page.MemoPage
- 原生窗口打交道：win32
- 尺寸常量：consts
"""

from .page import MemoPage
from .sticky_note import StickyNote
from .tab_strip import TabStrip
