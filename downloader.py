# downloader.py
import sys
import os
import re
import threading
import subprocess
import shutil
import json
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional
import requests

from PySide6 import QtCore, QtWidgets, QtGui
from urllib.parse import urlparse

# ----------------------------
# 設定 / 翻訳（英語/日本語）
# ----------------------------
LANG_STRINGS = {
    "en": {
        "title": "yt-dlp Downloader",
        "add_url": "Add URL",
        "start_all": "Start Queue",
        "import_cookies": "Import cookies.txt",
        "choose_outdir": "Output Folder",
        "embed_thumb": "Embed thumbnail",
        "filename": "Filename (optional)",
        "ext": "Extension",
        "check_update": "Check / Update yt-dlp",
        "current_version": "Current version: {}",
        "latest_version": "Latest version: {}",
        "update_available": "Update available",
        "no_update": "Up-to-date",
        "open_file": "Open file / Folder",
        "language": "Language",
        "queue": "Queue",
    },
    "jp": {
        "title": "yt-dlp ダウンローダー",
        "add_url": "URL 追加",
        "start_all": "キューを開始",
        "import_cookies": "cookies.txt をインポート",
        "choose_outdir": "保存先フォルダ",
        "embed_thumb": "サムネを埋め込む",
        "filename": "ファイル名（任意）",
        "ext": "拡張子",
        "check_update": "yt-dlp チェック / 更新",
        "current_version": "現在のバージョン: {}",
        "latest_version": "最新バージョン: {}",
        "update_available": "更新があります",
        "no_update": "最新版です",
        "open_file": "ファイルを開く / フォルダを開く",
        "language": "言語",
        "queue": "待ち列",
    }
}

# ----------------------------
# Job 定義
# ----------------------------
@dataclass
class DownloadJob:
    url: str
    outdir: str
    filename: Optional[str]
    ext: str
    cookies: Optional[str]
    embed_thumbnail: bool
    lang: str  # 'en' or 'jp'
    id: int

# ----------------------------
# Download Worker (QThread)
# ----------------------------
class DownloadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, str)   # job_id, text
    finished_sig = QtCore.Signal(int, str)  # job_id, final_path_or_error

    def __init__(self, job: DownloadJob, host_semaphore: threading.Semaphore, yt_dlp_path="yt-dlp"):
        super().__init__()
        self.job = job
        self._stop_requested = False
        self.host_semaphore = host_semaphore
        self.yt_dlp_path = yt_dlp_path

    def run(self):
        # Acquire semaphore (blocks but since in separate thread it's fine)
        acquired = self.host_semaphore.acquire(timeout=600)
        if not acquired:
            self.finished_sig.emit(self.job.id, "Semaphore acquire timeout")
            return

        try:
            self._run_download()
        finally:
            # Release semaphore
            try:
                self.host_semaphore.release()
            except Exception:
                pass

    def _emit(self, text: str):
        self.progress.emit(self.job.id, text)

    def _run_download(self):
        job = self.job
        out_template = job.filename.strip() if job.filename else "%(title)s"
        # Ensure extension placeholder so we know final name:
        out_template = out_template + ".%(ext)s"
        out_template = os.path.join(job.outdir, out_template)

        # Build yt-dlp command: try using --recode-video to request extension conversion during/after download.
        # But user asked: "選択した拡張子でダウンロードを試行し、エラーの場合は mp4 でダウンロードして ffmpeg で変換"
        # We'll attempt a direct download+recode first; on error fallback to mp4 then ffmpeg convert.

        base_cmd = [self.yt_dlp_path, job.url, "-o", out_template, "--no-embed-metadata"]
        if job.cookies:
            base_cmd += ["--cookies", job.cookies]
        if job.embed_thumbnail:
            base_cmd += ["--embed-thumbnail"]
        # request to recode to target ext:
        recode_cmd = base_cmd + ["--recode-video", job.ext]

        # run recode attempt
        self._emit(f"Starting download (requesting .{job.ext}) ...")
        rc, stdout_text = self._popen_and_stream(recode_cmd)
        if rc == 0:
            # success; find final file path from stdout or by glob
            final_path = self._find_latest_file(job.outdir, job.filename, job.ext)
            if final_path:
                self.finished_sig.emit(job.id, final_path)
                return
            else:
                self.finished_sig.emit(job.id, f"Download succeeded but file not found (. {job.ext})")
                return
        else:
            # fallback: download mp4 and convert using ffmpeg
            self._emit("Primary attempt failed — falling back: download mp4 then convert with ffmpeg.")
            mp4_cmd = base_cmd + ["--recode-video", "mp4"]
            rc2, _ = self._popen_and_stream(mp4_cmd)
            if rc2 != 0:
                self.finished_sig.emit(job.id, "Download failed (both direct and mp4 fallback).")
                return

            # find mp4 path
            src = self._find_latest_file(job.outdir, job.filename, "mp4")
            if not src:
                self.finished_sig.emit(job.id, "Downloaded mp4 not found for conversion.")
                return

            # convert with ffmpeg
            dest_ext = job.ext
            dest = os.path.splitext(src)[0] + "." + dest_ext
            convert_rc = self._ffmpeg_convert(src, dest)
            if convert_rc == 0 and os.path.exists(dest):
                try:
                    os.remove(src)
                except Exception:
                    pass
                self.finished_sig.emit(job.id, dest)
                return
            else:
                self.finished_sig.emit(job.id, f"Conversion failed: attempted {src} -> {dest}")
                return

    def _popen_and_stream(self, cmd):
        """Run subprocess, stream stdout lines, emit progress lines. Return (rc, full_stdout)"""
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
        except Exception as e:
            self._emit(f"Failed to start process: {e}")
            return 1, ""

        full_out = ""
        prog_re = re.compile(r'^\[download\].*')  # simple: pass all [download] lines
        # Read lines
        while True:
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if line:
                full_out += line
                line_stripped = line.rstrip()
                if prog_re.match(line_stripped):
                    self._emit(line_stripped)
                else:
                    # other useful lines (e.g., ffmpeg merging) — emit less frequently
                    self._emit(line_stripped)
            # check cancel
            if self._stop_requested:
                try:
                    proc.kill()
                except Exception:
                    pass
                self._emit("Cancelled by user")
                return 1, full_out

        rc = proc.wait()
        return rc, full_out

    def _find_latest_file(self, outdir, filename_hint, ext):
        # If filename_hint provided and exact path exists, return it
        if filename_hint:
            candidate = os.path.join(outdir, filename_hint + "." + ext)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
        # otherwise, scan outdir for newest file with ext
        candidates = []
        for root, dirs, files in os.walk(outdir):
            for f in files:
                if f.lower().endswith("." + ext.lower()):
                    candidates.append(os.path.join(root, f))
        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return os.path.abspath(candidates[0])

    def _ffmpeg_convert(self, src, dest):
        # ffmpeg -y -i src dest
        cmd = ["ffmpeg", "-y", "-i", src, dest]
        self._emit(f"Converting with ffmpeg: {os.path.basename(src)} -> {os.path.basename(dest)}")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        except Exception as e:
            self._emit(f"Failed to start ffmpeg: {e}")
            return 1
        while True:
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if line:
                self._emit(line.rstrip())
            if self._stop_requested:
                try:
                    proc.kill()
                except Exception:
                    pass
                return 1
        rc = proc.wait()
        return rc

    def request_stop(self):
        self._stop_requested = True

# ----------------------------
# Download Manager (GUI + queue)
# ----------------------------
class DownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.lang = "jp"  # default
        self.strings = LANG_STRINGS[self.lang]
        self.setWindowTitle(self.strings["title"])
        self.resize(900, 600)

        # State
        self.queue = deque()
        self.job_counter = 0
        self.workers = {}  # job_id -> worker
        self.host_semaphores = defaultdict(lambda: threading.Semaphore(4))
        self.yt_dlp_path = self._locate_yt_dlp()

        # UI
        self._build_ui()
        self._refresh_ui_texts()

    def _locate_yt_dlp(self):
        # Prefer yt-dlp.exe in same folder, else rely on PATH
        exe_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
        local = os.path.join(os.path.dirname(sys.argv[0]), exe_name)
        if os.path.exists(local):
            return local
        return exe_name

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)

        # Top controls
        top_h = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("https://...")
        top_h.addWidget(self.url_input)

        self.add_btn = QtWidgets.QPushButton()
        self.add_btn.clicked.connect(self.add_url)
        top_h.addWidget(self.add_btn)

        self.start_btn = QtWidgets.QPushButton()
        self.start_btn.clicked.connect(self.process_queue)
        top_h.addWidget(self.start_btn)

        v.addLayout(top_h)

        options_h = QtWidgets.QHBoxLayout()
        self.cookies_btn = QtWidgets.QPushButton()
        self.cookies_btn.clicked.connect(self.import_cookies)
        options_h.addWidget(self.cookies_btn)

        self.outdir_btn = QtWidgets.QPushButton()
        self.outdir_btn.clicked.connect(self.choose_outdir)
        options_h.addWidget(self.outdir_btn)
        self.outdir_label = QtWidgets.QLabel(os.getcwd())
        options_h.addWidget(self.outdir_label)

        self.embed_chk = QtWidgets.QCheckBox()
        options_h.addWidget(self.embed_chk)
        self.filename_edit = QtWidgets.QLineEdit()
        self.filename_edit.setPlaceholderText(self.strings["filename"])
        options_h.addWidget(self.filename_edit)

        self.ext_combo = QtWidgets.QComboBox()
        self.ext_combo.addItems(["mp4", "mkv", "webm", "mov", "avi", "mp3"])
        options_h.addWidget(QtWidgets.QLabel(self.strings["ext"]))
        options_h.addWidget(self.ext_combo)

        v.addLayout(options_h)

        # Queue and logs
        mid_h = QtWidgets.QHBoxLayout()
        left_v = QtWidgets.QVBoxLayout()
        left_v.addWidget(QtWidgets.QLabel(self.strings["queue"]))
        self.queue_list = QtWidgets.QListWidget()
        left_v.addWidget(self.queue_list)
        mid_h.addLayout(left_v, 3)

        right_v = QtWidgets.QVBoxLayout()
        right_v.addWidget(QtWidgets.QLabel("Log / Progress"))
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        right_v.addWidget(self.log_text)
        mid_h.addLayout(right_v, 5)

        v.addLayout(mid_h)

        # bottom: update, language, open file
        bottom_h = QtWidgets.QHBoxLayout()
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.clicked.connect(self.check_update)
        bottom_h.addWidget(self.update_btn)

        self.version_label = QtWidgets.QLabel("")
        bottom_h.addWidget(self.version_label)

        bottom_h.addStretch()

        self.open_btn = QtWidgets.QPushButton()
        self.open_btn.clicked.connect(self.open_file_dialog)
        bottom_h.addWidget(self.open_btn)

        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems(["日本語", "English"])
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        bottom_h.addWidget(QtWidgets.QLabel(self.strings["language"]))
        bottom_h.addWidget(self.lang_combo)

        v.addLayout(bottom_h)

        # defaults
        self.cookies_path = None
        self.outdir = os.getcwd()

    def _refresh_ui_texts(self):
        s = LANG_STRINGS[self.lang]
        self.setWindowTitle(s["title"])
        self.add_btn.setText(s["add_url"])
        self.start_btn.setText(s["start_all"])
        self.cookies_btn.setText(s["import_cookies"])
        self.outdir_btn.setText(s["choose_outdir"])
        self.embed_chk.setText(s["embed_thumb"])
        self.filename_edit.setPlaceholderText(s["filename"])
        self.update_btn.setText(s["check_update"])
        self.open_btn.setText(s["open_file"])
        # version label left blank until checked

    def change_language(self, idx):
        self.lang = "jp" if idx == 0 else "en"
        self._refresh_ui_texts()

    def add_url(self):
        url = self.url_input.text().strip()
        if not url:
            return
        self.job_counter += 1
        job = DownloadJob(
            url=url,
            outdir=self.outdir,
            filename=self.filename_edit.text().strip() or None,
            ext=self.ext_combo.currentText(),
            cookies=self.cookies_path,
            embed_thumbnail=self.embed_chk.isChecked(),
            lang=self.lang,
            id=self.job_counter
        )
        self.queue.append(job)
        self.queue_list.addItem(f"[{job.id}] {job.url} -> .{job.ext}")
        self.log(f"Queued job {job.id}: {job.url}")
        self.url_input.clear()

    def process_queue(self):
        """Try to start as many queued jobs as semaphores allow."""
        # iterate over the queue and try to start jobs whose host semaphore has capacity
        # we pop from left when job started
        remaining = deque()
        while self.queue:
            job = self.queue.popleft()
            host = urlparse(job.url).netloc
            sem = self.host_semaphores[host]
            # try acquire non-blocking to check capacity
            acquired = sem.acquire(blocking=False)
            if acquired:
                # we actually need to release now because worker will acquire again, to avoid double-acquire
                sem.release()
                # start worker
                worker = DownloadWorker(job, sem, yt_dlp_path=self.yt_dlp_path)
                worker.progress.connect(self.on_progress)
                worker.finished_sig.connect(self.on_finished)
                self.workers[job.id] = worker
                worker.start()
                self.log(f"Started job {job.id} on host {host}")
                # update queue list UI: remove corresponding item
                for i in range(self.queue_list.count()):
                    it = self.queue_list.item(i)
                    if it.text().startswith(f"[{job.id}]"):
                        self.queue_list.takeItem(i)
                        break
            else:
                remaining.append(job)
        self.queue = remaining

    def import_cookies(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "cookies.txt (cookies.txt);;All Files (*)")
        if path:
            self.cookies_path = path
            self.log(f"Imported cookies: {path}")

    def choose_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder", self.outdir)
        if d:
            self.outdir = d
            self.outdir_label.setText(self.outdir)
            self.log(f"Output folder set: {self.outdir}")

    @QtCore.Slot(int, str)
    def on_progress(self, job_id, text):
        # append to log and update queue item (if desired)
        ts = time.strftime("%H:%M:%S")
        self.log(f"[{job_id}] {text}")

    @QtCore.Slot(int, str)
    def on_finished(self, job_id, result):
        # result is path or error message
        self.log(f"[{job_id}] Finished: {result}")
        # show clickable label in UI - for simplicity, append a clickable link in the log area text
        if os.path.exists(result):
            self.log(f"[{job_id}] File: {result}")
        # remove worker record
        try:
            w = self.workers.pop(job_id, None)
            if w and w.isRunning():
                w.quit()
        except Exception:
            pass
        # after finishing, try to start queued jobs
        self.process_queue()

    def log(self, text):
        self.log_text.appendPlainText(text)

    def open_file_dialog(self):
        # open the folder where last file was saved or open file dialog
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file to open", self.outdir, "All Files (*)")
        if path:
            # open
            try:
                if os.name == "nt":
                    os.startfile(path)
                else:
                    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            except Exception as e:
                self.log(f"Failed to open: {e}")

    def check_update(self):
        # get current version
        try:
            proc = subprocess.Popen([self.yt_dlp_path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            out, _ = proc.communicate(timeout=10)
            current = out.strip().splitlines()[0] if out else "?"
        except Exception:
            current = "?"
        self.version_label.setText(LANG_STRINGS[self.lang]["current_version"].format(current))
        # query GitHub API for latest release
        self.log("Checking latest yt-dlp release on GitHub...")
        try:
            r = requests.get("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", timeout=10)
            r.raise_for_status()
            data = r.json()
            latest_tag = data.get("tag_name") or data.get("name") or "?"
            self.log(f"Latest: {latest_tag}")
            self.version_label.setText(LANG_STRINGS[self.lang]["current_version"].format(current) + "   " + LANG_STRINGS[self.lang]["latest_version"].format(latest_tag))
            if latest_tag and latest_tag != current:
                self.log("Update available.")
                # Download new yt-dlp.exe asset for Windows if available
                assets = data.get("assets", [])
                exe_asset = None
                for a in assets:
                    name = a.get("name", "")
                    if name.lower().endswith(".exe"):
                        exe_asset = a
                        break
                if exe_asset:
                    dl_url = exe_asset.get("browser_download_url")
                    self.log(f"Downloading {exe_asset['name']} ...")
                    try:
                        dl = requests.get(dl_url, stream=True, timeout=30)
                        dl.raise_for_status()
                        target = os.path.join(os.path.dirname(sys.argv[0]), exe_asset['name'])
                        with open(target, "wb") as f:
                            for chunk in dl.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        # optionally replace current yt-dlp path if same name
                        if os.path.basename(self.yt_dlp_path).lower() == exe_asset['name'].lower() or self.yt_dlp_path == "yt-dlp.exe":
                            self.yt_dlp_path = target
                        self.log("Update downloaded to: " + target)
                    except Exception as e:
                        self.log("Failed to download update: " + str(e))
                else:
                    self.log("No executable asset found in latest release; consider pip install -U yt-dlp.")
            else:
                self.log("yt-dlp is up-to-date.")
        except Exception as e:
            self.log("Failed to check update: " + str(e))


# ----------------------------
# Run
# ----------------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    win = DownloaderApp()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

