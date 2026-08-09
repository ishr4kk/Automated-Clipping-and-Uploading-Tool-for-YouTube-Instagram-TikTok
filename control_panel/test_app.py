"""Self-running test suite for the control panel (plain asserts).

Run from the project root:
    python control_panel/test_app.py
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from control_panel import config
from control_panel.config import PLATFORMS, Theme
from control_panel.logbus import LEVEL_ERROR, LEVEL_INFO, LEVEL_OK, LEVEL_WARN, LogBus
from control_panel.workers import (
    UploadManager,
    WorkflowController,
    WorkflowError,
    classify_line,
    find_video_pairs,
    list_video_files,
)

PASSED = 0


def ok(name):
    global PASSED
    PASSED += 1
    print(f"PASS  {name}")






def test_logbus():
    bus = LogBus(ring_size=3)
    seen = []
    unsubscribe = bus.subscribe(seen.append)
    bus.emit("A", LEVEL_INFO, "hello")
    bus.emit("A", LEVEL_WARN, "careful")
    bus.emit("A", LEVEL_ERROR, "boom")
    assert len(seen) == 3, seen
    assert seen[0].source == "A" and seen[0].level == LEVEL_INFO
    assert seen[1].level == LEVEL_WARN
    assert seen[2].level == LEVEL_ERROR
    assert len(bus.ring) == 3

    bus.emit("A", LEVEL_INFO, "ring overflow")
    assert len(bus.ring) == 3
    assert bus.ring[0].message == "careful"

    unsubscribe()
    bus.emit("A", LEVEL_INFO, "not seen")
    assert len(seen) == 4
    assert seen[3].message == "ring overflow"
    ok("logbus: subscribe/unsubscribe/ring")


def test_classify_line():
    assert classify_line("[INFO] doing a thing") == LEVEL_INFO
    assert classify_line("[OK  ] all good") == LEVEL_OK
    assert classify_line("[WARN] something") == LEVEL_WARN
    assert classify_line("[FAIL] nope") == LEVEL_ERROR
    assert classify_line("[ERROR] nope") == LEVEL_ERROR
    assert classify_line("Upload failed for video") == LEVEL_ERROR
    assert classify_line("warning: retrying") == LEVEL_WARN
    assert classify_line("Upload completed") == LEVEL_OK
    assert classify_line("just a normal line") == LEVEL_INFO
    ok("workers: classify_line")






def test_find_video_pairs():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "queue" / "insta" / "upload"
        folder.mkdir(parents=True)
        (folder / "a.mp4").write_bytes(b"v")
        (folder / "a.description").write_text("desc")
        (folder / "b.mp4").write_bytes(b"v")
        (folder / "c.description").write_text("desc")
        (folder / "z.mp4").write_bytes(b"v")
        (folder / "z.txt").write_text("sidecar via txt")
        assert find_video_pairs(folder) == ["a", "z"]
    assert find_video_pairs(Path(tmp2 := tempfile.mkdtemp()) / "missing") == []
    shutil.rmtree(tmp2)
    ok("workers: find_video_pairs")






FOLDER_BY_SOURCE = {"TIKTOK": "tiktok", "YOUTUBE": "yt", "INSTAGRAM": "insta"}


class FakeRunner:
    """Simulates a successful uploader run: with exit code 0 the platform's
    videos are moved from queue/<folder>/upload to queue/<folder>/done,
    exactly like the real uploaders do after a confirmed upload."""

    instances = []
    exit_codes = {}

    def __init__(self, command, source, bus, cwd=None):
        self.command = list(command)
        self.source = source
        self.bus = bus
        self.cwd = cwd
        FakeRunner.instances.append(self)

    def run(self):
        key = " ".join(self.command)
        code = FakeRunner.exit_codes.get(key, 0)
        folder = FOLDER_BY_SOURCE.get(self.source)
        if code == 0 and folder:
            upload = Path(self.cwd) / "queue" / folder / "upload"
            done = Path(self.cwd) / "queue" / folder / "done"
            if upload.is_dir():
                done.mkdir(parents=True, exist_ok=True)
                for f in list(upload.iterdir()):
                    if f.is_file() and f.suffix.lower() in config.VIDEO_EXTENSIONS:
                        shutil.move(str(f), str(done / f.name))
        return code

    def terminate(self):
        pass


def make_platforms(keys):
    return [next(p for p in PLATFORMS if p["key"] == k) for k in keys]


def make_fake_workflow(keys, tmp, exit_codes, on_event=None, delays=None):
    """Build a WorkflowController whose fake runners honour exit_codes
    (keyed by joined command) and whose queue dirs contain ready pairs."""
    for key in keys:
        upload = Path(tmp) / "queue" / next(p["folder"] for p in PLATFORMS if p["key"] == key) / "upload"
        upload.mkdir(parents=True, exist_ok=True)
        (upload / "test.mp4").write_bytes(b"v")
        (upload / "test.description").write_text("desc")
    FakeRunner.instances = []
    FakeRunner.exit_codes = exit_codes
    return WorkflowController(
        make_platforms(keys),
        bus=LogBus(),
        runner_factory=FakeRunner,
        on_event=on_event,
        cwd=tmp,
        delays=delays,
    )


def _await_stop(wf, timeout=15):
    """Wait for the workflow thread to finish; returns False on timeout."""
    deadline = time.time() + timeout
    while wf.is_alive() and time.time() < deadline:
        time.sleep(0.05)
    return not wf.is_alive()


def test_workflow_parallel_uploader_commands():
    with tempfile.TemporaryDirectory() as tmp:
        events = []
        wf = make_fake_workflow(["tiktok", "youtube", "instagram"], tmp, {}, events.append)
        summary = []
        assert wf._execute(summary) is True
        commands = [" ".join(r.command) for r in FakeRunner.instances]
        generator = next(c for c in commands if "run.js" in c)
        assert generator == "node run.js --platforms tiktok,yt,insta", commands


        uploaders = [c for c in commands if "run.js" not in c]
        assert uploaders == [
            "node tiktok_uploader/main.js",
            f"{config.PYTHON_EXE} yt_uploader/uploader.py",
            "node instagram_uploader/main.js",
        ], uploaders
        stages = [e["text"] for e in events if e["type"] == "stage"]
        assert any("Starting uploader workers" in s for s in stages)
        assert any("Generating" in s for s in stages)
        assert all("✓" in s for s in summary if s != "Generated"), summary
        ok("workflow: generator + 3 independent watch-mode uploader workers, all drained")


def test_workflow_subset_platforms():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow(["youtube"], tmp, {})
        summary = []
        assert wf._execute(summary) is True
        commands = [" ".join(r.command) for r in FakeRunner.instances]
        assert f"{config.PYTHON_EXE} yt_uploader/uploader.py" in commands, commands
        assert "--once" not in " ".join(commands)
        assert any("YouTube ✓" in s for s in summary)
        ok("workflow: single platform subset")


def test_workflow_per_platform_delays():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow(
            ["tiktok", "youtube", "instagram"],
            tmp,
            {},
            delays={"tiktok": 30, "instagram": 2.5},
        )
        summary = []
        assert wf._execute(summary) is True
        commands = [" ".join(r.command) for r in FakeRunner.instances]
        assert "node tiktok_uploader/main.js --delay 30" in commands, commands
        assert f"{config.PYTHON_EXE} yt_uploader/uploader.py" in commands, commands
        assert "node instagram_uploader/main.js --delay 2.5" in commands, commands
        ok("workflow: per-platform delay appended as --delay (watch mode)")


def test_workflow_generator_failure_stops_workers():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow(
            ["tiktok", "instagram"],
            tmp,
            {"node run.js --platforms tiktok,insta": 1},
        )
        summary = []
        try:
            wf._execute(summary)
            assert False, "expected WorkflowError"
        except WorkflowError as exc:
            assert "generation failed" in str(exc)
        deadline = time.time() + 10
        while time.time() < deadline and wf.manager.running_keys():
            time.sleep(0.05)
        assert wf.manager.running_keys() == [], "workers must be stopped after generator failure"
        ok("workflow: generator failure stops the uploader workers")


def test_workflow_missing_description_warns_and_continues():
    with tempfile.TemporaryDirectory() as tmp:
        bus = LogBus()
        for key in ("tiktok", "youtube"):
            upload = Path(tmp) / "queue" / next(p["folder"] for p in PLATFORMS if p["key"] == key) / "upload"
            upload.mkdir(parents=True, exist_ok=True)
            (upload / "test.mp4").write_bytes(b"v")
            (upload / "test.description").write_text("desc")

        (Path(tmp) / "queue" / "tiktok" / "upload" / "test.description").unlink()
        FakeRunner.instances = []
        FakeRunner.exit_codes = {}
        wf = WorkflowController(
            make_platforms(["tiktok", "youtube"]),
            bus=bus,
            runner_factory=FakeRunner,
            cwd=tmp,
        )
        summary = []


        assert wf._execute(summary) is True
        messages = [e.message for e in bus.ring]
        assert any("No video with a description file" in m and "TikTok" in m for m in messages)
        assert any("TikTok ✓" in s for s in summary), summary
        ok("workflow: missing description sidecar -> warning only, upload continues")


def test_workflow_delivery_evidence_via_manifest():
    """When the uploader already moved this run's video to done, the delivery
    check reports it as evidence instead of a false 'no video' warning."""
    with tempfile.TemporaryDirectory() as tmp:
        jobs = Path(tmp) / "jobs"
        jobs.mkdir(parents=True)
        stem = "2026-08-09T10-00-00-000Z-abc123"
        (jobs / f"{stem}.json").write_text('{"jobId": "abc123", "platforms": ["tiktok"]}')
        done = Path(tmp) / "queue" / "tiktok" / "done"
        done.mkdir(parents=True)
        (done / f"{stem}.mp4").write_bytes(b"v")
        (done / f"{stem}.description").write_text("desc")
        FakeRunner.instances = []
        FakeRunner.exit_codes = {}
        bus = LogBus()
        wf = WorkflowController(
            make_platforms(["tiktok"]),
            bus=bus,
            runner_factory=FakeRunner,
            cwd=tmp,
        )
        summary = []
        assert wf._execute(summary) is True
        messages = [e.message for e in bus.ring]
        assert any("already picked up" in m for m in messages), messages
        assert not any("No video with a description file" in m for m in messages), messages
        ok("workflow: uploader-drained queue reported via job manifest evidence")


def test_yt_token_path_resolution():
    import importlib

    import yt_uploader.config as yt_config

    tmp = tempfile.mkdtemp()
    try:
        override = os.path.join(tmp, "custom-token.json")
        os.environ["YT_UPLOADER_TOKEN_PATH"] = override
        yt_config = importlib.reload(yt_config)
        assert str(yt_config.TOKEN_PATH) == override
        del os.environ["YT_UPLOADER_TOKEN_PATH"]
        yt_config = importlib.reload(yt_config)
        assert yt_config.TOKEN_PATH.name == "youtube_token.json", yt_config.TOKEN_PATH
        assert yt_config.TOKEN_PATH.parent.name == "yt_uploader"
    finally:
        os.environ.pop("YT_UPLOADER_TOKEN_PATH", None)
        shutil.rmtree(tmp, ignore_errors=True)
    ok("yt uploader: token path resolves to youtube_token.json, env override wins")


def test_workflow_uploader_failure_continues():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow(
            ["tiktok", "youtube", "instagram"],
            tmp,
            {"node tiktok_uploader/main.js": 3},
        )
        summary = []
        assert wf._execute(summary) is True
        assert any("TikTok ✗" in s and "not uploaded" in s for s in summary), summary
        assert any("YouTube ✓" in s for s in summary)
        assert any("Instagram ✓" in s for s in summary)

        assert (Path(tmp) / "queue" / "tiktok" / "upload" / "test.mp4").is_file()
        assert not (Path(tmp) / "queue" / "tiktok" / "done" / "test.mp4").exists()
        ok("workflow: failed uploader does not stop the other platforms, file recoverable")


def test_workflow_no_platforms():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow([], tmp, {})
        summary = []
        try:
            wf._execute(summary)
            assert False, "expected WorkflowError"
        except WorkflowError as exc:
            assert "No platform selected" in str(exc)
        ok("workflow: no platforms selected -> clear error")


def test_workflow_stop_requested():
    with tempfile.TemporaryDirectory() as tmp:
        wf = make_fake_workflow(["tiktok"], tmp, {})
        wf._stop_event.set()
        summary = []
        assert wf._execute(summary) is False
        assert FakeRunner.instances == []
        ok("workflow: stop requested before run aborts")


def test_workflow_parallel_workers_independent():
    """All three platform workers must run at the same time (none blocks
    another) and a stop releases every one of them."""
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("tiktok", "youtube", "instagram"):
            upload = Path(tmp) / "queue" / next(p["folder"] for p in PLATFORMS if p["key"] == key) / "upload"
            upload.mkdir(parents=True, exist_ok=True)
            (upload / "test.mp4").write_bytes(b"v")
            (upload / "test.description").write_text("desc")

        entered = {key.upper(): threading.Event() for key in ("tiktok", "youtube", "instagram")}
        gate = threading.Event()

        class BlockingRunner(FakeRunner):
            def run(self):
                if self.source in entered:
                    entered[self.source].set()
                    gate.wait(15)
                return super().run()

        wf = WorkflowController(
            make_platforms(["tiktok", "youtube", "instagram"]),
            bus=LogBus(),
            runner_factory=BlockingRunner,
            cwd=tmp,
        )
        wf.start()
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                if all(e.is_set() for e in entered.values()):
                    break
                time.sleep(0.05)

            assert all(e.is_set() for e in entered.values()), "workers did not run concurrently"
            assert all(wf.manager.is_running(k) for k in ("tiktok", "youtube", "instagram"))
        finally:
            gate.set()
            wf.stop()
            assert _await_stop(wf)
        ok("workflow: TikTok + Instagram + YouTube run independently and stop together")


def test_upload_manager_no_duplicate_worker():
    class BlockingRunner(FakeRunner):
        def __init__(self, command, source, bus, cwd=None):
            super().__init__(command, source, bus, cwd)
            self.gate = threading.Event()

        def run(self):
            self.gate.wait(15)
            return super().run()

        def terminate(self):
            self.gate.set()

    with tempfile.TemporaryDirectory() as tmp:
        FakeRunner.instances = []
        FakeRunner.exit_codes = {}
        manager = UploadManager(LogBus(), runner_factory=BlockingRunner, cwd=tmp)
        tiktok = next(p for p in PLATFORMS if p["key"] == "tiktok")
        worker_a = manager.start(tiktok, delay=5)
        worker_b = manager.start(tiktok, delay=5)
        assert worker_a is worker_b
        tiktok_runners = [r for r in FakeRunner.instances if r.source == "TIKTOK"]
        assert len(tiktok_runners) == 1
        assert worker_a.command == ["node", "tiktok_uploader/main.js", "--delay", "5"]
        manager.stop_all()
        ok("upload manager: Upload All twice never creates a duplicate worker")


def test_upload_manager_three_platforms_independent():
    class BlockingRunner(FakeRunner):
        def __init__(self, command, source, bus, cwd=None):
            super().__init__(command, source, bus, cwd)
            self.gate = threading.Event()

        def run(self):
            self.gate.wait(15)
            return super().run()

        def terminate(self):
            self.gate.set()

    with tempfile.TemporaryDirectory() as tmp:
        FakeRunner.instances = []
        FakeRunner.exit_codes = {}
        manager = UploadManager(LogBus(), runner_factory=BlockingRunner, cwd=tmp)
        for key in ("tiktok", "youtube", "instagram"):
            platform = next(p for p in PLATFORMS if p["key"] == key)
            manager.start(platform)
        deadline = time.time() + 10
        while time.time() < deadline and set(manager.running_keys()) != {"tiktok", "youtube", "instagram"}:
            time.sleep(0.05)
        assert set(manager.running_keys()) == {"tiktok", "youtube", "instagram"}
        manager.stop(["tiktok"])
        deadline = time.time() + 10
        while time.time() < deadline and "tiktok" in manager.running_keys():
            time.sleep(0.05)
        assert set(manager.running_keys()) == {"youtube", "instagram"}, manager.running_keys()
        manager.stop_all()
        deadline = time.time() + 10
        while time.time() < deadline and manager.running_keys():
            time.sleep(0.05)
        assert manager.running_keys() == []
        ok("upload manager: three platform workers, per-platform stop")







ROOT = None


def ensure_root():
    global ROOT
    if ROOT is None:
        ROOT = tk.Tk()
        ROOT.withdraw()
    return ROOT


def test_tabs_and_nav():
    root = ensure_root()
    from control_panel.app import App

    app = App(root)
    assert set(app.tabs) == set(config.NAV_ITEMS)
    assert app.current_tab is app.tabs["Overview"]
    app.show_tab("Console")
    assert app.current_tab is app.tabs["Console"]
    assert app.tabs["Console"]._visible is True
    app.show_tab("Overview")
    assert app.tabs["Console"]._visible is False
    app.show_tab("Console")
    ok("app: layout, nav switching, console visibility flag")


def test_overview_checkboxes_and_start():
    root = ensure_root()
    from control_panel.tabs import OverviewTab

    captured, stops = [], []
    tab = OverviewTab(root, on_start=captured.append, on_stop=lambda: stops.append(True))
    assert [p["key"] for p in PLATFORMS] == ["tiktok", "youtube", "instagram"]
    assert all(tab._platform_vars[p["key"]].get() is True for p in PLATFORMS)

    tab._on_start_clicked()
    assert [p["key"] for p in captured[0]] == ["tiktok", "youtube", "instagram"]

    tab._platform_vars["youtube"].set(False)
    tab._on_start_clicked()
    assert [p["key"] for p in captured[1]] == ["tiktok", "instagram"]

    tab.set_running(True)
    assert tab.start_button._state == "disabled"
    assert tab.stop_button._state == "normal"
    tab._on_stop_clicked()
    assert stops == [True]
    tab.set_running(False)
    assert tab.start_button._state == "normal"
    assert tab.stop_button._state == "disabled"
    tab.set_stage("generating...")
    tab.set_finished(True, "Generated | TikTok ✓")
    assert tab.start_button._state == "normal"
    assert "Workflow finished" in tab._status_label.cget("text")
    tab.set_running(False)
    assert "Workflow finished" in tab._status_label.cget("text"), "finish status must survive set_running(False)"
    ok("app: overview checkboxes, START payload, STOP wiring, running state")


def test_uploader_tab_delays_and_buttons():
    root = ensure_root()
    from control_panel.tabs import UploaderTab

    clicked, stopped = [], []
    tab = UploaderTab(root, on_upload_all=clicked.append)
    tab.on_stop_upload = stopped.append
    assert set(tab._delay_vars) == {"tiktok", "youtube", "instagram"}
    assert tab.get_delays() == {"tiktok": 0, "youtube": 0, "instagram": 0}

    tab._delay_vars["tiktok"].set("45")
    tab._delay_vars["instagram"].set("2.5")
    assert tab.get_delays() == {"tiktok": 45, "youtube": 0, "instagram": 2.5}

    tab._delay_vars["tiktok"].set("invalid")
    tab._delay_vars["youtube"].set("")
    tab._delay_vars["instagram"].set("-5")
    assert tab.get_delays() == {"tiktok": 0, "youtube": 0, "instagram": 0}


    assert set(tab._upload_buttons) == {"tiktok", "youtube", "instagram"}
    tab._on_upload_all("tiktok")
    assert clicked == ["tiktok"]
    tab.set_upload_running("tiktok", True)
    assert tab._upload_buttons["tiktok"]._state == "disabled"
    assert tab._stop_buttons["tiktok"]._state == "normal"
    tab.set_upload_running("youtube", True)
    tab._on_stop_upload("youtube")
    assert stopped == ["youtube"]
    tab.set_upload_running("tiktok", False)
    assert tab._upload_buttons["tiktok"]._state == "normal"
    assert tab._stop_buttons["tiktok"]._state == "disabled"
    ok("uploader tab: per-platform delay parsing, Upload All/Stop wiring + running states")


def test_first_run_flag_and_dialog():
    from control_panel.first_run import FirstRunDialog, is_first_run, mark_seen, maybe_show_first_run

    original = config.FIRST_RUN_STATE
    with tempfile.TemporaryDirectory() as tmp:
        flag = Path(tmp) / "first_run.json"
        config.FIRST_RUN_STATE = flag

        assert is_first_run() is True
        dialog = maybe_show_first_run(ensure_root())
        assert isinstance(dialog, FirstRunDialog), "first run -> dialog shown"
        dialog.window.destroy()

        mark_seen()
        assert is_first_run() is False, "flag file must be written by mark_seen"
        assert flag.is_file()
        assert maybe_show_first_run(ensure_root()) is None, "seen -> no dialog"

        dialog = FirstRunDialog(ensure_root())
        assert dialog.window.winfo_exists()
        dialog._finish()
        assert not dialog.window.winfo_exists(), "dialog destroyed on continue"
        assert is_first_run() is False, "continue marks the popup as seen"
    config.FIRST_RUN_STATE = original
    ok("first run: flag default, mark_seen, dialog builds and closes once")


def test_console_rendering():
    root = ensure_root()
    from control_panel.tabs import ConsoleTab
    from control_panel.logbus import LogEntry
    from datetime import datetime

    tab = ConsoleTab(root)
    tab.on_shown()
    entry = LogEntry("YOUTUBE", LEVEL_ERROR, "boom boom", datetime(2026, 8, 6, 12, 0, 0))
    tab.append(entry)
    content = tab.text.get("1.0", "end-1c")
    assert "12:00:00" in content
    assert "YOUTUBE" in content
    assert "boom boom" in content
    assert "ERROR" not in content
    tab.clear()
    assert tab.text.get("1.0", "end-1c") == ""
    assert tab.entries == []
    ok("console: timestamped line rendering + clear")


def test_console_buffers_while_hidden():
    root = ensure_root()
    from control_panel.tabs import ConsoleTab
    from control_panel.logbus import LogEntry
    from datetime import datetime

    tab = ConsoleTab(root)
    assert tab._visible is False
    entry = LogEntry("GENERATOR", LEVEL_OK, "hidden line", datetime.now())
    tab.append(entry)
    assert tab.text.get("1.0", "end-1c") == ""
    assert len(tab.entries) == 1
    tab.on_shown()
    content = tab.text.get("1.0", "end-1c")
    assert "hidden line" in content
    ok("console: hidden tab buffers, replays on show")


def test_setup_tab_graceful_missing_editor():
    root = ensure_root()
    from control_panel.tabs import SetupTab

    tab = SetupTab(root)
    original = config.ENV_EDITOR_PATH
    config.ENV_EDITOR_PATH = Path("definitely/missing/editor.pyw")
    try:
        tab._open_editor()
        assert tab._status.cget("fg") == Theme.ERROR
    finally:
        config.ENV_EDITOR_PATH = original
    ok("setup: missing env editor -> graceful error status")


def test_info_tab_links():
    root = ensure_root()
    from control_panel.tabs import InfoTab
    from control_panel.widgets import RoundedButton

    tab = InfoTab(root)

    def collect(widget, kind=None):
        found = []
        for child in widget.winfo_children():
            if kind is None:
                if isinstance(child, RoundedButton):
                    found.append(child)
            elif isinstance(child, kind):
                found.append(child)
            found.extend(collect(child, kind))
        return found

    buttons = collect(tab)
    assert [b._text for b in buttons] == ["Instagram", "GitHub", "Discord"]
    labels = [c.cget("text") for c in collect(tab, tk.Label)
              if c.cget("text").startswith("https://")]
    for _, url in config.INFO_LINKS:
        assert url in labels, url
    for button in buttons:
        button._draw()
    ok("info: contact entries are buttons with icons + urls")


def test_splash_graceful_skip():
    from control_panel.splash import Splash

    original = config.SPLASH_IMAGE
    config.SPLASH_IMAGE = Path("definitely/missing/author.png")
    try:
        splash = Splash(ensure_root())
        assert splash.shown is False
    finally:
        config.SPLASH_IMAGE = original
    ok("splash: missing image -> gracefully skipped")






def test_widgets_icons_and_cards():
    root = ensure_root()
    from control_panel.widgets import Card, IconDot, RoundedButton

    root.configure(bg="#242424")
    button = RoundedButton(root, text="TEST", icon="play", command=lambda: None, width=120, height=40)
    button._draw()
    assert button._icon == "play"
    assert button._state == "normal"
    button.set_state("disabled")
    assert button._state == "disabled"
    button.set_state("normal")
    for icon in ("play", "stop", "wrench", "trash", "plus", "refresh"):
        button.set_icon(icon)
        button._draw()

    card = Card(root)
    assert hasattr(card, "inner")
    assert card.inner.cget("bg") == card.cget("bg")

    dot = IconDot(root, "#ff0000")
    assert dot.winfo_width() > 0
    ok("widgets: icon buttons draw, cards and icon dots construct")


def test_fonts_fallback_and_switch():
    root = ensure_root()
    import control_panel.fonts as fonts
    import control_panel.widgets as widgets

    original_path = fonts.FONT_PATH
    before = widgets.FONT_FAMILY
    try:
        fonts.FONT_PATH = Path("definitely/missing/Relidux.otf")
        assert fonts.register_font(root) == ""
        assert widgets.FONT_FAMILY == before, "failed registration must not change the family"
    finally:
        fonts.FONT_PATH = original_path

    widgets.set_font_family("Relidux")
    assert widgets.ui_font(12, "bold") == ("Relidux", 12, "bold")
    assert widgets.ui_font(10) == ("Relidux", 10)
    widgets.set_font_family(before)
    ok("fonts: missing file falls back, family switch + ui_font")






def test_set_env_key():
    import control_panel.repair as repair

    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text("A=1\nVIDEO_CUT=sideways\nB=2\n", encoding="utf-8")
        repair.set_env_key(env, "VIDEO_CUT", "starting")
        repair.set_env_key(env, "NEW_KEY", "42")
        content = env.read_text(encoding="utf-8")
        assert "VIDEO_CUT=starting" in content
        assert "NEW_KEY=42" in content
        assert "sideways" not in content
    ok("repair: set_env_key replaces and appends keys")


def test_repair_env_fixes_invalid_values():
    import control_panel.repair as repair

    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text("VIDEO_CUT=sideways\nVIDEO_LENGTH_SECONDS=abc\nOPENROUTER_API_KEY=\n", encoding="utf-8")
        bus = LogBus()
        report = repair.RepairReport()
        repair.repair_env(bus, Path(tmp), report)
        content = env.read_text(encoding="utf-8")
        assert "VIDEO_CUT=starting" in content
        assert "VIDEO_LENGTH_SECONDS=30" in content
        assert report.error >= 1
    ok("repair: invalid VIDEO_CUT/length auto-corrected, missing key reported")


def test_clear_cache_keeps_pending_and_state():
    import control_panel.repair as repair

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "logs").mkdir()
        (root / "logs" / "machine.log").write_text("x")
        (root / "work").mkdir()
        (root / "work" / "tmp.mp4").write_bytes(b"v")
        (root / "stderr.tmp").write_text("x")
        (root / "queue" / "insta" / "done").mkdir(parents=True)
        (root / "queue" / "insta" / "done" / "old.mp4").write_bytes(b"v")
        (root / "queue" / "insta" / "upload").mkdir(parents=True)
        pending = root / "queue" / "insta" / "upload" / "pending.mp4"
        pending.write_bytes(b"v")
        (root / "queue" / "tiktok" / "done").mkdir(parents=True)
        (root / "state").mkdir()
        state_file = root / "state" / "processed.json"
        state_file.write_text("{}")
        (root / "src").mkdir()
        (root / "src" / "__pycache__").mkdir()

        bus = LogBus()
        removed = repair.clear_cache(bus, root=root)

        assert not (root / "logs").exists()
        assert not (root / "work").exists()
        assert not (root / "stderr.tmp").exists()
        assert not (root / "queue" / "insta" / "done" / "old.mp4").exists()
        assert pending.is_file(), "pending upload must survive"
        assert state_file.is_file(), "state must survive"
        assert not (root / "src" / "__pycache__").exists()
        assert removed >= 5
    ok("repair: clear cache removes logs/work/done/pycache, keeps pending + state")


def test_settings_tab_fix_wiring():
    root = ensure_root()
    from control_panel.tabs import SettingsTab
    from control_panel.repair import RepairReport

    bus = LogBus()
    tab = SettingsTab(root)
    tab.bind_bus(bus)

    calls = []
    started = threading.Event()
    gate = threading.Event()

    def fake_fix(bus_ref):
        calls.append(bus_ref)
        started.set()
        gate.wait(10)
        report = RepairReport()
        report.ok_line(bus_ref, "fake ok")
        return report

    import control_panel.tabs as tabs_module
    original = tabs_module.run_fix
    tabs_module.run_fix = fake_fix
    try:
        tab._run_fix()
        assert started.wait(10), "task started"
        assert tab.fix_button._state == "disabled", "button disabled while running"
        gate.set()
        deadline = time.time() + 15
        while tab.fix_button._state == "disabled" and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        assert tab.fix_button._state == "normal", "button re-enabled after task"
        assert calls == [bus]
        assert tab._fix_status.cget("text") != ""
    finally:
        gate.set()
        tabs_module.run_fix = original
    ok("settings: fix button disables, runs task on bus, re-enables + status")




def main():
    test_logbus()
    test_classify_line()
    test_find_video_pairs()
    test_workflow_parallel_uploader_commands()
    test_workflow_subset_platforms()
    test_workflow_per_platform_delays()
    test_workflow_generator_failure_stops_workers()
    test_workflow_missing_description_warns_and_continues()
    test_workflow_delivery_evidence_via_manifest()
    test_yt_token_path_resolution()
    test_workflow_uploader_failure_continues()
    test_workflow_no_platforms()
    test_workflow_stop_requested()
    test_workflow_parallel_workers_independent()
    test_upload_manager_no_duplicate_worker()
    test_upload_manager_three_platforms_independent()
    test_tabs_and_nav()
    test_overview_checkboxes_and_start()
    test_uploader_tab_delays_and_buttons()
    test_first_run_flag_and_dialog()
    test_console_rendering()
    test_console_buffers_while_hidden()
    test_setup_tab_graceful_missing_editor()
    test_info_tab_links()
    test_splash_graceful_skip()
    test_widgets_icons_and_cards()
    test_fonts_fallback_and_switch()
    test_set_env_key()
    test_repair_env_fixes_invalid_values()
    test_clear_cache_keeps_pending_and_state()
    test_settings_tab_fix_wiring()
    print(f"\n{PASSED} tests passed")


if __name__ == "__main__":
    main()
