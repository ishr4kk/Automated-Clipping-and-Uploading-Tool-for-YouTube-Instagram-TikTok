"""Tab pages for the control panel (Overview, Console, Settings, Setup, Info)."""

import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from webbrowser import open as open_url

from . import config
from .config import PLATFORM_BY_KEY, PLATFORMS, Theme
from .logbus import LEVEL_INFO
from .repair import BackgroundTask, clear_cache, run_fix
from .widgets import (
    AccentLabel,
    Card,
    IconDot,
    MutedLabel,
    RoundedButton,
    SectionLabel,
    theme,
    ui_font,
)

PLATFORM_COLORS = {
    "tiktok": "#69C9D0",
    "youtube": "#FF0033",
    "instagram": "#E1306C",
}


class BaseTab(tk.Frame):
    """Common base: themed background + optional header."""

    def __init__(self, master, title=None):
        super().__init__(master, bg=theme.BG)
        self.title = title
        if title:
            SectionLabel(self, text=title).pack(anchor="w", padx=28, pady=(22, 2))

    def on_shown(self):
        """Called by the navigator whenever this tab becomes visible."""


class OverviewTab(BaseTab):
    """Platform selection + the START / STOP controls."""

    def __init__(self, master, on_start, on_stop):
        super().__init__(master, title="Overview")
        self.on_start = on_start
        self.on_stop = on_stop
        self._platform_vars = {}
        self._finished_at_least_once = False

        intro = MutedLabel(
            self,
            "Generate one video, then upload it to the selected platforms in parallel.",
            size=10,
        )
        intro.pack(anchor="w", padx=28, pady=(2, 14))

        card = Card(self)
        card.pack(fill="x", padx=28, pady=(0, 6))
        self._card_inner = card.inner
        SectionLabel(card.inner, text="Platforms", size=11).pack(anchor="w")
        MutedLabel(card.inner, text="Unchecked platforms are skipped.", size=8).pack(anchor="w", pady=(1, 10))

        for platform in PLATFORMS:
            row = tk.Frame(card.inner, bg=card.inner.cget("bg"))
            row.pack(fill="x", pady=4)

            var = tk.BooleanVar(value=True)
            self._platform_vars[platform["key"]] = var

            IconDot(row, PLATFORM_COLORS[platform["key"]]).pack(side="left", padx=(2, 10))

            checkbox = tk.Checkbutton(
                row,
                text=platform["label"],
                variable=var,
                bg=card.inner.cget("bg"),
                fg=theme.TEXT,
                activebackground=card.inner.cget("bg"),
                activeforeground=theme.TEXT,
                selectcolor=theme.FIELD,
                font=ui_font(11, "bold"),
                highlightthickness=0,
                bd=0,
                cursor="hand2",
            )
            checkbox.pack(side="left")

            folder_note = MutedLabel(
                row,
                text=f"queue/{platform['folder']}",
                size=8,
                bg=card.inner.cget("bg"),
            )
            folder_note.pack(side="right")

        controls = tk.Frame(self, bg=theme.BG)
        controls.pack(fill="x", padx=28, pady=(18, 10))

        self.start_button = RoundedButton(
            controls,
            text="START",
            icon="play",
            command=self._on_start_clicked,
            bg=theme.ACCENT,
            fg=theme.TEXT,
            hover_bg=theme.ACCENT_DARK,
            radius=14,
            width=230,
            height=58,
            font=ui_font(17, "bold"),
        )
        self.start_button.pack(side="left")

        self.stop_button = RoundedButton(
            controls,
            text="STOP",
            icon="stop",
            command=self._on_stop_clicked,
            bg=theme.FIELD,
            fg=theme.ERROR,
            hover_bg=theme.ERROR,
            hover_fg=theme.FIELD,
            radius=14,
            width=150,
            height=58,
            font=ui_font(15, "bold"),
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=(16, 0))

        self._status_label = MutedLabel(self, "Ready.")
        self._status_label.pack(anchor="w", padx=28, pady=(2, 6))

        self._stage_label = MutedLabel(self, "")
        self._stage_label.pack(anchor="w", padx=28)



    def _on_start_clicked(self):
        selected = [p for p in PLATFORMS if self._platform_vars[p["key"]].get()]
        self.on_start(selected)

    def _on_stop_clicked(self):
        self.on_stop()

    def set_running(self, running):
        self.start_button.set_state("disabled" if running else "normal")
        self.stop_button.set_state("normal" if running else "disabled")
        if running:
            self._status_label.config(
                text="Workflow in progress - STOP to cancel at any time.", fg=theme.WARN
            )
        elif not self._finished_at_least_once:
            self._status_label.config(text="Ready.", fg=theme.TEXT_DIM)

    def set_stage(self, text):
        self._stage_label.config(text=text)

    def set_finished(self, ok, summary):
        self._finished_at_least_once = True
        self._status_label.config(
            text="Workflow finished." if ok else "Workflow finished with errors - check the Console tab.",
            fg=theme.OK if ok else theme.ERROR,
        )
        self._stage_label.config(text=summary, fg=theme.TEXT_DIM)


class UploaderTab(BaseTab):
    """Per-platform upload section: Upload All / Stop, cooldown delay input
    and a live status line for each platform.

    Each platform runs its own independent worker thread (see workers.py);
    the delay is the cooldown between videos on that platform, applied by
    the platform's uploader subprocess — it never blocks the UI or any
    other platform.
    """

    def __init__(self, master, on_upload_all=None):
        super().__init__(master, title="Uploader")
        self.on_upload_all = on_upload_all or (lambda key: None)
        self.on_stop_upload = None
        self._delay_vars = {}
        self._upload_buttons = {}
        self._stop_buttons = {}
        self._status_labels = {}

        intro = MutedLabel(
            self,
            "Upload every video in a platform's queue/upload folder. Each platform "
            "runs its own independent worker, so uploads never block each other.",
            size=9,
        )
        intro.pack(anchor="w", padx=28, pady=(2, 12))

        for key in config.UPLOADER_TAB_KEYS:
            platform = PLATFORM_BY_KEY[key]
            self._build_platform_card(platform)

        hint = MutedLabel(
            self,
            "Delay (s) = cooldown between videos on that platform (after an upload "
            "finishes). Applied to the Overview workflow and to Upload All; "
            "leave 0 for no cooldown.",
            size=8,
        )
        hint.pack(anchor="w", padx=28, pady=(2, 0))

    def _build_platform_card(self, platform):
        key = platform["key"]
        card = Card(self)
        card.pack(fill="x", padx=28, pady=(0, 10))

        top = tk.Frame(card.inner, bg=card.inner.cget("bg"))
        top.pack(fill="x")

        title_row = tk.Frame(top, bg=card.inner.cget("bg"))
        title_row.pack(side="left")
        IconDot(title_row, PLATFORM_COLORS[key]).pack(side="left", padx=(2, 10))
        SectionLabel(title_row, text=platform["label"], size=12).pack(side="left")

        controls = tk.Frame(top, bg=card.inner.cget("bg"))
        controls.pack(side="right")

        MutedLabel(controls, "Delay (s):", size=9, bg=card.inner.cget("bg")).pack(side="left")
        delay_var = tk.StringVar(value="0")
        self._delay_vars[key] = delay_var
        delay_entry = tk.Entry(
            controls,
            textvariable=delay_var,
            width=6,
            bg=theme.FIELD,
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief="flat",
            justify="center",
            font=ui_font(10),
        )
        delay_entry.pack(side="left", padx=(4, 12))

        upload_button = RoundedButton(
            controls,
            text="Upload All",
            icon="play",
            command=lambda k=key: self._on_upload_all(k),
            bg=theme.ACCENT,
            fg=theme.TEXT,
            hover_bg=theme.ACCENT_DARK,
            radius=10,
            width=130,
            height=36,
            font=ui_font(10, "bold"),
        )
        upload_button.pack(side="left")
        self._upload_buttons[key] = upload_button

        stop_button = RoundedButton(
            controls,
            text="Stop",
            icon="stop",
            command=lambda k=key: self._on_stop_upload(k),
            bg=theme.FIELD,
            fg=theme.ERROR,
            hover_bg=theme.ERROR,
            hover_fg=theme.FIELD,
            radius=10,
            width=80,
            height=36,
            font=ui_font(10, "bold"),
            state="disabled",
        )
        stop_button.pack(side="left", padx=(8, 0))
        self._stop_buttons[key] = stop_button

        status = MutedLabel(card.inner, "Idle", size=9, bg=card.inner.cget("bg"))
        status.pack(anchor="w", pady=(6, 0))
        self._status_labels[key] = status

        folder_note = MutedLabel(
            card.inner,
            f"queue/{platform['folder']}/upload",
            size=8,
            bg=card.inner.cget("bg"),
        )
        folder_note.pack(anchor="w")



    def _on_upload_all(self, key):
        self.on_upload_all(key)

    def _on_stop_upload(self, key):
        if self.on_stop_upload:
            self.on_stop_upload(key)

    def set_upload_running(self, key, running):
        """Update the per-platform controls (safe to call on the Tk thread)."""
        upload = self._upload_buttons.get(key)
        stop = self._stop_buttons.get(key)
        status = self._status_labels.get(key)
        if upload is None:
            return
        if running:
            upload.set_state("disabled")
            upload.set_text("Uploading...")
            stop.set_state("normal")
            status.config(text="Running - watch the Console for upload progress.", fg=theme.WARN)
        else:
            upload.set_state("normal")
            upload.set_text("Upload All")
            stop.set_state("disabled")
            status.config(text="Idle", fg=theme.TEXT_DIM)



    def get_delays(self):
        """Return {platform key: delay in seconds}; invalid or empty -> 0.

        Accepts numerical values only, rejects negative values and handles
        empty input safely (defaults to 0 = no cooldown).
        """
        import math

        delays = {}
        for key, var in self._delay_vars.items():
            raw = var.get().strip()
            try:
                value = float(raw)
            except ValueError:
                value = 0
            if not math.isfinite(value) or value <= 0:
                value = 0
            delays[key] = value
        return delays


class ConsoleTab(BaseTab):
    """Master Console: time-stamped, color-coded, auto-scrolling log view."""

    def __init__(self, master):
        super().__init__(master, title="Master Console")
        self.entries = []
        self._visible = False

        controls = tk.Frame(self, bg=theme.BG)
        controls.pack(fill="x", padx=28, pady=(2, 8))

        self._autoscroll_var = tk.BooleanVar(value=True)
        autoscroll = tk.Checkbutton(
            controls,
            text="Auto-scroll",
            variable=self._autoscroll_var,
            bg=theme.BG,
            fg=theme.TEXT_DIM,
            activebackground=theme.BG,
            activeforeground=theme.TEXT,
            selectcolor=theme.FIELD,
            font=ui_font(9),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        autoscroll.pack(side="left")

        RoundedButton(
            controls,
            text="Clear",
            command=self.clear,
            radius=10,
            width=90,
            height=28,
            font=ui_font(9),
        ).pack(side="right")

        outer = tk.Frame(self, bg=theme.FIELD)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        self.text = tk.Text(
            outer,
            bg=theme.FIELD,
            fg=theme.TEXT,
            insertbackground=theme.TEXT,
            relief="flat",
            bd=0,
            wrap="none",
            font=ui_font(9),
            state="disabled",
            padx=10,
            pady=8,
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for level, color in Theme.CONSOLE_LEVEL_TAGS.items():
            self.text.tag_configure(level, foreground=color)
        self.text.tag_configure("time", foreground=theme.COMMENT)
        self.text.tag_configure("source", foreground=theme.TEXT_DIM)



    def append(self, entry):
        """Append a LogEntry. Safe to call from any thread only via the
        Tk main-thread pump (app.py routes bus events through root.after)."""
        self.entries.append(entry)
        if len(self.entries) > config.CONSOLE_MAX_LINES:
            del self.entries[: len(self.entries) - config.CONSOLE_MAX_LINES]
        if self._visible:
            self._render_line(entry)

    def _render_line(self, entry):
        self.text.configure(state="normal")
        self.text.insert("end", f"{entry.format_time()}  ", ("time",))
        self.text.insert("end", f"{entry.source:<11} ", ("source",))
        self.text.insert("end", f"{entry.message}\n", (entry.level,))
        if len(self.text.get("1.0", "end-1c").splitlines()) > config.CONSOLE_MAX_LINES:
            self.text.delete("1.0", f"{config.CONSOLE_MAX_LINES + 1}.0")
        self.text.configure(state="disabled")
        if self._autoscroll_var.get():
            self.text.see("end")

    def clear(self):
        self.entries.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def on_shown(self):
        self._visible = True
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        for entry in self.entries:
            self._render_line(entry)

    def on_hidden(self):
        self._visible = False


class SettingsTab(BaseTab):
    """Fix problems and clear caches."""

    def __init__(self, master):
        super().__init__(master, title="Settings")
        self._bus = None
        self._task = None
        self._task_queue = queue.Queue()

        fix_card = Card(self)
        fix_card.pack(fill="x", padx=28, pady=(2, 10))
        SectionLabel(fix_card.inner, text="Fix", size=11).pack(anchor="w")
        MutedLabel(
            fix_card.inner,
            "Diagnose and repair the project: reinstall broken dependencies, "
            "restore missing files and fix invalid settings.",
            size=9,
        ).pack(anchor="w", pady=(1, 10))

        fix_row = tk.Frame(fix_card.inner, bg=fix_card.inner.cget("bg"))
        fix_row.pack(anchor="w")
        self.fix_button = RoundedButton(
            fix_row,
            text="Run fix",
            icon="wrench",
            command=self._run_fix,
            bg=theme.ACCENT,
            hover_bg=theme.ACCENT_DARK,
            radius=12,
            width=170,
            height=40,
            font=ui_font(11, "bold"),
        )
        self.fix_button.pack(side="left")
        self._fix_status = MutedLabel(fix_row, "", size=9, bg=fix_card.inner.cget("bg"))
        self._fix_status.pack(side="left", padx=(12, 0))

        cache_card = Card(self)
        cache_card.pack(fill="x", padx=28)
        SectionLabel(cache_card.inner, text="Clear cache", size=11).pack(anchor="w")
        MutedLabel(
            cache_card.inner,
            "Delete generated logs, temp render files and uploaded videos kept "
            "in the done folders. Pending uploads and dedupe state are kept.",
            size=9,
        ).pack(anchor="w", pady=(1, 10))

        cache_row = tk.Frame(cache_card.inner, bg=cache_card.inner.cget("bg"))
        cache_row.pack(anchor="w")
        self.clear_button = RoundedButton(
            cache_row,
            text="Clear cache",
            icon="trash",
            command=self._run_clear,
            bg=theme.FIELD,
            fg=theme.TEXT,
            hover_bg=theme.ERROR,
            hover_fg=theme.FIELD,
            radius=12,
            width=170,
            height=40,
            font=ui_font(11, "bold"),
        )
        self.clear_button.pack(side="left")
        self._clear_status = MutedLabel(cache_row, "", size=9, bg=cache_card.inner.cget("bg"))
        self._clear_status.pack(side="left", padx=(12, 0))

    def bind_bus(self, bus):
        self._bus = bus

    def _run_fix(self):
        if self._bus is None:
            return
        self.fix_button.set_state("disabled")
        self._fix_status.config(text="working...", fg=theme.WARN)
        self._bus.emit("SETTINGS", LEVEL_INFO, "Fix requested")
        self._task = BackgroundTask(
            lambda: run_fix(self._bus),
            on_done=lambda result: self._task_queue.put("fix"),
        )
        self._task.start()
        self.after(50, self._poll_task)

    def _run_clear(self):
        if self._bus is None:
            return
        confirmed = messagebox.askyesno(
            "Clear cache",
            "Delete logs, temp work, __pycache__ and videos in the done folders?\n\n"
            "Pending uploads and upload history are kept.",
            parent=self,
        )
        if not confirmed:
            return
        self.clear_button.set_state("disabled")
        self._clear_status.config(text="clearing...", fg=theme.WARN)
        self._task = BackgroundTask(
            lambda: clear_cache(self._bus),
            on_done=lambda result: self._task_queue.put("clear"),
        )
        self._task.start()
        self.after(50, self._poll_task)

    def _poll_task(self):
        """Deliver a finished background task on the Tk main thread.

        BackgroundTask.run() calls its ``on_done`` from the worker thread;
        touching Tk widgets there is unsafe, so the worker only pushes a
        marker into a thread-safe queue and we drain it from the main loop.
        """
        if self._task is None:
            return
        try:
            kind = self._task_queue.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_task)
            return
        self._task_done(kind)
        self._task = None

    def _task_done(self, kind):
        label = self._fix_status if kind == "fix" else self._clear_status
        button = self.fix_button if kind == "fix" else self.clear_button
        button.set_state("normal")
        if isinstance(self._task.result, Exception):
            label.config(text=f"{'Fix' if kind == 'fix' else 'Clear'} failed: {self._task.result}", fg=theme.ERROR)
            return
        if kind == "fix":
            summary = self._task.result.summary
            color = theme.OK if self._task.result.error == 0 else theme.ERROR
        else:
            summary = f"{self._task.result} item(s) removed"
            color = theme.OK
        label.config(text=summary, fg=color)


class SetupTab(BaseTab):
    """Launch the existing environment editor (single instance)."""

    def __init__(self, master):
        super().__init__(master, title="Setup")
        self._editor_proc = None
        MutedLabel(
            self,
            "Open the environment editor to manage session cookies and\n"
            "generation options (VIDEO_CUT, VIDEO_LENGTH_SECONDS, captions, ...).",
            size=9,
        ).pack(anchor="w", padx=28, pady=(2, 12))

        RoundedButton(
            self,
            text="Open env editor",
            icon="wrench",
            command=self._open_editor,
            bg=theme.ACCENT,
            hover_bg=theme.ACCENT_DARK,
            radius=12,
            width=190,
            height=42,
            font=ui_font(11, "bold"),
        ).pack(anchor="w", padx=28)

        self._status = MutedLabel(self, "")
        self._status.pack(anchor="w", padx=28, pady=(10, 0))

    def _editor_running(self):
        """True while the editor we spawned is alive, or when any process is
        running env_editor.pyw. Scanning for any pythonw.exe would always
        match the control panel itself, so the command line is inspected."""
        proc = self._editor_proc
        if proc is not None:
            if proc.poll() is None:
                return True
            self._editor_proc = None
        if os.name != "nt":
            return False
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" |"
                    " Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return "env_editor.pyw" in (result.stdout or "").lower()
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _pythonw_exe():
        """pythonw.exe living next to the interpreter running the panel."""
        if os.name != "nt":
            return "python3"
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
        return "pythonw.exe"

    def _open_editor(self):
        editor = config.ENV_EDITOR_PATH
        if not editor.is_file():
            self._status.config(text=f"env editor not found: {editor}", fg=theme.ERROR)
            return
        if self._editor_running():
            self._status.config(
                text="The env editor is already open - check its window.",
                fg=theme.WARN,
            )
            return
        try:
            self._editor_proc = subprocess.Popen(
                [self._pythonw_exe(), str(editor)],
                cwd=str(config.PROJECT_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._status.config(
                text=f"Opened env editor ({editor.name}).",
                fg=theme.OK,
            )
        except OSError as exc:
            self._status.config(text=f"Could not open the env editor: {exc}", fg=theme.ERROR)


class InfoTab(BaseTab):
    """About + contact buttons."""

    LINK_ICONS = {
        "Instagram": "instagram",
        "GitHub": "github",
        "Discord": "discord",
    }

    def __init__(self, master):
        super().__init__(master)
        AccentLabel(self, text="ishr4k._", size=26).pack(anchor="w", padx=28, pady=(36, 2))
        MutedLabel(self, text="r4k auto - Control Panel").pack(anchor="w", padx=28)

        SectionLabel(self, text="Contact", size=11).pack(anchor="w", padx=28, pady=(24, 10))
        for name, url in config.INFO_LINKS:
            row = tk.Frame(self, bg=theme.BG)
            row.pack(anchor="w", padx=28, pady=4)

            button = RoundedButton(
                row,
                text=name,
                icon=self.LINK_ICONS.get(name, "globe"),
                command=lambda target=url: open_url(target),
                bg=theme.PANEL,
                fg=theme.TEXT,
                hover_bg=theme.ACCENT,
                radius=12,
                width=150,
                height=42,
                font=ui_font(11, "bold"),
            )
            button.pack(side="left")

            MutedLabel(row, text=url, size=8, bg=theme.BG).pack(side="left", padx=(12, 0))

        MutedLabel(self, text=f"version {config.APP_VERSION}", size=8).pack(anchor="w", padx=28, pady=(24, 0))
