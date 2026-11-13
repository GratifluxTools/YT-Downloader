"""Queue manager: tasks, scheduling and settings. No UI / HTTP code here."""
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import core

URL_RE = re.compile(r"https?://\S+", re.I)

SETTING_KEYS = ("lang", "outdir", "ext", "quality", "audio_quality", "filename", "thumb", "meta", "subs",
                "playlist", "browser", "profile", "live_wait", "live_from_start", "interval", "concurrent",
                "kind", "settings_open")


class Task:
    def __init__(self, tid: int, job: core.Job):
        self.id = tid
        self.job = job
        self.status = core.PENDING
        self.msg = ""
        self.pct = 0.0
        self.indeterminate = False
        self.log: list = []
        self.last_replace = False
        self.runner: Optional[core.Runner] = None

    def to_dict(self) -> dict:
        j = self.job
        return {
            "id": self.id, "status": self.status, "msg": self.msg, "pct": round(self.pct, 1),
            "indeterminate": self.indeterminate, "kind": j.kind,
            "url": "" if j.kind == "update" else j.url, "outdir": j.outdir, "ext": j.ext,
        }


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.tasks: dict = {}
        self.order: list = []
        self.queue: deque = deque()
        self.active: dict = {}
        self.waiting: set = set()
        self.counter = 0
        self.settings = core.load_settings()
        self.settings.setdefault("lang", core.system_lang())
        self.release: Optional[dict] = None
        self._warn_cache = (0.0, {})
        self.on_finish = None          # callback(task) after a task has ended (UI notification)

    # ------------------------------------------------------------ settings
    @property
    def max_concurrent(self) -> int:
        try:
            return max(1, min(6, int(self.settings.get("concurrent", 3))))
        except (TypeError, ValueError):
            return 3

    def set_settings(self, data: dict) -> None:
        with self.lock:
            for k in SETTING_KEYS:
                if k in data:
                    self.settings[k] = data[k]
            core.save_settings(self.settings)
        self.process_queue()

    def cookies_file(self) -> str:
        p = self.settings.get("cookies_file", "")
        return p if p and os.path.isfile(p) else ""

    def save_cookies(self, content: str) -> str:
        d = core.user_data_dir() / "cookies"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "cookies.txt"
        p.write_text(content, encoding="utf-8")
        try:
            p.chmod(0o600)  # contains login sessions
        except OSError:
            pass
        with self.lock:
            self.settings["cookies_file"] = str(p)
            core.save_settings(self.settings)
        return str(p)

    def clear_cookies(self) -> None:
        with self.lock:
            p = self.settings.pop("cookies_file", "")
            core.save_settings(self.settings)
        try:
            if p and Path(p).parent == core.user_data_dir() / "cookies":
                Path(p).unlink()
        except OSError:
            pass

    # ------------------------------------------------------------ job input
    @staticmethod
    def valid_url(u: str) -> bool:
        return bool(URL_RE.fullmatch(u or ""))  # also blocks option injection ("-o ...")

    def build_job(self, url: str, f: dict) -> core.Job:
        def pick(v, allowed, default):
            return v if v in allowed else default

        ext = pick(f.get("ext"), core.VIDEO_FORMATS + core.AUDIO_FORMATS, "mp4")
        q = str(f.get("quality", "best"))
        try:
            interval = max(5, min(600, int(f.get("interval", 15))))
        except (TypeError, ValueError):
            interval = 15
        one_line = lambda v: re.sub(r"[\r\n]+", " ", str(v or "")).strip()
        return core.Job(
            url=url,
            outdir=one_line(f.get("outdir")) or core.default_outdir(),
            filename=one_line(f.get("filename")),
            ext=ext,
            quality=q if q in core.QUALITIES else "best",
            audio_quality=pick(f.get("audio_quality"), core.AUDIO_QUALITIES, "128kbps"),
            embed_thumbnail=bool(f.get("thumb", True)),
            embed_metadata=bool(f.get("meta", True)),
            subs=bool(f.get("subs")) and ext in core.VIDEO_FORMATS,
            playlist=bool(f.get("playlist")),
            cookies_file=self.cookies_file(),
            cookies_browser=pick(f.get("browser"), core.BROWSERS, ""),
            browser_profile=one_line(f.get("profile")),
            live_wait=bool(f.get("live_wait", True)),
            live_from_start=bool(f.get("live_from_start")),
            wait_interval=interval,
        )

    # ---------------------------------------------------------------- queue
    def add_urls(self, urls: list, form: dict) -> int:
        n = 0
        seen = set()
        for u in urls:
            u = (u or "").strip()
            if u in seen or not self.valid_url(u):
                continue
            seen.add(u)
            job = self.build_job(u, form)
            try:
                os.makedirs(job.outdir, exist_ok=True)
            except OSError:
                pass
            self._add(job)
            n += 1
        return n

    def _add(self, job: core.Job, front: bool = False) -> Task:
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
        self.process_queue()
        return task

    def trigger_update(self) -> bool:
        with self.lock:
            for t in self.tasks.values():
                if t.job.kind == "update" and t.status not in core.FINAL:
                    return False
        self._add(core.Job(kind="update", outdir=core.default_outdir()), front=True)
        return True

    def process_queue(self) -> None:
        with self.lock:
            while self.queue:
                task = self.tasks.get(self.queue[0])
                if task is None:
                    self.queue.popleft()
                    continue
                busy = [i for i in self.active if i not in self.waiting]
                updating = any(self.tasks[i].job.kind == "update" for i in self.active if i in self.tasks)
                if task.job.kind == "update":
                    if busy:
                        break  # let running downloads finish before replacing the binary
                elif updating or len(busy) >= self.max_concurrent:
                    break
                self.queue.popleft()
                self._start(task)

    def _start(self, task: Task) -> None:
        task.status, task.msg = core.RUNNING, "Starting..."
        runner = core.Runner(
            task.job,
            on_status=lambda st, msg, pct: self._on_status(task, st, msg, pct),
            on_log=lambda line, rep: self._on_log(task, line, rep),
            on_done=lambda: self._on_done(task),
        )
        task.runner = runner
        self.active[task.id] = runner
        runner.start()

    def _on_status(self, task: Task, status: str, msg: str, pct) -> None:
        with self.lock:
            changed = (status == core.WAITING) != (task.id in self.waiting)
            (self.waiting.add if status == core.WAITING else self.waiting.discard)(task.id)
            task.status, task.msg = status, msg
            task.indeterminate = pct is None
            if pct is not None:
                task.pct = pct
        if changed:
            self.process_queue()  # a waiting stream does not occupy a download slot

    def _on_log(self, task: Task, line: str, replace: bool) -> None:
        with self.lock:
            if replace and task.last_replace and task.log:
                task.log[-1] = line
            else:
                task.log.append(line)
            task.last_replace = replace
            if len(task.log) > 4000:
                del task.log[:1000]

    def _on_done(self, task: Task) -> None:
        with self.lock:
            self.active.pop(task.id, None)
            self.waiting.discard(task.id)
        if self.on_finish:
            try:
                self.on_finish(task)
            except Exception:
                pass
        self.process_queue()

    def stop(self, tid: int) -> None:
        with self.lock:
            task = self.tasks.get(tid)
            if task is None:
                return
            runner = self.active.get(tid)
            queued = tid in self.queue
            if queued:
                self.queue.remove(tid)
                task.status, task.msg, task.indeterminate = core.CANCELLED, "", False
        if runner is not None:
            runner.cancel()

    def retry(self, tid: int) -> None:
        with self.lock:
            task = self.tasks.get(tid)
            if task is None or tid in self.active or tid in self.queue or task.job.kind == "update":
                return
            task.status, task.msg, task.pct, task.indeterminate = core.PENDING, "", 0.0, False
            task.log.append("----- retry -----")
            task.last_replace = False
            self.queue.append(tid)
        self.process_queue()

    def delete(self, tid: int) -> None:
        self.stop(tid)
        with self.lock:
            self.tasks.pop(tid, None)
            if tid in self.order:
                self.order.remove(tid)

    def clear_finished(self) -> None:
        with self.lock:
            ids = [i for i, t in self.tasks.items()
                   if t.status in (core.FINISHED, core.CANCELLED) and i not in self.active]
        for i in ids:
            self.delete(i)

    # ---------------------------------------------------------------- state
    def warnings(self) -> dict:
        now = time.time()
        if now - self._warn_cache[0] > 4:
            self._warn_cache = (now, {
                "ytdlp": core.locate_ytdlp() is None,
                "ffmpeg": core.locate_ffmpeg() is None,
                "js": core.find_js_runtime() is None,
            })
        return self._warn_cache[1]

    def snapshot(self, sel: Optional[int] = None, log_lines: int = 300) -> dict:
        with self.lock:
            tasks = [self.tasks[i].to_dict() for i in self.order if i in self.tasks]
            log = []
            if sel in self.tasks:
                log = self.tasks[sel].log[-log_lines:]
            return {"tasks": tasks, "log": log, "warnings": self.warnings(), "release": self.release,
                    "active": len(self.active)}

    def full_log(self, tid: int) -> str:
        with self.lock:
            t = self.tasks.get(tid)
            return "\n".join(t.log[-5000:]) if t else ""

    def task_outdir(self, tid: int) -> Optional[str]:
        with self.lock:
            t = self.tasks.get(tid)
            return t.job.outdir if t else None

    def check_release(self) -> None:
        try:
            self.release = core.latest_release()
        except Exception:
            self.release = None

    # ------------------------------------------------------------ lifecycle
    def any_active(self) -> bool:
        with self.lock:
            return bool(self.active or self.queue)

    def stop_all(self, wait: float = 15) -> None:
        with self.lock:
            runners = list(self.active.values())
            self.queue.clear()
        for r in runners:
            r.cancel()
        end = time.time() + wait
        for r in runners:
            r.thread.join(max(0.1, end - time.time()))
