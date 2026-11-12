"""Logic tests for src/core.py using a fake yt-dlp executable (POSIX only).

    python -m unittest discover -s tests -v
"""
import os
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import core  # noqa: E402

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import sys, time, os
    args = sys.argv[1:]
    def out(s, end="\\n"):
        sys.stdout.write(s + end); sys.stdout.flush()
    if "-g" in args:
        out("https://cdn.example/video.m3u8"); out("https://cdn.example/audio.m3u8"); sys.exit(0)
    if "--flat-playlist" in args:
        out("https://www.youtube.com/watch?v=aaa"); out("https://www.youtube.com/watch?v=bbb"); sys.exit(0)
    url = args[0]
    outdir = os.path.dirname(args[args.index("-o") + 1])
    if "err" in url:
        out("ERROR: [youtube] xyz: Video unavailable"); sys.exit(1)
    if "vod" in url:
        out("[download] Destination: " + os.path.join(outdir, "vod.mp4"))
        for p in (5.0, 50.5, 100.0):
            out("[download]  %.1f%% of  10.00MiB at  2.00MiB/s ETA 00:0%d" % (p, int(5 - p / 25)), end="\\r\\n")
            time.sleep(0.05)
        sys.exit(0)
    if "live" in url:
        out("[youtube] abc: Downloading webpage")
        out("[wait] Waiting for 00:00:02 - Press Ctrl+C to try now")
        out("[wait] Remaining time until next attempt: 00:00:01", end="\\r")
        time.sleep(0.3)
        dest = os.path.join(outdir, "live.mp4")
        out("[download] Destination: " + dest)
        open(dest + ".part", "wb").write(b"x" * 1000)
        while True:
            out("[download]   1.00MiB at  500.00KiB/s (00:00:02)")
            time.sleep(0.1)
''')


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@unittest.skipIf(os.name == "nt", "fake yt-dlp is a POSIX script")
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.fake = self.dir / "yt-dlp"
        self.fake.write_text(FAKE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        core.locate_ytdlp = lambda: str(self.fake)
        core.locate_ffmpeg = lambda: None
        core.find_js_runtime = lambda: None

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, url, **kw):
        events, logs = [], []
        done = threading.Event()
        job = core.Job(url=url, outdir=str(self.dir), **kw)
        r = core.Runner(job, lambda s, m, p: events.append((s, m, p)),
                        lambda l, rep: logs.append((l, rep)), done.set)
        r.start()
        return r, events, logs, done

    # ---- command building
    def test_cmd_mp4_1080(self):
        c = core.build_download_cmd("yt-dlp", "/ff", core.Job(url="U", outdir="/o", quality="1080"))
        self.assertIn("bv*[height<=1080]+ba/b[height<=1080]", c)
        self.assertIn("--merge-output-format", c)
        self.assertNotIn("--recode-video", c)
        self.assertIn("--embed-thumbnail", c)
        self.assertIn("--no-playlist", c)
        self.assertEqual(c[c.index("--wait-for-video") + 1], "15-60")

    def test_cmd_audio_and_thumb_rules(self):
        c = core.build_download_cmd("y", None, core.Job(url="U", outdir="/o", ext="mp3", audio_quality="192kbps"))
        self.assertEqual(c[c.index("--audio-quality") + 1], "192K")
        c = core.build_download_cmd("y", None, core.Job(url="U", outdir="/o", ext="wav"))
        self.assertNotIn("--embed-thumbnail", c)   # wav cannot embed thumbnails
        self.assertNotIn("--audio-quality", c)

    def test_cmd_cookies_live_playlist(self):
        j = core.Job(url="U", outdir="/o", cookies_browser="firefox", browser_profile="default",
                     cookies_file="/c.txt", live_from_start=True, playlist=True, live_wait=False)
        c = core.build_download_cmd("y", None, j)
        self.assertEqual(c[c.index("--cookies-from-browser") + 1], "firefox:default")
        self.assertNotIn("--cookies", c)            # browser wins over cookies.txt
        self.assertIn("--live-from-start", c)
        self.assertNotIn("--wait-for-video", c)
        self.assertIn("--yes-playlist", c)
        self.assertIn("%(playlist_title&{}/|)s", c[c.index("-o") + 1])

    def test_misc(self):
        self.assertTrue(core.ver_tuple("v2.1.0") > core.ver_tuple("2.0.9"))
        self.assertEqual(core._sha_from_sums("abc  *yt-dlp.exe\ndef  yt-dlp", "yt-dlp.exe"), "abc")

    # ---- runner
    def test_vod_progress_and_finish(self):
        r, ev, logs, done = self.run_job("http://x/vod")
        self.assertTrue(done.wait(10))
        pcts = [p for s, m, p in ev if s == core.RUNNING and p is not None]
        self.assertEqual(pcts[-1], 100.0)
        self.assertIn(50.5, pcts)
        self.assertEqual(ev[-1][0], core.FINISHED)

    def test_error_message(self):
        r, ev, logs, done = self.run_job("http://x/err")
        self.assertTrue(done.wait(10))
        self.assertEqual(ev[-1], (core.ERROR, "[youtube] xyz: Video unavailable", None))

    def test_live_wait_record_stop_salvage(self):
        r, ev, logs, done = self.run_job("http://x/live")
        self.assertTrue(wait_for(lambda: any(s == core.WAITING for s, m, p in ev)), "never WAITING")
        self.assertTrue(wait_for(lambda: any(s == core.LIVE for s, m, p in ev)), "never LIVE")
        self.assertIn(("1.00MiB @ 500.00KiB/s", ), [(m,) for s, m, p in ev if s == core.LIVE][:1])
        r.cancel()
        self.assertTrue(done.wait(15), "did not stop")
        self.assertEqual(ev[-1][0], core.CANCELLED)
        self.assertIn("live.mp4", ev[-1][1])
        self.assertTrue((self.dir / "live.mp4").is_file())       # .part renamed -> playable
        self.assertFalse((self.dir / "live.mp4.part").exists())
        # progress lines replace each other in the log instead of flooding it
        self.assertTrue(any(rep for l, rep in logs))

    def test_cancel_before_start(self):
        job = core.Job(url="http://x/vod", outdir=str(self.dir))
        evs, done = [], threading.Event()
        r = core.Runner(job, lambda s, m, p: evs.append(s), lambda l, rep: None, done.set)
        r.cancel()
        r.start()
        self.assertTrue(done.wait(5))
        self.assertEqual(evs[-1], core.CANCELLED)

    # ---- URL-only
    def test_fetch_stream_and_page(self):
        j = core.Job(url="http://x/vod", outdir=str(self.dir))
        text = core.fetch_urls([(j, "stream")])
        self.assertEqual(text.splitlines(), ["https://cdn.example/video.m3u8", "https://cdn.example/audio.m3u8"])
        text = core.fetch_urls([(j, "page")])
        self.assertIn("watch?v=bbb", text)

    def test_fetch_error_reported_as_comment(self):
        bad = self.dir / "bad"
        bad.write_text("#!/bin/sh\necho 'ERROR: Private video' >&2\nexit 1\n")
        bad.chmod(0o755)
        core.locate_ytdlp = lambda: str(bad)
        text = core.fetch_urls([(core.Job(url="http://x/p", outdir="."), "stream")])
        self.assertIn("# ERROR: Private video", text)


if __name__ == "__main__":
    unittest.main()
