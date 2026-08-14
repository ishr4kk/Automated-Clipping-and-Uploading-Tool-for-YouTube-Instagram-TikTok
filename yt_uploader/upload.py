

import time
from functools import wraps
from pathlib import Path

from .config import CATEGORY_ID, DEFAULT_LANG, UPLOAD_BASE_DELAY, UPLOAD_MAX_RETRIES
from .logger import log, warn, fail
from .oauth import get_credentials


def with_retry(max_retries: int = UPLOAD_MAX_RETRIES, base_delay: float = UPLOAD_BASE_DELAY):
    """Exponential backoff: delays base_delay * 2^attempt."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        warn(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): "
                            f"{exc} - retrying in {delay:.1f}s"
                        )
                        time.sleep(delay)
                    else:
                        fail(f"{func.__name__} failed after {max_retries + 1} attempts: {exc}")
            raise last_exc
        return wrapper
    return decorator


@with_retry()
def upload_video(video_path: Path, title: str, description: str) -> str:
    """Upload video_path with the given title/description. Returns the
    youtu.be URL. Retries the whole upload with backoff on failure."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    log(f"Uploading {video_path.name}...")
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": ["shorts", "short", "movie", "movieclips", "trending"],
            "categoryId": CATEGORY_ID,
            "defaultLanguage": DEFAULT_LANG,
            "defaultAudioLanguage": DEFAULT_LANG,
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            log(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    log(f"Uploaded: {url}")
    return url
