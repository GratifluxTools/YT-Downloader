"""Download yt-dlp / ffmpeg / ffprobe / deno for a release build (stdlib only, SHA-256 verified when published).

    python tools/fetch_bin.py --target windows --out bin_cache
    python tools/fetch_bin.py --target linux   --out bin_cache
"""
import argparse
import hashlib
import io
import re
import tarfile
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "YT-Downloader-build"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
        return r.read()


def decode_text(blob: bytes) -> str:
    """Checksum files made by PowerShell can be UTF-16 (with BOM); handle both."""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in blob[:64]:
        return blob.decode("utf-16", "replace")
    return blob.decode("utf-8-sig", "replace")


def parse_sha(text: str, name: str = ""):
    """Return the sha256 for `name` (line mentioning it), else the only/first hash in the text."""
    hashes = [(ln, m.group(0).lower()) for ln in text.splitlines()
              for m in [re.search(r"\b[0-9a-fA-F]{64}\b", ln)] if m]
    for ln, h in hashes:
        if name and name in ln:
            return h
    return hashes[0][1] if hashes and (len(hashes) == 1 or not name) else None


def sums_lookup(url: str, name: str):
    try:
        return parse_sha(decode_text(get(url)), name)
    except Exception as e:
        print(f"  (no checksum list: {e})")
    return None


def fetch(url: str, expected=None) -> bytes:
    print("GET", url)
    blob = get(url)
    actual = hashlib.sha256(blob).hexdigest()
    if expected and actual != expected:
        raise SystemExit(f"checksum mismatch: {url}\n  expected {expected}\n  actual   {actual}")
    print(f"  ok {len(blob) / 1e6:.1f} MB" + ("  (sha256 verified)" if expected else "  (unverified)"))
    return blob


def put(out: Path, name: str, data: bytes, mode=0o755):
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data)
    (out / name).chmod(mode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["windows", "linux"], required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out, win = Path(a.out), a.target == "windows"

    # yt-dlp (official standalone executable; bundles yt-dlp-ejs and can self-update with -U)
    ytd = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
    asset = "yt-dlp.exe" if win else "yt-dlp_linux"
    put(out, "yt-dlp.exe" if win else "yt-dlp", fetch(ytd + asset, sums_lookup(ytd + "SHA2-256SUMS", asset)))

    # ffmpeg + ffprobe (BtbN FFmpeg-Builds)
    fb = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    asset = "ffmpeg-master-latest-win64-gpl.zip" if win else "ffmpeg-master-latest-linux64-gpl.tar.xz"
    blob = fetch(fb + asset, sums_lookup(fb + "checksums.sha256", asset))
    want = {"ffmpeg.exe", "ffprobe.exe"} if win else {"ffmpeg", "ffprobe"}
    if win:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                if "/bin/" in n and Path(n).name in want:
                    put(out, Path(n).name, z.read(n))
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as t:
            for m in t.getmembers():
                if m.isfile() and "/bin/" in m.name and Path(m.name).name in want:
                    put(out, Path(m.name).name, t.extractfile(m).read())

    # deno (JavaScript runtime that yt-dlp needs for YouTube)
    dn = "https://github.com/denoland/deno/releases/latest/download/"
    asset = "deno-x86_64-pc-windows-msvc.zip" if win else "deno-x86_64-unknown-linux-gnu.zip"
    exp = sums_lookup(dn + asset + ".sha256sum", asset)
    with zipfile.ZipFile(io.BytesIO(fetch(dn + asset, exp))) as z:
        n = "deno.exe" if win else "deno"
        put(out, n, z.read(n))

    missing = [n for n in (want | {"deno.exe" if win else "deno", "yt-dlp.exe" if win else "yt-dlp"})
               if not (out / n).is_file()]
    if missing:
        raise SystemExit(f"missing after fetch: {missing}")
    print("bundle:", ", ".join(sorted(p.name for p in out.iterdir())))


if __name__ == "__main__":
    main()
