"""更新器「主源优先」的回归测试。

主源是自建对象存储（阿里云 OSS / 腾讯云 COS 等），放一份 latest.json 描述最新版本。
规则是：主源给出更新就直接用，主源没配/连不上/版本不新都退回 GitHub 与镜像。
这里把网络函数换掉，盯住这条分叉不走样。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 让测试能 import 到程序模块（仓库根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import updater as u  # noqa: E402

PRIMARY = "https://bucket.example.com/schedule"
META_URL = PRIMARY + "/latest.json"


def _github_payload(version: str = "9.9.9") -> dict:
    return {
        "tag_name": f"v{version}",
        "body": "GitHub 上的更新说明",
        "html_url": "https://example.com/release",
        "assets": [{
            "name": "default.exe",
            "browser_download_url": "https://github.com/a/b/x.exe",
            "size": 42,
        }],
    }


class PrimarySourceTest(unittest.TestCase):
    def setUp(self):
        self.real_source = u.PRIMARY_SOURCE
        self.real_read = u._read_json
        self.calls = []
        u.PRIMARY_SOURCE = PRIMARY

    def tearDown(self):
        u.PRIMARY_SOURCE = self.real_source
        u._read_json = self.real_read

    def test_primary_newer_version_wins_without_github(self):
        """主源给出更新，就直接用它，不必再去连 GitHub。"""
        asset_url = PRIMARY + "/v9.9.9/日程计划表.exe"

        def fake(url, timeout):
            self.calls.append(url)
            return {
                "version": "9.9.9",
                "notes": "主源说明",
                "asset_name": "日程计划表.exe",
                "asset_size": 123,
                "asset_url": asset_url,
            }

        u._read_json = fake
        info = u.fetch_latest()

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.notes, "主源说明")
        self.assertEqual(info.asset_candidates, (asset_url,))
        # 只问了主源一次，没有去碰 GitHub 的接口
        self.assertEqual(self.calls, [META_URL])

    def test_primary_down_falls_back_to_github(self):
        """主源连不上时，照旧走 GitHub。"""
        def fake(url, timeout):
            self.calls.append(url)
            if url == META_URL:
                raise OSError("主源不通")
            return _github_payload()

        u._read_json = fake
        info = u.fetch_latest()

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.notes, "GitHub 上的更新说明")
        self.assertEqual(self.calls[0], META_URL)
        self.assertEqual(self.calls[1], u.API_LATEST)

    def test_stale_primary_does_not_hide_new_github_release(self):
        """主源没同步、版本不比当前新时，仍要去问 GitHub。"""
        def fake(url, timeout):
            self.calls.append(url)
            if url == META_URL:
                return {"version": u.VERSION}       # 停在当前版本，等于没更新
            return _github_payload()

        u._read_json = fake
        info = u.fetch_latest()

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(self.calls[0], META_URL)
        self.assertEqual(self.calls[1], u.API_LATEST)

    def test_no_primary_configured_goes_straight_to_github(self):
        """没配主源时，第一步就是 GitHub，行为与从前一致。"""
        u.PRIMARY_SOURCE = ""

        def fake(url, timeout):
            self.calls.append(url)
            return _github_payload()

        u._read_json = fake
        info = u.fetch_latest()

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(self.calls, [u.API_LATEST])

    def test_missing_asset_url_is_built_from_version(self):
        """latest.json 没写 asset_url 时，按 {主源}/v{版本}/{文件名} 拼。"""
        u._read_json = lambda url, timeout: {"version": "9.9.9"}

        info = u.fetch_latest()

        self.assertEqual(info.asset_name, f"{u.APP_NAME}.exe")
        self.assertEqual(info.asset_url, f"{PRIMARY}/v9.9.9/{u.APP_NAME}.exe")


class DownloadCandidateTest(unittest.TestCase):
    def setUp(self):
        self.real = u._download_once
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "new.exe"

    def tearDown(self):
        u._download_once = self.real
        self.tmp.cleanup()

    def test_candidate_list_is_used_as_is(self):
        """主源给的候选列表按原样下，不会去套 GitHub 镜像前缀。"""
        def fake(url, dest, on_progress, cancel, timeout):
            self.calls.append(url)
            Path(dest).write_bytes(b"MZ fake exe")
            return True

        u._download_once = fake
        oss_url = PRIMARY + "/v9.9.9/日程计划表.exe"

        ok = u.download_asset((oss_url,), self.dest)

        self.assertTrue(ok)
        self.assertEqual(self.calls, [oss_url])

    def test_encode_url_escapes_chinese_filename(self):
        encoded = u._encode_url(PRIMARY + "/v9.9.9/日程计划表.exe")

        self.assertNotIn("日程", encoded)
        self.assertTrue(encoded.startswith(PRIMARY + "/v9.9.9/%E6%97%A5"))
        self.assertTrue(encoded.endswith(".exe"))


if __name__ == "__main__":
    unittest.main()
