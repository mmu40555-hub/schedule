"""到点提醒的提示音。

默认用 Windows 自带的系统音，也可以换成用户自己添加的本地音频文件；
非 Windows 平台或播放失败就静默跳过，绝不会因为出不了声影响提醒本身。
"""

import sys
from pathlib import Path

# 系统提示音：能不能出声取决于系统有没有登记这个别名，播不出来会静默跳过
SYSTEM_SOUNDS = [
    ("SystemAsterisk", "系统提示音 · 星号"),
    ("SystemExclamation", "系统提示音 · 感叹号"),
    ("SystemHand", "系统提示音 · 错误"),
    ("SystemQuestion", "系统提示音 · 询问"),
    ("SystemDefault", "系统默认提示音"),
]

# 没选过时用第一个系统音
DEFAULT_CHOICE = f"alias:{SYSTEM_SOUNDS[0][0]}"

# 只挑 wav：Windows 的 PlaySound 只认这一种
AUDIO_FILTER = "音频文件 (*.wav)"


def alias_choice(alias: str) -> str:
    return f"alias:{alias}"


def file_choice(path: str) -> str:
    return f"file:{path}"


def choice_label(choice: str) -> str:
    """下拉框里显示的名字。"""
    if choice.startswith("alias:"):
        alias = choice.split(":", 1)[1]
        for name, label in SYSTEM_SOUNDS:
            if name == alias:
                return label
        return "系统提示音"
    if choice.startswith("file:"):
        return Path(choice.split(":", 1)[1]).name
    return "系统提示音"


def play_remind_sound(choice: str = "") -> None:
    """按用户选的音频响一声；异步播放，不阻塞界面。"""
    if sys.platform != "win32":
        return
    try:
        import winsound
    except ImportError:
        return

    kind, _, value = (choice or DEFAULT_CHOICE).partition(":")
    flags = winsound.SND_ASYNC | winsound.SND_NODEFAULT
    if kind == "file" and value:
        flags |= winsound.SND_FILENAME
        target = value
    else:
        flags |= winsound.SND_ALIAS
        target = value or SYSTEM_SOUNDS[0][0]

    try:
        winsound.PlaySound(target, flags)
    except RuntimeError:
        # 别名没登记、文件不在或格式不对时会抛异常；提醒本身不受影响
        pass
