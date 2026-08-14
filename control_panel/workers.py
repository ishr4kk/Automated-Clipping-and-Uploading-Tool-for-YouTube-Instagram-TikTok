"""Worker layer: subprocess execution, per-platform upload threads and the
START workflow controller.

The UI never blocks: every uploader runs as its own independent worker
thread (one per platform, subprocess in watch mode), the generator runs on
the workflow thread, and every child process has its stdout piped back into
the log bus line by line, in real time.

Architecture::

                  Uploader / Workflow
                          │
           ┌──────────────┼──────────────┐
           ↓              ↓              ↓
     TikTok Thread    YouTube Thread  Instagram Thread
           │              │              │
     TikTok Queue    YouTube Queue  Instagram Queue
"""

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .config import (
    DRAIN_POLL_SECONDS,
    DRAIN_TIMEOUT_SECONDS,
    GENERATOR_COMMAND,
    PROJECT_ROOT,
    SIDECAR_EXTENSIONS,
    UPLOAD_FOLDER_NAME,
    VIDEO_EXTENSIONS,
)
from .logbus import LEVEL_ERROR, LEVEL_INFO, LEVEL_OK, LEVEL_WARN, LogBus


_LEVEL_TOKEN = re.compile(r"\[\s*(INFO|OK|WARN|FAIL|ERROR|WARNING|DEBUG)\s*\]", re.IGNORECASE)

_OK_WORDS = ("success", "successful", "completed", "complete", "done", "finished", "passed", "confirmed")
_WARN_WORDS = ("warn", "warning", "skip", "defer", "retry", "still being written")
_ERROR_WORDS = ("fail", "error", "exception", "traceback", "cannot", "could not", "timed out", "aborted")


def classify_line(line):
    """Map an arbitrary subprocess log line to a bus level.

    Uses the machine/uploader "[LEVEL]" tokens first, then falls back to
    content heuristics so python/third-party output is still color-coded.
    """
    match = _LEVEL_TOKEN.search(line)
    if match:
        token = match.group(1).upper()
        if token in ("OK",):
            return LEVEL_OK
        if token in ("WARN", "WARNING"):
            return LEVEL_WARN
        if token in ("FAIL", "ERROR"):
            return LEVEL_ERROR
        return LEVEL_INFO

    lowered = line.lower()
    if any(word in lowered for word in _ERROR_WORDS):
        return LEVEL_ERROR
    if any(word in lowered for word in _WARN_WORDS):
        return LEVEL_WARN
    if any(word in lowered for word in _OK_WORDS):
        return LEVEL_OK
    return LEVEL_INFO


class ProcessRunner:
    """Run one child process and stream its output into the log bus.

    ``run()`` blocks until the process exits and returns the exit code.
    Call ``terminate()`` from another thread to stop it early.
    """

    def __init__(self, command, source, bus, cwd=None):
        self.command = list(command)
        self.source = source
        self.bus = bus
        self.cwd = str(cwd or PROJECT_ROOT)
        self.process = None
        self._lock = threading.Lock()
        self._stop_requested = threading.Event()

    def _spawn_flags(self):
        flags = 0
        if os.name == "nt":
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return flags

    def run(self):
        self.bus.emit(self.source, LEVEL_INFO, "Starting: " + " ".join(self.command))
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self._spawn_flags(),
            )
        except OSError as exc:
            self.bus.emit(self.source, LEVEL_ERROR, f"Could not start process: {exc}")
            return -1

        try:
            for raw in iter(self.process.stdout.readline, ""):
                if not raw:
                    break
                line = raw.rstrip()
                if line:
                    self.bus.emit(self.source, classify_line(line), line)
        except ValueError:

            pass

        code = self.process.wait()
        if self._stop_requested.is_set():
            self.bus.emit(self.source, LEVEL_INFO, f"Process stopped (code {code})")
            return 0
        self.bus.emit(self.source, LEVEL_INFO, f"Process exited (code {code})")
        return code

    def terminate(self):
        with self._lock:
            proc = self.process
        if proc and proc.poll() is None:
            self._stop_requested.set()
            try:
                proc.terminate()
            except OSError:
                pass


class WorkflowError(Exception):
    """Raised by the workflow controller for recoverable failures."""


def find_video_pairs(upload_dir):
    """Return bases that have a video file AND a sidecar in the upload dir.

    ``upload_dir`` may be a Path or str. Returns a sorted list of base names.
    """
    folder = Path(upload_dir)
    if not folder.is_dir():
        return []
    videos = {path.stem for path in folder.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS}
    sidecars = {
        path.stem
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SIDECAR_EXTENSIONS
    }
    return sorted(videos & sidecars)


def list_video_files(upload_dir):
    """Return the names of all video files currently in the upload folder."""
    folder = Path(upload_dir)
    if not folder.is_dir():
        return []
    return sorted(
        path.name
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


class PlatformUploadWorker(threading.Thread):
    """One platform's uploader running on its own independent thread.

    The platform uploader subprocess runs in watch mode: it scans the
    platform's ``queue/<folder>/upload`` folder, uploads every video one by
    one (stability check -> ffmpeg verify -> upload -> move to ``done``),
    keeps failed uploads in place (recoverable), applies the configured
    per-platform cooldown between videos, and continues watching for new
    videos. The browser/session is initialized once per worker, not per
    video.

    A crash in this thread only ever affects its own platform.
    """

    def __init__(self, platform, bus, delay=0.0, runner_factory=None, cwd=None, on_state=None):
        super().__init__(daemon=True)
        self.platform = platform
        self.key = platform["key"]
        self.bus = bus
        self.delay = delay
        self.runner_factory = runner_factory or ProcessRunner
        self.cwd = str(cwd or PROJECT_ROOT)
        self.on_state = on_state or (lambda key, running: None)
        self.command = list(platform["watch_command"]())
        if delay > 0:
            self.command += ["--delay", f"{delay:g}"]
        self.runner = self.runner_factory(self.command, platform["source"], self.bus, cwd=self.cwd)
        self._current_runner = self.runner
        self.exit_code = None

    def run(self):
        source = self.platform["source"]
        self.bus.emit(source, LEVEL_INFO, f"{self.platform['label']} uploader started")
        if self.delay > 0:
            self.bus.emit(source, LEVEL_INFO, f"{self.platform['label']} cooldown: {self.delay:g}s between videos")
        self.on_state(self.key, True)
        try:
            self.exit_code = self.runner.run()
        finally:
            self._current_runner = None
        if self.exit_code != 0:
            self.bus.emit(source, LEVEL_ERROR, f"{self.platform['label']} uploader stopped with errors (exit code {self.exit_code})")
        else:
            self.bus.emit(source, LEVEL_INFO, f"{self.platform['label']} uploader stopped")
        self.on_state(self.key, False)

    def stop(self):
        runner = self._current_runner
        if runner:
            runner.terminate()


class UploadManager:
    """Owns at most one worker thread per platform.

    ``start()`` is idempotent: clicking "Upload All" twice (or starting the
    Overview workflow while a platform is already uploading) never creates a
    duplicate worker — the running one keeps processing the queue.
    """

    def __init__(self, bus, runner_factory=None, cwd=None, on_state=None):
        self.bus = bus
        self.runner_factory = runner_factory or ProcessRunner
        self.cwd = str(cwd or PROJECT_ROOT)
        self.on_state = on_state or (lambda key, running: None)
        self._workers = {}
        self._lock = threading.Lock()

    def start(self, platform, delay=0.0):
        """Start (or reuse) the worker for one platform. Returns the worker."""
        key = platform["key"]
        with self._lock:
            existing = self._workers.get(key)
            if existing is not None and existing.is_alive():
                self.bus.emit(
                    platform["source"],
                    LEVEL_WARN,
                    f"{platform['label']} uploader is already running - keeping the existing worker",
                )
                return existing
            worker = PlatformUploadWorker(
                platform,
                self.bus,
                delay=delay,
                runner_factory=self.runner_factory,
                cwd=self.cwd,
                on_state=self.on_state,
            )
            self._workers[key] = worker
        worker.start()
        return worker

    def is_running(self, key):
        worker = self._workers.get(key)
        return bool(worker is not None and worker.is_alive())

    def running_keys(self):
        return [key for key, worker in self._workers.items() if worker.is_alive()]

    def stop(self, keys=None):
        """Stop the workers for ``keys`` (all of them when None)."""
        targets = []
        with self._lock:
            if keys is None:
                keys = list(self._workers)
            for key in keys:
                worker = self._workers.get(key)
                if worker is not None and worker.is_alive():
                    targets.append(worker)
                    self.bus.emit("CONTROLLER", LEVEL_INFO, f"Stop requested for the {worker.platform['label']} uploader")
        for worker in targets:
            worker.stop()

    def stop_all(self):
        self.stop()


class WorkflowController(threading.Thread):
    """Runs the START workflow on a background thread, continuously:

    One video at a time, strictly sequential: generate a video, upload it to
    every selected platform (each uploader runs in watch mode on its own
    independent thread), wait for the queues to fully drain, then generate
    the next video and upload it — repeating until STOP is pressed.

    Per video, the steps are:
    1. Start the selected platforms' uploader workers (watch mode) so they
       are already draining their queues while the generator still runs.
    2. Generate one video (node run.js) and stream its output live.
    3. Verify each selected platform received a video + description sidecar.
    4. Wait for the uploaders to drain every queue (uploads overlap with
       generation; each platform uploads independently).
    5. Report per-platform results; videos that could not be uploaded stay in
       the upload folders, recoverable, and are never marked done.

    The uploader workers stay alive between videos (each browser/session is
    initialized once), so the whole pipeline is an endless generate/upload
    loop. A failed generation is reported and the loop moves on; if uploads
    cannot complete the workflow stops so files are never silently dropped.

    UI state is delivered through ``on_event`` (called from this thread;
    marshaling onto the Tk main thread is the listener's responsibility):

        {"type": "stage", "text": str}
        {"type": "finished", "ok": bool, "summary": str}

    ``delays`` maps a platform key to a per-platform cooldown in seconds.
    Values > 0 are appended to the uploader command as ``--delay <n>``,
    overriding the uploader's own UPLOAD_DELAY_SECONDS default.
    """

    def __init__(self, platforms, bus, runner_factory=None, on_event=None, cwd=None, delays=None, manager=None):
        super().__init__(daemon=True)
        self.platforms = list(platforms)
        self.bus = bus
        self.runner_factory = runner_factory or ProcessRunner
        self.on_event = on_event or (lambda event: None)
        self.cwd = str(cwd or PROJECT_ROOT)
        self.delays = delays or {}
        self.manager = manager or UploadManager(bus, runner_factory=self.runner_factory, cwd=self.cwd)
        self._stop_event = threading.Event()
        self._current_runner = None
        self._workers = {}



    def stop(self):
        self._stop_event.set()
        runner = self._current_runner
        if runner:
            runner.terminate()

    @property
    def stop_requested(self):
        return self._stop_event.is_set()



    def _stage(self, text):
        self.bus.emit("CONTROLLER", LEVEL_INFO, text)
        self.on_event({"type": "stage", "text": text})

    def _finish(self, ok, summary):
        self.on_event({"type": "finished", "ok": ok, "summary": summary})



    def run(self):
        summary = []
        ok = False
        try:
            ok = self._execute_loop(summary)
        except WorkflowError as exc:
            self.bus.emit("CONTROLLER", LEVEL_ERROR, str(exc))
        except Exception as exc:
            self.bus.emit("CONTROLLER", LEVEL_ERROR, f"Unexpected workflow failure: {exc}")
        finally:


            self.manager.stop([p["key"] for p in self.platforms])
            self._finish(ok, " | ".join(summary) if summary else "Workflow stopped.")

    def _execute_loop(self, summary):
        """Run the START workflow continuously until STOP is pressed.

        One video at a time, strictly sequential: generate -> upload to every
        selected platform -> wait for the queues to drain -> generate the
        next video -> upload -> ... The uploader workers stay alive between
        videos (browser/session initialized once), so the whole pipeline is
        an endless generate/upload loop.

        A failed generation is reported and the loop moves on to the next
        video (matching the machine's default stopOnError=false). If videos
        cannot be uploaded — a dead uploader worker or the drain deadline —
        the loop stops so files are never silently dropped.
        """
        if not self.platforms:
            raise WorkflowError("No platform selected. Select at least one platform and try again.")

        labels = ", ".join(p["label"] for p in self.platforms)
        self._stage(f"Continuous workflow started for: {labels} - press STOP to end the session")

        iteration = 0
        while not self.stop_requested:
            iteration += 1
            self._stage(f"Starting video #{iteration}: generate, then upload to every selected platform")
            try:
                self._execute(summary)
            except WorkflowError as exc:
                self.bus.emit(
                    "CONTROLLER",
                    LEVEL_ERROR,
                    f"Video #{iteration}: {exc} - moving on to the next video",
                )
                summary.append(f"Video #{iteration} ✗ ({exc})")
                continue
            if self.stop_requested:
                break
            leftovers = self._pending_videos()
            for platform in self.platforms:
                key = platform["key"]
                new_failed = self._failed_dir_files(platform) - self._failed_baseline.get(key, set())
                if new_failed:
                    leftovers.setdefault(key, len(new_failed))
            if leftovers:
                raise WorkflowError(
                    "Some uploads did not complete - the workflow was stopped. "
                    "Failed videos stay recoverable in queue/<platform>/upload (or queue/yt/failed)."
                )
            self.bus.emit(
                "CONTROLLER",
                LEVEL_OK,
                f"Video #{iteration} uploaded to every selected platform - generating the next video...",
            )
            summary.append(f"Video #{iteration} ✓")

        summary.append(f"Session stopped after {iteration} video(s)")
        return True

    def _platform_upload_dir(self, platform):
        return Path(self.cwd) / "queue" / platform["folder"] / UPLOAD_FOLDER_NAME

    def _pending_videos(self):
        """Map platform key -> video names still waiting in its upload dir."""
        pending = {}
        for platform in self.platforms:
            files = list_video_files(self._platform_upload_dir(platform))
            if files:
                pending[platform["key"]] = files
        return pending

    def _latest_job_manifest(self):
        """Newest ``jobs/*.json`` created by this workflow run, if any.

        The machine writes one manifest per run and its stem
        (``<timestamp>-<jobId>``) is the exact file-name prefix of the
        videos/sidecars that run delivers to the platform queues.
        """
        jobs_dir = Path(self.cwd) / "jobs"
        if not jobs_dir.is_dir():
            return None
        started = getattr(self, "_started_at", 0.0)
        candidates = [
            p
            for p in jobs_dir.glob("*.json")
            if p.is_file() and p.stat().st_mtime >= started - 1.0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _job_delivery_evidence(self, platform, manifest):
        """Files of the newest job the uploader already moved to ``done``.

        With uploaders running in watch mode a video can be picked up and
        moved out of the upload folder before the delivery check runs;
        without this, an empty upload folder would be reported as "no video
        generated" even though the upload succeeded.
        """
        done_dir = Path(self.cwd) / "queue" / platform["folder"] / "done"
        if not done_dir.is_dir():
            return []
        return sorted(
            p.name for p in done_dir.glob(f"{manifest.stem}.*") if p.is_file()
        )

    def _execute(self, summary):
        if self.stop_requested:
            return False
        if not self.platforms:
            raise WorkflowError("No platform selected. Select at least one platform and try again.")

        self._started_at = time.time()
        labels = ", ".join(p["label"] for p in self.platforms)
        self._stage(f"Workflow started for: {labels}")




        self._failed_baseline = {
            p["key"]: self._failed_dir_files(p) for p in self.platforms
        }


        self._stage("Starting uploader workers...")
        for platform in self.platforms:
            delay = self.delays.get(platform["key"], 0) or 0
            worker = self.manager.start(platform, delay=delay)
            self._workers[platform["key"]] = worker
        self._stage("Generating video... (machine) - uploaders are already watching their queues")


        machine_keys = [p["machine_key"] for p in self.platforms]
        command = [part.replace("{platforms}", ",".join(machine_keys)) for part in GENERATOR_COMMAND]
        generator = self.runner_factory(command, "GENERATOR", self.bus, cwd=self.cwd)
        self._current_runner = generator
        code = generator.run()
        self._current_runner = None
        if self.stop_requested:
            return False
        if code != 0:
            raise WorkflowError(f"Video generation failed (exit code {code}); uploaders were stopped.")

        summary.append("Generated")



        self._stage("Verifying generated videos + description files...")
        manifest = self._latest_job_manifest()
        for platform in self.platforms:
            pairs = find_video_pairs(self._platform_upload_dir(platform))
            if pairs:
                self.bus.emit(
                    "CONTROLLER",
                    LEVEL_OK,
                    f"{platform['label']}: {len(pairs)} video(s) with description ready",
                )
                continue
            evidence = self._job_delivery_evidence(platform, manifest) if manifest else []
            if evidence:
                job_id = manifest.stem.rsplit("-", 1)[-1]
                self.bus.emit(
                    "CONTROLLER",
                    LEVEL_OK,
                    f"{platform['label']}: {len(evidence)} file(s) of job {job_id} "
                    "already picked up by the uploader",
                )
                continue
            self.bus.emit(
                "CONTROLLER",
                LEVEL_WARN,
                f"No video with a description file was generated for {platform['label']}.",
            )


        self._stage("Uploading to the selected platforms in parallel...")
        leftovers = self._wait_for_drain()
        if self.stop_requested:
            return False

        for platform in self.platforms:
            key = platform["key"]
            if key in leftovers:
                summary.append(f"{platform['label']} ✗ ({leftovers[key]} video(s) not uploaded)")
            else:
                summary.append(f"{platform['label']} ✓")
        if leftovers:
            self.bus.emit(
                "CONTROLLER",
                LEVEL_ERROR,
                "Some uploads did not complete - the affected videos are still recoverable: "
                "failed files stay in queue/<platform>/upload (or queue/yt/failed). "
                "Click Upload All or press START to retry them.",
            )
        else:
            self.bus.emit("CONTROLLER", LEVEL_OK, "All queues drained - every video was uploaded.")

        return True

    def _failed_dir_files(self, platform):
        """Video files currently in the platform's ``failed`` folder."""
        folder = Path(self.cwd) / "queue" / platform["folder"] / "failed"
        if not folder.is_dir():
            return set()
        return {
            path.name
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        }

    def _wait_for_drain(self):
        """Wait until every selected platform's queue is fully drained.

        Per platform, "done" means: upload folder empty AND no new video in
        the failed folder (YouTube moves failed uploads there). A platform
        with pending files and a live worker keeps the wait going; a dead
        worker with pending files, or a settled failure, is reported
        immediately. The global deadline caps the wait. Videos are never
        moved, deleted or marked done here.
        """
        deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS
        reported = set()
        while not self.stop_requested:
            pending = self._pending_videos()
            leftover = {}
            waiting = False
            for platform in self.platforms:
                key = platform["key"]
                n_pending = len(pending.get(key, []))
                n_failed = len(self._failed_dir_files(platform) - self._failed_baseline.get(key, set()))
                if n_pending == 0 and n_failed == 0:
                    continue
                if n_pending > 0 and self._workers.get(key) is not None and self._workers[key].is_alive():
                    waiting = True
                    continue
                leftover[key] = n_pending + n_failed
                if key not in reported:
                    reported.add(key)
                    self.bus.emit(
                        "CONTROLLER",
                        LEVEL_ERROR,
                        f"{platform['label']} uploader is not running and {n_pending + n_failed} "
                        f"video(s) were not uploaded.",
                    )
            if not waiting:
                return leftover
            if time.monotonic() >= deadline:
                for platform in self.platforms:
                    key = platform["key"]
                    n_pending = len(pending.get(key, []))
                    n_failed = len(self._failed_dir_files(platform) - self._failed_baseline.get(key, set()))
                    if n_pending or n_failed:
                        leftover[key] = n_pending + n_failed
                        if key not in reported:
                            self.bus.emit(
                                "CONTROLLER",
                                LEVEL_ERROR,
                                f"Timed out waiting for {platform['label']} - {n_pending + n_failed} "
                                f"video(s) were not uploaded.",
                            )
                return leftover
            time.sleep(DRAIN_POLL_SECONDS)
        return {}

    def build_generator_command(self):
        machine_keys = [p["machine_key"] for p in self.platforms]
        return [part.replace("{platforms}", ",".join(machine_keys)) for part in GENERATOR_COMMAND]
