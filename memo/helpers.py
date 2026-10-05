"""便签通用小工具：样式重刷、内容摘要、合并拼接、重叠比例。"""

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from .consts import MERGE_DIVIDER


def _repolish(widget: QWidget) -> None:
    """objectName 变了要重新走一遍样式，否则界面不会立即刷新。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _preview(content: str, limit: int = 24) -> str:
    """把便签内容压成一行短摘要，给页签提示与删除确认用。"""
    text = " ".join(content.split())
    if not text:
        return "（空白便签）"
    return text if len(text) <= limit else text[:limit] + "…"


def _merge_texts(contents: list[str]) -> str:
    """按顺序把几张便签的正文拼起来，中间垫一条分割线；空白的那几张跳过。"""
    parts = [text.strip() for text in contents if text.strip()]
    return f"\n\n{MERGE_DIVIDER}\n\n".join(parts)


def _overlap_ratio(a: QRect, b: QRect) -> float:
    """重叠面积占较小一张的比例：0 是没碰上，1 是完全盖住。"""
    overlap = a.intersected(b)
    if overlap.isEmpty():
        return 0.0
    smaller = min(a.width() * a.height(), b.width() * b.height())
    if smaller <= 0:
        return 0.0
    return overlap.width() * overlap.height() / smaller
