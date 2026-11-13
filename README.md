# YT-Downloader

yt-dlp ベースの動画・音声ダウンローダー（Windows / Linux）。[Flet](https://flet.dev) 製のデスクトップアプリです（ブラウザは使いません）。
`flet build` で、exe（Linux は実行ファイル）+ Python 同梱のフォルダになります。

<p align="center"><img src="src/assets/icon.png" width="128" alt="icon"></p>

## 機能

元の機能はすべて引き継いでいます（下の対応表）。追加した機能:

- **URLのみ取得**: ダウンロードせずに、ストリームの直リンク（`yt-dlp -g` 相当）または、プレイリスト/チャンネルの動画ページURL一覧を表示。コピー・`.txt` 保存可
- **ブラウザのCookieを利用**: Chrome / Firefox / Edge / Brave / Chromium / Opera / Vivaldi（プロファイル指定可）。`cookies.txt` の読み込みにも対応
- **ライブ配信・プレミア公開**: 開始前のURLを追加すると、開始まで待機して自動で録画開始（`--wait-for-video`）。「最初から録画」（YouTube）。停止しても録画済み分を再生できる形で保存
- **Linux 対応**
- 複数URLの一括追加 / プレイリスト / 字幕埋め込み / 停止・再試行 / 同時ダウンロード数の変更（1〜6）/ 設定の保存
- yt-dlp・ffmpeg・Deno（YouTube に必要な JavaScript ランタイム）を同梱。「yt-dlp 更新」で最新版へ（SHA-256 検証付き）。未同梱の環境でも初回に自動取得

## 元の機能との対応

| 元の機能 | 状態 |
|---|---|
| URL入力 + 「URL 追加」 / Enterで追加 | ✅ （複数URL可。Shift+Enterで改行） |
| 保存先の選択 / 「保存先を開く」 | ✅ |
| 形式 mp4 / mp3 / mkv / wav / webm / m4a | ✅ （flac / aac を追加） |
| 解像度 Best〜360p / 音質 320〜96kbps（形式で切替） | ✅ （4K・2K が最高画質になる不具合を修正） |
| サムネ・メタデータの埋め込み（既定オン） | ✅ |
| ファイル名の指定（任意） | ✅ （yt-dlp テンプレート可） |
| cookies.txt の読み込み | ✅ |
| 最大3件の同時ダウンロード | ✅ （既定3、設定で変更可） |
| キュー表（ID / 状態 / 進捗・ETA / URL、状態の色分け） | ✅ |
| タスクをクリックでログ表示（「Task #N Logs」、進捗行は上書き） | ✅ |
| 右クリックでタスク削除 | ✅ （停止・再試行・URLコピー・ログ全体も追加） |
| 「yt-dlp 更新」（キュー先頭で優先実行） | ✅ |
| 使い方 / ABOUT | ✅ |
| 英語 / 日本語（既定は OS の言語） | ✅ |
| 完了時のデスクトップ通知（ウィンドウが前面でないとき） | ✅ （失敗時の通知も追加） |
| GitHub の最新リリース自動チェック | ✅ （新しい版のときだけ表示。表示言語に対応） |
| 同梱 yt-dlp / ffmpeg の利用 | ✅ （`bin/` に同梱） |
| ダークテーマ・ウィンドウタイトル | ✅ |

意図的に変えた点:
- 映像の保存方法: 全編再エンコード（`--recode-video`）をやめ、コンテナへの結合（`--merge-output-format`）に変更。高速で劣化しません。`webm` は、取得した映像・音声が webm に入らない場合に mkv になることがあります
- 指定した解像度の映像が無い動画は、最高画質に切り替えず失敗します（元は黙って最高画質へ）
- 停止・削除は実際に yt-dlp のプロセスを止めます（元は止まらず実行が続きました）

## 使い方

### Windows
`YT-Downloader-windows.zip` を展開し、`yt_downloader.exe` を実行。

### Linux
```bash
unzip YT-Downloader-linux.zip -d YT-Downloader && cd YT-Downloader
./yt_downloader          # そのまま起動
./install.sh             # メニューに登録（~/.local/share、root 不要） / 削除は ./install.sh --remove
```
- フォルダ・ファイルの選択ダイアログに `zenity` か `kdialog` が必要です（`sudo apt install zenity`）。日本語表示には CJK フォント（`fonts-noto-cjk` 等）、GTK3 も必要です
- 完了通知は `notify-send`（libnotify）があれば表示されます

### YouTube について
yt-dlp 2025.11.12 以降、YouTube には JavaScript ランタイム（Deno 推奨）が必要です。リリース版には Deno を同梱しています。ソースから実行する場合は別途導入してください。

### Cookie の注意
Windows の Chrome は Cookie の復号に失敗することがあります。その場合は Firefox を使うか、`cookies.txt` を読み込んでください。

## 配布フォルダの構成

`flet build` の出力に、同梱ツール用の `bin/` が加わった形です。

```
YT-Downloader-windows/
├─ yt_downloader.exe
├─ flutter_windows.dll / python312.dll / *_plugin.dll ...
├─ data/            # flutter_assets（app.zip = アプリ本体）, app.so, icudtl.dat
├─ DLLs/  Lib/  site-packages/   # 同梱 Python 3.12
└─ bin/             # yt-dlp.exe, ffmpeg.exe, ffprobe.exe, deno.exe
```
ユーザーデータ（設定・更新した yt-dlp・cookies）は `%APPDATA%\YT-Downloader`（Linux: `~/.local/share/YT-Downloader`）に保存されます。

## 開発

```
src/main.py      画面（Flet）
src/manager.py   キュー・スケジューラ・設定（UI 非依存）
src/core.py      yt-dlp のコマンド生成 / 実行・停止 / URL取得 / ツール取得 / 通知
src/i18n.py      文言（ja / en）
src/assets/      icon.png（flet build が各OS用アイコンに変換）
tools/           make_icons.py（アイコン生成）, fetch_bin.py（同梱ツール取得）
tests/           core / manager のテスト、画面（実際の Flet 部品）のテスト
packaging/       Linux 用 .desktop / install.sh、アイコン
```

```bash
pip install -r requirements.txt
cd src && python main.py                    # 実行
python -m unittest discover -s tests -v     # テスト（Linux/macOS。画面のテストは flet があれば実行）
pip install "flet[cli]==0.28.3" && flet build windows     # または linux
```
Release を公開すると GitHub Actions が Windows / Linux 版をビルドして添付します（タグ `vX.Y.Z` からバージョンを埋め込み）。

### 画面のレイアウトについて
Flet では、`Row(wrap=True)` の中や、スクロールする `Column` の直下に `expand` を置くとレイアウトが壊れます（過去にそれで画面が崩れました）。
`tests/test_ui_tree.py` が実際の Flet 部品で画面を組み立て、この種の構造と横幅の溢れを検査します（CI でも実行）。画面を追加・変更するときは、このテストを通してください。
