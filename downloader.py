import sys
import os
import threading
import subprocess
import re
import json
import webbrowser
from urllib.request import Request, urlopen
from urllib.error import URLError
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional

from PySide6 import QtCore, QtWidgets, QtGui

# ----------------------------
# バージョン情報
# ----------------------------
CURRENT_VERSION = "v1.0.0"  # 現在のバージョン（リリースタグに合わせて変更してください）
REPO_URL = "https://github.com/GratifluxTools/YT-Downloader"
API_URL = "https://api.github.com/repos/GratifluxTools/YT-Downloader/releases/latest"

# ----------------------------
# 実行環境のパス解決
# ----------------------------
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ----------------------------
# 定数・設定
# ----------------------------
STATUS_PENDING = "Pending"
STATUS_RUNNING = "Running"
STATUS_FINISHED = "Finished"
STATUS_ERROR = "Error"

LANG_STRINGS = {
    "en": {
        "title": "yt-dlp Downloader Pro",
        "add_url": "Add URL",
        "import_cookies": "Import cookies.txt",
        "choose_outdir": "Output Folder",
        "embed_thumb": "Embed Thumbnail",
        "embed_meta": "Embed Metadata",
        "filename": "Filename (optional)",
        "ext": "Format",
        "check_update": "Update yt-dlp",
        "usage": "Usage",
        "about": "About",
        "open_file": "Open Folder",
        "queue_header": ["ID", "Status", "Info", "URL"],
        "ctx_delete": "Delete Task",
        "log_placeholder": "Select a task to view its logs.",
        "usage_title": "How to Use",
        "usage_text": (
            "1. Enter the YouTube URL in the top bar.\n"
            "2. Select output folder and format (mp3/mp4, etc).\n"
            "3. Click 'Add URL' to add to queue.\n"
            "4. The download will start automatically.\n"
            "   (Max 3 concurrent downloads)\n\n"
            "Right-click a task to delete it."
        ),
        "about_title": "About",
        "update_avail_title": "Update Available",
        "update_avail_msg": "A new version of the application is available on GitHub.\nWould you like to open the download page?",
        "notification_title": "Download Complete",
        "notification_msg": "Task #{} has finished."
    },
    "jp": {
        "title": "yt-dlp ダウンローダー Pro",
        "add_url": "URL 追加",
        "import_cookies": "cookies.txt をインポート",
        "choose_outdir": "保存先フォルダ",
        "embed_thumb": "サムネを埋め込む",
        "embed_meta": "メタデータを埋め込む",
        "filename": "ファイル名（任意）",
        "ext": "形式",
        "check_update": "yt-dlp 更新",
        "usage": "使い方",
        "about": "ABOUT",
        "open_file": "保存先を開く",
        "queue_header": ["ID", "状態", "進捗・情報", "URL"],
        "ctx_delete": "タスクを削除",
        "log_placeholder": "タスクを選択するとここにログが表示されます。",
        "usage_title": "使い方",
        "usage_text": (
            "1. 上部のバーにYouTubeのURLを入力します。\n"
            "2. 保存先フォルダや形式（mp3/mp4など）を選択します。\n"
            "3. 「URL 追加」を押すとキューに追加されます。\n"
            "4. 自動的にダウンロードが開始されます。\n"
            "   （最大3つまで同時実行されます）\n\n"
            "タスクを右クリックすると削除できます。"
        ),
        "about_title": "このアプリについて",
        "update_avail_title": "アップデート",
        "update_avail_msg": "GitHubに新しいバージョンがあります。\nダウンロードページを開きますか？",
        "notification_title": "ダウンロード完了",
        "notification_msg": "タスク #{} が完了しました。"
    }
}

@dataclass
class DownloadJob:
    id: int
    url: str
    outdir: str
    filename: Optional[str]
    ext: str
    cookies: Optional[str]
    embed_thumbnail: bool
    embed_metadata: bool  # 追加: メタデータ埋め込み
    is_update_task: bool = False

# ----------------------------
# GitHub Update Checker Thread
# ----------------------------
class UpdateChecker(QtCore.QThread):
    update_available = QtCore.Signal(str) # url passed back

    def run(self):
        try:
            req = Request(API_URL)
            req.add_header('User-Agent', 'Python-App')
            with urlopen(req) as response:
                data = json.load(response)
                latest_tag = data.get('tag_name', '')
                # バージョン比較（単純な文字列比較。必要ならsemverライブラリ等を使用）
                if latest_tag and latest_tag != CURRENT_VERSION:
                    html_url = data.get('html_url', REPO_URL)
                    self.update_available.emit(html_url)
        except Exception:
            pass # ネットがない場合などは無視

# ----------------------------
# Worker Thread
# ----------------------------
class DownloadWorker(QtCore.QThread):
    log_signal = QtCore.Signal(int, str, bool)
    status_signal = QtCore.Signal(int, str, str)
    finished_signal = QtCore.Signal(int)

    def __init__(self, job: DownloadJob, semaphore: threading.Semaphore, yt_dlp_path, ffmpeg_path):
        super().__init__()
        self.job = job
        self.semaphore = semaphore
        self.yt_dlp_path = yt_dlp_path
        self.ffmpeg_path = ffmpeg_path
        self._is_cancelled = False

    def run(self):
        acquired = self.semaphore.acquire(timeout=600)
        if not acquired:
            self.status_signal.emit(self.job.id, STATUS_ERROR, "Timeout")
            self.finished_signal.emit(self.job.id)
            return

        try:
            if self._is_cancelled: return
            self.status_signal.emit(self.job.id, STATUS_RUNNING, "Starting...")
            
            if self.job.is_update_task:
                self._run_update()
            else:
                self._run_download()
        except Exception as e:
            self.status_signal.emit(self.job.id, STATUS_ERROR, str(e))
        finally:
            self.semaphore.release()
            self.finished_signal.emit(self.job.id)

    def _run_update(self):
        cmd = [self.yt_dlp_path, "-U"]
        rc = self._execute_command(cmd)
        if rc == 0:
            self.status_signal.emit(self.job.id, STATUS_FINISHED, "Updated")
        else:
            self.status_signal.emit(self.job.id, STATUS_ERROR, "Update Failed")

    def _run_download(self):
        job = self.job
        
        out_name = job.filename.strip() if job.filename else "%(title)s"
        out_template = f"{out_name}.%(ext)s"
        full_template = os.path.join(job.outdir, out_template)

        cmd = [
            self.yt_dlp_path, job.url,
            "-o", full_template,
            "--ffmpeg-location", self.ffmpeg_path,
            "--no-mtime",
            "--newline"
        ]

        if job.cookies:
            cmd += ["--cookies", job.cookies]
        if job.embed_thumbnail:
            cmd += ["--embed-thumbnail"]
        if job.embed_metadata:
            cmd += ["--add-metadata"]

        audio_formats = ["mp3", "m4a", "wav", "flac", "aac"]
        if job.ext in audio_formats:
            cmd += ["-x", "--audio-format", job.ext]
        else:
            cmd += ["--recode-video", job.ext]

        rc = self._execute_command(cmd)

        if rc == 0:
            self.status_signal.emit(job.id, STATUS_FINISHED, "Done")
        else:
            self.status_signal.emit(job.id, STATUS_ERROR, "Failed (Check Logs)")
            self._cleanup_failed_files(job.outdir, out_name)

    def _execute_command(self, cmd):
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # ---------------------------------------------------------
            # 文字化け対策: 環境変数でUTF-8出力を強制する
            # ---------------------------------------------------------
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            proc = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                bufsize=1, 
                universal_newlines=True, 
                encoding='utf-8',       # UTF-8として読み込む
                errors='replace', 
                startupinfo=startupinfo,
                env=env                 # 環境変数を適用
            )

            for line in proc.stdout:
                line = line.strip()
                if not line: continue

                is_eta = False
                if "[download]" in line and "ETA" in line and "%" in line:
                    is_eta = True
                    self.status_signal.emit(self.job.id, STATUS_RUNNING, self._extract_progress(line))

                self.log_signal.emit(self.job.id, line, is_eta)

            proc.wait()
            return proc.returncode
        except Exception as e:
            self.log_signal.emit(self.job.id, f"Process Error: {e}", False)
            return 1

    def _extract_progress(self, text):
        match = re.search(r"(\d+\.\d+%).*?(ETA\s+\S+)", text)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "Downloading..."

    def _cleanup_failed_files(self, outdir, filename_base):
        self.log_signal.emit(self.job.id, "--- Download failed. Cleaning up... ---", False)
        if not filename_base or "%" in filename_base:
            self.log_signal.emit(self.job.id, "Warning: Cannot auto-delete dynamic filenames safely.", False)
            return
        self.log_signal.emit(self.job.id, "Cleanup: Please check folder for partial files.", False)


# ----------------------------
# Main App
# ----------------------------
class DownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        # デフォルト言語を英語に変更
        self.lang = "en"
        self.strings = LANG_STRINGS[self.lang]
        
        self.yt_dlp_path = self._locate_binary("yt-dlp.exe")
        self.ffmpeg_path = self._locate_binary("ffmpeg.exe")
        
        self.job_counter = 0
        self.jobs = {}
        self.logs = defaultdict(list)
        self.log_is_last_eta = defaultdict(bool)

        self.waiting_queue = deque()
        self.active_workers = {}
        
        self.max_concurrent = 3
        self.semaphore = threading.Semaphore(self.max_concurrent)

        self.outdir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.cookies_path = None

        # トレイアイコンの初期化（通知用）
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        # アイコン画像がないと表示されない場合があるため、標準アイコンを使用
        self.tray_icon.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowDown))
        self.tray_icon.show()

        self._build_ui()
        self._refresh_ui_texts()
        
        self.scheduler_timer = QtCore.QTimer()
        self.scheduler_timer.timeout.connect(self.process_queue)
        self.scheduler_timer.start(1000)

        # 起動時にGitHub更新確認
        self.check_github_update()

    def check_github_update(self):
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.on_update_available)
        self.update_checker.start()

    def on_update_available(self, url):
        # 英語で通知
        s_en = LANG_STRINGS["en"]
        reply = QtWidgets.QMessageBox.question(
            self, 
            s_en["update_avail_title"], 
            s_en["update_avail_msg"],
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            webbrowser.open(url)

    def _locate_binary(self, name):
        bundled = get_resource_path(name)
        return bundled if os.path.exists(bundled) else name

    def _build_ui(self):
        self.resize(1100, 750)
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Top Input ---
        top_h = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.returnPressed.connect(self.add_url)
        top_h.addWidget(self.url_input, 4)
        
        self.add_btn = QtWidgets.QPushButton()
        self.add_btn.clicked.connect(self.add_url)
        top_h.addWidget(self.add_btn, 1)
        main_layout.addLayout(top_h)

        # --- Options ---
        opt_group = QtWidgets.QGroupBox("Options")
        opt_layout = QtWidgets.QGridLayout(opt_group)

        self.outdir_btn = QtWidgets.QPushButton()
        self.outdir_btn.clicked.connect(self.choose_outdir)
        opt_layout.addWidget(self.outdir_btn, 0, 0)
        self.outdir_label = QtWidgets.QLabel(self.outdir)
        self.outdir_label.setStyleSheet("color: gray;")
        opt_layout.addWidget(self.outdir_label, 0, 1)

        self.cookies_btn = QtWidgets.QPushButton()
        self.cookies_btn.clicked.connect(self.import_cookies)
        opt_layout.addWidget(self.cookies_btn, 0, 2)

        self.filename_edit = QtWidgets.QLineEdit()
        opt_layout.addWidget(self.filename_edit, 1, 0, 1, 2)

        # 形式選択
        self.ext_combo = QtWidgets.QComboBox()
        self.ext_combo.addItems(["mp4", "mp3", "mkv", "wav", "webm", "m4a"])
        opt_layout.addWidget(self.ext_combo, 1, 2)

        # チェックボックス用のレイアウト
        chk_layout = QtWidgets.QVBoxLayout()
        self.embed_chk = QtWidgets.QCheckBox()
        self.embed_chk.setChecked(True)
        chk_layout.addWidget(self.embed_chk)
        
        self.meta_chk = QtWidgets.QCheckBox() # メタデータ追加
        self.meta_chk.setChecked(True)
        chk_layout.addWidget(self.meta_chk)
        
        opt_layout.addLayout(chk_layout, 1, 3)

        main_layout.addWidget(opt_group)

        # --- Main Content (Splitter) ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.itemClicked.connect(self.on_table_click)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        splitter.addWidget(self.table)

        # Log
        log_container = QtWidgets.QWidget()
        log_layout = QtWidgets.QVBoxLayout(log_container)
        log_layout.setContentsMargins(0,0,0,0)
        self.log_label = QtWidgets.QLabel("Task Logs")
        log_layout.addWidget(self.log_label)
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas;")
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_container)
        
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 1)

        # --- Bottom ---
        bot_h = QtWidgets.QHBoxLayout()
        
        # Update Button
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.setStyleSheet("background-color: #d35400; color: white; font-weight: bold;")
        self.update_btn.clicked.connect(self.trigger_update)
        bot_h.addWidget(self.update_btn)

        # Usage Button
        self.usage_btn = QtWidgets.QPushButton()
        self.usage_btn.clicked.connect(self.show_usage)
        bot_h.addWidget(self.usage_btn)

        # About Button
        self.about_btn = QtWidgets.QPushButton()
        self.about_btn.clicked.connect(self.show_about)
        bot_h.addWidget(self.about_btn)
        
        bot_h.addStretch()
        
        self.open_btn = QtWidgets.QPushButton()
        self.open_btn.clicked.connect(self.open_folder)
        bot_h.addWidget(self.open_btn)

        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItems(["English", "日本語"])
        self.lang_combo.currentIndexChanged.connect(self.change_language)
        bot_h.addWidget(self.lang_combo)

        main_layout.addLayout(bot_h)

    def _refresh_ui_texts(self):
        s = LANG_STRINGS[self.lang]
        self.setWindowTitle(s["title"])
        self.add_btn.setText(s["add_url"])
        self.cookies_btn.setText(s["import_cookies"])
        self.outdir_btn.setText(s["choose_outdir"])
        self.embed_chk.setText(s["embed_thumb"])
        self.meta_chk.setText(s["embed_meta"])
        self.filename_edit.setPlaceholderText(s["filename"])
        self.update_btn.setText(s["check_update"])
        self.usage_btn.setText(s["usage"])
        self.about_btn.setText(s["about"])
        self.open_btn.setText(s["open_file"])
        self.table.setHorizontalHeaderLabels(s["queue_header"])
        self.log_text.setPlaceholderText(s["log_placeholder"])

    def change_language(self, idx):
        self.lang = "en" if idx == 0 else "jp"
        self.strings = LANG_STRINGS[self.lang]
        self._refresh_ui_texts()

    # ------------------
    # Action Methods
    # ------------------
    def add_url(self):
        url = self.url_input.text().strip()
        if not url: return
        
        self.job_counter += 1
        job = DownloadJob(
            id=self.job_counter,
            url=url,
            outdir=self.outdir,
            filename=self.filename_edit.text().strip() or None,
            ext=self.ext_combo.currentText(),
            cookies=self.cookies_path,
            embed_thumbnail=self.embed_chk.isChecked(),
            embed_metadata=self.meta_chk.isChecked()
        )
        self._register_job(job)
        self.url_input.clear()

    def trigger_update(self):
        self.job_counter += 1
        job = DownloadJob(
            id=self.job_counter,
            url="UPDATE_YT_DLP",
            outdir=self.outdir,
            filename=None,
            ext="",
            cookies=None,
            embed_thumbnail=False,
            embed_metadata=False,
            is_update_task=True
        )
        self.waiting_queue.appendleft(job.id)
        self.jobs[job.id] = job
        self._add_table_row(job)
        self.update_table_status(job.id, STATUS_PENDING, "Priority Update")
        self.process_queue()

    def _register_job(self, job):
        self.jobs[job.id] = job
        self.waiting_queue.append(job.id)
        self._add_table_row(job)
        self.process_queue()

    def _add_table_row(self, job):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        item_id = QtWidgets.QTableWidgetItem(str(job.id))
        item_id.setTextAlignment(QtCore.Qt.AlignCenter)
        self.table.setItem(row, 0, item_id)
        
        item_status = QtWidgets.QTableWidgetItem(STATUS_PENDING)
        item_status.setTextAlignment(QtCore.Qt.AlignCenter)
        self.table.setItem(row, 1, item_status)

        item_info = QtWidgets.QTableWidgetItem("Waiting...")
        self.table.setItem(row, 2, item_info)

        url_display = "System Update" if job.is_update_task else job.url
        item_url = QtWidgets.QTableWidgetItem(url_display)
        self.table.setItem(row, 3, item_url)

    def process_queue(self):
        running_cnt = len(self.active_workers)
        if running_cnt >= self.max_concurrent:
            return

        if not self.waiting_queue:
            return

        job_id = self.waiting_queue.popleft()
        job = self.jobs.get(job_id)
        if not job: return

        worker = DownloadWorker(job, self.semaphore, self.yt_dlp_path, self.ffmpeg_path)
        worker.log_signal.connect(self.handle_log)
        worker.status_signal.connect(self.update_table_status)
        worker.finished_signal.connect(self.on_worker_finished)
        
        self.active_workers[job_id] = worker
        worker.start()

    # ------------------
    # Dialogs
    # ------------------
    def show_usage(self):
        QtWidgets.QMessageBox.information(
            self, 
            self.strings["usage_title"], 
            self.strings["usage_text"]
        )

    def show_about(self):
        info_text = (
            "YT-Downloader Pro\n"
            f"Version: {CURRENT_VERSION}\n\n"
            "Creator: Gratiflux Tools\n"
            "Email: ss872927net@gmail.com\n"
            "Web: https://ss872927.stars.ne.jp\n"
            f"GitHub: {REPO_URL}\n\n"
            "Libraries used:\n"
            "- Python 3\n"
            "- PySide6 (Qt)\n"
            "- yt-dlp\n"
            "- ffmpeg"
        )
        QtWidgets.QMessageBox.about(self, self.strings["about_title"], info_text)

    # ------------------
    # Event Handlers
    # ------------------
    def handle_log(self, jid, text, is_eta):
        log_list = self.logs[jid]
        
        if is_eta and self.log_is_last_eta[jid] and log_list:
            log_list[-1] = text
        else:
            log_list.append(text)
        
        self.log_is_last_eta[jid] = is_eta

        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            current_row = selected_rows[0].row()
            current_id = int(self.table.item(current_row, 0).text())
            if current_id == jid:
                self._update_log_view(jid)

    def update_table_status(self, jid, status, msg):
        row = self._find_row_by_id(jid)
        if row is None: return

        item_status = self.table.item(row, 1)
        item_status.setText(status)
        
        if status == STATUS_RUNNING:
            item_status.setBackground(QtGui.QColor("#3498db"))
            item_status.setForeground(QtGui.QColor("white"))
        elif status == STATUS_FINISHED:
            item_status.setBackground(QtGui.QColor("#2ecc71"))
            item_status.setForeground(QtGui.QColor("white"))
        elif status == STATUS_ERROR:
            item_status.setBackground(QtGui.QColor("#e74c3c"))
            item_status.setForeground(QtGui.QColor("white"))
        else:
            item_status.setBackground(QtGui.QColor("transparent"))
            item_status.setForeground(QtGui.QColor("#dcdcdc" if self.palette().windowText().color().lightness() > 128 else "black"))

        self.table.item(row, 2).setText(msg)

    def on_worker_finished(self, jid):
        if jid in self.active_workers:
            del self.active_workers[jid]
        
        # 通知機能（ウィンドウがアクティブでない場合）
        if not self.isActiveWindow():
            self.tray_icon.showMessage(
                self.strings["notification_title"],
                self.strings["notification_msg"].format(jid),
                QtWidgets.QSystemTrayIcon.Information,
                3000
            )

        self.process_queue()

    def on_table_click(self, item):
        row = item.row()
        jid = int(self.table.item(row, 0).text())
        self.log_label.setText(f"Task #{jid} Logs")
        self._update_log_view(jid)

    def _update_log_view(self, jid):
        text = "\n".join(self.logs[jid])
        self.log_text.setPlainText(text)
        self.log_text.moveCursor(QtGui.QTextCursor.End)

    def _find_row_by_id(self, jid):
        for r in range(self.table.rowCount()):
            if int(self.table.item(r, 0).text()) == jid:
                return r
        return None

    def show_context_menu(self, pos):
        menu = QtWidgets.QMenu()
        delete_action = menu.addAction(self.strings["ctx_delete"])
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == delete_action:
            self.delete_selected_task()

    def delete_selected_task(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows: return
        
        row = rows[0].row()
        jid = int(self.table.item(row, 0).text())
        
        if jid in self.active_workers:
            self.active_workers[jid]._is_cancelled = True
        
        if jid in self.waiting_queue:
            self.waiting_queue.remove(jid)
            
        if jid in self.jobs:
            del self.jobs[jid]
        if jid in self.logs:
            del self.logs[jid]
            
        self.table.removeRow(row)
        self.log_text.clear()

    # ------------------
    # Utils
    # ------------------
    def choose_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder", self.outdir)
        if d:
            self.outdir = d
            self.outdir_label.setText(d)

    def import_cookies(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text Files (*.txt);;All Files (*)")
        if f: 
            self.cookies_path = f
            self.outdir_label.setText("Cookies loaded")

    def open_folder(self):
        if os.path.exists(self.outdir):
            if os.name == 'nt':
                os.startfile(self.outdir)
            else:
                subprocess.run(['open', self.outdir])

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
    app.setPalette(palette)
    
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())
