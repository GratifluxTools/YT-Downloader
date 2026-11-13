"""Manager tests (fake yt-dlp, POSIX only): input sanitising and the scheduling rules."""
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
from test_core import FAKE, wait_for  # noqa: E402


@unittest.skipIf(os.name == "nt", "fake yt-dlp is a POSIX script")
class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        fake = t / "yt-dlp"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        core.user_data_dir = lambda: t / "data"
        core.locate_ytdlp = lambda: str(fake)
        core.locate_ffmpeg = lambda: None
        core.find_js_runtime = lambda: None
        from manager import Manager
        self.m = Manager()
        self.out = str(t / "out")

    def tearDown(self):
        self.m.stop_all(5)
        self.tmp.cleanup()

    def test_url_validation_blocks_option_injection(self):
        for bad in ("-o /etc/x", "--exec rm", "file:///etc/passwd", "javascript:alert(1)", "", "https://a b"):
            self.assertFalse(self.m.valid_url(bad), bad)
        self.assertTrue(self.m.valid_url("https://www.youtube.com/watch?v=abc"))

    def test_build_job_sanitises(self):
        j = self.m.build_job("https://x/v", {"ext": "exe", "quality": "9999", "audio_quality": "x", "browser": "../../x",
                                             "interval": "abc", "filename": "a\nb", "subs": True, "outdir": ""})
        self.assertEqual((j.ext, j.quality, j.audio_quality, j.cookies_browser, j.wait_interval),
                         ("mp4", "best", "128kbps", "", 15))
        self.assertNotIn("\n", j.filename)
        self.assertEqual(j.outdir, core.default_outdir())
        a = self.m.build_job("https://x/v", {"ext": "mp3", "subs": True})
        self.assertFalse(a.subs)                       # subtitles only for video containers

    def test_waiting_stream_does_not_occupy_a_slot(self):
        self.m.set_settings({"concurrent": 1})
        self.m.add_urls(["https://x/wait", "https://x/vod"], {"outdir": self.out})
        ok = wait_for(lambda: self.m.snapshot()["tasks"][1]["status"] == core.FINISHED, 15)
        st = [t["status"] for t in self.m.snapshot()["tasks"]]
        self.assertTrue(ok, st)
        self.assertEqual(st[0], core.WAITING)

    def test_recording_holds_the_only_slot(self):
        self.m.set_settings({"concurrent": 1})
        self.m.add_urls(["https://x/live"], {"outdir": self.out})
        self.assertTrue(wait_for(lambda: self.m.snapshot()["tasks"][0]["status"] == core.LIVE, 10))
        self.m.add_urls(["https://x/vod"], {"outdir": self.out})   # added while the recording is running
        time.sleep(0.6)
        self.assertEqual(self.m.snapshot()["tasks"][1]["status"], core.PENDING)   # slot is taken
        self.m.stop(1)
        self.assertTrue(wait_for(lambda: self.m.snapshot()["tasks"][1]["status"] == core.FINISHED, 15))

    def test_retry_delete_clear(self):
        self.m.add_urls(["https://x/err", "https://x/vod"], {"outdir": self.out})
        self.assertTrue(wait_for(lambda: all(t["status"] in core.FINAL for t in self.m.snapshot()["tasks"]), 15))
        self.m.retry(1)
        self.assertTrue(wait_for(lambda: self.m.snapshot()["tasks"][0]["status"] == core.ERROR, 10))
        self.m.clear_finished()
        self.assertEqual([t["id"] for t in self.m.snapshot()["tasks"]], [1])
        self.m.delete(1)
        self.assertEqual(self.m.snapshot()["tasks"], [])


if __name__ == "__main__":
    unittest.main()
