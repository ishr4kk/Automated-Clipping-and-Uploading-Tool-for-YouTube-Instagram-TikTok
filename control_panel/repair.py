"""Settings helpers: "Fix" (diagnose + repair the project) and
"Clear cache" (remove logs, temp work, uploaded-video backups).

Both run on background threads and report through the log bus so every
step is visible in the Master Console. Nothing here touches pending
uploads (queue/*/upload) or dedupe state (state/).
"""

import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from .config import (
    PLATFORMS,
    PROJECT_ROOT,
    PYTHON_EXE,
    YTDLP_PATH,
    YTDLP_URL,
)
from .logbus import LEVEL_ERROR, LEVEL_INFO, LEVEL_OK, LEVEL_WARN

VALID_CUTS = ("starting", "anywhere", "end")
CRITICAL_ENV_KEYS = ("OPENROUTER_API_KEY", "AUTO_VIDEO_CHANNELS")
ASSET_CHECKS = (
    ("ffmpeg", "ffmpeg"),
    ("node", "node"),
    ("npm", "npm"),
)

CACHE_TARGETS = ("logs", "work", "stderr.tmp")
DONE_DIRS = [Path("queue") / platform["folder"] / "done" for platform in PLATFORMS]
UPLOAD_DIRS = [Path("queue") / platform["folder"] / "upload" for platform in PLATFORMS]
STATE_DIRS = (
    Path("queue"),
    *UPLOAD_DIRS,
    *DONE_DIRS,
    Path("state"),
    Path("jobs"),
    Path("user-assets"),
    Path("autodownload"),
)

SKIP_PYCACHE_DIRS = ("node_modules", "autodownload", ".git")






def _run(cwd, command, timeout=None):
    resolved = [shutil.which(command[0]) or command[0]] + list(command[1:])
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            resolved, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, creationflags=flags,
        )
        return result.returncode
    except FileNotFoundError:
        return -1
    except subprocess.TimeoutExpired:
        return -2


def set_env_key(path, key, value):
    """Set or replace a single-line key in an .env-style file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    out = []
    for line in lines:
        if line.strip().startswith(prefix) and not line.strip().startswith("#"):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_env(path):
    values = {}
    current_key = None
    pieces = []
    quote_balance = 0

    def finish():
        if current_key is not None:
            raw = "".join(pieces)
            if raw.startswith('"') and raw.endswith('"') and quote_balance == 0:
                raw = raw[1:-1]
            values[current_key] = raw

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if current_key is None:
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, rest = line.partition("=")
            current_key = key.strip()
            pieces = [rest]
            quote_balance = rest.count('"') % 2
            if quote_balance == 0:
                finish()
                current_key = None
        else:
            pieces.append(raw_line)
            quote_balance = (quote_balance + line.count('"')) % 2
            if quote_balance == 0:
                finish()
                current_key = None
    return values






class RepairReport:
    def __init__(self):
        self.ok = 0
        self.warn = 0
        self.error = 0

    def ok_line(self, bus, text):
        self.ok += 1
        bus.emit("SETTINGS", LEVEL_OK, text)

    def warn_line(self, bus, text):
        self.warn += 1
        bus.emit("SETTINGS", LEVEL_WARN, text)

    def error_line(self, bus, text):
        self.error += 1
        bus.emit("SETTINGS", LEVEL_ERROR, text)

    @property
    def summary(self):
        return f"Fix finished - {self.ok} ok, {self.warn} warnings, {self.error} errors"


def ensure_project_dirs(bus, root, report):
    for relative in STATE_DIRS:
        target = root / relative
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            report.warn_line(bus, f"Recreated missing directory: {relative}")
    report.ok_line(bus, "Project directories verified")


def repair_assets(bus, root, report):
    for name, command in ASSET_CHECKS:
        exe = shutil.which(command)
        if exe:
            report.ok_line(bus, f"{name} found")
        else:
            report.error_line(bus, f"{name} not found on PATH - install it and rerun Fix")


def repair_node_deps(bus, root, report):
    node_modules = root / "node_modules"
    if not node_modules.is_dir():
        report.warn_line(bus, "node_modules missing - running npm install")
        code = _run(root, ["npm", "install"], timeout=900)
        if code == 0:
            report.ok_line(bus, "npm install completed")
            return
        report.error_line(bus, f"npm install failed (exit code {code})")
        return
    if _run(root, ["npm", "ls", "--depth=0"], timeout=120) == 0:
        report.ok_line(bus, "npm dependencies healthy")
    else:
        report.warn_line(bus, "npm dependency tree broken - running npm install")
        code = _run(root, ["npm", "install"], timeout=900)
        if code == 0:
            report.ok_line(bus, "npm dependencies repaired")
        else:
            report.error_line(bus, f"npm install failed (exit code {code})")


def repair_python_deps(bus, root, report):
    try:
        import googleapiclient
        import google.auth
        import google_auth_oauthlib
        report.ok_line(bus, "python uploader dependencies present")
        return
    except ImportError:
        pass
    report.warn_line(bus, "python uploader dependencies missing - running pip install")
    code = _run(root, [PYTHON_EXE, "-m", "pip", "install", "-r", str(root / "yt_uploader" / "requirements.txt")], timeout=900)
    if code == 0:
        report.ok_line(bus, "pip install completed")
    else:
        report.error_line(bus, f"pip install failed (exit code {code})")


def repair_ytdlp(bus, root, report):
    if YTDLP_PATH.is_file():
        report.ok_line(bus, "bundled yt-dlp present")
        return
    report.warn_line(bus, "bundled yt-dlp missing - downloading")
    try:
        YTDLP_PATH.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(YTDLP_URL, headers={"User-Agent": "r4k-auto-repair/1.0"})
        with urllib.request.urlopen(request, timeout=300) as response, open(YTDLP_PATH, "wb") as out:
            shutil.copyfileobj(response, out)
        if YTDLP_PATH.stat().st_size > 100_000:
            report.ok_line(bus, "yt-dlp downloaded")
        else:
            report.error_line(bus, "yt-dlp download produced an invalid file")
    except Exception as exc:
        report.error_line(bus, f"yt-dlp download failed: {exc}")


def repair_env(bus, root, report):
    env = root / ".env"
    if not env.is_file():
        example = root / ".env.example"
        if example.is_file():
            shutil.copyfile(example, env)
            report.warn_line(bus, ".env was missing - recreated from .env.example. Fill in your keys.")
        else:
            report.error_line(bus, ".env and .env.example both missing - cannot repair")
            return None
    values = load_env(env)
    if not values.get("OPENROUTER_API_KEY", "").strip():
        report.error_line(bus, "OPENROUTER_API_KEY is empty - add your key at https://openrouter.ai/keys")
    channels = [v.strip() for v in values.get("AUTO_VIDEO_CHANNELS", "").split(",") if v.strip()]
    if not any(v.startswith(("https://", "http://")) or v.startswith("@") or " " not in v for v in channels):
        report.error_line(bus, "AUTO_VIDEO_CHANNELS has no source channels - add at least one channel")

    cut = (values.get("VIDEO_CUT") or "").strip().lower()
    if cut not in VALID_CUTS:
        set_env_key(env, "VIDEO_CUT", "starting")
        report.warn_line(bus, f"VIDEO_CUT={cut or '(empty)'} was invalid - reset to starting")

    length = (values.get("VIDEO_LENGTH_SECONDS") or "").strip()
    try:
        if int(length) <= 0:
            raise ValueError
    except ValueError:
        set_env_key(env, "VIDEO_LENGTH_SECONDS", "30")
        report.warn_line(bus, f"VIDEO_LENGTH_SECONDS={length or '(empty)'} was invalid - reset to 30")
    return values


def repair_js_syntax(bus, root, report):
    code = _run(root, ["npm", "run", "check"], timeout=600)
    if code == 0:
        report.ok_line(bus, "JS syntax check passed (npm run check)")
    else:
        report.error_line(bus, f"JS syntax check failed (exit code {code}) - see the console output")


def run_fix(bus, root=None):
    root = Path(root or PROJECT_ROOT)
    report = RepairReport()
    bus.emit("SETTINGS", LEVEL_INFO, "Fix started ...")
    ensure_project_dirs(bus, root, report)
    repair_assets(bus, root, report)
    repair_node_deps(bus, root, report)
    repair_python_deps(bus, root, report)
    repair_ytdlp(bus, root, report)
    repair_env(bus, root, report)
    repair_js_syntax(bus, root, report)
    bus.emit("SETTINGS", LEVEL_INFO, report.summary)
    return report






def _delete_pycache(root, bus):
    removed = 0
    for folder in sorted(root.rglob("__pycache__")):
        if any(part in SKIP_PYCACHE_DIRS for part in folder.relative_to(root).parts):
            continue
        try:
            shutil.rmtree(folder)
            removed += 1
        except OSError:
            pass
    return removed


def _clear_folder(folder, bus, label):
    if not folder.is_dir():
        return 0
    removed = 0
    for item in folder.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
    if removed:
        bus.emit("SETTINGS", LEVEL_INFO, f"{label}: cleared {removed} item(s)")
    return removed


def clear_cache(bus, root=None):
    """Delete logs, temp work, pycache and uploaded videos in done dirs.

    Pending uploads (queue/*/upload) and state/ are never touched.
    Returns the number of files removed.
    """
    root = Path(root or PROJECT_ROOT)
    bus.emit("SETTINGS", LEVEL_INFO, "Clearing cache ...")
    total = 0
    for target in CACHE_TARGETS:
        path = root / target
        if path.is_file():
            try:
                path.unlink()
                total += 1
                bus.emit("SETTINGS", LEVEL_INFO, f"Removed {target}")
            except OSError:
                pass
        elif path.is_dir():
            total += _clear_folder(path, bus, target)

    for done in DONE_DIRS:
        total += _clear_folder(root / done, bus, f"done ({done.parent.name})")

    pycache = _delete_pycache(root, bus)
    if pycache:
        bus.emit("SETTINGS", LEVEL_INFO, f"Removed {pycache} __pycache__ folder(s)")
    total += pycache

    bus.emit("SETTINGS", LEVEL_OK, f"Cache cleared - {total} item(s) removed.")
    return total






class BackgroundTask(threading.Thread):
    """Run a callable on a daemon thread; invoke on_done(result) afterwards."""

    def __init__(self, fn, on_done=None):
        super().__init__(daemon=True)
        self._fn = fn
        self.on_done = on_done
        self.result = None

    def run(self):
        try:
            self.result = self._fn()
        except Exception as exc:
            self.result = exc
        if self.on_done:
            self.on_done(self.result)


def result_summary(result):
    if isinstance(result, Exception):
        return f"Task failed: {result}"
    if hasattr(result, "summary"):
        return result.summary
    return "Done."
