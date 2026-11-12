import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import flet as ft

import core
import i18n
from app_version import __version__
from i18n import t

STATUS_COLORS = {
    core.PENDING: ft.Colors.GREY_700,
    core.RUNNING: ft.Colors.BLUE_700,
    core.WAITING: ft.Colors.PURPLE_600,
    core.LIVE: ft.Colors.RED_700,
    core.FINISHED: ft.Colors.GREEN_700,
    core.ERROR: ft.Colors.RED_600,
    core.CANCELLED: ft.Colors.BLUE_GREY_600,
}


# =============================================================================
# One queue entry: state + its card
# =============================================================================
class Task:
    def __init__(self, tid: int, job: core.Job):
        self.id = tid
        self.job = job
        self.status = core.PENDING
        self.msg = "Waiting..."
        self.pct = 0.0
        self.indeterminate = False
        self.log: list = []
        self.last_replace = False
        self.runner = None
        self.refs = None
        self._last_ui = 0.0

    @property
    def display_url(self) -> str:
        return "yt-dlp / ffmpeg" if self.job.kind == "update" else self.job.url

    def build(self, app: "App") -> ft.Control:
        """(Re)create the card controls from the current state."""
        r = SimpleNamespace()
        r.title = ft.Text(self.display_url, size=13, weight=ft.FontWeight.BOLD, max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip=self.display_url)
        r.chip_text = ft.Text("", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        r.chip = ft.Container(content=r.chip_text, padding=ft.padding.symmetric(horizontal=10, vertical=3),
                              border_radius=12)
        r.bar = ft.ProgressBar(value=0, bar_height=6)
        r.info = ft.Text("", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1,
                         overflow=ft.TextOverflow.ELLIPSIS)

        def btn(icon, tip_key, fn):
            return ft.IconButton(icon=icon, icon_size=18, tooltip=t(tip_key), on_click=fn)

        r.stop = btn(ft.Icons.STOP_CIRCLE_OUTLINED, "stop", lambda e: app.stop_task(self))
        r.retry = btn(ft.Icons.REPLAY, "retry", lambda e: app.retry_task(self))
        r.log_btn = btn(ft.Icons.ARTICLE_OUTLINED, "show_log", lambda e: app.show_log(self))
        r.copy = btn(ft.Icons.CONTENT_COPY, "copy_url", lambda e: app.copy_text(self.job.url))
        r.open = btn(ft.Icons.FOLDER_OPEN, "open_file_folder", lambda e: core.open_path(self.job.outdir))
        r.delete = btn(ft.Icons.DELETE_OUTLINE, "delete", lambda e: app.delete_task(self))
        if self.job.kind == "update":
            r.copy.visible = r.open.visible = False
        r.card = ft.Container(
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row([ft.Text(f"#{self.id}", size=12, color=ft.Colors.GREY_500), r.title, r.chip],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    r.bar,
                    ft.Row([r.info, r.stop, r.retry, r.log_btn, r.copy, r.open, r.delete],
                           spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ],
            ),
            padding=12,
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.07, ft.Colors.ON_SURFACE),
            border=ft.border.all(1, ft.Colors.TRANSPARENT),
            on_click=lambda e: app.select_task(self),
        )
        self.refs = r
        self.refresh(force=True, push=False)
        return r.card

    def refresh(self, force: bool = False, push: bool = True) -> None:
        r = self.refs
        if r is None:
            return
        now = time.time()
        if not force and now - self._last_ui < 0.25:  # throttle progress updates
            return
        self._last_ui = now
        st = self.status
        r.chip_text.value = t("status").get(st, st)
        r.chip.bgcolor = STATUS_COLORS.get(st, ft.Colors.GREY_700)
        if st == core.FINISHED:
            r.bar.value = 1
        elif st in (core.PENDING, core.ERROR, core.CANCELLED):
            r.bar.value = 0
        elif st in (core.WAITING, core.LIVE) or self.indeterminate:
            r.bar.value = None  # indeterminate
        else:
            r.bar.value = max(0.0, min(1.0, self.pct / 100))
        r.info.value = self.msg
        r.info.color = ft.Colors.RED_300 if st == core.ERROR else ft.Colors.GREY_400
        r.stop.visible = st not in core.FINAL
        r.retry.visible = st in core.FINAL and self.job.kind == "download"
        if push:
            try:
                r.card.update()
            except Exception:
                pass


# =============================================================================
# Application
# =============================================================================
class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.s = core.load_settings()
        i18n.set_lang(self.s.get("lang") or core.system_lang())
        self.tasks: dict = {}
        self.order: list = []
        self.queue = deque()
        self.active: dict = {}
        self.waiting_ids: set = set()
        self.counter = 0
        self.lock = threading.RLock()
        self.selected = None
        self.cookies_file = self.s.get("cookies_file", "") if os.path.exists(self.s.get("cookies_file", "")) else ""
        self.max_concurrent = int(self.s.get("concurrent", 3))
        self._log_ui = 0.0
        self._pending_save = ""

        self.fp_dir = ft.FilePicker(on_result=self._on_dir)
        self.fp_cookies = ft.FilePicker(on_result=self._on_cookies)
        self.fp_save = ft.FilePicker(on_result=self._on_save)
        page.overlay.extend([self.fp_dir, self.fp_cookies, self.fp_save])

        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.padding = 16
        page.window.width = 1100
        page.window.height = 860
        page.window.min_width = 820
        page.window.min_height = 620
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event

        self.render()
        threading.Thread(target=self._startup, daemon=True).start()

    # ------------------------------------------------------------------ UI
    def render(self) -> None:
        s = self.s
        p = self.page
        p.title = t("title")

        # --- top: URL box + buttons
        self.f_url = ft.TextField(hint_text=t("urls_hint"), multiline=True, min_lines=3, max_lines=5,
                                  expand=True, text_size=13)
        self.btn_add = ft.FilledButton(text=t("add"), icon=ft.Icons.DOWNLOAD, on_click=self.add_clicked, height=44)
        self.f_kind = ft.Dropdown(
            value=s.get("kind", "stream"), dense=True, width=300,
            options=[ft.dropdown.Option("stream", t("kind_stream")), ft.dropdown.Option("page", t("kind_page"))])
        self.btn_get = ft.OutlinedButton(text=t("get_urls"), icon=ft.Icons.LINK, on_click=self.get_urls_clicked)
        top = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[self.f_url, ft.Column(spacing=6, controls=[self.btn_add, self.btn_get, self.f_kind])])

        # --- settings
        self.f_outdir = ft.TextField(label=t("outdir"), value=s.get("outdir") or core.default_outdir(),
                                     expand=True, dense=True, text_size=13)
        row_dir = ft.Row(controls=[
            self.f_outdir,
            ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip=t("browse"),
                          on_click=lambda e: self.fp_dir.get_directory_path(dialog_title=t("outdir"))),
            ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip=t("open_folder"),
                          on_click=lambda e: core.open_path(self.f_outdir.value)),
        ])
        ext = s.get("ext", "mp4")
        self.f_ext = ft.Dropdown(label=t("format"), value=ext, dense=True, width=120, on_change=self._on_ext,
                                 options=[ft.dropdown.Option(x) for x in core.VIDEO_FORMATS + core.AUDIO_FORMATS])
        self.f_quality = ft.Dropdown(
            label=t("quality"), value=s.get("quality", "best"), dense=True, width=150,
            disabled=ext in core.AUDIO_FORMATS,
            options=[ft.dropdown.Option(q, self._quality_label(q)) for q in core.QUALITIES])
        self.f_aq = ft.Dropdown(label=t("audio_quality"), value=s.get("audio_quality", "128kbps"), dense=True,
                                width=150, disabled=ext not in core.AUDIO_FORMATS,
                                options=[ft.dropdown.Option(x) for x in core.AUDIO_QUALITIES])
        self.f_filename = ft.TextField(label=t("filename"), value=s.get("filename", ""), dense=True,
                                       expand=True, text_size=13)
        row_fmt = ft.Row(wrap=True, run_spacing=8, controls=[self.f_ext, self.f_quality, self.f_aq, self.f_filename])

        self.c_thumb = ft.Checkbox(label=t("thumb"), value=s.get("thumb", True))
        self.c_meta = ft.Checkbox(label=t("meta"), value=s.get("meta", True))
        self.c_subs = ft.Checkbox(label=t("subs"), value=s.get("subs", False))
        self.c_playlist = ft.Checkbox(label=t("playlist"), value=s.get("playlist", False))
        row_chk = ft.Row(wrap=True, controls=[self.c_thumb, self.c_meta, self.c_subs, self.c_playlist])

        self.f_browser = ft.Dropdown(
            label=t("browser_cookie"), value=s.get("browser") or "none", dense=True, width=210,
            options=[ft.dropdown.Option("none", t("browser_none"))] +
                    [ft.dropdown.Option(b, b.capitalize()) for b in core.BROWSERS])
        self.f_profile = ft.TextField(label=t("profile"), value=s.get("profile", ""), dense=True, width=210,
                                      text_size=13)
        self.cookies_lbl = ft.Text("", size=12, color=ft.Colors.GREY_400)
        self._refresh_cookies_label()
        row_cookie = ft.Row(wrap=True, run_spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self.f_browser, self.f_profile,
            ft.OutlinedButton(text=t("cookies_file"), icon=ft.Icons.FILE_OPEN,
                              on_click=lambda e: self.fp_cookies.pick_files(dialog_title=t("cookies_file"))),
            self.cookies_lbl,
            ft.TextButton(text=t("clear"), on_click=self._clear_cookies),
        ])

        self.c_wait = ft.Checkbox(label=t("live_wait"), value=s.get("live_wait", True))
        self.c_start = ft.Checkbox(label=t("live_from_start"), value=s.get("live_from_start", False))
        self.f_interval = ft.TextField(label=t("live_interval"), value=str(s.get("interval", 15)), dense=True,
                                       width=120, text_size=13, input_filter=ft.NumbersOnlyInputFilter())
        row_live = ft.Row(wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                          controls=[ft.Text(t("live"), weight=ft.FontWeight.BOLD, size=13), self.c_wait,
                                    self.c_start, self.f_interval])

        settings = ft.Card(content=ft.ExpansionTile(
            title=ft.Text(t("settings"), weight=ft.FontWeight.BOLD),
            initially_expanded=True, maintain_state=True,
            controls=[ft.Container(padding=ft.padding.only(left=12, right=12, bottom=12), content=ft.Column(
                spacing=10, controls=[row_dir, row_fmt, row_chk, row_cookie, row_live]))]))

        # --- warnings / queue / log
        self.warn_text = ft.Text("", size=12, color=ft.Colors.ORANGE_300)
        self.warn = ft.Container(content=self.warn_text, visible=False, padding=10, border_radius=8,
                                 bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ORANGE))
        self.listview = ft.ListView(expand=True, spacing=8, padding=ft.padding.only(top=4, bottom=4))
        for tid in self.order:
            self.listview.controls.append(self.tasks[tid].build(self))
        mono = "Consolas" if core.IS_WIN else "monospace"
        self.log_view = ft.TextField(value=t("log_empty"), multiline=True, read_only=True, min_lines=7,
                                     max_lines=7, text_size=11, text_style=ft.TextStyle(font_family=mono))
        log_tile = ft.Card(content=ft.ExpansionTile(
            title=ft.Text(t("log"), weight=ft.FontWeight.BOLD), maintain_state=True,
            controls=[ft.Container(content=self.log_view, padding=ft.padding.only(left=12, right=12, bottom=12))]))

        # --- footer
        self.f_conc = ft.Dropdown(label=t("concurrent"), value=str(self.max_concurrent), dense=True, width=110,
                                  on_change=self._on_conc, options=[ft.dropdown.Option(str(i)) for i in range(1, 7)])
        self.f_lang = ft.Dropdown(label=t("language"), value=i18n.LANG, dense=True, width=130,
                                  on_change=self._on_lang,
                                  options=[ft.dropdown.Option("en", "English"), ft.dropdown.Option("ja", "日本語")])
        footer = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.ElevatedButton(text=t("update_tools"), icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=self.trigger_update,
                              style=ft.ButtonStyle(bgcolor=ft.Colors.ORANGE_800, color=ft.Colors.WHITE)),
            ft.TextButton(text=t("usage"), icon=ft.Icons.HELP_OUTLINE, on_click=self.show_usage),
            ft.TextButton(text=t("about"), icon=ft.Icons.INFO_OUTLINE, on_click=self.show_about),
            ft.Container(expand=True),
            self.f_conc,
            ft.OutlinedButton(text=t("clear_done"), icon=ft.Icons.CLEANING_SERVICES, on_click=self.clear_finished),
            self.f_lang,
        ])

        p.controls.clear()
        p.add(ft.Column(expand=True, spacing=10, controls=[top, settings, self.warn, self.listview, log_tile, footer]))
        p.update()
        self.refresh_warnings()

    @staticmethod
    def _quality_label(q: str) -> str:
        if q == "best":
            return t("best")
        return {"2160": "4K (2160p)", "1440": "2K (1440p)"}.get(q, f"{q}p")

    # ---- small UI handlers
    def _on_ext(self, e):
        audio = self.f_ext.value in core.AUDIO_FORMATS
        self.f_quality.disabled = audio
        self.f_aq.disabled = not audio
        self.c_subs.disabled = audio
        self.page.update()

    def _on_conc(self, e):
        self.max_concurrent = int(self.f_conc.value)
        self.process_queue()

    def _on_lang(self, e):
        self.save_form()
        i18n.set_lang(self.f_lang.value)
        self.s["lang"] = i18n.LANG
        core.save_settings(self.s)
        self.render()

    def _on_dir(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.f_outdir.value = e.path
            self.page.update()

    def _on_cookies(self, e: ft.FilePickerResultEvent):
        if e.files:
            self.cookies_file = e.files[0].path
            self._refresh_cookies_label()
            self.page.update()

    def _on_save(self, e: ft.FilePickerResultEvent):
        if e.path:
            path = e.path if Path(e.path).suffix else e.path + ".txt"
            try:
                Path(path).write_text(self._pending_save + "\n", encoding="utf-8")
            except OSError as ex:
                self.snack(str(ex))

    def _clear_cookies(self, e=None):
        self.cookies_file = ""
        self.f_browser.value = "none"
        self._refresh_cookies_label()
        self.page.update()

    def _refresh_cookies_label(self):
        self.cookies_lbl.value = os.path.basename(self.cookies_file) if self.cookies_file else t("cookies_none")

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

    def refresh_warnings(self):
        msgs = []
        if not core.locate_ytdlp():
            msgs.append(t("warn_ytdlp"))
        if not core.locate_ffmpeg():
            msgs.append(t("warn_ffmpeg"))
        if not core.find_js_runtime():
            msgs.append(t("warn_js"))
        self.warn_text.value = "\n".join("⚠ " + m for m in msgs)
        self.warn.visible = bool(msgs)
        try:
            self.page.update()
        except Exception:
            pass

    # ------------------------------------------------------------ settings
    def collect(self) -> dict:
        return {
            "lang": i18n.LANG,
            "outdir": self.f_outdir.value.strip(),
            "ext": self.f_ext.value,
            "quality": self.f_quality.value,
            "audio_quality": self.f_aq.value,
            "filename": self.f_filename.value.strip(),
            "thumb": self.c_thumb.value,
            "meta": self.c_meta.value,
            "subs": self.c_subs.value,
            "playlist": self.c_playlist.value,
            "browser": "" if self.f_browser.value == "none" else self.f_browser.value,
            "profile": self.f_profile.value.strip(),
            "cookies_file": self.cookies_file,
            "live_wait": self.c_wait.value,
            "live_from_start": self.c_start.value,
            "interval": self._interval(),
            "concurrent": self.max_concurrent,
            "kind": self.f_kind.value,
        }

    def save_form(self):
        self.s.update(self.collect())
        core.save_settings(self.s)

    def _interval(self) -> int:
        try:
            return max(5, min(600, int(self.f_interval.value)))
        except (TypeError, ValueError):
            return 15

    def make_job(self, url: str) -> core.Job:
        c = self.collect()
        return core.Job(
            url=url, outdir=c["outdir"] or core.default_outdir(), filename=c["filename"], ext=c["ext"],
            quality=c["quality"], audio_quality=c["audio_quality"], embed_thumbnail=c["thumb"],
            embed_metadata=c["meta"], subs=c["subs"] and c["ext"] not in core.AUDIO_FORMATS,
            playlist=c["playlist"], cookies_file=c["cookies_file"], cookies_browser=c["browser"],
            browser_profile=c["profile"], live_wait=c["live_wait"], live_from_start=c["live_from_start"],
            wait_interval=c["interval"])

    def parse_urls(self) -> list:
        urls = []
        for u in re.split(r"\s+", (self.f_url.value or "").strip()):
            if re.match(r"https?://", u, re.I) and u not in urls:
                urls.append(u)
        return urls

    # ------------------------------------------------------------- actions
    def add_clicked(self, e=None):
        urls = self.parse_urls()
        if not urls:
            self.snack(t("no_url"))
            return
        self.save_form()
        for u in urls:
            job = self.make_job(u)
            try:
                os.makedirs(job.outdir, exist_ok=True)
            except OSError:
                pass
            self.add_task(job)
        self.f_url.value = ""
        self.page.update()

    def add_task(self, job: core.Job, front: bool = False) -> Task:
        with self.lock:
            self.counter += 1
            task = Task(self.counter, job)
            self.tasks[task.id] = task
            if front:
                self.order.insert(0, task.id)
                self.queue.appendleft(task.id)
            else:
                self.order.append(task.id)
                self.queue.append(task.id)
        card = task.build(self)
        if front:
            self.listview.controls.insert(0, card)
        else:
            self.listview.controls.append(card)
        self.page.update()
        self.process_queue()
        return task

    def trigger_update(self, e=None):
        with self.lock:
            for tk in self.tasks.values():
                if tk.job.kind == "update" and tk.status not in core.FINAL:
                    return
        t_ = self.add_task(core.Job(kind="update", outdir=self.f_outdir.value), front=True)
        t_.msg = "Priority Update"
        t_.refresh(force=True)

    def get_urls_clicked(self, e=None):
        urls = self.parse_urls()
        if not urls:
            self.snack(t("no_url"))
            return
        if not core.locate_ytdlp():
            self.ask_install()
            return
        self.save_form()
        items = [(self.make_job(u), self.f_kind.value) for u in urls]
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
        field = ft.TextField(value=text, multiline=True, read_only=True, min_lines=10, max_lines=18, width=760,
                             text_size=12)
        holder = {}

        def close(e=None):
            self.page.close(holder["dlg"])

        def save(e=None):
            self._pending_save = field.value
            self.fp_save.save_file(dialog_title=t("save"), file_name="urls.txt")

        holder["dlg"] = self.dialog(t("result_title"), field, [
            ft.TextButton(text=t("copy"), icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.copy_text(field.value)),
            ft.TextButton(text=t("save"), icon=ft.Icons.SAVE_ALT, on_click=save),
            ft.TextButton(text=t("close"), on_click=close),
        ])

    def show_log(self, task: Task):
        field = ft.TextField(value="\n".join(task.log[-2000:]) or t("log_empty"), multiline=True, read_only=True,
                             min_lines=18, max_lines=18, width=820, text_size=11,
                             text_style=ft.TextStyle(font_family="Consolas" if core.IS_WIN else "monospace"))
        holder = {}
        holder["dlg"] = self.dialog(f"#{task.id}", field, [
            ft.TextButton(text=t("copy"), icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.copy_text(field.value)),
            ft.TextButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"])),
        ])

    def show_usage(self, e=None):
        holder = {}
        holder["dlg"] = self.dialog(t("usage"), ft.Container(width=640, content=ft.Column(
            scroll=ft.ScrollMode.AUTO, height=420, controls=[ft.Text(t("usage_text"), size=13, selectable=True)])),
            [ft.TextButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def show_about(self, e=None):
        holder = {}
        holder["dlg"] = self.dialog(t("about"), ft.Text(t("about_text", v=__version__, url=core.REPO_URL),
                                                         selectable=True),
                                    [ft.TextButton(text=t("close"), on_click=lambda e: self.page.close(holder["dlg"]))])

    def ask_install(self):
        holder = {}

        def yes(e):
            self.page.close(holder["dlg"])
            self.trigger_update()

        holder["dlg"] = self.dialog(t("ask_install_title"), ft.Text(t("ask_install_msg")), [
            ft.TextButton(text=t("no"), on_click=lambda e: self.page.close(holder["dlg"])),
            ft.FilledButton(text=t("yes"), on_click=yes),
        ])

    # --------------------------------------------------------------- queue
    def process_queue(self):
        with self.lock:
            while self.queue:
                task = self.tasks.get(self.queue[0])
                if task is None:
                    self.queue.popleft()
                    continue
                busy = [i for i in self.active if i not in self.waiting_ids]
                updating = any(self.tasks[i].job.kind == "update" for i in self.active if i in self.tasks)
                if task.job.kind == "update":
                    if busy:
                        break  # let running downloads finish before replacing the binary
                elif updating or len(busy) >= self.max_concurrent:
                    break
                self.queue.popleft()
                self._start(task)

    def _start(self, task: Task):
        runner = core.Runner(
            task.job,
            on_status=lambda st, msg, pct: self.on_status(task, st, msg, pct),
            on_log=lambda line, rep: self.on_log(task, line, rep),
            on_done=lambda: self.on_done(task),
        )
        task.runner = runner
        self.active[task.id] = runner
        runner.start()

    def on_status(self, task: Task, status: str, msg: str, pct):
        with self.lock:
            changed_wait = (status == core.WAITING) != (task.id in self.waiting_ids)
            (self.waiting_ids.add if status == core.WAITING else self.waiting_ids.discard)(task.id)
            prev = task.status
            task.status, task.msg = status, msg
            task.indeterminate = pct is None
            if pct is not None:
                task.pct = pct
        task.refresh(force=status in core.FINAL or status != prev)
        if changed_wait:
            self.process_queue()  # a waiting stream does not occupy a download slot

    def on_log(self, task: Task, line: str, replace: bool):
        if replace and task.last_replace and task.log:
            task.log[-1] = line
        else:
            task.log.append(line)
        task.last_replace = replace
        if len(task.log) > 4000:
            del task.log[:1000]
        if self.selected == task.id:
            self._refresh_log(task)

    def on_done(self, task: Task):
        with self.lock:
            self.active.pop(task.id, None)
            self.waiting_ids.discard(task.id)
        if task.job.kind == "update":
            self.refresh_warnings()
        elif task.status == core.FINISHED:
            self.snack(t("task_done", n=task.id))
        elif task.status == core.ERROR:
            self.snack(t("task_failed", n=task.id))
        self.process_queue()

    def stop_task(self, task: Task):
        with self.lock:
            runner = self.active.get(task.id)
            queued = task.id in self.queue
            if queued:
                self.queue.remove(task.id)
        if runner is not None:
            runner.cancel()
        elif queued:
            task.status, task.msg = core.CANCELLED, ""
            task.refresh(force=True)

    def retry_task(self, task: Task):
        with self.lock:
            if task.id in self.active or task.id in self.queue:
                return
            task.status, task.msg, task.pct, task.indeterminate = core.PENDING, "Waiting...", 0.0, False
            task.log.append("----- retry -----")
            task.last_replace = False
            self.queue.append(task.id)
        task.refresh(force=True)
        self.process_queue()

    def delete_task(self, task: Task):
        self.stop_task(task)
        with self.lock:
            self.tasks.pop(task.id, None)
            if task.id in self.order:
                self.order.remove(task.id)
        if task.refs is not None and task.refs.card in self.listview.controls:
            self.listview.controls.remove(task.refs.card)
        if self.selected == task.id:
            self.selected = None
            self.log_view.value = t("log_empty")
        self.page.update()

    def clear_finished(self, e=None):
        for tk in list(self.tasks.values()):
            if tk.status in (core.FINISHED, core.CANCELLED) and tk.id not in self.active:
                self.delete_task(tk)

    def select_task(self, task: Task):
        self.selected = task.id
        for tk in self.tasks.values():
            if tk.refs is not None:
                tk.refs.card.border = ft.border.all(1, ft.Colors.INDIGO_300 if tk.id == task.id else ft.Colors.TRANSPARENT)
        self._refresh_log(task, force=True)
        self.page.update()

    def _refresh_log(self, task: Task, force: bool = False):
        now = time.time()
        if not force and now - self._log_ui < 0.4:
            return
        self._log_ui = now
        self.log_view.value = "\n".join(task.log[-12:]) or t("log_empty")  # tail; full log via the log button
        try:
            self.log_view.update()
        except Exception:
            pass

    # ------------------------------------------------------ start / quit
    def _startup(self):
        time.sleep(0.5)
        self.refresh_warnings()
        if not core.locate_ytdlp():
            self.ask_install()
        try:
            rel = core.latest_release()
        except Exception:
            rel = None
        if rel and rel["newer"]:
            holder = {}

            def go(e):
                self.page.close(holder["dlg"])
                self.page.launch_url(rel["url"])

            holder["dlg"] = self.dialog(t("update_avail_title"), ft.Text(t("update_avail_msg", v=rel["version"])), [
                ft.TextButton(text=t("later"), on_click=lambda e: self.page.close(holder["dlg"])),
                ft.FilledButton(text=t("open"), on_click=go),
            ])

    def _on_window_event(self, e):
        if str(getattr(e, "data", "")) == "close" or getattr(e, "type", None) == ft.WindowEventType.CLOSE:
            busy = [r for r in self.active.values() if r.is_alive()]
            if not busy:
                self.quit(busy)
                return
            holder = {}

            def yes(ev):
                self.page.close(holder["dlg"])
                threading.Thread(target=self.quit, args=(busy,), daemon=True).start()

            holder["dlg"] = self.dialog(t("confirm_exit_title"), ft.Text(t("confirm_exit_msg")), [
                ft.TextButton(text=t("cancel"), on_click=lambda ev: self.page.close(holder["dlg"])),
                ft.FilledButton(text=t("quit"), on_click=yes),
            ])

    def quit(self, busy: list):
        self.save_form()
        for r in busy:
            r.cancel()
        for r in busy:
            r.thread.join(timeout=15)
        self.page.window.destroy()


def main(page: ft.Page):
    App(page)


if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
