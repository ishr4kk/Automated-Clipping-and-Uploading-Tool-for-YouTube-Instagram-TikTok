import os
from pathlib import Path

UPLOADER_DIR = Path(__file__).resolve().parent
MACHINE_ROOT = UPLOADER_DIR.parent

WATCH_DIR = Path(os.environ.get("YT_UPLOADER_WATCH_DIR", str(MACHINE_ROOT / "queue" / "yt" / "upload")))
DONE_DIR = Path(os.environ.get("YT_UPLOADER_DONE_DIR", str(MACHINE_ROOT / "queue" / "yt" / "done")))
FAILED_DIR = Path(os.environ.get("YT_UPLOADER_FAILED_DIR", str(MACHINE_ROOT / "queue" / "yt" / "failed")))

CLIENT_SECRET = MACHINE_ROOT / "client_secret.json"
STATE_DIR = Path(os.environ.get("YT_UPLOADER_STATE_DIR", str(UPLOADER_DIR / "state")))
STATE_PATH = STATE_DIR / "processed.json"



TOKEN_PATH = Path(
    os.environ.get("YT_UPLOADER_TOKEN_PATH")
    or next(
        (
            p
            for p in (UPLOADER_DIR / "youtube_token.json", UPLOADER_DIR / "token.json")
            if p.is_file()
        ),
        UPLOADER_DIR / "youtube_token.json",
    )
)

LOGS_DIR = MACHINE_ROOT / "logs"
LOG_FILE = Path(os.environ.get("YT_UPLOADER_LOG_FILE", str(LOGS_DIR / "yt-uploader.log")))

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
SIDECAR_EXTENSIONS = {".txt", ".description"}

POLL_INTERVAL = float(os.environ.get("YT_UPLOADER_POLL_SECONDS", "20") or 20)
STABILITY_DELAY = float(os.environ.get("YT_UPLOADER_STABILITY_SECONDS", "8") or 8)
MISSING_SIDECAR_LIMIT = int(os.environ.get("YT_UPLOADER_SIDECAR_WAIT_CYCLES", "3") or 3)



UPLOAD_DELAY = max(0.0, float(os.environ.get("UPLOAD_DELAY_SECONDS", "0") or 0))

UPLOAD_MAX_RETRIES = 2
UPLOAD_BASE_DELAY = 5.0

CATEGORY_ID = "20"
DEFAULT_LANG = "en"

TITLE_TAGS = ["#shorts", "#SHORT", "#short"]
DESCRIPTION_TAGS = ["#movieclips", "#movie", "#latest", "#trending"]
