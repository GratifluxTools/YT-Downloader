"""Tiny i18n helper: t("key") / t("key", n=1)."""

LANG = "en"

STRINGS = {
    "en": {
        "title": "YT-Downloader",
        "urls_hint": "Paste URLs here (one per line). Live / premiere URLs can be added before they start.",
        "add": "Add to queue",
        "get_urls": "Get URLs only",
        "kind_stream": "Direct stream URLs",
        "kind_page": "Video page URLs (playlist / channel)",
        "settings": "Settings",
        "outdir": "Output folder",
        "browse": "Browse",
        "open_folder": "Open folder",
        "filename": "Filename (optional, yt-dlp template OK)",
        "format": "Format",
        "quality": "Resolution",
        "audio_quality": "Audio quality",
        "best": "Best",
        "thumb": "Embed thumbnail",
        "meta": "Embed metadata",
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
        "queue": "Queue",
        "log": "Log",
        "log_empty": "Select a task to see its log.",
        "update_tools": "Update yt-dlp",
        "clear_done": "Clear finished",
        "concurrent": "Concurrent",
        "language": "Language",
        "usage": "Usage",
        "about": "About",
        "status": {
            "Pending": "Pending", "Running": "Running", "Waiting": "Waiting",
            "Live": "Recording", "Finished": "Finished", "Error": "Error", "Cancelled": "Cancelled",
        },
        "stop": "Stop",
        "retry": "Retry",
        "copy_url": "Copy URL",
        "delete": "Delete",
        "show_log": "Show log",
        "open_file_folder": "Open folder",
        "warn_ytdlp": "yt-dlp was not found. Press 'Update yt-dlp' to download it automatically.",
        "warn_ffmpeg": "ffmpeg was not found (it is downloaded together with yt-dlp on update). Merging/converting will fail.",
        "warn_js": "No JavaScript runtime (Deno recommended). Some YouTube formats may be unavailable.",
        "ask_install_title": "yt-dlp not found",
        "ask_install_msg": "yt-dlp was not found. Download it now from the official release?",
        "yes": "Yes",
        "no": "No",
        "ok": "OK",
        "close": "Close",
        "copy": "Copy",
        "save": "Save...",
        "copied": "Copied",
        "no_url": "Please enter at least one http/https URL.",
        "fetching": "Fetching URLs...",
        "result_title": "URL result",
        "update_avail_title": "Update available",
        "update_avail_msg": "Version {v} is available on GitHub. Open the download page?",
        "open": "Open",
        "later": "Later",
        "task_done": "Task #{n} finished",
        "task_failed": "Task #{n} failed",
        "confirm_exit_title": "Quit",
        "confirm_exit_msg": "Tasks are still running. Stop them and quit?",
        "quit": "Stop and quit",
        "cancel": "Cancel",
        "usage_text": (
            "1. Paste one or more URLs (one per line) and press 'Add to queue'.\n"
            "2. Choose folder / format / resolution in Settings.\n\n"
            "Get URLs only: shows direct stream URLs (like yt-dlp -g) or the video page URLs of a "
            "playlist / channel, without downloading.\n\n"
            "Cookies: choose a browser to read its login cookies directly, or import a cookies.txt. "
            "(Chrome on Windows may fail to decrypt cookies - try Firefox or cookies.txt.)\n\n"
            "Live / Premiere: add the URL before it starts. With 'Wait' enabled the task waits and starts "
            "recording automatically. Press Stop to end a recording; what was recorded so far is kept.\n\n"
            "Linux: file dialogs need zenity or kdialog; Japanese text needs a CJK font (e.g. fonts-noto-cjk)."
        ),
        "about_text": "YT-Downloader\nVersion: {v}\n\nCreator: Gratiflux Tools\n{url}",
    },
    "ja": {
        "title": "YT-Downloader",
        "urls_hint": "URLを貼り付け（1行に1つ）。ライブ配信・プレミア公開は開始前のURLも追加できます。",
        "add": "キューに追加",
        "get_urls": "URLのみ取得",
        "kind_stream": "ストリームURL（直リンク）",
        "kind_page": "動画ページURL一覧（プレイリスト/チャンネル）",
        "settings": "設定",
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
        "queue": "キュー",
        "log": "ログ",
        "log_empty": "タスクを選択するとログが表示されます。",
        "update_tools": "yt-dlp 更新",
        "clear_done": "完了を一覧から消去",
        "concurrent": "同時実行",
        "language": "言語",
        "usage": "使い方",
        "about": "ABOUT",
        "status": {
            "Pending": "待機中", "Running": "実行中", "Waiting": "開始待ち",
            "Live": "録画中", "Finished": "完了", "Error": "エラー", "Cancelled": "中止",
        },
        "stop": "停止",
        "retry": "再試行",
        "copy_url": "URLをコピー",
        "delete": "削除",
        "show_log": "ログを表示",
        "open_file_folder": "フォルダを開く",
        "warn_ytdlp": "yt-dlp が見つかりません。「yt-dlp 更新」を押すと自動でダウンロードします。",
        "warn_ffmpeg": "ffmpeg が見つかりません（更新時に yt-dlp と一緒に自動取得します）。結合・変換に失敗します。",
        "warn_js": "JavaScriptランタイム(Deno推奨)が見つかりません。YouTubeで一部の形式が取得できない場合があります。",
        "ask_install_title": "yt-dlp が見つかりません",
        "ask_install_msg": "yt-dlp が見つかりません。公式リリースから今すぐダウンロードしますか？",
        "yes": "はい",
        "no": "いいえ",
        "ok": "OK",
        "close": "閉じる",
        "copy": "コピー",
        "save": "保存...",
        "copied": "コピーしました",
        "no_url": "http/https のURLを1つ以上入力してください。",
        "fetching": "URLを取得中...",
        "result_title": "URL取得結果",
        "update_avail_title": "アップデート",
        "update_avail_msg": "GitHubに新しいバージョン {v} があります。ダウンロードページを開きますか？",
        "open": "開く",
        "later": "後で",
        "task_done": "タスク #{n} が完了しました",
        "task_failed": "タスク #{n} が失敗しました",
        "confirm_exit_title": "終了",
        "confirm_exit_msg": "実行中のタスクがあります。停止して終了しますか？",
        "quit": "停止して終了",
        "cancel": "キャンセル",
        "usage_text": (
            "1. URLを貼り付け（1行に1つ）、「キューに追加」を押します。\n"
            "2. 保存先・形式・解像度などは「設定」で選びます。\n\n"
            "URLのみ取得: ダウンロードせず、ストリームの直リンク(yt-dlp -g 相当)、または"
            "プレイリスト/チャンネルの動画ページURL一覧を表示します。\n\n"
            "Cookie: ブラウザを選ぶとそのログイン情報を直接読み込みます。cookies.txt の読み込みも可能です。"
            "（Windowsの Chrome は復号に失敗することがあります。Firefox か cookies.txt をお試しください）\n\n"
            "ライブ/プレミア: 開始前にURLを追加できます。「待機」を有効にすると開始まで待って自動で録画を始めます。"
            "録画を終えるには「停止」を押します（それまでの録画分は残ります）。\n\n"
            "Linux: ファイル選択に zenity か kdialog が必要です。日本語表示にはCJKフォント(fonts-noto-cjk等)が必要です。"
        ),
        "about_text": "YT-Downloader\nVersion: {v}\n\nCreator: Gratiflux Tools\n{url}",
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
