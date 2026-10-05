"""全局配色与样式表。"""

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

FONT_FAMILY = "Microsoft YaHei UI"

# 基础色
BG = "#F4F5F7"
SURFACE = "#FFFFFF"
SURFACE_HOVER = "#FBFCFE"
BORDER = "#E6E8EB"
BORDER_STRONG = "#D5D9DE"

TEXT_PRIMARY = "#1F2937"
TEXT_SECONDARY = "#6B7280"
TEXT_MUTED = "#9AA1AC"
TEXT_DONE = "#AEB4BC"

# 三栏主题色
ACCENT = {
    "urgent": "#E5484D",
    "unscheduled": "#2F80ED",
    "backlog": "#94A3B8",
}

# 任务来源标签色
SOURCE_COLOR = {
    "daily": "#0E9F6E",
    "once": "#E5484D",
    "period": "#7C5CFF",
}

# 优先级色条
PRIORITY_COLOR = {
    "high": "#E5484D",
    "medium": "#F2994A",
    "low": "#CBD2D9",
}


def rgba(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转成 QSS 可用的 rgba() 字符串。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# QSS 没法用边框拼出三角，箭头只能画成图片再引用
_CHEVRON_POINTS = {
    "down": [(2.5, 4.5), (6.0, 8.0), (9.5, 4.5)],
    "up": [(2.5, 7.5), (6.0, 4.0), (9.5, 7.5)],
}


def _chevron(direction: str, color: str = TEXT_SECONDARY, size: int = 12) -> str:
    """画一个箭头存成 PNG（放在临时目录），返回可写进 QSS 的路径。"""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(pen)
    painter.drawPolyline([QPointF(x, y) for x, y in _CHEVRON_POINTS[direction]])
    painter.end()

    path = Path(tempfile.gettempdir()) / f"schedule_chevron_{direction}_{size}.png"
    image.save(str(path))
    return path.as_posix()


CHEVRON = {name: _chevron(name) for name in _CHEVRON_POINTS}


APP_QSS = f"""
QWidget {{
    font-family: "{FONT_FAMILY}";
    color: {TEXT_PRIMARY};
}}

QMainWindow, #TodayView {{
    background: {BG};
}}

#PageTitle {{
    font-size: 23px;
    font-weight: 600;
}}

#PageDate {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}

#StatText {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}

#TaskCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#TaskCard:hover {{
    background: {SURFACE_HOVER};
    border-color: #C9D0D8;
}}

#TaskCardDone {{
    background: #FAFBFC;
    border: 1px solid #E9ECEF;
    border-radius: 10px;
}}

#TaskCardDone:hover {{
    background: #F5F7F9;
    border-color: #DDE2E7;
}}

#ColumnTitle {{
    font-size: 15px;
    font-weight: 600;
}}

#ColumnSub {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}

#TaskTitle {{
    font-size: 14px;
}}

#TaskMeta {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

#TaskFoot {{
    font-size: 11px;
    color: {TEXT_MUTED};
}}

#BannerTitle {{
    font-size: 13px;
    font-weight: 600;
    color: #8A5A00;
}}

#BannerText {{
    font-size: 12px;
    color: #9A6A10;
}}

#Banner {{
    background: #FFF8E6;
    border: 1px solid #F3E0AE;
    border-radius: 10px;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0 2px 0;
}}

QScrollBar::handle:vertical {{
    background: #D8DCE1;
    border-radius: 4px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: #C2C8CF;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QSplitter::handle {{
    background: transparent;
}}

QSplitter::handle:hover {{
    background: {rgba("#2F80ED", 0.18)};
}}

#GhostButton {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
}}

#GhostButton:hover {{
    background: {SURFACE};
    color: {TEXT_PRIMARY};
}}

#PrimaryButton {{
    background: #2F80ED;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
}}

#PrimaryButton:hover {{
    background: #1F6FDC;
}}

/* ---------- 日期挑选 ---------- */

/* 日期自带的上下微调箭头已关掉，这里只留下拉日历 */

QCalendarWidget QWidget {{
    alternate-background-color: {SURFACE};
}}

QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}

QCalendarWidget QToolButton {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 5px 9px;
    margin: 2px;
    font-size: 13px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

QCalendarWidget QToolButton:hover {{
    background: #EDF0F3;
}}

QCalendarWidget QToolButton::menu-indicator {{
    image: none;
}}

QCalendarWidget QAbstractItemView {{
    background: {SURFACE};
    outline: none;
    font-size: 12px;
}}

QCalendarWidget QAbstractItemView:enabled {{
    color: {TEXT_PRIMARY};
    selection-background-color: #2F80ED;
    selection-color: #FFFFFF;
}}

QCalendarWidget QAbstractItemView:disabled {{
    color: #C6CCD3;
}}

QCalendarWidget QSpinBox {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 2px 4px;
    font-size: 13px;
}}

/* ---------- 桌面悬浮窗 ---------- */

#FloatingBoard {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
}}

#FloatHeader {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
}}

#FloatTab {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

#FloatTab:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#FloatTabActive {{
    background: {rgba("#2F80ED", 0.12)};
    border: none;
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 12px;
    font-weight: 600;
    color: #2F80ED;
}}

#FloatClose {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 13px;
    color: {TEXT_MUTED};
}}

#FloatClose:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#FloatIcon {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 13px;
    color: {TEXT_MUTED};
}}

#FloatIcon:hover {{
    background: #EDF0F3;
    color: #2F80ED;
}}

/* ---------- 透明度拉条 ---------- */

#OpacityPopup {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
}}

#OpacityIcon {{
    font-size: 13px;
    color: {TEXT_MUTED};
}}

#OpacityValue {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

QSlider#OpacitySlider::groove:horizontal {{
    height: 4px;
    background: #E3E7EC;
    border-radius: 2px;
}}

QSlider#OpacitySlider::sub-page:horizontal {{
    height: 4px;
    background: #2F80ED;
    border-radius: 2px;
}}

QSlider#OpacitySlider::handle:horizontal {{
    width: 12px;
    margin: -5px 0;
    background: #2F80ED;
    border-radius: 6px;
}}

QSlider#OpacitySlider::handle:horizontal:hover {{
    background: #1E6FD9;
}}

/* ---------- 贴顶收起后的小横条 ---------- */

#EdgeHandle {{
    background: #2F80ED;
    border-bottom-left-radius: 4px;
    border-bottom-right-radius: 4px;
}}

#EdgeHandle:hover {{
    background: #1E6FD9;
}}

/* ---------- 到点提醒 ---------- */

#RemindBar {{
    background: #FFF8E6;
    border-bottom: 1px solid #F3E0AE;
}}

#RemindPopup {{
    background: #FFF8E6;
    border: 1px solid #F3E0AE;
    border-radius: 10px;
}}

#RemindTitle {{
    font-size: 13px;
    font-weight: 600;
    color: #8A5A00;
}}

#RemindText {{
    font-size: 12px;
    color: #9A6A10;
}}

/* ---------- 组别标题 ---------- */

#GroupHeader {{
    background: transparent;
}}

#GroupToggle {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 2px 4px;
    font-size: 12px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}

#GroupToggle:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#IconButton {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 3px 8px;
    font-size: 12px;
    color: {TEXT_MUTED};
}}

#IconButton:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

/* 任务条与组别标题上的「⋯」：比其它小图标更大更粗，方便点中 */
#MoreButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0;
    font-size: 19px;
    font-weight: 700;
    color: {TEXT_SECONDARY};
}}

#MoreButton:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#ErrorText {{
    color: #E5484D;
    font-size: 12px;
}}

#FieldHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* ---------- 表单控件 ---------- */

QDialog {{
    background: {SURFACE};
}}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 13px;
    selection-background-color: #2F80ED;
    selection-color: #FFFFFF;
}}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QTextEdit:focus {{
    border-color: #2F80ED;
}}

QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled,
QTimeEdit:disabled, QTextEdit:disabled {{
    background: #F4F5F7;
    color: {TEXT_MUTED};
}}

QComboBox {{
    padding-right: 26px;
}}

/* 下拉箭头 */

QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    background: transparent;
}}

QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url("{CHEVRON["down"]}");
    width: 12px;
    height: 12px;
}}

/* 时间的微调箭头 */

QTimeEdit::up-button, QTimeEdit::down-button {{
    subcontrol-origin: border;
    width: 20px;
    background: transparent;
    border: none;
}}

QTimeEdit::up-arrow {{
    image: url("{CHEVRON["up"]}");
    width: 12px;
    height: 12px;
}}

QTimeEdit::down-arrow {{
    image: url("{CHEVRON["down"]}");
    width: 12px;
    height: 12px;
}}

QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {rgba("#2F80ED", 0.12)};
    selection-color: {TEXT_PRIMARY};
    outline: none;
}}

QCheckBox {{
    spacing: 7px;
    font-size: 13px;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1.5px solid #C6CCD3;
    border-radius: 4px;
    background: {SURFACE};
}}

QCheckBox::indicator:hover {{
    border-color: #2F80ED;
}}

QCheckBox::indicator:checked {{
    background: #2F80ED;
    border-color: #2F80ED;
}}

/* ---------- 主导航 ---------- */

#NavBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}

#NavRail {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}

#NavButton {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
    font-size: 14px;
    color: {TEXT_SECONDARY};
}}

#NavButton:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#NavButtonActive {{
    background: {rgba("#2F80ED", 0.12)};
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
    font-size: 14px;
    font-weight: 600;
    color: #2F80ED;
}}

/* ---------- 备忘录便签 ---------- */

#MemoPage {{
    background: {BG};
}}

#MemoScroll {{
    background: transparent;
    border: none;
}}

#MemoCanvas {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

#CanvasHint {{
    font-size: 13px;
    color: {TEXT_MUTED};
}}

/* 便签底色：一点浅黄，像真的便利贴 */
#StickyNote {{
    background: #FFF7CC;
    border: 1px solid #EFE0A0;
    border-radius: 8px;
}}

#StickyNote:hover {{
    background: #FFFADF;
    border-color: #E2CE7E;
}}

#StickyNoteEditing {{
    background: #FFFFFF;
    border: 2px solid #2F80ED;
    border-radius: 8px;
}}

#StickyLabel {{
    background: transparent;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}

#StickyPlaceholder {{
    background: transparent;
    font-size: 13px;
    color: #B0A87A;
}}

QTextEdit#StickyEdit {{
    background: transparent;
    border: none;
    padding: 0;
    font-size: 13px;
}}

/* 便签右上角的钉住按钮：没钉住时几乎隐形，钉住了就变成灰底 */
#StickyPin {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 0;
    font-size: 10px;
    color: #A99F70;
}}

#StickyPin:hover {{
    background: rgba(0, 0, 0, 0.10);
    border-color: rgba(0, 0, 0, 0.14);
    color: {TEXT_PRIMARY};
}}

#StickyPinOn {{
    background: #B9B9B9;
    border: 1px solid #9E9E9E;
    border-radius: 4px;
    padding: 0;
    font-size: 10px;
    font-weight: 600;
    color: #FFFFFF;
}}

#StickyPinOn:hover {{
    background: #A8A8A8;
    border-color: #8D8D8D;
}}

/* 挑宿主窗口时跟着鼠标跑的提示条 */
#PickHint {{
    background: {TEXT_PRIMARY};
    border: 1px solid {TEXT_PRIMARY};
    border-radius: 6px;
    padding: 6px 10px;
    color: #FFFFFF;
    font-size: 12px;
}}

/* 一摞便签右侧的竖排小页签 */
#TabStrip {{
    background: transparent;
}}

#StackTab {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 0;
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

#StackTab:hover {{
    background: #EDF0F3;
    color: {TEXT_PRIMARY};
}}

#StackTabActive {{
    background: #2F80ED;
    border: 1px solid #2F80ED;
    border-radius: 6px;
    padding: 0;
    font-size: 12px;
    font-weight: 600;
    color: #FFFFFF;
}}

/* ---------- 历史汇总 ---------- */

#HistoryPage, #TrashPage {{
    background: {BG};
}}

#HistoryScroll, #TrashBarScroll, #TrashContentScroll {{
    background: transparent;
    border: none;
}}

#SearchBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 13px;
}}

#SearchBox:focus {{
    border-color: #2F80ED;
}}

#HistoryEntry {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}

#HistoryEntry:hover {{
    border-color: {BORDER_STRONG};
}}

#EntryChip {{
    font-weight: 600;
}}

#EntryTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

#EntryTime {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}

#EntryMeta {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

#EmptyHint {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding: 40px 0;
}}

/* ---------- 废弃栏 ---------- */

#TrashBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}

#SubPageItem {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 7px;
}}

#SubPageItem:hover {{
    background: #EDF0F3;
}}

#SubPageItemOn {{
    background: {rgba("#2F80ED", 0.10)};
    border: 1px solid #2F80ED;
    border-radius: 7px;
}}

#SubPageTitle {{
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}

#SubPageTime {{
    font-size: 11px;
    color: {TEXT_MUTED};
}}

#TrashCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}

#TrashCardTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

#TrashCardBody {{
    font-size: 13px;
    color: {TEXT_PRIMARY};
    line-height: 150%;
}}

#DangerButton {{
    background: transparent;
    border: 1px solid {rgba("#E5484D", 0.5)};
    border-radius: 7px;
    padding: 6px 14px;
    font-size: 13px;
    color: #E5484D;
}}

#DangerButton:hover {{
    background: {rgba("#E5484D", 0.10)};
}}

#DangerButton:disabled {{
    border-color: {BORDER};
    color: {TEXT_DONE};
}}
"""
