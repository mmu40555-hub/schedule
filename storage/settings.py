from .schema import (
    DEFAULT_NEW_NOTE_HOTKEY,
    DEFAULT_REMIND_MINUTES,
    NAV_POSITIONS,
    NAV_TOP,
    REMIND_AUTO,
    REMIND_MODES,
    SETTING_AUTO_UPDATE,
    SETTING_DEFAULT_REMIND,
    SETTING_NAV_POSITION,
    SETTING_NEW_NOTE_HOTKEY,
    SETTING_REMIND_MODE,
    SETTING_REMIND_SOUND,
    SETTING_REMIND_SOUND_CHOICE,
    SETTING_REMIND_SOUND_FILES,
    SETTING_UPDATE_LAST,
    SETTING_UPDATE_SKIP,
)


# 应用设置：key-value 读写与各设置项的默认值。
class SettingsMixin:
    # ================= 应用设置 =================

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def default_remind_minutes(self) -> int:
        """新建任务时提醒量输入框的默认值。"""
        raw = self.get_setting(SETTING_DEFAULT_REMIND, "")
        try:
            return max(0, min(600, int(raw)))
        except ValueError:
            return DEFAULT_REMIND_MINUTES

    def remind_mode(self) -> str:
        """到点提醒怎么弹：自动 / 只用置底小窗 / 两处都提示。"""
        mode = self.get_setting(SETTING_REMIND_MODE, REMIND_AUTO)
        return mode if mode in {value for value, _ in REMIND_MODES} else REMIND_AUTO

    def remind_sound_enabled(self) -> bool:
        """到点提醒要不要响一声。默认响，只有明确存过 "0" 才静音。"""
        return self.get_setting(SETTING_REMIND_SOUND, "1") != "0"

    def remind_sound_choice(self) -> str:
        """当前选的提醒音：alias:xxx 是系统音，file:xxx 是本地音频；空串表示用默认。"""
        choice = self.get_setting(SETTING_REMIND_SOUND_CHOICE, "")
        return choice if choice.startswith(("alias:", "file:")) else ""

    def set_remind_sound_choice(self, choice: str) -> None:
        self.set_setting(SETTING_REMIND_SOUND_CHOICE, str(choice))

    def remind_sound_files(self) -> list[str]:
        """用户添加过的本地音频文件，按添加顺序去重。"""
        files: list[str] = []
        for line in self.get_setting(SETTING_REMIND_SOUND_FILES, "").splitlines():
            path = line.strip()
            if path and path not in files:
                files.append(path)
        return files

    def set_remind_sound_files(self, paths: list[str]) -> None:
        files: list[str] = []
        for path in paths:
            path = str(path).strip()
            if path and path not in files:
                files.append(path)
        self.set_setting(SETTING_REMIND_SOUND_FILES, "\n".join(files))

    def nav_position(self) -> str:
        """主导航在顶部还是左侧。"""
        position = self.get_setting(SETTING_NAV_POSITION, NAV_TOP)
        return position if position in {value for value, _ in NAV_POSITIONS} else NAV_TOP

    def new_note_hotkey(self) -> str:
        """新建便签的全局快捷键；空串表示用户把它关掉了。"""
        return self.get_setting(SETTING_NEW_NOTE_HOTKEY, DEFAULT_NEW_NOTE_HOTKEY).strip()

    def set_new_note_hotkey(self, shortcut: str) -> None:
        self.set_setting(SETTING_NEW_NOTE_HOTKEY, str(shortcut).strip())

    def auto_update_check(self) -> bool:
        """启动时要不要自动查一次新版本。默认开，只有明确存过 "0" 才关。"""
        return self.get_setting(SETTING_AUTO_UPDATE, "1") != "0"

    def set_auto_update_check(self, enabled: bool) -> None:
        self.set_setting(SETTING_AUTO_UPDATE, "1" if enabled else "0")

    def update_last_check(self) -> float:
        """上次自动检查更新的时间戳；没查过返回 0。"""
        raw = self.get_setting(SETTING_UPDATE_LAST, "")
        try:
            return float(raw)
        except ValueError:
            return 0.0

    def set_update_last_check(self, stamp: float) -> None:
        self.set_setting(SETTING_UPDATE_LAST, repr(float(stamp)))

    def update_skip_version(self) -> str:
        """用户选过「跳过这个版本」的版本号，空串表示没跳过谁。"""
        return self.get_setting(SETTING_UPDATE_SKIP, "").strip()

    def set_update_skip_version(self, version: str) -> None:
        self.set_setting(SETTING_UPDATE_SKIP, str(version).strip())
