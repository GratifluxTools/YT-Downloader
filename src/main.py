import os
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import flet as ft

import core
import i18n
from app_version import __version__
from i18n import t
from manager import Manager

# Layout rules (learned the hard way, checked by tests/test_ui_tree.py):
#  * `expand` is only used for a direct child of a Row/Column/Tabs (never inside Row(wrap=True)
#    and never directly inside a scrolling Column)
#  * same building blocks as the ClipboardTimeTravel app: Tabs -> Column(expand) ->
#    Container(expand=N) -> ListView(expand), Column(scroll, expand) for the settings page

STATUS_COLORS = {
    core.PENDING: ft.Colors.GREY_700,
    core.RUNNING: ft.Colors.BLUE_700,
    core.WAITING: ft.Colors.PURPLE_600,
    core.LIVE: ft.Colors.RED_700,
    core.FINISHED: ft.Colors.GREEN_700,
    core.ERROR: ft.Colors.RED_600,
    core.CANCELLED: ft.Colors.BLUE_GREY_600,
}
MONO = "Consolas" if core.IS_WIN else "monospace"


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.mgr = Manager()
        self.mgr.on_finish = self._on_finish
        s = self.mgr.settings
        i18n.set_lang(s.get("lang") or core.system_lang())
        self.ui_lock = threading.RLock()
        self.cards: dict = {}
        self.ids: list = []
        self.selected = None
        self.log_shown = None
        self.log_for = None
        self.tab_index = 0
        self.ready = False
        self._save_timer = None
        self._asked_install = False
        self._pending_save = ""

        self.fp_dir = ft.FilePicker(on_result=self._on_dir)
        self.fp_cookies = ft.FilePicker(on_result=self._on_cookies)
        self.fp_save = ft.FilePicker(on_result=self._on_save)
        page.overlay.extend([self.fp_dir, self.fp_cookies, self.fp_save])

        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 10
        page.window.width = 1150
        page.window.height = 800
        page.window.min_width = 900
        page.window.min_height = 620
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event

        self.render()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._startup, daemon=True).start()

    # ================================================================ UI
    def render(self) -> None:
        with self.ui_lock:
            self.ready = False
            s = self.mgr.settings
            p = self.page
            p.title = t("title")
            self.cards.clear()
            self.ids = None            # force the first sync() to fill the lists
            self.log_shown, self.log_for = None, None

            # ---- top: URL input + buttons (original: URL bar + "Add URL")
            self.f_url = ft.TextField(hint_text=t("urls_hint"), multiline=True, shift_enter=True, min_lines=2,
                                      max_lines=3, expand=True, text_size=13, on_submit=self.add_clicked)
            self.btn_add = ft.FilledButton(text=t("add"), icon=ft.Icons.DOWNLOAD, on_click=self.add_clicked)
            self.btn_get = ft.OutlinedButton(text=t("get_urls"), icon=ft.Icons.LINK, on_click=self.get_urls_clicked)
            top = ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                self.f_url, ft.Column(spacing=6, controls=[self.btn_add, self.btn_get])])

            # ---- quick options (original: format / resolution / audio quality next to the URL bar)
            ext = s.get("ext", "mp4")
            self.f_ext = ft.Dropdown(label=t("format"), value=ext, width=120, dense=True, on_change=self._on_ext,
                                     options=[ft.dropdown.Option(x) for x in core.VIDEO_FORMATS + core.AUDIO_FORMATS])
            self.f_quality = ft.Dropdown(
                label=t("quality"), value=s.get("quality", "best"), width=150, dense=True,
                disabled=ext in core.AUDIO_FORMATS, on_change=self._changed,
                options=[ft.dropdown.Option(q, self._quality_label(q)) for q in core.QUALITIES])
            self.f_aq = ft.Dropdown(label=t("audio_quality"), value=s.get("audio_quality", "128kbps"), width=150,
                                    dense=True, disabled=ext not in core.AUDIO_FORMATS, on_change=self._changed,
                                    options=[ft.dropdown.Option(x) for x in core.AUDIO_QUALITIES])
            self.f_kind = ft.Dropdown(
                label=t("get_urls"), value=s.get("kind", "stream"), width=300, dense=True, on_change=self._changed,
                options=[ft.dropdown.Option("stream", t("kind_stream")), ft.dropdown.Option("page", t("kind_page"))])
            quick = ft.Row(controls=[self.f_ext, self.f_quality, self.f_aq, self.f_kind])

            self.warn_text = ft.Text("", size=12, color=ft.Colors.ORANGE_300)
            self.warn = ft.Container(content=self.warn_text, visible=False, padding=8, border_radius=8,
                                     bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ORANGE))

            # ---- queue + log (original: table on the left / log on the right -> stacked here)
            self.queue = ft.ListView(expand=True, spacing=6)
            self.empty = ft.Container(padding=20, alignment=ft.alignment.center, content=ft.Text(
                t("queue_empty"), color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER))
            self.log_label = ft.Text(t("log_title", n=self.selected) if self.selected is not None else t("log_empty"),
                                     size=12, color=ft.Colors.GREY_400)
            self.log_list = ft.ListView(expand=True, spacing=0, auto_scroll=True)
            log_box = ft.Container(
                expand=2, padding=8, border_radius=8, bgcolor="#1e1e1e",
                content=ft.Column(spacing=4, expand=True, controls=[self.log_label, self.log_list]))

            # ---- footer (original: update / usage / about ... open folder / language)
            self.f_lang = ft.Dropdown(value=i18n.LANG, width=120, dense=True, on_change=self._on_lang,
                                      options=[ft.dropdown.Option("en", "English"), ft.dropdown.Option("ja", "日本語")])
            footer = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.ElevatedButton(text=t("update_tools"), on_click=self.update_clicked,
                                  style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE_800, color=ft.Colors.WHITE)),
                ft.TextButton(text=t("usage"), on_click=self.show_usage),
                ft.TextButton(text=t("about"), on_click=self.show_about),
                ft.Container(expand=True),
                ft.IconButton(icon=ft.Icons.CLEANING_SERVICES, tooltip=t("clear_done"), on_click=self.clear_finished),
                ft.OutlinedButton(text=t("open_folder"), on_click=self.open_folder),
                self.f_lang,
            ])

            downloads = ft.Column(expand=True, spacing=8, controls=[
                ft.Container(height=2), top, quick, self.warn,
                ft.Container(content=self.queue, expand=3),
                log_box, footer])

            # ---- settings page (Column with scroll, like ClipboardTimeTravel's settings tab)
            self.f_outdir = ft.TextField(label=t("outdir"), value=s.get("outdir") or core.default_outdir(),
                                         expand=True, dense=True, text_size=13, on_change=self._changed)
            self.f_filename = ft.TextField(label=t("filename"), value=s.get("filename", ""), expand=True, dense=True,
                                           text_size=13, on_change=self._changed)
            self.c_thumb = ft.Checkbox(label=t("thumb"), value=s.get("thumb", True), on_change=self._changed)
            self.c_meta = ft.Checkbox(label=t("meta"), value=s.get("meta", True), on_change=self._changed)
            self.c_subs = ft.Checkbox(label=t("subs"), value=s.get("subs", False), on_change=self._changed,
                                      disabled=ext in core.AUDIO_FORMATS)
            self.c_playlist = ft.Checkbox(label=t("playlist"), value=s.get("playlist", False), on_change=self._changed)
            self.f_browser = ft.Dropdown(
                label=t("browser_cookie"), value=s.get("browser") or "none", width=240, dense=True,
                on_change=self._on_browser,
                options=[ft.dropdown.Option("none", t("browser_none"))] +
                        [ft.dropdown.Option(b, b.capitalize()) for b in core.BROWSERS])
            self.f_profile = ft.TextField(label=t("profile"), value=s.get("profile", ""), width=240, dense=True,
                                          text_size=13, on_change=self._changed, disabled=not s.get("browser"))
            self.cookies_lbl = ft.Text("", size=12, color=ft.Colors.GREY_400)
            self.btn_cookies = ft.OutlinedButton(
                text=t("cookies_file"), icon=ft.Icons.FILE_OPEN, disabled=bool(s.get("browser")),
                on_click=lambda e: self.fp_cookies.pick_files(dialog_title=t("cookies_file")))
            self._refresh_cookies_label()
            self.c_wait = ft.Checkbox(label=t("live_wait"), value=s.get("live_wait", True), on_change=self._changed)
            self.c_start = ft.Checkbox(label=t("live_from_start"), value=s.get("live_from_start", False),
                                       on_change=self._changed)
            self.f_interval = ft.TextField(label=t("live_interval"), value=str(s.get("interval", 15)), width=140,
                                           dense=True, text_size=13, on_change=self._changed,
                                           input_filter=ft.NumbersOnlyInputFilter())
            self.f_conc = ft.Dropdown(label=t("concurrent"), value=str(self.mgr.max_concurrent), width=200,
                                      dense=True, on_change=self._on_conc,
                                      options=[ft.dropdown.Option(str(i)) for i in range(1, 7)])
            h = lambda key: ft.Text(t(key), weight=ft.FontWeight.BOLD, size=14)
            settings = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=12, controls=[
                ft.Container(height=2),
                ft.Row(controls=[
                    self.f_outdir,
                    ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip=t("browse"),
                                  on_click=lambda e: self.fp_dir.get_directory_path(dialog_title=t("pick_folder"))),
                ]),
                ft.Row(controls=[self.f_filename]),
                ft.Row(controls=[self.c_thumb, self.c_meta]),
                ft.Row(controls=[self.c_subs, self.c_playlist]),
                ft.Divider(),
                h("browser_cookie"),
                ft.Row(controls=[self.f_browser, self.f_profile]),
                ft.Row(controls=[self.btn_cookies, self.cookies_lbl,
                                 ft.TextButton(text=t("clear"), on_click=self._clear_cookies)]),
                ft.Divider(),
                h("live"),
                ft.Row(controls=[self.c_wait]),
                ft.Row(controls=[self.c_start]),
                ft.Row(controls=[self.f_interval]),
                ft.Divider(),
                ft.Row(controls=[self.f_conc]),
                ft.Row(controls=[ft.OutlinedButton(text=t("quit_app"), icon=ft.Icons.POWER_SETTINGS_NEW,
                                                   on_click=self._quit_clicked)]),
            ])

            tabs = ft.Tabs(expand=True, selected_index=self.tab_index, animation_duration=150, on_change=self._tab,
                           tabs=[ft.Tab(text=t("tab_downloads"), content=downloads),
                                 ft.Tab(text=t("tab_settings"), content=settings)])
            p.controls.clear()
            p.add(tabs)
            p.update()
            self.ready = True
        self.sync(force=True)

    @staticmethod
    def _quality_label(q: str) -> str:
        if q == "best":
            return t("best")
        return {"2160": "4K (2160p)", "1440": "2K (1440p)"}.get(q, f"{q}p")

    def _tab(self, e):
        self.tab_index = e.control.selected_index

    # ------------------------------------------------------ small handlers
    def _on_ext(self, e):
        audio = self.f_ext.value in core.AUDIO_FORMATS
        self.f_quality.disabled = audio
        self.f_aq.disabled = not audio
        self.c_subs.disabled = audio
        self.page.update()
        self._changed()

    def _on_browser(self, e):
        has = self.f_browser.value != "none"
        self.f_profile.disabled = not has
        self.btn_cookies.disabled = has
        self.page.update()
        self._changed()

    def _on_conc(self, e):
        self._changed()

    def _on_lang(self, e):
        self.save()
        i18n.set_lang(self.f_lang.value)
        self.mgr.set_settings({"lang": i18n.LANG})
        self.render()

    def _changed(self, e=None):
        """Save settings shortly after the last change."""
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.6, self.save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def collect(self) -> dict:
        try:
            interval = max(5, min(600, int(self.f_interval.value)))
        except (TypeError, ValueError):
            interval = 15
        return {
            "lang": i18n.LANG,
            "outdir": (self.f_outdir.value or "").strip(),
            "ext": self.f_ext.value, "quality": self.f_quality.value, "audio_quality": self.f_aq.value,
            "filename": (self.f_filename.value or "").strip(),
            "thumb": bool(self.c_thumb.value), "meta": bool(self.c_meta.value),
            "subs": bool(self.c_subs.value), "playlist": bool(self.c_playlist.value),
            "browser": "" if self.f_browser.value == "none" else self.f_browser.value,
            "profile": (self.f_profile.value or "").strip(),
            "live_wait": bool(self.c_wait.value), "live_from_start": bool(self.c_start.value),
            "interval": interval, "concurrent": int(self.f_conc.value or 3), "kind": self.f_kind.value,
        }

    def save(self):
        try:
            self.mgr.set_settings(self.collect())
        except Exception:
            pass

    def snack(self, text: str):
        try:
            self.page.open(ft.SnackBar(ft.Text(text)))
        except Exception:
            pass

    def copy_text(self, text: str):
        self.page.set_clipboard(text)
        self.snack(t("copied"))

    def dialog(self, title: str, content, actions: list) -> ft.AlertDialog:
        dlg = ft.AlertDialog(modal=True, title=ft.Text(title), content=content, actions=actions)
        self.page.open(dlg)
        return dlg

    def _refresh_cookies_label(self):
        name = os.path.basename(self.mgr.cookies_file())
        self.cookies_lbl.value = name or t("cookies_none")

    # ------------------------------------------------------ file pickers
    def _on_dir(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.f_outdir.value = e.path
            self.page.update()
            self._changed()

    def _on_cookies(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        try:
            text = Path(e.files[0].path).read_text(encoding="utf-8", errors="replace")
            self.mgr.save_cookies(text)
            self._refresh_cookies_label()
            self.page.update()
            self.snack(t("cookies_saved"))
        except OSError as ex:
            self.snack(str(ex))

    def _on_save(self, e: ft.FilePickerResultEvent):
        if e.path:
            path = e.path if Path(e.path).suffix else e.path + ".txt"
            try:
                Path(path).write_text(self._pending_save + "\n", encoding="utf-8")
            except OSError as ex:
                self.snack(str(ex))

    def _clear_cookies(self, e=None):
        self.mgr.clear_cookies()
        self.f_browser.value = "none"
        self.f_profile.disabled = True
        self.btn_cookies.disabled = False
        self._refresh_cookies_label()
        self.page.update()
        self._changed()

    # ================================================================ actions
    def parse_urls(self) -> list:
        seen, out = set(), []
        for u in re.split(r"\s+", (self.f_url.value or "").strip()):
            if re.fullmatch(r"https?://\S+", u, re.I) and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def add_clicked(self, e=None):
        urls = self.parse_urls()
        if not urls:
            if (self.f_url.value or "").strip():
                self.snack(t("no_url"))
            return
        self.save()
        n = self.mgr.add_urls(urls, self.collect())
        self.f_url.value = ""
        self.page.update()
        self.snack(t("added", n=n))
        self.sync()

    def get_urls_clicked(self, e=None):
        urls = self.parse_urls()
        if not urls:
            self.snack(t("no_url"))
            return
        if not core.locate_ytdlp():
            self.ask_install()
            return
        self.save()
        form, kind = self.collect(), self.f_kind.value
        items = [(self.mgr.build_job(u, form), "page" if kind == "page" else "stream") for u in urls]
        btn = self.btn_get
        btn.disabled, btn.text = True, t("fetching")
        self.page.update()

        def work():
            try:
                text, err = core.fetch_urls(items), None
            except Exception as ex:
                text, err = None, str(ex)
            btn.disabled, btn.text = False, t("get_urls")
            self.page.update()
            if err:
                self.snack(err)
            else:
                self.show_result(text)

        threading.Thread(target=work, daemon=True).start()

    def show_result(self, text: str):
        field = ft.TextField(value=text, multiline=True, read_only=True, min_lines=10, max_lines=16, width=760,
                             text_size=12)
        holder = {}

        def save(e):
            self._pending_save = field.value
            self.fp_save.save_file(dialog_title=t("save"), file_name="urls.txt")

        holder["dlg"] = self.dialog(t("result_title"), field, [
            ft.TextButton(text=t("copy"), on_click=lambda e: self.copy_text(field.value)),
            ft.TextButton(text=t("save"), on_click=save),
            ft.FilledButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"])),
        ])

    def update_clicked(self, e=None):
        self.mgr.trigger_update()
        self.sync()

    def clear_finished(self, e=None):
        self.mgr.clear_finished()
        self.sync()

    def open_folder(self, e=None):
        p = (self.f_outdir.value or "").strip()
        if p and os.path.isdir(p):
            core.open_path(p)

    def show_usage(self, e=None):
        holder = {}
        holder["dlg"] = self.dialog(t("usage_title"), ft.Container(width=620, content=ft.Column(
            scroll=ft.ScrollMode.AUTO, height=360, controls=[ft.Text(t("usage_text"), size=13, selectable=True)])),
            [ft.FilledButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def show_about(self, e=None):
        holder = {}
        holder["dlg"] = self.dialog(t("about"), ft.Text(t("about_text", v=__version__, url=core.REPO_URL),
                                                         selectable=True),
                                    [ft.FilledButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def ask_install(self):
        holder = {}

        def yes(e):
            self.page.close(holder["dlg"])
            self.update_clicked()

        holder["dlg"] = self.dialog(t("ask_install_title"), ft.Text(t("ask_install_msg")), [
            ft.TextButton(text=t("no"), on_click=lambda e: self.page.close(holder["dlg"])),
            ft.FilledButton(text=t("yes"), on_click=yes)])

    # ---- per-task actions (buttons on the card and the right-click menu)
    def select(self, tid: int):
        self.selected = tid
        self.log_shown, self.log_for = None, None
        self.sync(force=True)

    def show_log(self, tid: int):
        text = self.mgr.full_log(tid) or t("log_empty")
        field = ft.TextField(value=text, multiline=True, read_only=True, min_lines=16, max_lines=16, width=820,
                             text_size=11, text_style=ft.TextStyle(font_family=MONO))
        holder = {}
        holder["dlg"] = self.dialog(t("log_title", n=tid), field, [
            ft.TextButton(text=t("copy"), on_click=lambda e: self.copy_text(field.value)),
            ft.FilledButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def task_menu(self, tid: int):
        """Right-click menu of a task (original: 'Delete Task')."""
        td = next((x for x in self.mgr.snapshot()["tasks"] if x["id"] == tid), None)
        if td is None:
            return
        holder = {}

        def act(fn):
            def run(e):
                self.page.close(holder["dlg"])
                fn()
                self.sync()
            return run

        final = td["status"] in core.FINAL
        items = []
        if not final:
            items.append(ft.TextButton(text=t("stop"), icon=ft.Icons.STOP_CIRCLE_OUTLINED,
                                       on_click=act(lambda: self.mgr.stop(tid))))
        elif td["kind"] == "download":
            items.append(ft.TextButton(text=t("retry"), icon=ft.Icons.REPLAY, on_click=act(lambda: self.mgr.retry(tid))))
        if td["kind"] == "download":
            items.append(ft.TextButton(text=t("copy_url"), icon=ft.Icons.CONTENT_COPY,
                                       on_click=act(lambda: self.copy_text(td["url"]))))
            items.append(ft.TextButton(text=t("open_folder"), icon=ft.Icons.FOLDER_OPEN,
                                       on_click=act(lambda: core.open_path(td["outdir"]) if os.path.isdir(td["outdir"]) else None)))
        items.append(ft.TextButton(text=t("show_log"), icon=ft.Icons.ARTICLE_OUTLINED,
                                   on_click=act(lambda: self.show_log(tid))))
        items.append(ft.TextButton(text=t("delete"), icon=ft.Icons.DELETE_OUTLINE, on_click=act(lambda: self._delete(tid))))
        holder["dlg"] = self.dialog(t("ctx_title", n=tid), ft.Column(tight=True, spacing=0, controls=items), [
            ft.TextButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def _delete(self, tid: int):
        self.mgr.delete(tid)
        if self.selected == tid:
            self.selected = None
            self.log_shown, self.log_for = None, None

    # ================================================================ queue view
    def make_card(self, td: dict) -> SimpleNamespace:
        tid = td["id"]
        c = SimpleNamespace(key=None, sel=None)
        c.title = ft.Text("", size=13, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                          expand=True)
        c.chip_text = ft.Text("", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        c.chip = ft.Container(content=c.chip_text, padding=ft.padding.symmetric(horizontal=10, vertical=2),
                              border_radius=12)
        c.bar = ft.ProgressBar(value=0, bar_height=6)
        c.info = ft.Text("", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1,
                         overflow=ft.TextOverflow.ELLIPSIS)

        def ib(icon, tip, fn):
            return ft.IconButton(icon=icon, icon_size=18, tooltip=tip, on_click=fn)

        c.stop = ib(ft.Icons.STOP_CIRCLE_OUTLINED, t("stop"), lambda e: (self.mgr.stop(tid), self.sync()))
        c.retry = ib(ft.Icons.REPLAY, t("retry"), lambda e: (self.mgr.retry(tid), self.sync()))
        c.log = ib(ft.Icons.ARTICLE_OUTLINED, t("show_log"), lambda e: self.show_log(tid))
        c.open = ib(ft.Icons.FOLDER_OPEN, t("open_folder"),
                    lambda e: core.open_path(td["outdir"]) if os.path.isdir(td["outdir"]) else None)
        c.delete = ib(ft.Icons.DELETE_OUTLINE, t("delete"), lambda e: (self._delete(tid), self.sync()))
        if td["kind"] == "update":
            c.open.visible = False
        c.inner = ft.Container(
            padding=10, border_radius=10, bgcolor=ft.Colors.with_opacity(0.07, ft.Colors.ON_SURFACE),
            border=ft.border.all(1, ft.Colors.TRANSPARENT),
            content=ft.Column(spacing=4, controls=[
                ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Text(f"#{tid}", size=12, color=ft.Colors.GREY_500), c.title, c.chip]),
                c.bar,
                ft.Row(spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                       controls=[c.info, c.stop, c.retry, c.log, c.open, c.delete])]))
        c.root = ft.GestureDetector(content=c.inner, on_tap=lambda e: self.select(tid),
                                    on_secondary_tap=lambda e: self.task_menu(tid))
        return c

    def update_card(self, c: SimpleNamespace, td: dict) -> bool:
        key = (td["status"], td["msg"], td["pct"], td["indeterminate"], i18n.LANG, td["id"] == self.selected)
        if c.key == key:
            return False
        c.key = key
        st = td["status"]
        final = st in core.FINAL
        c.title.value = "yt-dlp / ffmpeg" if td["kind"] == "update" else td["url"]
        c.chip_text.value = t("status").get(st, st)
        c.chip.bgcolor = STATUS_COLORS.get(st, ft.Colors.GREY_700)
        if st == core.FINISHED:
            c.bar.value = 1
        elif st in (core.PENDING, core.ERROR, core.CANCELLED):
            c.bar.value = 0
        elif st in (core.WAITING, core.LIVE) or td["indeterminate"]:
            c.bar.value = None
        else:
            c.bar.value = max(0.0, min(1.0, td["pct"] / 100))
        c.info.value = td["msg"] or ""
        c.info.color = ft.Colors.RED_300 if st == core.ERROR else ft.Colors.GREY_400
        c.stop.visible = not final
        c.retry.visible = final and td["kind"] == "download"
        c.inner.border = ft.border.all(1, ft.Colors.INDIGO_300 if td["id"] == self.selected else ft.Colors.TRANSPARENT)
        return True

    def sync(self, force: bool = False) -> None:
        """Bring the view in line with the manager state (called every 0.5 s and after actions)."""
        if not self.ready:
            return
        with self.ui_lock:
            snap = self.mgr.snapshot(self.selected)
            changed = force
            tasks = snap["tasks"]
            ids = [x["id"] for x in tasks]
            for tid in [i for i in self.cards if i not in ids]:
                del self.cards[tid]
                changed = True
            for td in tasks:
                if td["id"] not in self.cards:
                    self.cards[td["id"]] = self.make_card(td)
                    changed = True
            if ids != self.ids:
                self.queue.controls = [self.cards[i].root for i in ids] or [self.empty]
                self.ids = ids
                changed = True
            for td in tasks:
                changed |= self.update_card(self.cards[td["id"]], td)

            # log panel: append / replace only what changed (keeps the ListView cheap)
            lines = snap["log"][-200:]
            if self.selected is None or self.selected not in ids:
                lines = []
            if lines != self.log_shown:
                old = self.log_shown or []
                if self.log_shown is not None and lines and lines[:len(old)] == old:        # lines appended
                    self.log_list.controls += [self._log_text(x) for x in lines[len(old):]]
                elif self.log_shown is not None and len(lines) == len(old) and lines[:-1] == old[:-1] and lines:
                    self.log_list.controls[-1].value = lines[-1]                            # progress line
                else:
                    self.log_list.controls = [self._log_text(x) for x in lines] or [
                        ft.Text(t("log_empty"), size=12, color=ft.Colors.GREY_600)]
                self.log_shown = list(lines)
                self.log_label.value = t("log_title", n=self.selected) if lines or self.selected in ids else t("log_empty")
                changed = True

            w = snap["warnings"]
            msgs = ([t("warn_ytdlp")] if w.get("ytdlp") else []) + ([t("warn_ffmpeg")] if w.get("ffmpeg") else []) \
                + ([t("warn_js")] if w.get("js") else [])
            text = "\n".join("⚠ " + m for m in msgs)
            if text != self.warn_text.value:
                self.warn_text.value, self.warn.visible = text, bool(msgs)
                changed = True
            if changed:
                self.page.update()

    @staticmethod
    def _log_text(line: str) -> ft.Text:
        return ft.Text(line, size=11, font_family=MONO, selectable=True, color="#dcdcdc")

    def _loop(self):
        while True:
            time.sleep(0.5)
            try:
                self.sync()
            except Exception:
                pass

    # ================================================================ lifecycle
    def _on_finish(self, task):
        """Desktop notification when a task ends and the window is not in front (original: tray message)."""
        if task.job.kind == "update":
            return
        try:
            focused = bool(self.page.window.focused)
        except Exception:
            focused = False
        if focused:
            return
        if task.status == core.FINISHED:
            core.notify(t("notify_title"), t("notify_msg", n=task.id))
        elif task.status == core.ERROR:
            core.notify(t("notify_err_title"), t("notify_err_msg", n=task.id))

    def _startup(self):
        time.sleep(0.6)
        if not core.locate_ytdlp() and not self._asked_install:
            self._asked_install = True
            self.ask_install()
        self.mgr.check_release()
        rel = self.mgr.release
        if rel and rel["newer"]:
            holder = {}

            def go(e):
                self.page.close(holder["dlg"])
                self.page.launch_url(rel["url"])

            holder["dlg"] = self.dialog(t("update_avail_title"), ft.Text(t("update_avail_msg", v=rel["version"])), [
                ft.TextButton(text=t("later"), on_click=lambda e: self.page.close(holder["dlg"])),
                ft.FilledButton(text=t("open"), on_click=go)])

    def _on_window_event(self, e):
        if str(getattr(e, "data", "")) == "close" or getattr(e, "type", None) == ft.WindowEventType.CLOSE:
            self._quit_clicked()

    def _quit_clicked(self, e=None):
        if not self.mgr.any_active():
            threading.Thread(target=self._quit, daemon=True).start()
            return
        holder = {}

        def yes(ev):
            self.page.close(holder["dlg"])
            threading.Thread(target=self._quit, daemon=True).start()

        holder["dlg"] = self.dialog(t("confirm_quit_title"), ft.Text(t("confirm_quit_msg")), [
            ft.TextButton(text=t("cancel"), on_click=lambda ev: self.page.close(holder["dlg"])),
            ft.FilledButton(text=t("quit_app"), on_click=yes)])

    def _quit(self):
        self.save()
        self.mgr.stop_all(15)
        try:
            self.page.window.prevent_close = False
            self.page.window.destroy()
        finally:
            threading.Timer(2.0, lambda: os._exit(0)).start()  # make sure the process ends


def main(page: ft.Page):
    App(page)


if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
