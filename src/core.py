"""YT-Downloader core (UI-independent).

yt-dlp / ffmpeg / deno are used as external executables (subprocess):
  * official yt-dlp executables bundle yt-dlp-ejs and can self-update (-U)
  * a running download can be stopped cleanly (process-group signal / taskkill)
"""
import hashlib
import io
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

try:
    from app_version import __version__
except Exception:  # pragma: no cover
    __version__ = "0.0.0"

APP_NAME = "YT-Downloader"
REPO_URL = "https://github.com/GratifluxTools/YT-Downloader"
API_URL = "https://api.github.com/repos/GratifluxTools/YT-Downloader/releases/latest"
YTDLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
FFMPEG_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

# ---- job / task status ------------------------------------------------------
PENDING, RUNNING, WAITING, LIVE = "Pending", "Running", "Waiting", "Live"
FINISHED, ERROR, CANCELLED = "Finished", "Error", "Cancelled"
FINAL = (FINISHED, ERROR, CANCELLED)

AUDIO_FORMATS = ["mp3", "m4a", "wav", "flac", "aac"]
VIDEO_FORMATS = ["mp4", "mkv", "webm"]
THUMB_FORMATS = ["mp3", "m4a", "mp4", "mkv", "flac"]  # containers that can embed a thumbnail
QUALITIES = ["best", "2160", "1440", "1080", "720", "480", "360"]
AUDIO_QUALITIES = ["320kbps", "256kbps", "192kbps", "128kbps", "96kbps"]
BROWSERS = ["chrome", "firefox", "edge", "brave", "chromium", "opera", "vivaldi"] + (["safari"] if IS_MAC else [])


# =============================================================================
# Paths / tools
# =============================================================================
def user_data_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def user_bin_dir() -> Path:
    return user_data_dir() / "bin"


def default_outdir() -> str:
    return str(Path.home() / "Downloads")


def _uniq(paths):
    out = []
    for p in paths:
        if p and p.is_dir() and p not in out:
            out.append(p)
    return out


def bundled_bin_dirs() -> list:
    """Where release builds put yt-dlp/ffmpeg/deno (<app>/bin). The app dir is found by several
    heuristics because embedded-Python layouts differ between Windows and Linux."""
    bases = []
    for v in (sys.executable, sys.argv[0] if sys.argv else "", __file__):
        if v:
            try:
                bases.append(Path(v).resolve().parent)
            except OSError:
                pass
    for v in (sys.prefix, sys.base_prefix, os.getcwd()):
        if v:
            bases.append(Path(v))
    cands = []
    for b in bases:
        for d in (b, b.parent):
            cands += [d / "bin", d]
    return _uniq(cands)


def search_dirs() -> list:
    return _uniq([user_bin_dir()] + bundled_bin_dirs())


def _is_exec(p: Path) -> bool:
    if not p.is_file():
        return False
    if IS_WIN or os.access(p, os.X_OK):
        return True
    try:
        p.chmod(p.stat().st_mode | 0o755)
        return True
    except OSError:
        return False


def _find(names: list, which: Optional[str] = None) -> Optional[str]:
    for d in search_dirs():
        for n in names:
            if _is_exec(d / n):
                return str(d / n)
    return shutil.which(which) if which else None


def locate_ytdlp() -> Optional[str]:
    names = ["yt-dlp.exe"] if IS_WIN else ["yt-dlp", "yt-dlp_linux", "yt-dlp_linux_aarch64", "yt-dlp_macos"]
    return _find(names, "yt-dlp")


def locate_ffmpeg() -> Optional[str]:
    return _find(["ffmpeg.exe"] if IS_WIN else ["ffmpeg"], "ffmpeg")


def find_js_runtime() -> Optional[str]:
    """YouTube needs an external JavaScript runtime (Deno recommended; yt-dlp >= 2025.11.12)."""
    if _find(["deno.exe"] if IS_WIN else ["deno"], "deno"):
        return "deno"
    deno = Path.home() / ".deno" / "bin" / ("deno.exe" if IS_WIN else "deno")
    if deno.is_file():
        return "deno"
    for name in ("node", "bun", "qjs"):
        if shutil.which(name):
            return name
    return None


def child_env() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # The embedded interpreter may export these; they must not leak into yt-dlp.
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONUTF8"):
        env.pop(k, None)
    if not IS_WIN and env.get("LD_LIBRARY_PATH"):
        keep = [p for p in env["LD_LIBRARY_PATH"].split(":") if p and not any(
            p.startswith(str(d.parent)) for d in bundled_bin_dirs())]
        env["LD_LIBRARY_PATH"] = ":".join(keep)
        if not keep:
            env.pop("LD_LIBRARY_PATH")
    extra = [str(d) for d in search_dirs()]
    deno_bin = Path.home() / ".deno" / "bin"
    if deno_bin.is_dir():
        extra.append(str(deno_bin))
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])  # lets yt-dlp find deno / ffprobe
    return env


def popen_kwargs() -> dict:
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}  # own process group -> killpg also stops ffmpeg


def open_path(path: str) -> None:
    try:
        if IS_WIN:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], env=child_env())
    except Exception:
        pass


def ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)


# =============================================================================
# Downloading tools (first run / update when the bundled copy is read-only)
# =============================================================================
def _http_get(url: str, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _sha_from_sums(text: str, filename: str) -> Optional[str]:
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            return parts[0].lower()
    return None


def _verify(blob: bytes, sums_url: str, filename: str, log) -> None:
    try:
        expected = _sha_from_sums(_http_get(sums_url, 60).decode("utf-8", "replace"), filename)
    except Exception as e:
        log(f"WARNING: could not fetch checksums ({e})")
        return
    if expected and hashlib.sha256(blob).hexdigest() != expected:
        raise RuntimeError(f"Checksum mismatch: {filename}")


def ytdlp_asset() -> str:
    if IS_WIN:
        return "yt-dlp.exe"
    if IS_MAC:
        return "yt-dlp_macos"
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "yt-dlp_linux_aarch64"
    if m.startswith("armv7"):
        return "yt-dlp_linux_armv7l"
    return "yt-dlp_linux"


def _write_exec(dst: Path, data: bytes) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".new")
    tmp.write_bytes(data)
    if not IS_WIN:
        tmp.chmod(0o755)
    os.replace(tmp, dst)


def download_ytdlp(log: Callable[[str], None]) -> str:
    asset = ytdlp_asset()
    log(f"Downloading {asset} (official yt-dlp release) ...")
    blob = _http_get(YTDLP_BASE + asset, 300)
    _verify(blob, YTDLP_BASE + "SHA2-256SUMS", asset, log)
    dst = user_bin_dir() / ("yt-dlp.exe" if IS_WIN else "yt-dlp")
    _write_exec(dst, blob)
    log(f"Saved: {dst}")
    return str(dst)


def download_ffmpeg(log: Callable[[str], None]) -> str:
    if IS_WIN:
        asset = "ffmpeg-master-latest-win64-gpl.zip"
    elif IS_MAC:
        raise RuntimeError("macOS: please install ffmpeg with Homebrew (brew install ffmpeg)")
    else:
        arch = "linuxarm64" if platform.machine().lower() in ("aarch64", "arm64") else "linux64"
        asset = f"ffmpeg-master-latest-{arch}-gpl.tar.xz"
    log(f"Downloading {asset} (BtbN FFmpeg-Builds) ... this is large")
    blob = _http_get(FFMPEG_BASE + asset, 900)
    _verify(blob, FFMPEG_BASE + "checksums.sha256", asset, log)
    want = {"ffmpeg.exe", "ffprobe.exe"} if IS_WIN else {"ffmpeg", "ffprobe"}
    dst_dir = user_bin_dir()
    got = []
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n in z.namelist():
                if "/bin/" in n and Path(n).name in want:
                    _write_exec(dst_dir / Path(n).name, z.read(n))
                    got.append(Path(n).name)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as t:
            for m in t.getmembers():
                if m.isfile() and "/bin/" in m.name and Path(m.name).name in want:
                    _write_exec(dst_dir / Path(m.name).name, t.extractfile(m).read())  # type: ignore[union-attr]
                    got.append(Path(m.name).name)
    if not got:
        raise RuntimeError("ffmpeg not found in the downloaded archive")
    log("Saved: " + ", ".join(got))
    return str(dst_dir)


# =============================================================================
# Job / command builders
# =============================================================================
@dataclass
class Job:
    url: str = ""
    outdir: str = ""
    filename: str = ""          # optional; yt-dlp output template allowed
    ext: str = "mp4"
    quality: str = "best"       # "best" or a height such as "1080"
    audio_quality: str = "128kbps"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    subs: bool = False
    playlist: bool = False
    cookies_file: str = ""
    cookies_browser: str = ""   # chrome / firefox / ...
    browser_profile: str = ""
    live_wait: bool = True
    live_from_start: bool = False
    wait_interval: int = 15
    kind: str = "download"      # "download" | "update"


def cookie_args(job: Job) -> list:
    if job.cookies_browser:
        spec = job.cookies_browser + (":" + job.browser_profile if job.browser_profile else "")
        return ["--cookies-from-browser", spec]
    if job.cookies_file:
        return ["--cookies", job.cookies_file]
    return []


def js_runtime_args() -> list:
    rt = find_js_runtime()
    return ["--js-runtimes", rt] if rt and rt != "deno" else []  # only deno is enabled by default


def format_selector(job: Job) -> str:
    if job.ext in AUDIO_FORMATS:
        return "bestaudio/best"
    if str(job.quality).isdigit():
        h = f"[height<={job.quality}]"
        return f"bv*{h}+ba/b{h}"
    return "bv*+ba/b"


def build_download_cmd(ytdlp: str, ffmpeg: Optional[str], job: Job) -> list:
    name = job.filename.strip() if job.filename else "%(title)s"
    tmpl = f"{name}.%(ext)s"
    if job.playlist:
        tmpl = "%(playlist_title&{}/|)s%(playlist_index&{} - |)s" + tmpl
    cmd = [ytdlp, job.url, "-o", os.path.join(job.outdir, tmpl),
           "--no-mtime", "--newline", "--color", "never",
           "--yes-playlist" if job.playlist else "--no-playlist"]
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
    cmd += cookie_args(job) + js_runtime_args()

    # live streams / premieres
    if job.live_wait:
        iv = max(1, int(job.wait_interval))
        cmd += ["--wait-for-video", f"{iv}-{iv * 4}"]
    if job.live_from_start:
        cmd.append("--live-from-start")
    cmd.append("--hls-use-mpegts")  # a stopped recording stays playable

    if job.ext in AUDIO_FORMATS:
        cmd += ["-f", format_selector(job), "-x", "--audio-format", job.ext]
        q = re.sub(r"\D", "", job.audio_quality or "")
        if q and job.ext in ("mp3", "m4a", "aac"):
            cmd += ["--audio-quality", q + "K"]
    else:
        # merge into the container instead of --recode-video (which re-encodes everything)
        cmd += ["-f", format_selector(job), "--merge-output-format", job.ext]
        if job.ext == "mp4":
            cmd += ["-S", "res,ext:mp4:m4a"]
        elif job.ext == "webm":
            cmd += ["-S", "res,vcodec:vp9,acodec:opus"]
        if job.subs:
            cmd += ["--write-subs", "--sub-langs", "ja,en", "--embed-subs"]
    if job.embed_thumbnail and job.ext in THUMB_FORMATS:
        cmd.append("--embed-thumbnail")
    if job.embed_metadata:
        cmd.append("--embed-metadata")
    return cmd


def build_fetch_cmd(ytdlp: str, job: Job, kind: str) -> list:
    cmd = [ytdlp, "--no-warnings", "--color", "never"] + cookie_args(job) + js_runtime_args()
    if kind == "page":
        cmd += ["--flat-playlist", "--yes-playlist", "--print", "%(webpage_url,url)s"]
    else:  # direct stream URLs (like yt-dlp -g)
        cmd += ["--yes-playlist" if job.playlist else "--no-playlist", "-g", "-f", format_selector(job)]
    cmd.append(job.url)
    return cmd


def fetch_urls(jobs_kind: list) -> str:
    """URL-only mode. jobs_kind: [(Job, "stream"|"page")]. Returns text (one URL per line,
    failed inputs are reported as '# ...' comment lines). Raises RuntimeError if yt-dlp is missing."""
    ytdlp = locate_ytdlp()
    if not ytdlp:
        raise RuntimeError("yt-dlp not found")
    out, errs = [], []
    for job, kind in jobs_kind:
        try:
            r = subprocess.run(build_fetch_cmd(ytdlp, job, kind), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600, env=child_env(), **popen_kwargs())
        except Exception as e:
            errs.append(f"# {job.url}\n# ERROR: {e}")
            continue
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        if r.returncode == 0 and lines:
            out += lines
        else:
            msg = next((ln for ln in reversed(r.stderr.splitlines()) if ln.startswith("ERROR")), "") \
                or f"exit code {r.returncode}"
            errs.append(f"# {job.url}\n# {msg}")
    return "\n".join(out + ([""] if out and errs else []) + errs)


def salvage_partials(dests) -> list:
    """Make a stopped live recording usable by removing the .part suffix."""
    saved = []
    for p in dests:
        part = Path(str(p) + ".part")
        try:
            if part.is_file() and part.stat().st_size > 0:
                dst = Path(p)
                if dst.exists():
                    dst = dst.with_name(dst.stem + ".partial" + dst.suffix)
                part.rename(dst)
                saved.append(str(dst))
        except OSError:
            pass
    return saved


RE_PCT = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+~?\s*(\S+)(?:\s+in\s+\S+)?(?:\s+at\s+(\S+))?(?:\s+ETA\s+(\S+))?")
RE_LIVE = re.compile(r"\[download\]\s+(\S+)\s+at\s+(\S+)")
RE_REMAIN = re.compile(r"Remaining time until next attempt:\s*(\S+)")
RE_DEST = re.compile(r"\[download\] Destination:\s*(.+)$")


# =============================================================================
# Runner: one subprocess per task
# =============================================================================
class Runner:
    """Runs one job in a background thread.

    on_status(status, message, pct)   pct: 0..100 or None (indeterminate)
    on_log(line, replaces_last)       replaces_last=True for progress lines
    on_done()                         called once, after the final status
    """

    def __init__(self, job: Job, on_status, on_log, on_done):
        self.job, self.on_status, self.on_log, self.on_done = job, on_status, on_log, on_done
        self.proc: Optional[subprocess.Popen] = None
        self.cancelled = False
        self.is_live = False
        self.dests: list = []
        self.last_error = ""
        self._checking = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    # ---- stop --------------------------------------------------------------
    def cancel(self):
        self.cancelled = True
        if self.proc is not None:
            threading.Thread(target=self._terminate, daemon=True).start()

    def _terminate(self):
        p = self.proc
        if p is None:
            return
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return
        # While waiting for a stream the first SIGINT means "try now", hence two of them.
        for sig, wait in ((signal.SIGINT, 3), (signal.SIGINT, 4), (signal.SIGTERM, 4), (signal.SIGKILL, 0)):
            if p.poll() is not None:
                return
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            end = time.time() + wait
            while time.time() < end and p.poll() is None:
                time.sleep(0.1)

    # ---- main --------------------------------------------------------------
    def _log(self, text):
        self.on_log(text, False)

    def _run(self):
        try:
            if self.cancelled:
                self.on_status(CANCELLED, "", None)
                return
            self.on_status(RUNNING, "Starting...", None)
            if self.job.kind == "update":
                self._run_update()
            else:
                self._run_download()
        except Exception as e:
            self.on_status(ERROR, str(e), None)
        finally:
            self.on_done()

    def _run_update(self):
        ytdlp = locate_ytdlp()
        rc = 1
        try:
            if ytdlp and Path(ytdlp).parent == user_bin_dir():
                rc = self._execute([ytdlp, "-U"])  # self-update of the managed copy
                if rc != 0 and not self.cancelled:
                    download_ytdlp(self._log)
                    rc = 0
            else:  # missing, or a read-only bundled / OS-managed copy -> keep our own copy
                download_ytdlp(self._log)
                rc = 0
            if rc == 0 and not self.cancelled and not locate_ffmpeg():
                download_ffmpeg(self._log)
        except Exception as e:
            self._log(f"ERROR: {e}")
            self.last_error = str(e)
            rc = 1
        if self.cancelled:
            self.on_status(CANCELLED, "", None)
        elif rc == 0:
            self.on_status(FINISHED, "Updated", 100)
        else:
            self.on_status(ERROR, self.last_error or "Update Failed", None)

    def _run_download(self):
        job = self.job
        ytdlp = locate_ytdlp()
        if not ytdlp:
            self.on_status(ERROR, "yt-dlp not found", None)
            return
        rc = self._execute(build_download_cmd(ytdlp, locate_ffmpeg(), job))
        if self.cancelled:
            saved = salvage_partials(self.dests) if self.is_live else []
            self.on_status(CANCELLED, ("Saved: " + ", ".join(os.path.basename(s) for s in saved)) if saved else "", None)
        elif rc == 0:
            self.on_status(FINISHED, "Done", 100)
        else:
            self.on_status(ERROR, self.last_error or "Failed (Check Logs)", None)

    def _execute(self, cmd) -> int:
        if self.cancelled:
            return -1
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                universal_newlines=True, encoding="utf-8", errors="replace",
                env=child_env(), **popen_kwargs())
        except Exception as e:
            self._log(f"Process Error: {e}")
            self.last_error = str(e)
            return 1
        if self.cancelled:
            threading.Thread(target=self._terminate, daemon=True).start()

        for line in self.proc.stdout:  # universal newlines: "\r" progress lines are split too
            line = line.strip()
            if not line:
                continue
            replace = False
            m = None
            if line.startswith("[wait]"):
                replace, self._checking = True, False
                m = RE_REMAIN.search(line)
                self.on_status(WAITING, m.group(1) if m else "...", None)
            elif RE_PCT.search(line):
                replace, self._checking = True, False
                m = RE_PCT.search(line)
                parts = [f"{m.group(1)}%"]
                if m.group(4):
                    parts.append(f"ETA {m.group(4)}")
                if m.group(3):
                    parts.append(m.group(3))
                self.on_status(RUNNING, "  ".join(parts), float(m.group(1)))
            elif RE_LIVE.search(line):  # no percentage -> live recording
                replace, self._checking = True, False
                self.is_live = True
                m = RE_LIVE.search(line)
                self.on_status(LIVE, f"{m.group(1)} @ {m.group(2)}", None)
            else:
                m = RE_DEST.search(line)
                if m:
                    self.dests.append(m.group(1).strip())
                if line.startswith("ERROR:"):
                    self.last_error = line[6:].strip()
                if line.startswith("[") and self.job.live_wait and not self.is_live and not self._checking:
                    self._checking = True  # a wait cycle ended and yt-dlp is re-checking
                    self.on_status(RUNNING, "Checking...", None)
            self.on_log(line, replace)
        self.proc.stdout.close()
        self.proc.wait()
        return self.proc.returncode


# =============================================================================
# Settings / misc
# =============================================================================
def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def job_from_dict(d: dict) -> Job:
    names = {f.name for f in fields(Job)}
    return Job(**{k: v for k, v in d.items() if k in names})


def job_to_dict(job: Job) -> dict:
    return asdict(job)


def system_lang() -> str:
    try:
        if IS_WIN:
            import ctypes
            return "ja" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF) == 0x11 else "en"
    except Exception:
        pass
    loc = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
    return "ja" if loc.startswith("ja") else "en"


def latest_release() -> Optional[dict]:
    """{"version", "url", "newer"} or None (network errors are swallowed by the caller)."""
    data = json.loads(_http_get(API_URL, 15))
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        return None
    return {"version": tag, "url": data.get("html_url", REPO_URL), "newer": ver_tuple(tag) > ver_tuple(__version__)}
