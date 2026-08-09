"""Setup / verify / launch script for the r4k auto project.

Usage (run from the project root):

    python setup.py              setup everything, verify, start control panel
    python setup.py --check      read-only verification (exit code only)
    python setup.py --no-start   setup + verify, do not launch the app
    python setup.py --check-sessions
                                 also live-check TikTok/Instagram sessions
    python setup.py --update-ytdlp
                                 force re-download of the bundled yt-dlp.exe

What it does in setup mode:
    1. Installs missing tooling: npm dependencies, pip requirements,
       bundled yt-dlp.exe, a .env file copied from .env.example.
    2. Verifies everything: python, node, ffmpeg, yt-dlp, .env contents,
       YouTube OAuth files and the JS syntax check (npm run check).
    3. Starts the control panel (pythonw) once the checks pass.

Exit codes: 0 = all ok, 1 = errors remain (--check reports them, too).
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
YTDLP_BUNDLED = PROJECT_ROOT / "autodownload" / "yt-dlp.exe"
REQUIREMENTS = PROJECT_ROOT / "yt_uploader" / "requirements.txt"
CLIENT_SECRET = PROJECT_ROOT / "client_secret.json"
YOUTUBE_TOKEN = PROJECT_ROOT / "yt_uploader" / "youtube_token.json"
DEFAULT_CAPTION = PROJECT_ROOT / "user-assets" / "caption.png"
FONT = PROJECT_ROOT / "src" / "Relidux.otf"

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

MIN_NODE_MAJOR = 18
MIN_PYTHON = (3, 10)

REPORT_LEVELS = ("ERROR", "WARN", "INFO", "OK")


def report(level, message):
    assert level in REPORT_LEVELS
    print(f"[{level}] {message}")


def run(command, timeout=None):
    """Run a command with hidden console window on Windows; return exit code."""
    resolved = [shutil.which(command[0]) or command[0]] + list(command[1:])
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            resolved,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
    except FileNotFoundError:
        return -1
    except subprocess.TimeoutExpired:
        return -2
    return result.returncode


def which(binary):
    return shutil.which(binary)







def load_env(path):
    """Return {KEY: value} for the .env file, values with quotes stripped."""
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


def count_urls(value):
    return sum(1 for part in str(value).split(",") if part.strip().startswith(("https://", "http://")))






class Verifier:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def ok(self, message):
        report("OK", message)

    def info(self, message):
        report("INFO", message)

    def warn(self, message):
        self.warnings += 1
        report("WARN", message)

    def error(self, message):
        self.errors += 1
        report("ERROR", message)


def check_python(verify):
    version = sys.version_info
    ok = version >= MIN_PYTHON
    text = f"Python {version.major}.{version.minor}.{version.micro} (>= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required)"
    (verify.ok if ok else verify.error)(text)
    try:
        import tkinter
        verify.ok("tkinter available (required by the control panel and env editor)")
    except ImportError:
        verify.error("tkinter not available - reinstall Python with the Tcl/Tk option")


def check_node(verify):
    exe = which("node")
    if not exe:
        verify.error("node.js not found on PATH - install from https://nodejs.org")
        return
    try:
        output = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        verify.error("could not read node version")
        return
    major = int(output.lstrip("v").split(".")[0])
    ok = major >= MIN_NODE_MAJOR
    text = f"node {output} (>= {MIN_NODE_MAJOR} required)"
    (verify.ok if ok else verify.error)(text)
    if which("npm") is None:
        verify.error("npm not found on PATH - reinstall node.js")


def check_ffmpeg(verify):
    exe = which("ffmpeg")
    if not exe:
        verify.error("ffmpeg not found on PATH - install it (e.g. gyan.dev builds) and add it to PATH")
        return
    try:
        output = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=20).stdout
        verify.ok(f"ffmpeg {output.splitlines()[0].split('ffmpeg version')[1].strip().split(' ')[0]}")
    except Exception:
        verify.error(f"ffmpeg at {exe} did not answer - is it a valid build?")


def check_ytdlp(verify, force_download):
    if YTDLP_BUNDLED.is_file():
        verify.ok(f"bundled yt-dlp present ({YTDLP_BUNDLED.name})")
        return False
    verify.error(f"bundled yt-dlp missing at autodownload{os.sep}yt-dlp.exe")
    return True


def download_ytdlp(verify):
    report("INFO", f"Downloading yt-dlp.exe from {YTDLP_URL} ...")
    YTDLP_BUNDLED.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        YTDLP_URL, headers={"User-Agent": "r4k-auto-setup/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response, open(YTDLP_BUNDLED, "wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:
        verify.error(f"yt-dlp download failed: {exc}")
        return
    if YTDLP_BUNDLED.is_file() and YTDLP_BUNDLED.stat().st_size > 100_000:
        verify.ok(f"yt-dlp downloaded ({YTDLP_BUNDLED.stat().st_size // 1024} KB)")
    else:
        verify.error("yt-dlp download produced an invalid file")


def check_node_modules(verify):
    if (PROJECT_ROOT / "node_modules").is_dir():
        verify.ok("npm dependencies installed (node_modules)")
        return False
    verify.error("npm dependencies missing (node_modules)")
    return True


def npm_install(verify):
    report("INFO", "Running: npm install ...")
    code = run(["npm", "install"], timeout=900)
    if code == 0:
        verify.ok("npm install completed")
    else:
        verify.error(f"npm install failed (exit code {code}) - check npm/node and network")


def check_python_deps(verify):
    try:
        import googleapiclient
        import google.auth
        import google_auth_oauthlib
        verify.ok("python uploader dependencies installed (google-api-python-client, google-auth)")
        return False
    except ImportError:
        verify.error("python uploader dependencies missing (google-api-python-client, google-auth, google-auth-oauthlib)")
        return True


def pip_install(verify):
    report("INFO", f"Running: pip install -r {REQUIREMENTS.name} ...")
    code = run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)], timeout=900)
    if code == 0:
        verify.ok("pip install completed")
    else:
        verify.error(f"pip install failed (exit code {code}) - check network and python")


def check_env(verify):
    if not ENV_PATH.is_file():
        verify.error(f".env missing - expected at {ENV_PATH}")
        return None
    verify.ok(".env present")
    return load_env(ENV_PATH)


def verify_env_values(verify, values):
    if values is None:
        return

    api_key = (values.get("OPENROUTER_API_KEY") or "").strip()
    if api_key.startswith("sk-or-v1") and len(api_key) > 20:
        verify.ok("OPENROUTER_API_KEY set")
    elif api_key:
        verify.warn("OPENROUTER_API_KEY does not look like a sk-or-v1 key - video analysis may fail")
    else:
        verify.error("OPENROUTER_API_KEY empty - get a key at https://openrouter.ai/keys")

    channels = count_urls(values.get("AUTO_VIDEO_CHANNELS", ""))
    if channels > 0:
        verify.ok(f"AUTO_VIDEO_CHANNELS: {channels} channel(s)")
    else:
        verify.error("AUTO_VIDEO_CHANNELS has no channel URLs - video generation cannot find sources")

    playlists = count_urls(values.get("BACKGROUND_MUSIC_PLAYLISTS", ""))
    if playlists > 0:
        verify.ok(f"BACKGROUND_MUSIC_PLAYLISTS: {playlists} playlist(s)")
    else:
        verify.warn("BACKGROUND_MUSIC_PLAYLISTS empty - videos will render without music")

    cut = (values.get("VIDEO_CUT") or "").strip().lower()
    if cut in ("starting", "anywhere", "end"):
        verify.ok(f"VIDEO_CUT={cut}")
    else:
        verify.warn(f"VIDEO_CUT={cut or '(empty)'} - expected starting | anywhere | end")

    try:
        length = int((values.get("VIDEO_LENGTH_SECONDS") or "").strip())
        if length > 0:
            verify.ok(f"VIDEO_LENGTH_SECONDS={length}s")
        else:
            verify.warn("VIDEO_LENGTH_SECONDS must be a positive number of seconds")
    except ValueError:
        verify.warn("VIDEO_LENGTH_SECONDS is not a number")

    caption = (values.get("AUTO_VIDEO_CAPTION_IMAGE") or "").strip()
    if caption:
        caption_path = Path(caption)
        if not caption_path.is_absolute():
            caption_path = PROJECT_ROOT / caption_path
        if caption_path.is_file():
            verify.ok(f"caption image found ({caption_path.name})")
        else:
            verify.warn(f"caption image not found: {caption}")
    elif DEFAULT_CAPTION.is_file():
        verify.ok(f"default caption image present ({DEFAULT_CAPTION.name})")
    else:
        verify.warn(f"no caption image - add one at user-assets{os.sep}caption.png or set AUTO_VIDEO_CAPTION_IMAGE")

    for key, label in (
        ("TIKTOKSESSIONID", "TikTok"),
        ("INSTAGRAMSESSIONID", "Instagram"),
    ):
        if (values.get(key) or "").strip():
            verify.ok(f"{label} session id set (TIKTOKSESSIONID/INSTAGRAMSESSIONID)")
        else:
            verify.warn(f"{label} session id empty - uploads to {label} will fail until set in .env")

    if CLIENT_SECRET.is_file():
        verify.ok("YouTube OAuth client_secret.json present")
    else:
        verify.warn("client_secret.json missing - create a Google OAuth client (Desktop app) and export it")

    if YOUTUBE_TOKEN.is_file():
        verify.ok("YouTube OAuth token present (youtube_token.json)")
    else:
        verify.warn("youtube_token.json missing - run: npm run oauth")

    if FONT.is_file():
        verify.ok("font asset present (src/Relidux.otf)")
    else:
        verify.warn("font asset missing (src/Relidux.otf) - renders will fall back to a system font")


def check_js_syntax(verify):
    code = run(["npm", "run", "check"], timeout=600)
    if code == 0:
        verify.ok("JS syntax check passed (npm run check)")
    else:
        verify.error(f"JS syntax check failed (exit code {code}) - run npm run check for details")


def check_sessions_live(verify):
    report("INFO", "Live session checks (network) ...")
    for script in ("tiktok-uploader:check", "instagram-uploader:check"):
        code = run(["npm", "run", script], timeout=120)
        if code == 0:
            verify.ok(f"{script} passed")
        else:
            verify.warn(f"{script} reported a problem (exit code {code})")


def verify_control_panel(verify):
    if (PROJECT_ROOT / "control_panel" / "main.py").is_file():
        verify.ok("control panel found")
    else:
        verify.error("control_panel/main.py missing - the app cannot be started")






def apply_fixes(verify, values, force_ytdlp):
    if check_ytdlp(verify, force_ytdlp) or force_ytdlp:
        download_ytdlp(verify)
    if check_node_modules(verify):
        npm_install(verify)
    if check_python_deps(verify):
        pip_install(verify)
    if values is None and ENV_EXAMPLE.is_file():
        report("INFO", f"Creating .env from {ENV_EXAMPLE.name} ...")
        shutil.copyfile(ENV_EXAMPLE, ENV_PATH)
        verify.ok(".env created from .env.example - fill it in (env editor: pythonw env_editor.pyw)")


def print_summary(verify):
    total = verify.errors + verify.warnings
    print("-" * 60)
    if verify.errors:
        print(f"[ERROR] {verify.errors} problem(s) remain")
    if verify.warnings:
        print(f"[WARN] {verify.warnings} warning(s) - things work but may not fully behave")
    if not total:
        print("Everything looks good. Ready to run.")
    print("-" * 60)






def start_control_panel():
    report("INFO", "Starting control panel ...")
    pythonw = None
    if os.name == "nt":
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.is_file():
            pythonw = str(candidate)
    command = [pythonw or sys.executable, "-m", "control_panel.main"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        subprocess.Popen(command, cwd=str(PROJECT_ROOT), creationflags=flags)
    except OSError as exc:
        report("ERROR", f"Could not start the control panel: {exc}")
        return False
    report("INFO", "Control panel launched (pythonw, no console attached).")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="r4k auto - setup, verify and launch")
    parser.add_argument("--check", action="store_true", help="verify only, change nothing, do not start")
    parser.add_argument("--no-start", action="store_true", help="setup + verify, but do not start the app")
    parser.add_argument("--check-sessions", action="store_true", help="live-check TikTok/Instagram sessions (network)")
    parser.add_argument("--update-ytdlp", action="store_true", help="re-download the bundled yt-dlp.exe")
    args = parser.parse_args(argv)

    print(f"r4k auto - setup for {PROJECT_ROOT}\n")

    verify = Verifier()

    check_python(verify)
    check_node(verify)
    check_ffmpeg(verify)
    check_ytdlp(verify, args.update_ytdlp)
    check_node_modules(verify)
    check_python_deps(verify)
    values = check_env(verify)
    verify_control_panel(verify)

    if args.check:
        if values is not None:
            verify_env_values(verify, values)
        if args.check_sessions:
            check_sessions_live(verify)
        print_summary(verify)
        return 1 if verify.errors else 0

    apply_fixes(verify, values, args.update_ytdlp)
    values = check_env(verify)
    verify_env_values(verify, values)
    check_js_syntax(verify)
    if args.check_sessions:
        check_sessions_live(verify)
    print_summary(verify)

    if verify.errors:
        report("ERROR", "Setup finished with errors - the control panel was not started.")
        return 1

    if args.no_start:
        report("INFO", "Setup complete. Start the control panel anytime with: pythonw -m control_panel.main")
        return 0

    return 0 if start_control_panel() else 1


if __name__ == "__main__":
    sys.exit(main())
