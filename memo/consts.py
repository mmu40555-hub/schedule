"""便签、页签、画布用的尺寸与节奏常量。"""

# 便签宽度固定，高度随内容长；超过上限就截住，免得一张便签占满整屏
NOTE_WIDTH = 220
NOTE_PAD = 12
NOTE_MIN_HEIGHT = 88
NOTE_MAX_HEIGHT = 460

# 右上角钉住按钮的尺寸，以及正文为它让出来的宽度
PIN_SIZE = 16
PIN_GAP = 6
TEXT_WIDTH = NOTE_WIDTH - NOTE_PAD * 2 - PIN_SIZE - PIN_GAP

# 钉到桌面时，便签跟主窗口边沿留出的空当
DESK_GAP = 24

# 重叠面积占到较小一张的这个比例，就算「高度重叠」，该叠成一摞
MERGE_RATIO = 0.55

# 按下后位移不超过这个像素算点击（进入编辑），超过才算拖动
CLICK_SLOP = 4

# 画布最小尺寸与四周留白
CANVAS_MIN_WIDTH = 2200
CANVAS_MIN_HEIGHT = 1400
CANVAS_MARGIN = 320

# 右侧小页签的尺寸与便签跟它的间隙
TAB_WIDTH = 26
TAB_HEIGHT = 26
TAB_SPACING = 2
STRIP_GAP = 6

PLACEHOLDER = "点一下写点什么…"

# 一摞便签合并成一整张时，正文之间的分割线；就是普通文字，合并后想删随手删掉
MERGE_DIVIDER = "─" * 24

# 便签盯着宿主窗口看的间隔；窗口一挪便签就跟上，靠的就是这个心跳
HOST_TICK_MS = 60
# 拾取宿主窗口时，查鼠标左右键的间隔
PICK_TICK_MS = 40
