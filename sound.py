"""到点提醒的提示音。

默认用 Windows 自带的系统音，也可以换成用户放在程序目录「铃声」文件夹里的
wav / mp3，或临时通过文件对话框挑一个音频文件。
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

# 铃声文件夹里放的音乐：wav 交给 winsound，mp3 交给 Qt 播放
SOUND_EXTENSIONS = (".wav", ".mp3")
AUDIO_FILTER = "音频文件 (*.wav *.mp3)"


def _app_dir() -> Path:
    """打包成 exe 后 __file__ 指向临时解包目录，铃声文件夹要落在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SOUND_DIR = _app_dir() / "铃声"


def ensure_sound_dir() -> Path:
    """确保「铃声」文件夹存在，返回它的路径。"""
    try:
        SOUND_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return SOUND_DIR


def list_sound_files() -> list[str]:
    """扫描「铃声」文件夹里的 wav / mp3，按文件名排序返回绝对路径。"""
    folder = ensure_sound_dir()
    if not folder.is_dir():
        return []
    files = [
        str(path)
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SOUND_EXTENSIONS
    ]
    files.sort(key=lambda item: Path(item).name.lower())
    return files


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


# Qt 播放器按需创建并常驻，否则对象一被回收音乐就停了
_player = None


def _play_with_qt(path: str) -> None:
    """mp3 等格式交给 QMediaPlayer 异步播放，播完不循环。"""
    global _player
    try:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:
        return
    try:
        if _player is None:
            _player = QMediaPlayer()
            _player.setAudioOutput(QAudioOutput())
        _player.stop()
        _player.setSource(QUrl.fromLocalFile(path))
        _player.play()
    except Exception:
        # 解码器缺失、文件损坏等都不该影响提醒本身
        pass


def play_remind_sound(choice: str = "") -> None:
    """按用户选的音频响一声；异步播放，不阻塞界面。"""
    kind, _, value = (choice or DEFAULT_CHOICE).partition(":")

    if kind == "file" and value:
        if Path(value).suffix.lower() == ".wav":
            if sys.platform != "win32":
                return
            try:
                import winsound
            except ImportError:
                return
            flags = winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_FILENAME
            try:
                winsound.PlaySound(value, flags)
            except RuntimeError:
                pass
        else:
            _play_with_qt(value)
        return

    if sys.platform != "win32":
        return
    try:
        import winsound
    except ImportError:
        return
    target = value or SYSTEM_SOUNDS[0][0]
    flags = winsound.SND_ASYNC | winsound.SND_NODEFAULT | winsound.SND_ALIAS
    try:
        winsound.PlaySound(target, flags)
    except RuntimeError:
        # 别名没登记时会抛异常；提醒本身不受影响
        pass
