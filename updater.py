"""自动更新：到 GitHub 上取最新发布，下载新版 exe 并替换自己。

更新源是仓库的 GitHub Releases：每次发版打一个 tag，并在 Release 里挂上打包好的
`日程计划表.exe`。程序启动后静默查一次（每 24 小时最多一次），发现新版就弹窗问一句，
用户点了「立即更新」才下载；下载完生成一个临时批处理，等本进程退出后把旧 exe 换掉并重启。

国内大部分网络连不上 GitHub，所以查询和下载都先直连、连不上再自动换镜像（见 MIRROR_PREFIXES）。
镜像只是把原始 GitHub 地址接在前缀后面，附件内容仍按大小与 MZ 头核对，避免下到残缺或非程序的东西。

更稳的办法是自建主源：把 exe 和一份 latest.json 放进对象存储（阿里云 OSS、腾讯云 COS 均可），
国内直连稳定、完全可控。填好 PRIMARY_SOURCE 后先问主源，主源不可用再退回 GitHub 与镜像。
latest.json 形如：
    {"version": "0.2.2", "notes": "更新说明", "asset_name": "日程计划表.exe",
     "asset_size": 38343151, "asset_url": "https://bucket.oss-cn-hangzhou.aliyuncs.com/schedule/日程计划表.exe"}
其中 asset_url、asset_name、asset_size、notes 都可省略，asset_url 缺省时按 {主源}/v{版本}/{文件名} 拼。

只换 exe 本身，程序目录里的 schedule.db 与「铃声」文件夹一概不碰。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
)

# 程序名与版本号：发版时和 git tag 一起改，tag 形如 v0.2.1
APP_NAME = "日程计划表"
VERSION = "0.2.1"

# 更新源仓库与发布页面
REPO = "mmu40555-hub/schedule"
RELEASE_PAGE = f"https://github.com/{REPO}/releases"

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
# HTTP 头只能放 ASCII，这里别写中文
HEADERS = {
    "User-Agent": "schedule-app-updater",
    "Accept": "application/vnd.github+json",
}

# 启动后隔多久再悄悄检查，免得跟程序启动抢网络
STARTUP_DELAY_MS = 8000
# 两次自动检查之间至少隔多久（秒）
CHECK_INTERVAL = 24 * 60 * 60

# 下载分块大小与默认超时
CHUNK = 64 * 1024
TIMEOUT = 30.0

# 主更新源：自建对象存储的目录地址（阿里云 OSS / 腾讯云 COS 等），末尾不要带斜杠。
# 目录里放一份 latest.json（格式见文件头说明）和对应的 exe。
# 留空表示不启用主源，行为跟以前一样只走 GitHub 与镜像；也可用环境变量临时覆盖。
PRIMARY_SOURCE = os.environ.get("SCHEDULE_UPDATE_SOURCE", "").strip().rstrip("/")
# 主源里描述最新版本的元数据文件名
PRIMARY_META = "latest.json"

# GitHub 加速镜像：国内连不上 GitHub 时自动改用它们。
# 用法就是把原始 GitHub 地址整个接在前缀后面，例如
#   https://gh-proxy.com/https://api.github.com/repos/...
# 顺序按可用性排：gh-proxy 同时支持 Release 附件与 REST API，其余主要兜底下载。
MIRROR_PREFIXES = (
    "https://gh-proxy.com/",
    "https://gh-proxy.org/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
    "https://gh.ddlc.top/",
    "https://github.boki.moe/",
)


def mirror_candidates(url: str) -> list[str]:
    """直连地址排第一，后面依次是各镜像拼出来的地址。"""
    return [url, *(prefix + url for prefix in MIRROR_PREFIXES)]


# 替换脚本里最多重试多少次（每次间隔约 1 秒），等旧进程放开 exe
REPLACE_TRIES = 90

# 替换用的批处理：全 ASCII，路径靠参数传，避开中文编码坑
REPLACER_BAT = r"""@echo off
setlocal
set "TARGET=%~1"
set "NEW=%~2"
set /a tries=0
:wait
copy /Y "%TARGET%" "%TARGET%.bak" >nul 2>nul
copy /Y "%NEW%" "%TARGET%" >nul 2>nul
if not errorlevel 1 goto done
set /a tries+=1
if %tries% GEQ %TRIES% goto fail
ping -n 2 127.0.0.1 >nul
goto wait
:done
del /Q "%NEW%" >nul 2>nul
start "" "%TARGET%"
goto cleanup
:fail
start "" "%TARGET%"
:cleanup
(goto) 2>nul & del /Q "%~f0" >nul 2>nul
exit /b 0
"""


@dataclass
class UpdateInfo:
    """远端的一个新版本：版本号、更新说明，以及可下载的 exe 附件。"""

    version: str            # 去掉前缀 v 的版本号，如 0.1.5
    notes: str              # 更新说明，来自 Release 或主源的 latest.json
    page_url: str           # 发布页，没挂 exe 时让用户去这里下
    asset_name: str = ""    # exe 附件文件名
    asset_url: str = ""     # exe 附件下载地址
    asset_size: int = 0     # 附件字节数，下载完用来核对
    # 下载地址的候选序列（主源直链，或「GitHub 直连 + 各镜像」）；
    # 为空时退回按 asset_url 现推。
    asset_candidates: tuple = ()


# ---------- 版本号 ----------

def parse_version(text: str) -> tuple[int, ...]:
    """把 v0.1.4 这类版本号拆成数字元组，方便比大小。"""
    numbers = re.findall(r"\d+", text or "")
    return tuple(int(item) for item in numbers) or (0,)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """candidate 比 current 新才算有更新。"""
    return parse_version(candidate) > parse_version(current)


# ---------- 运行环境 ----------

def is_frozen() -> bool:
    """打包成 exe 运行时为真；源码运行没法自我替换。"""
    return bool(getattr(sys, "frozen", False))


def target_exe() -> Path | None:
    """当前运行的程序本体；源码运行时返回 None。"""
    if not is_frozen():
        return None
    return Path(sys.executable).resolve()


# ---------- 网络 ----------

def _encode_url(url: str) -> str:
    """转义 URL 里的非 ASCII（例如中文文件名），urllib 只认 ASCII 地址。

    safe 里留着 %，已经是 %XX 的部分不会再被二次编码。
    """
    return quote(url, safe=":/?#[]@!$&'()*+,;=%")


def _read_json(url: str, timeout: float) -> dict:
    """GET 一个 JSON 接口并解析；出错直接抛给调用方。"""
    request = urllib.request.Request(_encode_url(url), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _fetch_release(timeout: float) -> dict | None:
    """取最新发布的数据：先直连 GitHub，不通再逐个试镜像。

    直连返回 404 是权威结果——仓库确实没发过 Release，此时不该再折腾镜像。
    """
    try:
        return _read_json(API_LATEST, timeout)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        direct_error = error
    except Exception as error:            # noqa: BLE001 直连失败的花样很多
        direct_error = error

    for prefix in MIRROR_PREFIXES:
        try:
            return _read_json(prefix + API_LATEST, timeout)
        except Exception:                 # noqa: BLE001 镜像不支持 API 也算失败，换下一个
            continue
    raise direct_error


def _from_primary(timeout: float) -> UpdateInfo | None:
    """从自建主源读 latest.json；没配主源就返回 None。

    主源是我们自己放的对象存储，返回的直链直接就能下，不必再套 GitHub 镜像。
    """
    if not PRIMARY_SOURCE:
        return None
    data = _read_json(f"{PRIMARY_SOURCE}/{PRIMARY_META}", timeout)
    version = str(data.get("version") or "").lstrip("vV")
    if not version:
        return None
    name = str(data.get("asset_name") or f"{APP_NAME}.exe")
    url = str(data.get("asset_url") or f"{PRIMARY_SOURCE}/v{version}/{name}")
    return UpdateInfo(
        version=version,
        notes=str(data.get("notes") or ""),
        page_url=str(data.get("page_url") or RELEASE_PAGE),
        asset_name=name,
        asset_url=url,
        asset_size=int(data.get("asset_size") or 0),
        asset_candidates=(url,),
    )


def fetch_latest(timeout: float = TIMEOUT) -> UpdateInfo | None:
    """取最新发布；仓库还没发过 Release 且主源也没消息时返回 None。

    先问主源：主源给出版本且确实比当前新，就直接用它，省得再去连 GitHub。
    主源没配、连不上、或版本不比当前新（可能没同步），都照旧走 GitHub 与镜像。

    网络或接口出错会抛异常，由调用方决定是静默跳过还是提示用户。
    """
    if PRIMARY_SOURCE:
        try:
            primary = _from_primary(timeout)
        except Exception:            # noqa: BLE001 主源挂了就当它没有，退回 GitHub
            primary = None
        if primary is not None and is_newer(primary.version):
            return primary

    data = _fetch_release(timeout)
    if data is None:
        return None

    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    version = tag.lstrip("vV")
    assets = data.get("assets") or []
    asset = next(
        (item for item in assets if str(item.get("name", "")).lower().endswith(".exe")),
        None,
    )
    return UpdateInfo(
        version=version,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or RELEASE_PAGE),
        asset_name=str(asset.get("name")) if asset else "",
        asset_url=str(asset.get("browser_download_url")) if asset else "",
        asset_size=int(asset.get("size") or 0) if asset else 0,
    )


def _download_once(url: str, dest: Path, on_progress, cancel, timeout: float) -> bool:
    """从一个具体地址下载，返回 False 表示中途被取消。"""
    request = urllib.request.Request(_encode_url(url), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as handle:
            while True:
                if cancel is not None and cancel():
                    return False
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    return True


def download_asset(url, dest: Path, on_progress=None, cancel=None,
                   timeout: float = TIMEOUT) -> bool:
    """把附件下到 dest；on_progress(已下载, 总大小) 用来刷进度条。

    url 可以是单个地址，也可以是已经排好序的候选列表：单个 GitHub 地址会展开成
    「直连 + 各镜像」逐个试；主源（对象存储）给的候选列表按原样用，不套 GitHub 镜像。
    返回 False 表示中途被用户取消。
    """
    candidates = mirror_candidates(url) if isinstance(url, str) else list(url)
    last_error = None
    for candidate in candidates:
        if cancel is not None and cancel():
            return False
        try:
            return _download_once(candidate, dest, on_progress, cancel, timeout)
        except Exception as error:        # noqa: BLE001 超时、断流、证书错误都算，换镜像
            last_error = error
    raise last_error


def verify_asset(path: Path, expected_size: int = 0) -> str:
    """下载完核对一下：大小对得上、且确实是 Windows 可执行文件。"""
    if not path.is_file():
        return "下载的文件不见了"
    size = path.stat().st_size
    if expected_size and size != expected_size:
        return f"下载不完整（{size} / {expected_size} 字节）"
    with open(path, "rb") as handle:
        if handle.read(2) != b"MZ":
            return "下载到的不是可执行文件"
    return ""


# ---------- 自我替换 ----------

def write_replacer(target: Path, new_exe: Path) -> Path:
    """把替换脚本写到新文件的同目录。脚本是纯 ASCII，路径全靠参数传进来。"""
    script = new_exe.parent / "apply_update.bat"
    script.write_text(REPLACER_BAT.replace("%TRIES%", str(REPLACE_TRIES)),
                      encoding="ascii")
    return script


def spawn_replacer(target: Path, new_exe: Path) -> Path:
    """拉起替换脚本，随后本进程就该退出了。

    脚本会等本进程放开 exe 再替换：先把旧 exe 备份成 .bak，再覆盖，
    失败就隔一秒重试，最多 REPLACE_TRIES 次；换好了顺手重启新程序。
    """
    script = write_replacer(target, new_exe)
    subprocess.Popen(
        ["cmd", "/c", str(script), str(target), str(new_exe)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return script


# ---------- 后台线程 ----------

# 活着的线程要有人提着，不然跑着跑着被回收就崩了
_running: set = set()


def _keep(thread: QThread) -> None:
    _running.add(thread)
    thread.finished.connect(lambda: _running.discard(thread))


class CheckThread(QThread):
    """后台查一次最新发布，别卡住界面。"""

    done = pyqtSignal(object)     # UpdateInfo | None
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            info = fetch_latest()
        except Exception as error:            # noqa: BLE001 网络状况五花八门
            self.failed.emit(str(error) or error.__class__.__name__)
            return
        self.done.emit(info)


class DownloadThread(QThread):
    """后台下载新 exe，顺带汇报进度。"""

    progress = pyqtSignal(int, int)
    failed = pyqtSignal(str)
    done = pyqtSignal(str)

    def __init__(self, url, dest: Path, expected_size: int = 0):
        super().__init__()
        self._url = url                  # 单个地址或候选列表，见 download_asset
        self._dest = dest
        self._expected = expected_size
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            finished = download_asset(
                self._url, self._dest, self.progress.emit, lambda: self._cancelled
            )
        except Exception as error:            # noqa: BLE001
            self.failed.emit(str(error) or error.__class__.__name__)
            return
        if not finished:
            self.failed.emit("已取消")
            return
        problem = verify_asset(self._dest, self._expected)
        if problem:
            self.failed.emit(problem)
            return
        self.done.emit(str(self._dest))


# ---------- 界面 ----------

# 用户在更新提示里选的三种态度
CHOICE_NOW = "now"
CHOICE_LATER = "later"
CHOICE_SKIP = "skip"


class UpdateDialog(QDialog):
    """发现新版本时的提示：摆出更新说明，让用户挑怎么办。"""

    NOW, LATER, SKIP = CHOICE_NOW, CHOICE_LATER, CHOICE_SKIP

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.choice = self.LATER
        self.setWindowTitle("发现新版本")
        self.setMinimumSize(520, 400)

        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 16)
        box.setSpacing(10)

        title = QLabel(f"{APP_NAME} 有新版本：v{VERSION} → v{info.version}")
        title.setObjectName("SectionTitle")
        box.addWidget(title)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(info.notes.strip() or "（这次发布没有写更新说明）")
        box.addWidget(notes, 1)

        hint = QLabel(
            "更新只会替换程序本身，日程数据（schedule.db）和你放的铃声都不会动。"
        )
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        box.addWidget(hint)

        buttons = QDialogButtonBox()
        later = buttons.addButton("稍后再说", QDialogButtonBox.ButtonRole.RejectRole)
        skip = buttons.addButton("跳过这个版本", QDialogButtonBox.ButtonRole.DestructiveRole)
        now = buttons.addButton("立即更新", QDialogButtonBox.ButtonRole.AcceptRole)
        now.setObjectName("PrimaryButton")
        later.clicked.connect(self.reject)
        skip.clicked.connect(self._on_skip)
        now.clicked.connect(self._on_now)
        box.addWidget(buttons)

    def _on_skip(self) -> None:
        self.choice = self.SKIP
        self.accept()

    def _on_now(self) -> None:
        self.choice = self.NOW
        self.accept()


class DownloadDialog(QDialog):
    """下载进度：一个进度条，一个取消按钮。"""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在下载新版本")
        self.setMinimumWidth(420)
        self.setModal(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 16)
        box.setSpacing(12)

        self.label = QLabel(f"正在下载 {APP_NAME} v{version}…")
        box.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        box.addWidget(self.bar)

        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton(
            "取消", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.cancel_button.clicked.connect(self.reject)
        box.addWidget(self.buttons)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(done * 100 / total))
            self.label.setText(
                f"正在下载 {APP_NAME}… {done / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
        else:
            self.bar.setRange(0, 0)       # 不知道总大小就转圈
            self.label.setText(f"正在下载 {APP_NAME}… {done / 1048576:.1f} MB")


# ---------- 流程编排 ----------

def _open_page(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _apply(parent, store, info: UpdateInfo) -> None:
    """下载新版并把自己换掉；换不了就退化成打开下载页。"""
    target = target_exe()
    if target is None:
        QMessageBox.information(
            parent,
            "需要手动更新",
            f"当前是以源码方式运行，没法自动替换。\n"
            f"请到发布页下载 v{info.version}：\n{info.page_url}",
        )
        _open_page(info.page_url)
        return
    if not info.asset_url:
        QMessageBox.information(
            parent,
            "需要手动下载",
            f"v{info.version} 这次发布没有附带 exe 附件。\n"
            f"请到发布页看看：\n{info.page_url}",
        )
        _open_page(info.page_url)
        return

    folder = Path(tempfile.mkdtemp(prefix="schedule-update-"))
    dest = folder / (info.asset_name or target.name)

    dialog = DownloadDialog(info.version, parent)
    thread = DownloadThread(info.asset_candidates or info.asset_url, dest, info.asset_size)
    _keep(thread)

    def on_progress(done: int, total: int) -> None:
        dialog.set_progress(done, total)

    def on_failed(message: str) -> None:
        dialog.reject()
        QMessageBox.warning(parent, "下载失败", f"新版本没能下载好：{message}")

    def on_done(path: str) -> None:
        dialog.accept()
        window = parent.window() if parent is not None else None
        try:
            spawn_replacer(target, Path(path))
        except OSError as error:
            QMessageBox.warning(parent, "更新失败", f"没法安排替换程序：{error}")
            return
        QMessageBox.information(
            parent,
            "更新就绪",
            f"{APP_NAME} 将关闭并在几秒后自动以 v{info.version} 重新打开。\n"
            f"你的日程数据与铃声都不会受影响。",
        )
        # 真正退出：托盘模式下光关窗只会收起来
        if hasattr(window, "quit_app"):
            window.quit_app()
        else:
            QApplication.quit()

    thread.progress.connect(on_progress)
    thread.failed.connect(on_failed)
    thread.done.connect(on_done)
    dialog.rejected.connect(thread.cancel)
    thread.start()
    dialog.exec()


def run_check(parent, store, silent: bool = False) -> None:
    """查一次更新。silent 为真时（启动自动检查）不弹「已是最新」与报错。"""
    thread = CheckThread()
    _keep(thread)

    def on_failed(message: str) -> None:
        if not silent:
            QMessageBox.warning(
                parent, "检查更新失败", f"没能连上更新源：\n{message}"
            )

    def on_done(info) -> None:
        if info is None or not is_newer(info.version):
            if not silent:
                QMessageBox.information(
                    parent, "检查更新", f"当前已是最新版本 v{VERSION}。"
                )
            return
        if info.version == store.update_skip_version():
            return                        # 用户说过跳过这版
        dialog = UpdateDialog(info, parent)
        dialog.exec()
        if dialog.choice == CHOICE_SKIP:
            store.set_update_skip_version(info.version)
        elif dialog.choice == CHOICE_NOW:
            _apply(parent, store, info)

    thread.done.connect(on_done)
    thread.failed.connect(on_failed)
    thread.start()


def auto_check_due(store) -> bool:
    """该不该在启动时悄悄查一次：开着自动检查、且距上次超过一天。"""
    if not store.auto_update_check():
        return False
    return time.time() - store.update_last_check() >= CHECK_INTERVAL


def schedule_startup_check(window, store) -> None:
    """启动后延一小会儿再静默检查，不打扰开程序这一下。"""

    def fire() -> None:
        if not auto_check_due(store):
            return
        store.set_update_last_check(time.time())
        run_check(window, store, silent=True)

    QTimer.singleShot(STARTUP_DELAY_MS, fire)
