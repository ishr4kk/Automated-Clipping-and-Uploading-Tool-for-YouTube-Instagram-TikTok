"""YouTube auto-uploader watcher.

Watches queue/yt/upload for finished videos (mp4/webm/mov/...). For each
video it finds the matching sidecar (<base>.txt or <base>.description,
written by the machine as "title\n\n<description>"), builds the final
title/description with the required hashtags, verifies the file is complete
(size stability + ffmpeg decode), uploads to YouTube, and moves the pair
into queue/yt/done. Permanent failures move the pair into queue/yt/failed
with an error note. A processed.json record prevents accidental duplicates.

Usage:
  python yt_uploader/uploader.py              watch continuously
  python yt_uploader/uploader.py --once       scan once and exit (testing)
  python yt_uploader/uploader.py --setup-oauth
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from yt_uploader.config import (
        DONE_DIR, FAILED_DIR, MISSING_SIDECAR_LIMIT, POLL_INTERVAL, SIDECAR_EXTENSIONS,
        STABILITY_DELAY, STATE_PATH, UPLOAD_DELAY, VIDEO_EXTENSIONS, WATCH_DIR,
    )
    from yt_uploader.hashtags import build_description, build_title
    from yt_uploader.logger import configure, fail, log, warn
    from yt_uploader.oauth import OAuthError, get_credentials, run_oauth_flow, token_summary
    from yt_uploader.upload import upload_video
else:
    from .config import (
        DONE_DIR,
        FAILED_DIR,
        MISSING_SIDECAR_LIMIT,
        POLL_INTERVAL,
        SIDECAR_EXTENSIONS,
        STABILITY_DELAY,
        STATE_PATH,
        UPLOAD_DELAY,
        VIDEO_EXTENSIONS,
        WATCH_DIR,
    )
    from .hashtags import build_description, build_title
    from .logger import configure, fail, log, warn
    from .oauth import OAuthError, get_credentials, run_oauth_flow, token_summary
    from .upload import upload_video


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            warn(f"State file unreadable ({exc}); starting fresh")
    return {"processed": {}}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def scan_videos() -> list:
    if not WATCH_DIR.exists():
        warn(f"Watch dir missing: {WATCH_DIR}")
        return []
    videos = []
    for entry in WATCH_DIR.iterdir():
        if entry.is_file() and not entry.name.startswith("."):
            if entry.suffix.lower() in VIDEO_EXTENSIONS:
                videos.append(entry)
    return sorted(videos)


def find_sidecar(video: Path) -> Path | None:
    for ext in SIDECAR_EXTENSIONS:
        candidate = video.with_suffix(ext)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def read_sidecar(sidecar: Path) -> tuple:
    """Return (title, description) from "title\n\n<description>"."""
    text = sidecar.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    title = lines[0].strip() if lines else ""
    description = "\n".join(lines[1:]).strip()
    return title, description


def is_stable(path: Path) -> bool:
    """True when the file size holds constant across two samples and is > 0."""
    try:
        size_a = path.stat().st_size
        if size_a <= 0:
            return False
        time.sleep(STABILITY_DELAY)
        size_b = path.stat().st_size
        return size_b == size_a
    except OSError:
        return False


def verify_video(path: Path) -> tuple:
    """Full decode check (same approach as machine.js verifyFinalFile).
    Returns (ok, detail)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return False, (proc.stderr or "ffmpeg decode failed").strip().splitlines()[-1][-300:]
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
             "-show_entries", "stream=codec_type", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120,
        )
        info = json.loads(proc.stdout or "{}")
        has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        duration = float(info.get("format", {}).get("duration", 0) or 0)
        if not has_video or not has_audio or duration <= 0:
            return False, f"bad streams (video={has_video} audio={has_audio} duration={duration})"
        return True, f"{duration:.1f}s"
    except FileNotFoundError:
        warn("ffmpeg/ffprobe not found; skipping decode verification")
        return True, "unverified (no ffmpeg)"
    except subprocess.TimeoutExpired:
        return False, "decode timed out"
    except Exception as exc:
        return False, str(exc)


def move_pair(video: Path, sidecar: Path | None, dest_dir: Path, note: str = None):
    dest_dir.mkdir(parents=True, exist_ok=True)
    if note:
        (dest_dir / f"{video.stem}.error.txt").write_text(note, encoding="utf-8")
    shutil.move(str(video), str(dest_dir / video.name))
    if sidecar and sidecar.exists():
        shutil.move(str(sidecar), str(dest_dir / sidecar.name))


def process_video(video: Path, sidecar: Path | None, state: dict) -> bool:
    base = video.stem
    log(f"Processing {video.name}")

    title, description = ("", "")
    if sidecar:
        try:
            title, description = read_sidecar(sidecar)
        except Exception as exc:
            fail(f"Could not read sidecar {sidecar.name}: {exc}")
            move_pair(video, sidecar, FAILED_DIR, f"unreadable sidecar: {exc}")
            return False
    else:
        warn(f"No sidecar for {video.name}; using derived title")

    final_title = build_title(title or base)
    final_description = build_description(description, base)
    log(f"  Title: {final_title}")
    log(f"  Description: {final_description}")

    ok, detail = verify_video(video)
    if not ok:
        fail(f"{video.name} failed verification: {detail}")
        move_pair(video, sidecar, FAILED_DIR, f"verification failed: {detail}")
        return False

    try:
        url = upload_video(video, final_title, final_description)
    except Exception as exc:
        fail(f"Upload failed for {video.name}: {exc}")
        move_pair(video, sidecar, FAILED_DIR, f"upload failed: {exc}")
        return False

    state.setdefault("processed", {})[base] = {
        "url": url,
        "video": video.name,
        "title": final_title,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_state(state)
    move_pair(video, sidecar, DONE_DIR)
    log(f"DONE: {video.name} -> {url} (moved to queue/yt/done)")
    return True


def run_cycle(state: dict, missing_since: dict, delay: float = UPLOAD_DELAY, quiet: bool = False) -> dict:
    """Scan and upload everything pending in the watch dir.

    Returns {"missing_since": dict, "processed": int, "failed": int}.
    When ``quiet`` is true (previous cycle found nothing) an empty scan is
    not logged at all, so a long-running watcher does not spam the console.
    """
    videos = scan_videos()
    if not videos:
        if not quiet:
            log("Scanning queue/yt/upload... no videos pending")
        return {"missing_since": missing_since, "processed": 0, "failed": 0}

    if quiet:
        log("New videos detected in queue/yt/upload")
    log(f"Scanning queue/yt/upload... {len(videos)} video(s) pending")

    processed = 0
    failed = 0
    for index, video in enumerate(videos):
        base = video.stem
        if base in state.get("processed", {}):
            warn(f"{video.name} already processed (recorded); moving to done")
            move_pair(video, find_sidecar(video), DONE_DIR)
            continue

        sidecar = find_sidecar(video)
        if sidecar is None:
            seen = missing_since.get(base, 0) + 1
            missing_since[base] = seen
            if seen < MISSING_SIDECAR_LIMIT:
                log(f"  {video.name}: waiting for sidecar (cycle {seen}/{MISSING_SIDECAR_LIMIT})")
                continue
            warn(f"{video.name}: sidecar still missing after {seen} cycles; proceeding without it")
        else:
            missing_since.pop(base, None)

        if not is_stable(video):
            warn(f"{video.name} still being written; deferring")
            continue

        processed += 1
        if not process_video(video, sidecar, state):
            failed += 1



        if delay > 0 and index < len(videos) - 1:
            log(f"Waiting {delay:.0f} seconds before next upload")
            time.sleep(delay)

    for base in list(missing_since):
        if base not in {v.stem for v in videos}:
            missing_since.pop(base, None)
    return {"missing_since": missing_since, "processed": processed, "failed": failed}


def watch_forever(delay: float = UPLOAD_DELAY):
    state = load_state()
    missing_since = {}
    quiet_cycle = False
    log("=" * 60)
    log("YouTube auto-uploader started")
    log(f"  Watch dir:    {WATCH_DIR}")
    log(f"  Done dir:     {DONE_DIR}")
    log(f"  Failed dir:   {FAILED_DIR}")
    log(f"  Poll interval: {POLL_INTERVAL}s")
    if delay > 0:
        log(f"  Inter-video delay: {delay:.0f}s")
    log(f"  OAuth:        {token_summary()}")
    log("=" * 60)
    get_credentials()

    while True:
        try:
            result = run_cycle(state, missing_since, delay, quiet=quiet_cycle)
            missing_since = result["missing_since"]
            quiet_cycle = result["processed"] == 0 and result["failed"] == 0
        except OAuthError as exc:
            fail(f"OAuth problem: {exc}")
        except Exception as exc:
            fail(f"Cycle error: {exc}")
        time.sleep(POLL_INTERVAL)


def main(argv=None):
    parser = argparse.ArgumentParser(description="YouTube auto-uploader for vs auto")
    parser.add_argument("--once", action="store_true", help="scan once and exit (testing)")
    parser.add_argument("--setup-oauth", action="store_true", help="run one-time OAuth and exit")
    parser.add_argument("--delay", type=float, default=None, help="cooldown between uploads (seconds)")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    configure(verbose=args.verbose)

    delay = args.delay if args.delay is not None else UPLOAD_DELAY
    if args.delay is not None:
        log(f"Inter-video delay: {delay:.0f}s (from --delay)")

    if args.setup_oauth:
        run_oauth_flow()
        log(f"Authorization complete. Token: {token_summary()}")
        return 0

    if args.once:
        state = load_state()
        result = run_cycle(state, {}, delay)
        save_state(state)
        if result["failed"]:
            fail(f"Cycle finished: {result['processed']} processed, {result['failed']} failed")
            return 1
        return 0

    watch_forever(delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
