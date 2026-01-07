import sys
import os
import threading
import subprocess
import re
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from PySide6 import QtCore, QtWidgets, QtGui

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
        "embed_thumb": "Embed thumbnail",
        "filename": "Filename (optional)",
        "ext": "Format",
        "check_update": "Update yt-dlp (Priority)",
        "open_file": "Open Folder",
        "queue_header": ["ID", "Status", "Info", "URL"],
        "ctx_delete": "Delete Task",
        "log_placeholder": "Select a task to view its logs.",
    },
    "jp": {
        "title": "yt-dlp ダウンローダー Pro",
        "add_url": "URL 追加",
        "import_cookies": "cookies.txt をインポート",
        "choose_outdir": "保存先フォルダ",
        "embed_thumb": "サムネを埋め込む",
        "filename": "ファイル名（任意）",
        "ext": "形式",
        "check_update": "yt-dlp 更新（優先実行）",
        "open_file": "保存先を開く",
        "queue_header": ["ID", "状態", "進捗・情報", "URL"],
        "ctx_delete": "タスクを削除",
        "log_placeholder": "タスクを選択するとここにログが表示されます。",
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
    is_update_task: bool = False # アップデート用特別タスクフラグ

# ----------------------------
# Worker Thread
# ----------------------------
class DownloadWorker(QtCore.QThread):
    # (job_id, log_text, is_eta_update)
    log_signal = QtCore.Signal(int, str, bool)
    # (job_id, status_enum, short_message)
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
        # セマフォ取得（同時実行数制御）
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
        """yt-dlp -U を実行"""
        cmd = [self.yt_dlp_path, "-U"]
        rc = self._execute_command(cmd)
        if rc == 0:
            self.status_signal.emit(self.job.id, STATUS_FINISHED, "Updated")
        else:
            self.status_signal.emit(self.job.id, STATUS_ERROR, "Update Failed")

    def _run_download(self):
        job = self.job
        
        # 出力パス構築
        out_name = job.filename.strip() if job.filename else "%(title)s"
        out_template = f"{out_name}.%(ext)s"
        full_template = os.path.join(job.outdir, out_template)

        cmd = [
            self.yt_dlp_path, job.url,
            "-o", full_template,
            "--ffmpeg-location", self.ffmpeg_path,
            "--no-mtime",
            "--newline" # 進捗解析をしやすくする
        ]

        if job.cookies:
            cmd += ["--cookies", job.cookies]
        if job.embed_thumbnail:
            cmd += ["--embed-thumbnail"]

        # フォーマット指定
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
        """サブプロセス実行とログ解析"""
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True, encoding='utf-8', errors='replace',
                startupinfo=startupinfo
            )

            for line in proc.stdout:
                line = line.strip()
                if not line: continue

                # ETA制御ロジック
                # [download]  45.0% of 10.00MiB at 2.00MiB/s ETA 00:05
                is_eta = False
                if "[download]" in line and "ETA" in line and "%" in line:
                    is_eta = True
                    # 進捗状況をステータスバー用に短縮抽出
                    self.status_signal.emit(self.job.id, STATUS_RUNNING, self._extract_progress(line))

                self.log_signal.emit(self.job.id, line, is_eta)

            proc.wait()
            return proc.returncode
        except Exception as e:
            self.log_signal.emit(self.job.id, f"Process Error: {e}", False)
            return 1

    def _extract_progress(self, text):
        """ログ行から xx% ... ETA xx:xx を抜き出す簡易パーサ"""
        # 正規表現で簡易抽出
        match = re.search(r"(\d+\.\d+%).*?(ETA\s+\S+)", text)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "Downloading..."

    def _cleanup_failed_files(self, outdir, filename_base):
        """失敗時にゴミファイルを削除する"""
        self.log_signal.emit(self.job.id, "--- Download failed. Cleaning up... ---", False)
        # ファイル名のワイルドカード的な削除は危険なので、yt-dlpが作りそうな拡張子を探す
        # 注意: %(title)s が使われている場合、正確なファイル名は特定困難だが、
        # 指定されたファイル名がある場合はそれを基準に削除試行
        
        # 簡易的な実装: フォルダ内の .part や .ytdl を探し、作成時間が直近のものを疑うなどのロジックが必要だが、
        # ここでは安全のため「指定ファイル名が存在する場合」のみ削除する
        # ※ ユーザー指定ファイル名がない場合（タイトル依存）は、完全なクリーンアップは難しい
        
        if not filename_base or "%" in filename_base:
            self.log_signal.emit(self.job.id, "Warning: Cannot auto-delete dynamic filenames safely.", False)
            return

        for ext in [".part", ".ytdl", ".f137.webm", ".f140.m4a", ".mp4", ".mkv", ".mp3"]: 
            # 一般的な一時ファイルや結合前のストリーム
            possible_path = os.path.join(outdir, filename_base + ext)
            # 再帰的に探すロジックを入れると危険なので、推測されるパスのみチェック
            # glob等を使ってもよい
            pass

        # 今回はエラーログを出すにとどめ、誤削除を防ぐ
        self.log_signal.emit(self.job.id, "Cleanup: Please check folder for partial files.", False)


# ----------------------------
# Main App
# ----------------------------
class DownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.lang = "jp"
        self.strings = LANG_STRINGS[self.lang]
        
        # パス設定
        self.yt_dlp_path = self._locate_binary("yt-dlp.exe")
        self.ffmpeg_path = self._locate_binary("ffmpeg.exe")
        
        # データ管理
        self.job_counter = 0
        self.jobs = {}       # id -> DownloadJob
        self.logs = defaultdict(list) # id -> list of log strings
        self.log_is_last_eta = defaultdict(bool) # id -> bool (最後の行がETAだったか)

        # キュー管理
        self.waiting_queue = deque() # job_id のリスト
        self.active_workers = {}     # job_id -> DownloadWorker
        
        # 同時実行制限 (ホストごとではなく全体で制限する場合の例。ホストごとならDict[Semaphore])
        # 今回はシンプルかつ強力に「最大3並列」とする
        self.max_concurrent = 3
        self.semaphore = threading.Semaphore(self.max_concurrent)

        self.outdir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.cookies_path = None

        self._build_ui()
        self._refresh_ui_texts()
        
        # タイマーでキュー監視（セマフォ管理はThread側だが、開始トリガーはMainでやる）
        self.scheduler_timer = QtCore.QTimer()
        self.scheduler_timer.timeout.connect(self.process_queue)
        self.scheduler_timer.start(1000) # 1秒ごとにチェック

    def _locate_binary(self, name):
        bundled = get_resource_path(name)
        return bundled if os.path.exists(bundled) else name

    def _build_ui(self):
        self.resize(1100, 700)
        main_layout = QtWidgets.QVBoxLayout(self)

        # --- Top Input ---
        top_h = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.returnPressed.connect(self.add_url) # Enterで追加
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

        self.ext_combo = QtWidgets.QComboBox()
        self.ext_combo.addItems(["mp4", "mp3", "mkv", "wav", "webm", "m4a"])
        opt_layout.addWidget(self.ext_combo, 1, 2)

        self.embed_chk = QtWidgets.QCheckBox()
        self.embed_chk.setChecked(True)
        opt_layout.addWidget(self.embed_chk, 1, 3)

        main_layout.addWidget(opt_group)

        # --- Main Content (Splitter) ---
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left: Task Table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(4)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 列幅調整
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents) # ID
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents) # Status
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)          # Info
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)          # URL
        
        self.table.itemClicked.connect(self.on_table_click)
        
        # コンテキストメニュー（右クリック削除用）
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        splitter.addWidget(self.table)

        # Right: Log View
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
        
        # Splitter比率
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

        # --- Bottom ---
        bot_h = QtWidgets.QHBoxLayout()
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.setStyleSheet("background-color: #d35400; color: white; font-weight: bold;")
        self.update_btn.clicked.connect(self.trigger_update)
        bot_h.addWidget(self.update_btn)
        
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
        self.cookies_btn.setText(s["import_cookies"])
        self.outdir_btn.setText(s["choose_outdir"])
        self.embed_chk.setText(s["embed_thumb"])
        self.filename_edit.setPlaceholderText(s["filename"])
        self.update_btn.setText(s["check_update"])
        self.open_btn.setText(s["open_file"])
        self.table.setHorizontalHeaderLabels(s["queue_header"])
        self.log_text.setPlaceholderText(s["log_placeholder"])

    def change_language(self, idx):
        self.lang = "jp" if idx == 0 else "en"
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
            embed_thumbnail=self.embed_chk.isChecked()
        )
        self._register_job(job)
        self.url_input.clear()

    def trigger_update(self):
        """yt-dlp更新を割り込み優先実行"""
        self.job_counter += 1
        job = DownloadJob(
            id=self.job_counter,
            url="UPDATE_YT_DLP",
            outdir=self.outdir,
            filename=None,
            ext="",
            cookies=None,
            embed_thumbnail=False,
            is_update_task=True
        )
        # キューの先頭に追加 (優先実行)
        self.waiting_queue.appendleft(job.id)
        self.jobs[job.id] = job
        self._add_table_row(job)
        self.update_table_status(job.id, STATUS_PENDING, "Priority Update")
        # 即時スケジュール試行
        self.process_queue()

    def _register_job(self, job):
        self.jobs[job.id] = job
        self.waiting_queue.append(job.id)
        self._add_table_row(job)
        self.process_queue() # 自動開始トリガー

    def _add_table_row(self, job):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # ID
        item_id = QtWidgets.QTableWidgetItem(str(job.id))
        item_id.setTextAlignment(QtCore.Qt.AlignCenter)
        self.table.setItem(row, 0, item_id)
        
        # Status
        item_status = QtWidgets.QTableWidgetItem(STATUS_PENDING)
        item_status.setTextAlignment(QtCore.Qt.AlignCenter)
        self.table.setItem(row, 1, item_status)

        # Info
        item_info = QtWidgets.QTableWidgetItem("Waiting...")
        self.table.setItem(row, 2, item_info)

        # URL
        url_display = "System Update" if job.is_update_task else job.url
        item_url = QtWidgets.QTableWidgetItem(url_display)
        self.table.setItem(row, 3, item_url)

    def process_queue(self):
        """スケジューラー: 空きスロットがあればキューから取り出して実行"""
        # 実行中の数をカウント
        running_cnt = len(self.active_workers)
        if running_cnt >= self.max_concurrent:
            return

        if not self.waiting_queue:
            return

        # 次のジョブを取得
        job_id = self.waiting_queue.popleft()
        job = self.jobs.get(job_id)
        if not job: return # 削除されていた場合など

        # ワーカー起動
        worker = DownloadWorker(job, self.semaphore, self.yt_dlp_path, self.ffmpeg_path)
        worker.log_signal.connect(self.handle_log)
        worker.status_signal.connect(self.update_table_status)
        worker.finished_signal.connect(self.on_worker_finished)
        
        self.active_workers[job_id] = worker
        worker.start()

    # ------------------
    # Event Handlers
    # ------------------
    def handle_log(self, jid, text, is_eta):
        """ログを受信してメモリに保存＋表示更新"""
        log_list = self.logs[jid]
        
        if is_eta and self.log_is_last_eta[jid] and log_list:
            # 前の行もETAなら上書き（リストの最後を置換）
            log_list[-1] = text
        else:
            # 新規行追加
            log_list.append(text)
        
        self.log_is_last_eta[jid] = is_eta

        # 現在選択中のタスクなら、画面も更新
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            current_row = selected_rows[0].row()
            current_id = int(self.table.item(current_row, 0).text())
            if current_id == jid:
                # 全文リロードは重いので、ETAだけなら最後の行だけ書き換えたいが、
                # 簡易実装としてログ全体をセットし直す（ただし頻度が高いとチラつくので、末尾更新が望ましい）
                # 今回はシンプルにリフレッシュ
                self._update_log_view(jid)

    def update_table_status(self, jid, status, msg):
        """テーブルのステータス表示を更新"""
        row = self._find_row_by_id(jid)
        if row is None: return

        # Status Column
        item_status = self.table.item(row, 1)
        item_status.setText(status)
        
        # Color
        if status == STATUS_RUNNING:
            item_status.setBackground(QtGui.QColor("#3498db")) # Blue
            item_status.setForeground(QtGui.QColor("white"))
        elif status == STATUS_FINISHED:
            item_status.setBackground(QtGui.QColor("#2ecc71")) # Green
            item_status.setForeground(QtGui.QColor("white"))
        elif status == STATUS_ERROR:
            item_status.setBackground(QtGui.QColor("#e74c3c")) # Red
            item_status.setForeground(QtGui.QColor("white"))
        else:
            item_status.setBackground(QtGui.QColor("transparent"))
            item_status.setForeground(QtGui.QColor("#dcdcdc" if self.palette().windowText().color().lightness() > 128 else "black"))

        # Info Column
        self.table.item(row, 2).setText(msg)

    def on_worker_finished(self, jid):
        if jid in self.active_workers:
            del self.active_workers[jid]
        # 次のタスクをすぐに確認
        self.process_queue()

    def on_table_click(self, item):
        """行クリック時にログを表示"""
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
        """右クリックメニュー"""
        menu = QtWidgets.QMenu()
        delete_action = menu.addAction(self.strings["ctx_delete"])
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        
        if action == delete_action:
            self.delete_selected_task()

    def delete_selected_task(self):
        """タスク削除"""
        rows = self.table.selectionModel().selectedRows()
        if not rows: return
        
        row = rows[0].row()
        jid = int(self.table.item(row, 0).text())
        
        # 実行中なら停止は難しいが、とりあえずリストからは消す
        # 安全な停止はworkerにflagを立てる必要がある
        if jid in self.active_workers:
            # 実行中の場合はログに「削除されました」と出して、UIから消す
            # 実際のスレッド停止は _is_cancelled フラグで対応
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
    
    # ダークモードパレット（オプション）
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
