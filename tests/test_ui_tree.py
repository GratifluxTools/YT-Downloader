"""UI tests with the REAL Flet controls (no window): builds src/main.py's screen, drives it with a fake
page + fake yt-dlp, and lints the control tree for the layout mistakes that broke an earlier version
(Flutter cannot lay out `expand` inside Row(wrap=True), inside a scrolling Column, ...).

    pip install flet==0.28.3 && python -m unittest tests.test_ui_tree -v
"""
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

try:
    import flet as ft
    HAVE_FLET = True
except Exception:  # pragma: no cover
    HAVE_FLET = False

import core  # noqa: E402
from test_core import FAKE, wait_for  # noqa: E402

MIN_WIDTH = 900


class FakePage:
    def __init__(self):
        self.controls, self.overlay, self.opened, self.closed = [], [], [], []
        self.window = SimpleNamespace(width=0, height=0, min_width=0, min_height=0, prevent_close=False,
                                      on_event=None, focused=True, destroy=lambda: None)
        self.title, self.theme_mode, self.padding, self.clip, self.launched = "", None, None, None, None

    def add(self, *c): self.controls.extend(c)
    def update(self, *a): pass
    def open(self, d): self.opened.append(d)
    def close(self, d): self.closed.append(d)
    def set_clipboard(self, t): self.clip = t
    def launch_url(self, u): self.launched = u


# ---------------------------------------------------------------- lint
def kids(c):
    out = []
    for attr in ("controls", "tabs"):
        v = getattr(c, attr, None)
        if isinstance(v, list):
            out += [x for x in v if isinstance(x, ft.Control)]
    v = getattr(c, "content", None)
    if isinstance(v, ft.Control):
        out.append(v)
    return out


def truthy(v):
    return bool(v) and v is not False


def est_width(c) -> int:
    """Rough width of a control in a Row (px); only used to catch gross horizontal overflow."""
    w = getattr(c, "width", None)
    if w:
        return int(w)
    cjk = lambda s: sum(15 if ord(ch) > 0x2E80 else 8 for ch in (s or ""))
    if isinstance(c, (ft.ElevatedButton, ft.OutlinedButton, ft.FilledButton, ft.TextButton)):
        return 40 + cjk(getattr(c, "text", "")) + (24 if getattr(c, "icon", None) else 0)
    if isinstance(c, ft.IconButton):
        return 40
    if isinstance(c, ft.Checkbox):
        return 40 + cjk(c.label)
    if isinstance(c, ft.Text):
        return cjk(c.value)
    if isinstance(c, ft.Column):
        return max([est_width(x) for x in c.controls] or [0])
    return 100


def lint(root_controls):
    errors = []

    def walk(c, parents):
        parent = parents[-1] if parents else None
        name = type(c).__name__
        if truthy(getattr(c, "expand", None)) or truthy(getattr(c, "expand_loose", None)):
            if parent is not None:
                if getattr(parent, "wrap", False):
                    errors.append(f"{name}(expand) inside {type(parent).__name__}(wrap=True)")
                if isinstance(parent, (ft.Row, ft.Column)) and getattr(parent, "scroll", None):
                    errors.append(f"{name}(expand) directly inside scrolling {type(parent).__name__}")
                if isinstance(parent, ft.ListView):
                    errors.append(f"{name}(expand) inside ListView")
            if isinstance(c, (ft.Column, ft.ListView)):
                for a in parents:
                    if isinstance(a, ft.Column) and getattr(a, "scroll", None):
                        errors.append(f"vertical {name}(expand) below a scrolling Column (unbounded height)")
        if isinstance(c, ft.Row) and not getattr(c, "wrap", False) and not getattr(c, "scroll", None):
            total = sum(est_width(x) for x in c.controls) + (c.spacing if c.spacing is not None else 10) * max(0, len(c.controls) - 1)
            if total > MIN_WIDTH - 40:
                errors.append(f"Row may overflow horizontally (~{total}px > {MIN_WIDTH - 40}px): "
                              f"{[type(x).__name__ for x in c.controls]}")
        for k in kids(c):
            walk(k, parents + [c])

    for r in root_controls:
        walk(r, [])
    return errors


def all_controls(root_controls):
    out = []

    def walk(c):
        out.append(c)
        for k in kids(c):
            walk(k)
    for r in root_controls:
        walk(r)
    return out


@unittest.skipUnless(HAVE_FLET and os.name != "nt", "needs flet and POSIX (fake yt-dlp)")
class UiTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        fake = t / "yt-dlp"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        core.user_data_dir = lambda: t / "data"
        core.locate_ytdlp = lambda: str(fake)
        core.locate_ffmpeg = lambda: None
        core.find_js_runtime = lambda: None
        core.latest_release = lambda: None
        cls.notes = []
        core.notify = lambda title, msg: cls.notes.append((title, msg))
        cls.out = t / "out"
        import i18n
        i18n.set_lang("en")
        import main
        cls.main = main
        cls.page = FakePage()
        cls.app = main.App(cls.page)

    @classmethod
    def tearDownClass(cls):
        cls.app.mgr.stop_all(5)
        cls.tmp.cleanup()

    def sync(self):
        self.app.sync(force=True)

    def test_01_tree_is_valid_and_lint_clean_in_both_languages(self):
        self.assertEqual(self.page.title, "yt-dlp Downloader Pro")
        self.assertEqual((self.page.window.min_width, self.page.window.prevent_close), (MIN_WIDTH, True))
        self.assertEqual(lint(self.page.controls), [])
        names = {type(c).__name__ for c in all_controls(self.page.controls)}
        self.assertTrue({"Tabs", "ListView", "TextField", "Dropdown", "Checkbox"} <= names)
        self.assertFalse(any(isinstance(c, ft.Stack) for c in all_controls(self.page.controls)))
        # every original control exists
        for attr in ("f_url", "btn_add", "f_ext", "f_quality", "f_aq", "f_outdir", "f_filename", "c_thumb", "c_meta",
                     "btn_cookies", "f_lang", "queue", "log_list"):
            self.assertTrue(hasattr(self.app, attr), attr)
        self.app.f_lang.value = "ja"
        self.app._on_lang(None)
        self.assertEqual(self.page.title, "yt-dlp ダウンローダー Pro")
        self.assertEqual(lint(self.page.controls), [])
        self.app.f_lang.value = "en"
        self.app._on_lang(None)

    def test_02_original_defaults(self):
        a = self.app
        self.assertEqual((a.f_ext.value, a.f_quality.value, a.f_aq.value, a.c_thumb.value, a.c_meta.value),
                         ("mp4", "best", "128kbps", True, True))
        self.assertTrue(a.f_aq.disabled and not a.f_quality.disabled)          # mp4 -> audio quality disabled
        self.assertEqual(a.mgr.max_concurrent, 3)
        self.assertEqual([o.key or o.text for o in a.f_ext.options][:6], ["mp4", "mkv", "webm", "mp3", "m4a", "wav"])
        self.assertTrue(a.f_url.shift_enter and a.f_url.on_submit)               # Enter adds, Shift+Enter = newline
        a.f_ext.value = "mp3"
        a._on_ext(None)
        self.assertTrue(a.f_quality.disabled and not a.f_aq.disabled)
        a.f_ext.value = "mp4"
        a._on_ext(None)

    def test_03_queue_flow_cards_log_menu_notification(self):
        a, p = self.app, self.page
        a.f_outdir.value = str(self.out)
        a.f_url.value = "https://x/vod\nhttps://x/err\nnot-a-url\nhttps://x/live"
        p.window.focused = False                      # window in the background -> notifications
        a.f_url.on_submit(None)                       # = pressing Enter
        self.assertEqual(a.f_url.value, "")
        self.assertTrue(wait_for(lambda: all(x["status"] in (core.FINISHED, core.ERROR, core.LIVE)
                                             for x in a.mgr.snapshot()["tasks"]) and len(a.mgr.snapshot()["tasks"]) == 3, 15))
        self.sync()
        c1, c2, c3 = (a.cards[i] for i in (1, 2, 3))
        self.assertEqual((c1.chip_text.value, c1.bar.value, c1.stop.visible, c1.retry.visible), ("Finished", 1, False, True))
        self.assertEqual((c2.chip_text.value, c2.info.value[:9]), ("Error", "[youtube]"))
        self.assertEqual((c3.chip_text.value, c3.bar._get_attr("value") in (None, ""), c3.stop.visible), ("Recording", True, True))   # indeterminate bar
        self.assertEqual(len(a.queue.controls), 3)
        self.assertEqual(lint(self.page.controls), [])
        # notifications (original: tray message when the window is not active)
        self.assertTrue(wait_for(lambda: len(self.notes) >= 2, 5))
        self.assertIn(("Download Complete", "Task #1 has finished."), self.notes)
        self.assertIn(("Download Failed", "Task #2 failed. Check the log."), self.notes)
        # click a task -> its log appears under "Task #N Logs"
        c3.root.on_tap(None)
        self.assertEqual(a.log_label.value, "Task #3 Logs")
        self.assertTrue(wait_for(lambda: (a.sync() or True) and any("Destination" in x.value for x in a.log_list.controls if hasattr(x, "value")), 5))
        n_before = len(a.log_list.controls)
        time.sleep(0.6)
        a.sync()
        self.assertLessEqual(abs(len(a.log_list.controls) - n_before), 1)       # progress line replaced, not appended
        # right-click menu (original: Delete Task)
        c3.root.on_secondary_tap(None)
        dlg = p.opened[-1]
        labels = [b.text for b in dlg.content.controls]
        self.assertIn("Stop", labels)
        self.assertIn("Delete Task", labels)
        next(b for b in dlg.content.controls if b.text == "Stop").on_click(None)
        self.assertTrue(wait_for(lambda: a.mgr.snapshot()["tasks"][2]["status"] == core.CANCELLED, 20))
        self.sync()
        self.assertEqual(a.cards[3].chip_text.value, "Cancelled")
        self.assertIn("live.mp4", a.cards[3].info.value)
        self.assertTrue((self.out / "live.mp4").is_file())
        # delete via menu
        a.task_menu(3)
        next(b for b in p.opened[-1].content.controls if b.text == "Delete Task").on_click(None)
        self.assertNotIn(3, a.cards)

    def test_04_url_only_dialog(self):
        a, p = self.app, self.page
        a.f_url.value = "https://x/vod"
        a.f_kind.value = "stream"
        n = len(p.opened)
        a.get_urls_clicked()
        self.assertTrue(wait_for(lambda: len(p.opened) > n, 10))
        field = p.opened[-1].content
        self.assertIn("https://cdn.example/video.m3u8", field.value)
        a.f_url.value = "https://x/vod"
        a.f_kind.value = "page"
        n = len(p.opened)
        a.get_urls_clicked()
        self.assertTrue(wait_for(lambda: len(p.opened) > n, 10))
        self.assertIn("watch?v=bbb", p.opened[-1].content.value)

    def test_05_settings_persist_and_cookies(self):
        a = self.app
        a.f_browser.value = "firefox"
        a._on_browser(None)
        self.assertTrue(a.btn_cookies.disabled and not a.f_profile.disabled)
        a.f_profile.value = "default"
        a.f_interval.value = "30"
        a.save()
        saved = core.load_settings()
        self.assertEqual((saved["browser"], saved["profile"], saved["interval"]), ("firefox", "default", 30))
        job = a.mgr.build_job("https://x/v", a.collect())
        cmd = core.build_download_cmd("y", None, job)
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "firefox:default")
        a._clear_cookies()
        self.assertEqual(a.f_browser.value, "none")
        # cookies.txt import through the file picker callback
        f = Path(self.tmp.name) / "c.txt"
        f.write_text("# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tk\tv\n")
        a._on_cookies(SimpleNamespace(files=[SimpleNamespace(path=str(f))]))
        self.assertEqual(a.cookies_lbl.value, "cookies.txt")
        self.assertTrue(a.mgr.cookies_file())

    def test_06_quit_flow(self):
        a = self.app
        destroyed = []
        a.page.window.destroy = lambda: destroyed.append(1)
        os_exit = os._exit
        os._exit = lambda c: None
        try:
            a._quit()
            time.sleep(0.1)
        finally:
            os._exit = os_exit
        self.assertTrue(destroyed)
        self.assertFalse(a.page.window.prevent_close)


if __name__ == "__main__":
    unittest.main()
