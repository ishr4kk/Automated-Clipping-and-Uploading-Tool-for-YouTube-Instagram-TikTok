

import logging
import sys
from datetime import datetime

from .config import LOG_FILE, LOGS_DIR

_LOGGER = None


def _stream():
    stream = logging.StreamHandler(sys.stdout)
    try:
        stream.stream = open(
            sys.stdout.fileno(), "w", encoding="utf-8", errors="replace", closefd=False
        )
    except Exception:
        pass
    return stream


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("yt_uploader")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    console = _stream()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("  %(message)s"))
    logger.addHandler(console)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
        )
    )
    logger.addHandler(file_handler)

    _LOGGER = logger
    return logger


def configure(verbose: bool = False):
    logger = get_logger()
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.DEBUG if verbose else logging.INFO)


def log(msg: str):
    get_logger().info("[%s] %s", datetime.now().isoformat(), msg)


def warn(msg: str):
    get_logger().warning("[%s] %s", datetime.now().isoformat(), msg)


def fail(msg: str):
    get_logger().error("[%s] %s", datetime.now().isoformat(), msg)
