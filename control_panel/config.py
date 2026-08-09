"""Static configuration for the control panel.

Centralizes every path, color and platform definition so the UI and the
workflow code stay decoupled. Nothing here reads from the environment at
import time except the python interpreter path used for child processes.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
SPLASH_IMAGE = PROJECT_ROOT / "src" / "author.png"
ENV_EDITOR_PATH = PROJECT_ROOT / "env_editor.pyw"
FONT_PATH = PROJECT_ROOT / "src" / "Relidux.otf"
FALLBACK_FONT_FAMILY = "Segoe UI"
REQUIREMENTS = PROJECT_ROOT / "yt_uploader" / "requirements.txt"
YTDLP_PATH = PROJECT_ROOT / "autodownload" / "yt-dlp.exe"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

FIRST_RUN_STATE = PROJECT_ROOT / "control_panel" / "state" / "first_run.json"

PYTHON_EXE = sys.executable





class Theme:
    BG = "#242424"
    PANEL = "#2b2b2b"
    FIELD = "#1a1a1a"
    ACCENT = "#7200A3"
    ACCENT_DARK = "#5a0085"
    ACCENT_SOFT = "#8b1fc4"
    TEXT = "#e8e8e8"
    TEXT_DIM = "#8a8a8a"
    COMMENT = "#6d6d6d"
    BORDER = "#3a3a3a"
    OK = "#6fdc8c"
    WARN = "#e0c068"
    ERROR = "#ff6b6b"
    DISABLED = "#555555"

    CONSOLE_LEVEL_TAGS = {
        "INFO": OK,
        "OK": OK,
        "WARN": WARN,
        "ERROR": ERROR,
    }

















def _cmd(python, *parts):
    return [part.replace("{python}", python) for part in parts]


def _node(python, script):

    return lambda: ["node", script]


PLATFORMS = [
    {
        "key": "tiktok",
        "label": "TikTok",
        "folder": "tiktok",
        "machine_key": "tiktok",
        "source": "TIKTOK",
        "command": lambda: ["node", "tiktok_uploader/main.js", "--once"],
        "watch_command": lambda: ["node", "tiktok_uploader/main.js"],
    },
    {
        "key": "youtube",
        "label": "YouTube",
        "folder": "yt",
        "machine_key": "yt",
        "source": "YOUTUBE",
        "command": lambda: _cmd(PYTHON_EXE, "{python}", "yt_uploader/uploader.py", "--once"),
        "watch_command": lambda: _cmd(PYTHON_EXE, "{python}", "yt_uploader/uploader.py"),
    },
    {
        "key": "instagram",
        "label": "Instagram",
        "folder": "insta",
        "machine_key": "insta",
        "source": "INSTAGRAM",
        "command": lambda: ["node", "instagram_uploader/main.js", "--once"],
        "watch_command": lambda: ["node", "instagram_uploader/main.js"],
    },
]

PLATFORM_BY_KEY = {platform["key"]: platform for platform in PLATFORMS}

GENERATOR_COMMAND = ["node", "run.js", "--platforms", "{platforms}"]


SIDECAR_EXTENSIONS = (".description", ".txt")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v")

UPLOAD_FOLDER_NAME = "upload"


UPLOADER_TAB_KEYS = ["tiktok", "instagram", "youtube"]





DRAIN_POLL_SECONDS = 3
DRAIN_TIMEOUT_SECONDS = 30 * 60


CONSOLE_RING_SIZE = 5000

CONSOLE_MAX_LINES = 3000

NAV_ITEMS = ["Overview", "Uploader", "Console", "Settings", "Setup", "Info"]

APP_TITLE = "r4k auto — Control Panel"
APP_VERSION = "1.0.0"

INFO_LINKS = [
    ("Instagram", "https://www.instagram.com/ishr4k._"),
    ("GitHub", "https://github.com/ishr4kk"),
    ("Discord", "https://discord.com/users/778585286044942358"),
]
