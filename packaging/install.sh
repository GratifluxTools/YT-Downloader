#!/usr/bin/env bash
# YT-Downloader (Linux): ユーザー領域へ登録し、アプリメニューに追加します。root 不要。
#   ./install.sh            インストール
#   ./install.sh --remove   アンインストール
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DEST/YT-Downloader-app"
DESKTOP="$DEST/applications/yt-downloader.desktop"
ICON="$DEST/icons/hicolor/256x256/apps/yt-downloader.png"

if [[ "${1:-}" == "--remove" ]]; then
  rm -rf "$APP" "$DESKTOP" "$ICON"
  echo "removed."; exit 0
fi

[[ -x "$HERE/yt_downloader" ]] || { echo "yt_downloader が見つかりません ($HERE)"; exit 1; }
rm -rf "$APP"; mkdir -p "$APP" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
cp -a "$HERE"/. "$APP"/
rm -f "$APP/install.sh" "$APP/yt-downloader.desktop" "$APP/yt-downloader.png"
sed "s|__EXEC__|$APP/yt_downloader|" "$HERE/yt-downloader.desktop" > "$DESKTOP"
cp "$HERE/yt-downloader.png" "$ICON"
command -v update-desktop-database >/dev/null && update-desktop-database "$DEST/applications" || true
echo "installed: $APP"
echo "メニューから YT-Downloader を起動できます。(ファイル選択には zenity か kdialog が必要です)"
