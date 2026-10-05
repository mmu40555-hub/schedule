"""更新器镜像回退的回归测试。

国内多数网络直连不上 GitHub，查询与下载都应当在直连失败后自动改用镜像。
这里把网络函数换掉，盯住「先直连、失败才退镜像」这条线不走样。
"""

import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 让测试能 import 到程序模块（仓库根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import updater as u  # noqa: E402


class MirrorCandidatesTest(unittest.TestCase):
    def test_direct_url_comes_first(self):
        """候选地址里第一位必须是原始直连地址，镜像排在后面。"""
        url = "https://github.com/a/b/releases/download/v1/x.exe"
        candidates = u.mirror_candidates(url)

        self.assertEqual(candidates[0], url)
        self.assertEqual(len(candidates), 1 + len(u.MIRROR_PREFIXES))
        for prefix in u.MIRROR_PREFIXES:
            self.assertIn(prefix + url, candidates)


class FetchReleaseFallbackTest(unittest.TestCase):
    """查询最新发布：直连不通要能退到镜像。"""

    def setUp(self):
        self.real = u._read_json
        self.real_source = u.PRIMARY_SOURCE
        # 这组测试只盯 GitHub 直连与镜像这条线，主源单独在 test_updater_primary 里测
        u.PRIMARY_SOURCE = ""
        self.calls = []

    def tearDown(self):
        u._read_json = self.real
        u.PRIMARY_SOURCE = self.real_source

    def _stub(self, direct_error, mirror_data):
        def fake(url, timeout):
            self.calls.append(url)
            if url == u.API_LATEST:
                raise direct_error
            return mirror_data
        u._read_json = fake

    def test_falls_back_to_mirror_when_direct_fails(self):
        payload = {
            "tag_name": "v9.9.9",
            "body": "更新说明",
            "html_url": "https://example.com/release",
            "assets": [{
                "name": "default.exe",
                "browser_download_url": "https://github.com/a/b/x.exe",
                "size": 42,
            }],
        }
        self._stub(OSError("连接被重置"), payload)

        info = u.fetch_latest()

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.notes, "更新说明")
        self.assertEqual(info.asset_name, "default.exe")
        self.assertEqual(info.asset_size, 42)
        # 第一次直连、第二次就已经是镜像了
        self.assertEqual(self.calls[0], u.API_LATEST)
        self.assertEqual(self.calls[1], u.MIRROR_PREFIXES[0] + u.API_LATEST)

    def test_direct_404_means_no_release_and_skips_mirrors(self):
        """直连 404 说明仓库没发过 Release，这是权威结果，不该再去问镜像。"""
        self._stub(urllib.error.HTTPError(u.API_LATEST, 404, "nf", {}, None), {})

        self.assertIsNone(u.fetch_latest())
        self.assertEqual(self.calls, [u.API_LATEST])

    def test_raises_when_everything_fails(self):
        """直连和所有镜像都挂了，应当抛错，让上层去决定提示还是静默。"""
        def fake(url, timeout):
            self.calls.append(url)
            raise OSError("全都不通")
        u._read_json = fake

        with self.assertRaises(OSError):
            u.fetch_latest()
        self.assertEqual(len(self.calls), 1 + len(u.MIRROR_PREFIXES))


class DownloadFallbackTest(unittest.TestCase):
    """下载附件：直连失败要能退到镜像重下。"""

    def setUp(self):
        self.real = u._download_once
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "new.exe"

    def tearDown(self):
        u._download_once = self.real
        self.tmp.cleanup()

    def _stub(self, fail_first: int):
        def fake(url, dest, on_progress, cancel, timeout):
            self.calls.append(url)
            if len(self.calls) <= fail_first:
                raise OSError("断流")
            Path(dest).write_bytes(b"MZ fake exe")
            return True
        u._download_once = fake

    def test_falls_back_to_mirror_when_direct_fails(self):
        self._stub(fail_first=1)
        url = "https://github.com/a/b/releases/download/v1/x.exe"

        ok = u.download_asset(url, self.dest)

        self.assertTrue(ok)
        self.assertEqual(self.calls[0], url)
        self.assertEqual(self.calls[1], u.MIRROR_PREFIXES[0] + url)
        self.assertEqual(self.dest.read_bytes(), b"MZ fake exe")

    def test_direct_success_never_touches_mirrors(self):
        self._stub(fail_first=0)
        url = "https://github.com/a/b/releases/download/v1/x.exe"

        u.download_asset(url, self.dest)

        self.assertEqual(self.calls, [url])

    def test_cancel_stops_before_trying_mirrors(self):
        self._stub(fail_first=1)
        url = "https://github.com/a/b/releases/download/v1/x.exe"

        ok = u.download_asset(url, self.dest, cancel=lambda: True)

        self.assertFalse(ok)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
