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
# 実行環境のパス解決（PyInstaller対応）
# ----------------------------
def get_resource_path(relative_path):
    """PyInstallerの一時フォルダ、または通常実行時のパスを返す"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ----------------------------
# 設定 / 翻訳（英語/日本語）
# ----------------------------
LANG_STRINGS = {
    "en": {
        "title": "yt-dlp Downloader Pro",
        "add_url": "Add URL",
        "start_all": "Start Queue",
        "import_cookies": "Import cookies.txt",
        "choose_outdir": "Output Folder",
        "embed_thumb": "Embed thumbnail",
        "filename": "Filename (optional)",
        "ext": "Format",
        "check_update": "Check / Update yt-dlp",
        "current_version": "Current version: {}",
        "latest_version": "Latest version: {}",
        "open_file": "Open Folder",
        "language": "Language",
        "queue": "Queue",
    },
    "jp": {
        "title": "yt-dlp ダウンローダー Pro",
        "add_url": "URL 追加",
        "start_all": "キューを開始",
        "import_cookies": "cookies.txt をインポート",
        "choose_outdir": "保存先フォルダ",
        "embed_thumb": "サムネを埋め込む",
        "filename": "ファイル名（任意）",
        "ext": "形式",
        "check_update": "yt-dlp チェック / 更新",
        "current_version": "現在のバージョン: {}",
        "latest_version": "最新バージョン: {}",
        "open_file": "保存先を開く",
        "language": "言語",
        "queue": "待ち列",
    }
}

@dataclass
class DownloadJob:
    url: str
    outdir: str
    filename: Optional[str]
    ext: str
    cookies: Optional[str]
    embed_thumbnail: bool
    lang: str
    id: int

# ----------------------------
# Worker Thread
# ----------------------------
class DownloadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, str)
    finished_sig = QtCore.Signal(int, str)

    def __init__(self, job: DownloadJob, host_semaphore: threading.Semaphore, yt_dlp_path, ffmpeg_path):
        super().__init__()
        self.job = job
        self._stop_requested = False
        self.host_semaphore = host_semaphore
        self.yt_dlp_path = yt_dlp_path
        self.ffmpeg_path = ffmpeg_path

    def run(self):
        acquired = self.host_semaphore.acquire(timeout=600)
        if not acquired:
            self.finished_sig.emit(self.job.id, "Semaphore acquire timeout")
            return
        try:
            self._run_download()
        finally:
            try:
                self.host_semaphore.release()
            except Exception:
                pass

    def _emit(self, text: str):
        self.progress.emit(self.job.id, text)

    def _run_download(self):
        job = self.job
        out_template = job.filename.strip() if job.filename else "%(title)s"
        out_template = out_template + ".%(ext)s"
        out_template = os.path.join(job.outdir, out_template)

        # 基本コマンド設定
        base_cmd = [
            self.yt_dlp_path, job.url, 
            "-o", out_template, 
            "--ffmpeg-location", self.ffmpeg_path,
            "--no-mtime" # 更新日時を現在の時刻にする
        ]
        
        if job.cookies:
            base_cmd += ["--cookies", job.cookies]
        if job.embed_thumbnail:
            base_cmd += ["--embed-thumbnail"]

        # 形式に応じた追加オプション
        audio_formats = ["mp3", "m4a", "wav", "flac", "aac"]
        if job.ext in audio_formats:
            base_cmd += ["-x", "--audio-format", job.ext]
        else:
            base_cmd += ["--recode-video", job.ext]

        self._emit(f"Starting: {job.ext} mode...")
        rc, _ = self._popen_and_stream(base_cmd)
        
        if rc == 0:
            final_path = self._find_latest_file(job.outdir, job.filename, job.ext)
            if final_path:
                self.finished_sig.emit(job.id, final_path)
            else:
                self.finished_sig.emit(job.id, "Success, but file path not resolved.")
        else:
            self._emit("Attempt failed. Retrying with generic MP4 then converting...")
            # Fallback logic
            # ... (中略：mp4で落としてからffmpegで指定形式に強制変換)
            self.finished_sig.emit(job.id, "Download failed (check logs)")

    def _popen_and_stream(self, cmd):
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                bufsize=1, universal_newlines=True, startupinfo=startupinfo
            )
        except Exception as e:
            self._emit(f"Error: {e}")
            return 1, ""

        full_out = ""
        while True:
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None: break
            if line:
                full_out += line
                self._emit(line.rstrip())
            if self._stop_requested:
                proc.terminate()
                return 1, full_out
        return proc.wait(), full_out

    def _find_latest_file(self, outdir, filename_hint, ext):
        if filename_hint:
            candidate = os.path.join(outdir, filename_hint + "." + ext)
            if os.path.exists(candidate): return os.path.abspath(candidate)
        
        # fallback: 拡張子から最新ファイルを探す
        files = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.lower().endswith("." + ext.lower())]
        if not files: return None
        return max(files, key=os.path.getmtime)

# ----------------------------
# Main App
# ----------------------------
class DownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.lang = "jp"
        self.strings = LANG_STRINGS[self.lang]
        
        # 内部バイナリパス
        self.yt_dlp_path = self._locate_binary("yt-dlp.exe")
        self.ffmpeg_path = self._locate_binary("ffmpeg.exe")
        
        self.queue = deque()
        self.job_counter = 0
        self.workers = {}
        self.host_semaphores = defaultdict(lambda: threading.Semaphore(4))
        self.outdir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.cookies_path = None

        self._build_ui()
        self._refresh_ui_texts()

    def _locate_binary(self, name):
        bundled = get_resource_path(name)
        return bundled if os.path.exists(bundled) else name

    def _build_ui(self):
        self.resize(1000, 650)
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Top Row ---
        top_h = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        top_h.addWidget(self.url_input, 4)
        
        self.add_btn = QtWidgets.QPushButton()
        self.add_btn.clicked.connect(self.add_url)
        top_h.addWidget(self.add_btn, 1)

        self.start_btn = QtWidgets.QPushButton()
        self.start_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold;")
        self.start_btn.clicked.connect(self.process_queue)
        top_h.addWidget(self.start_btn, 1)
        main_layout.addLayout(top_h)

        # --- Options Group ---
        opt_group = QtWidgets.QGroupBox("Options")
        opt_layout = QtWidgets.QGridLayout(opt_group)

        self.outdir_btn = QtWidgets.QPushButton()
        self.outdir_btn.clicked.connect(self.choose_outdir)
        opt_layout.addWidget(self.outdir_btn, 0, 0)
        self.outdir_label = QtWidgets.QLabel(self.outdir)
        opt_layout.addWidget(self.outdir_label, 0, 1)

        self.cookies_btn = QtWidgets.QPushButton()
        self.cookies_btn.clicked.connect(self.import_cookies)
        opt_layout.addWidget(self.cookies_btn, 0, 2)

        self.filename_edit = QtWidgets.QLineEdit()
        opt_layout.addWidget(self.filename_edit, 1, 0, 1, 2)

        # 拡張子選択（主要なものを追加）
        self.ext_combo = QtWidgets.QComboBox()
        self.ext_combo.addItems([
            "mp4", "mkv", "mov", "avi", "flv", "webm", # 動画
            "mp3", "m4a", "wav", "flac", "aac"         # 音声
        ])
        opt_layout.addWidget(self.ext_combo, 1, 2)

        self.embed_chk = QtWidgets.QCheckBox()
        self.embed_chk.setChecked(True)
        opt_layout.addWidget(self.embed_chk, 1, 3)

        main_layout.addWidget(opt_group)

        # --- Content Area ---
        content_h = QtWidgets.QHBoxLayout()
        
        # Queue List
        queue_v = QtWidgets.QVBoxLayout()
        self.ql_label = QtWidgets.QLabel("Queue")
        queue_v.addWidget(self.ql_label)
        self.queue_list = QtWidgets.QListWidget()
        queue_v.addWidget(self.queue_list)
        content_h.addLayout(queue_v, 1)

        # Log
        log_v = QtWidgets.QVBoxLayout()
        log_v.addWidget(QtWidgets.QLabel("Logs"))
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas;")
        log_v.addWidget(self.log_text)
        content_h.addLayout(log_v, 2)

        main_layout.addLayout(content_h)

        # --- Bottom Bar ---
        bot_h = QtWidgets.QHBoxLayout()
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.clicked.connect(self.check_update)
        bot_h.addWidget(self.update_btn)
        
        self.version_label = QtWidgets.QLabel("yt-dlp: ready")
        bot_h.addWidget(self.version_label)
        
        bot_h.addStretch()
        
        self.open_btn = QtWidgets.QPushButton()
        self.open_btn.clicked.connect(self.open_folder)
        bot_h.addWidget(self.open_btn)

        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems(["日本語", "English"])
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        bot_h.addWidget(self.lang_combo)

        main_layout.addLayout(bot_h)

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
        self.ql_label.setText(s["queue"])

    def change_language(self, idx):
        self.lang = "jp" if idx == 0 else "en"
        self.strings = LANG_STRINGS[self.lang]
        self._refresh_ui_texts()

    def add_url(self):
        url = self.url_input.text().strip()
        if not url: return
        self.job_counter += 1
        job = DownloadJob(
            url=url, outdir=self.outdir, 
            filename=self.filename_edit.text().strip() or None,
            ext=self.ext_combo.currentText(), cookies=self.cookies_path,
            embed_thumbnail=self.embed_chk.isChecked(),
            lang=self.lang, id=self.job_counter
        )
        self.queue.append(job)
        self.queue_list.addItem(f"[{job.id}] {job.ext.upper()} | {job.url}")
        self.url_input.clear()

    def process_queue(self):
        remaining = deque()
        while self.queue:
            job = self.queue.popleft()
            host = urlparse(job.url).netloc or "unknown"
            sem = self.host_semaphores[host]
            if sem.acquire(blocking=False):
                sem.release()
                worker = DownloadWorker(job, sem, self.yt_dlp_path, self.ffmpeg_path)
                worker.progress.connect(self.on_progress)
                worker.finished_sig.connect(self.on_finished)
                self.workers[job.id] = worker
                worker.start()
                self._remove_from_list(job.id)
            else:
                remaining.append(job)
        self.queue = remaining

    def _remove_from_list(self, jid):
        for i in range(self.queue_list.count()):
            if self.queue_list.item(i).text().startswith(f"[{jid}]"):
                self.queue_list.takeItem(i)
                break

    def on_progress(self, jid, txt):
        self.log_text.appendPlainText(f"[{jid}] {txt}")
        # 自動スクロール
        self.log_text.moveCursor(QtGui.QTextCursor.End)

    def on_finished(self, jid, res):
        self.log_text.appendPlainText(f"[{jid}] ★ FINISHED: {res}")
        self.workers.pop(jid, None)
        self.process_queue()

    def choose_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder", self.outdir)
        if d:
            self.outdir = d
            self.outdir_label.setText(d)

    def import_cookies(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text Files (*.txt);;All Files (*)")
        if f: 
            self.cookies_path = f
            self.log_text.appendPlainText(f"Cookies loaded: {f}")

    def open_folder(self):
        if os.path.exists(self.outdir):
            os.startfile(self.outdir) if os.name == 'nt' else subprocess.run(['open', self.outdir])

    def check_update(self):
        self.log_text.appendPlainText("Update check is handled by GitHub Actions build process.")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion") # どのOSでも統一感のある見た目に
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())
