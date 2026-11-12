# YT-Downloader

yt-dlp ベースの動画・音声ダウンローダー（[Flet](https://flet.dev) 製 / Windows・Linux）。
`flet build` で、そのまま配布できるフォルダ（exe / 実行ファイル + Python 同梱）になります。

<p align="center"><img src="src/assets/icon.png" width="128" alt="icon"></p>

## 機能

- **URLのみ取得**: ダウンロードせずに、ストリームの直リンク（`yt-dlp -g` 相当）または、プレイリスト/チャンネルの動画ページURL一覧を表示。コピー・テキスト保存可
- **ブラウザのCookieを利用**: Chrome / Firefox / Edge / Brave / Chromium / Opera / Vivaldi（プロファイル指定可）。`cookies.txt` の読み込みにも対応
- **ライブ配信・プレミア公開**: 開始前のURLを追加すると、開始まで待機して自動で録画開始（`--wait-for-video`）。「最初から録画」（YouTube）、停止しても録画済み分を再生できる形で保存
- **Linux 対応**（Windows と同じ GUI）
- 複数URLの一括追加 / 同時実行数の指定 / プレイリスト対応 / 字幕埋め込み / 停止・再試行・削除 / タスクごとのログ / 設定の保存 / 日本語・English
- yt-dlp・ffmpeg・Deno（YouTube に必要な JavaScript ランタイム）を同梱。「yt-dlp 更新」で最新版に更新（SHA-256 検証付き）。未同梱の環境でも初回に自動取得

## 使い方

### Windows
`YT-Downloader-windows.zip` を展開し、`yt_downloader.exe` を実行。

### Linux
```bash
unzip YT-Downloader-linux.zip -d YT-Downloader && cd YT-Downloader
./yt_downloader          # そのまま起動
./install.sh             # メニューに登録（~/.local/share、root 不要） / 削除は ./install.sh --remove
```
- フォルダ選択ダイアログに `zenity` または `kdialog` が必要です（`sudo apt install zenity`）
- 日本語表示には CJK フォントが必要です（`sudo apt install fonts-noto-cjk`）
- GTK3 が必要です（デスクトップ環境なら通常は導入済み）

### YouTube について
yt-dlp 2025.11.12 以降、YouTube には JavaScript ランタイム（Deno 推奨）が必要です。リリース版には Deno を同梱しています。ソースから実行する場合は別途導入してください。

### Cookie の注意
Windows の Chrome は Cookie の復号に失敗することがあります。その場合は Firefox を使うか、`cookies.txt` を読み込んでください。

## ビルド後のファイル構成

`flet build` の出力に、同梱ツール用の `bin/` が加わった形です。

```
YT-Downloader-windows/
├─ yt_downloader.exe
├─ flutter_windows.dll / python312.dll / *_plugin.dll / vcruntime140*.dll ...
├─ data/            # flutter_assets（app.zip = アプリ本体）, app.so, icudtl.dat
├─ DLLs/  Lib/  site-packages/   # 同梱 Python 3.12
└─ bin/             # yt-dlp.exe, ffmpeg.exe, ffprobe.exe, deno.exe
```
Linux 版も同様（`yt_downloader`, `lib/`, `data/`, `bin/`, ほか `install.sh` など）。

## 開発

```
src/main.py      UI（Flet）
src/core.py      ロジック（UI非依存: コマンド生成 / 実行・停止 / URL取得 / ツール取得）
src/i18n.py      文言（ja / en）
src/assets/      icon.png（flet build が各OS用アイコンに変換）
tools/           make_icons.py（アイコン生成）, fetch_bin.py（同梱ツール取得）
tests/           core.py のテスト（擬似 yt-dlp を使用）
packaging/       Linux 用 .desktop / install.sh
```

```bash
pip install -r requirements.txt
cd src && python main.py                    # 実行（yt-dlp が無ければ初回に取得を案内）
python -m unittest discover -s tests -v     # テスト（Linux/macOS）
pip install "flet[cli]==0.28.3" && flet build windows   # または linux
```
Release を公開すると GitHub Actions が Windows / Linux 版をビルドして添付します（タグ `vX.Y.Z` からバージョンを埋め込み）。
アイコンを変えるときは `python tools/make_icons.py`（要 Pillow）。

## 旧版からの移行

旧 `downloader.py`（PySide6 版）と旧ワークフローは不要になります。削除して、このリポジトリ構成に置き換えてください。
旧版からの主な変更: 全編再エンコード（`--recode-video`）をやめコンテナへの結合に変更（高速・無劣化）、
「4K/2K」選択が最高画質になる不具合の修正、`wav`/`webm` でのサムネ埋め込みエラー回避、
停止が実際にプロセスを止めるよう修正、Linux で保存先を開けない問題の修正。
