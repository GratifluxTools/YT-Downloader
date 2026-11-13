"""UI strings (ja / en)."""

LANG = "en"

STRINGS = {
    "en": {
        "title": "yt-dlp Downloader Pro",
        "tab_downloads": "Downloads",
        "tab_settings": "Settings",
        "urls_hint": "Paste URLs here (Enter = add, Shift+Enter = new line). Live / premiere URLs can be added before they start.",
        "add": "Add to queue",
        "get_urls": "Get URLs only",
        "kind_stream": "Direct stream URLs",
        "kind_page": "Video page URLs (list / channel)",
        "outdir": "Output folder",
        "browse": "Browse",
        "open_folder": "Open Folder",
        "filename": "Filename (optional, yt-dlp template OK)",
        "format": "Format",
        "quality": "Resolution",
        "audio_quality": "Audio Quality",
        "best": "Best",
        "thumb": "Embed Thumbnail",
        "meta": "Embed Metadata",
        "subs": "Embed subtitles (ja/en)",
        "playlist": "Whole playlist",
        "browser_cookie": "Cookies from browser",
        "browser_none": "Don't use",
        "profile": "Profile (optional)",
        "cookies_file": "Import cookies.txt",
        "cookies_none": "No cookies.txt",
        "clear": "Clear",
        "live": "Live / Premiere",
        "live_wait": "Wait for the start and record automatically",
        "live_from_start": "Record from the beginning (YouTube)",
        "live_interval": "Re-check (sec)",
        "queue_empty": "No tasks yet. Paste a URL above and press \"Add to queue\".",
        "log_empty": "Select a task to view its logs.",
        "log_title": "Task #{n} Logs",
        "update_tools": "Update yt-dlp",
        "clear_done": "Clear finished",
        "concurrent": "Concurrent downloads",
        "language": "Language",
        "usage": "Usage",
        "about": "About",
        "quit_app": "Quit",
        "status": {
            "Pending": "Pending", "Running": "Running", "Waiting": "Waiting",
            "Live": "Recording", "Finished": "Finished", "Error": "Error", "Cancelled": "Cancelled",
        },
        "stop": "Stop",
        "retry": "Retry",
        "copy_url": "Copy URL",
        "delete": "Delete Task",
        "show_log": "Show full log",
        "ctx_title": "Task #{n}",
        "notify_title": "Download Complete",
        "notify_msg": "Task #{n} has finished.",
        "notify_err_title": "Download Failed",
        "notify_err_msg": "Task #{n} failed. Check the log.",
        "warn_ytdlp": "yt-dlp was not found. Press \"Update yt-dlp\" to download it automatically.",
        "warn_ffmpeg": "ffmpeg was not found (it is downloaded together with yt-dlp on update). Merging/converting will fail.",
        "warn_js": "No JavaScript runtime (Deno recommended). Some YouTube formats may be unavailable.",
        "ask_install_title": "yt-dlp not found",
        "ask_install_msg": "yt-dlp was not found. Download it now from the official release?",
        "yes": "Yes",
        "no": "No",
        "close": "Close",
        "cancel": "Cancel",
        "copy": "Copy",
        "save": "Save as .txt",
        "copied": "Copied",
        "no_url": "Please enter at least one http/https URL.",
        "fetching": "Fetching...",
        "result_title": "URL result",
        "added": "{n} added to the queue",
        "update_avail_title": "Update Available",
        "update_avail_msg": "A new version ({v}) of the application is available on GitHub.\nWould you like to open the download page?",
        "open": "Open",
        "later": "Later",
        "confirm_quit_title": "Quit",
        "confirm_quit_msg": "Tasks are still running. Stop them and quit?",
        "pick_folder": "Select Folder",
        "cookies_saved": "cookies.txt imported",
        "usage_title": "How to Use",
        "usage_text": (
            "1. Paste one or more URLs (one per line) in the top bar and press Enter (Shift+Enter = new line).\n"
            "2. Choose format / resolution (top) and folder etc. (Settings tab).\n"
            "3. Click 'Add to queue'. Downloads start automatically (3 at a time by default).\n\n"
            "Get URLs only: shows direct stream URLs (like yt-dlp -g) or the video page URLs of a "
            "playlist / channel, without downloading.\n\n"
            "Cookies: choose a browser to read its login cookies directly, or import a cookies.txt. "
            "(Chrome on Windows may fail to decrypt cookies - try Firefox or cookies.txt.)\n\n"
            "Live / Premiere: add the URL before it starts. With 'Wait' enabled the task waits and starts "
            "recording automatically. Press Stop to end a recording; what was recorded so far is kept.\n\n"
            "Click a task to see its log. Right-click a task for Stop / Retry / Copy URL / Delete."
        ),
        "about_text": "YT-Downloader Pro\nVersion: {v}\n\nCreator: Gratiflux Tools\nGitHub: {url}",
    },
    "ja": {
        "title": "yt-dlp ダウンローダー Pro",
        "tab_downloads": "ダウンロード",
        "tab_settings": "設定",
        "urls_hint": "URLを貼り付け（Enterで追加、Shift+Enterで改行）。ライブ配信・プレミア公開は開始前のURLも追加できます。",
        "add": "キューに追加",
        "get_urls": "URLのみ取得",
        "kind_stream": "ストリームURL（直リンク）",
        "kind_page": "動画ページURL一覧（リスト/チャンネル）",
        "outdir": "保存先フォルダ",
        "browse": "参照",
        "open_folder": "保存先を開く",
        "filename": "ファイル名（任意・yt-dlpテンプレート可）",
        "format": "形式",
        "quality": "解像度",
        "audio_quality": "音質",
        "best": "最高",
        "thumb": "サムネを埋め込む",
        "meta": "メタデータを埋め込む",
        "subs": "字幕を埋め込む(ja/en)",
        "playlist": "プレイリスト全体",
        "browser_cookie": "ブラウザのCookieを利用",
        "browser_none": "使用しない",
        "profile": "プロファイル（任意）",
        "cookies_file": "cookies.txt をインポート",
        "cookies_none": "cookies.txt 未選択",
        "clear": "解除",
        "live": "ライブ配信 / プレミア公開",
        "live_wait": "開始まで待機して自動で録画開始",
        "live_from_start": "配信を最初から録画（YouTube）",
        "live_interval": "再確認(秒)",
        "queue_empty": "タスクはまだありません。上にURLを貼り付けて「キューに追加」を押してください。",
        "log_empty": "タスクを選択するとここにログが表示されます。",
        "log_title": "タスク #{n} のログ",
        "update_tools": "yt-dlp 更新",
        "clear_done": "完了を一覧から消去",
        "concurrent": "同時ダウンロード数",
        "language": "言語",
        "usage": "使い方",
        "about": "ABOUT",
        "quit_app": "終了",
        "status": {
            "Pending": "待機中", "Running": "実行中", "Waiting": "開始待ち",
            "Live": "録画中", "Finished": "完了", "Error": "エラー", "Cancelled": "中止",
        },
        "stop": "停止",
        "retry": "再試行",
        "copy_url": "URLをコピー",
        "delete": "タスクを削除",
        "show_log": "ログ全体を表示",
        "ctx_title": "タスク #{n}",
        "notify_title": "ダウンロード完了",
        "notify_msg": "タスク #{n} が完了しました。",
        "notify_err_title": "ダウンロード失敗",
        "notify_err_msg": "タスク #{n} が失敗しました。ログを確認してください。",
        "warn_ytdlp": "yt-dlp が見つかりません。「yt-dlp 更新」を押すと自動でダウンロードします。",
        "warn_ffmpeg": "ffmpeg が見つかりません（更新時に yt-dlp と一緒に自動取得します）。結合・変換に失敗します。",
        "warn_js": "JavaScriptランタイム(Deno推奨)が見つかりません。YouTubeで一部の形式が取得できない場合があります。",
        "ask_install_title": "yt-dlp が見つかりません",
        "ask_install_msg": "yt-dlp が見つかりません。公式リリースから今すぐダウンロードしますか？",
        "yes": "はい",
        "no": "いいえ",
        "close": "閉じる",
        "cancel": "キャンセル",
        "copy": "コピー",
        "save": ".txt で保存",
        "copied": "コピーしました",
        "no_url": "http/https のURLを1つ以上入力してください。",
        "fetching": "取得中...",
        "result_title": "URL取得結果",
        "added": "{n} 件をキューに追加しました",
        "update_avail_title": "アップデート",
        "update_avail_msg": "GitHubに新しいバージョン ({v}) があります。\nダウンロードページを開きますか？",
        "open": "開く",
        "later": "後で",
        "confirm_quit_title": "終了",
        "confirm_quit_msg": "実行中のタスクがあります。停止して終了しますか？",
        "pick_folder": "フォルダを選択",
        "cookies_saved": "cookies.txt を取り込みました",
        "usage_title": "使い方",
        "usage_text": (
            "1. 上部のバーにURLを入力します（複数は1行に1つ。Enterで追加、Shift+Enterで改行）。\n"
            "2. 形式・解像度（上部）と保存先など（設定タブ）を選びます。\n"
            "3. 「キューに追加」を押すと、自動でダウンロードが始まります（既定は3件まで同時）。\n\n"
            "URLのみ取得: ダウンロードせず、ストリームの直リンク(yt-dlp -g 相当)、または"
            "プレイリスト/チャンネルの動画ページURL一覧を表示します。\n\n"
            "Cookie: ブラウザを選ぶとそのログイン情報を直接読み込みます。cookies.txt の読み込みも可能です。"
            "（Windowsの Chrome は復号に失敗することがあります。Firefox か cookies.txt をお試しください）\n\n"
            "ライブ/プレミア: 開始前にURLを追加できます。「待機」を有効にすると開始まで待って自動で録画を始めます。"
            "録画を終えるには「停止」を押します（それまでの録画分は残ります）。\n\n"
            "タスクをクリックでログ表示。右クリックで 停止 / 再試行 / URLコピー / 削除 ができます。"
        ),
        "about_text": "YT-Downloader Pro\nVersion: {v}\n\nCreator: Gratiflux Tools\nGitHub: {url}",
    },
}


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang if lang in STRINGS else "en"


def t(key: str, **kw):
    v = STRINGS.get(LANG, STRINGS["en"]).get(key)
    if v is None:
        v = STRINGS["en"].get(key, key)
    return v.format(**kw) if kw and isinstance(v, str) else v
