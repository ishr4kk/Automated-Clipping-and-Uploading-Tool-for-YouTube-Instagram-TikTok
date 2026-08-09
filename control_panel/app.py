"""Main window and application controller.

The controller owns the LogBus and a Tk event queue. Workflow events and
log entries arrive from background threads, are pushed into a
thread-safe queue, and are drained every 50 ms by ``root.after`` on the
Tk main thread - the UI itself never touches widgets from other threads.
"""

import ctypes
import queue
import tkinter as tk

from . import config
from .config import NAV_ITEMS, PLATFORM_BY_KEY
from .fonts import register_font
from .logbus import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARN, LogBus
from .splash import Splash
from .tabs import ConsoleTab, InfoTab, OverviewTab, SettingsTab, SetupTab, UploaderTab
from .widgets import AccentLabel, MutedLabel, RoundedButton, theme, ui_font
from .workers import UploadManager, WorkflowController

POLL_MS = 50


class App:
    def __init__(self, root):
        self.root = root
        root.title(config.APP_TITLE)
        root.configure(bg=theme.BG)
        root.geometry("1000x640")
        root.minsize(820, 520)

        register_font(root)

        self.bus = LogBus()
        self._event_queue = queue.Queue()
        self._workflow = None
        self._upload_manager = UploadManager(self.bus, on_state=self._on_worker_state)

        self._build_layout()

        self.bus.subscribe(self._on_log_entry)
        self._poll_events()





    def _build_layout(self):
        self.sidebar = tk.Frame(self.root, bg=theme.PANEL, width=200)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo = tk.Frame(self.sidebar, bg=theme.PANEL)
        logo.pack(pady=(22, 2))
        AccentLabel(logo, text="r4k auto", size=17).pack()
        MutedLabel(logo, text="Control Panel", size=8).pack(pady=(1, 0))
        tk.Frame(logo, bg=theme.ACCENT, height=2).pack(fill="x", pady=(8, 0))

        self.nav_buttons = {}
        for name in NAV_ITEMS:
            button = RoundedButton(
                self.sidebar,
                text=name,
                command=lambda n=name: self.show_tab(n),
                radius=10,
                bg=theme.PANEL,
                hover_bg=theme.ACCENT,
                width=164,
                height=38,
                font=ui_font(11),
            )
            button.pack(pady=4)
            self.nav_buttons[name] = button

        MutedLabel(self.sidebar, text=f"v{config.APP_VERSION}", size=8).pack(
            side="bottom", pady=14
        )

        self.content = tk.Frame(self.root, bg=theme.BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.tabs = {
            "Overview": OverviewTab(self.content, on_start=self.start_workflow, on_stop=self.stop_workflow),
            "Uploader": UploaderTab(
                self.content,
                on_upload_all=self.start_platform_upload,
            ),
            "Console": ConsoleTab(self.content),
            "Settings": SettingsTab(self.content),
            "Setup": SetupTab(self.content),
            "Info": InfoTab(self.content),
        }
        self.tabs["Uploader"].on_stop_upload = self.stop_platform_upload
        self.tabs["Settings"].bind_bus(self.bus)
        for tab in self.tabs.values():
            tab.pack(fill="both", expand=True)

        self.current_tab = None
        self.show_tab("Overview")





    def show_tab(self, name):
        tab = self.tabs[name]
        if self.current_tab is tab:
            return
        if self.current_tab is not None:
            self.current_tab.pack_forget()
            if hasattr(self.current_tab, "on_hidden"):
                self.current_tab.on_hidden()
        self.current_tab = tab
        tab.pack(fill="both", expand=True)
        tab.on_shown()





    def start_workflow(self, platforms):
        if self._workflow and self._workflow.is_alive():
            return
        selected = list(platforms)
        self.tabs["Overview"].set_running(True)
        self.bus.emit("CONTROLLER", LEVEL_INFO, "START pressed")
        self._workflow = WorkflowController(
            selected,
            bus=self.bus,
            on_event=self._on_workflow_event,
            delays=self.tabs["Uploader"].get_delays(),
            manager=self._upload_manager,
        )
        self._workflow.start()

    def stop_workflow(self):
        if self._workflow and self._workflow.is_alive():
            self.bus.emit("CONTROLLER", LEVEL_ERROR, "STOP pressed - stopping the whole process ...")
            self._workflow.stop()
        self._upload_manager.stop_all()





    def start_platform_upload(self, key):
        platform = PLATFORM_BY_KEY.get(key)
        if platform is None:
            return
        if self._upload_manager.is_running(key):
            self.bus.emit(
                platform["source"],
                LEVEL_WARN,
                f"{platform['label']} uploader is already running - no duplicate worker started.",
            )
            return
        delay = self.tabs["Uploader"].get_delays().get(key, 0) or 0
        self.bus.emit("CONTROLLER", LEVEL_INFO, f"Upload All requested for {platform['label']}")
        self._upload_manager.start(platform, delay=delay)
        self.tabs["Uploader"].set_upload_running(key, True)

    def stop_platform_upload(self, key):
        platform = PLATFORM_BY_KEY.get(key)
        if platform is None:
            return
        self._upload_manager.stop([key])

    def _on_worker_state(self, key, running):
        self._event_queue.put(("worker_state", key, running))

    def _on_workflow_event(self, event):
        self._event_queue.put(event)

    def _on_log_entry(self, entry):
        self._event_queue.put(("log", entry))





    def _poll_events(self):
        try:
            while True:
                item = self._event_queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "log":
                    self.tabs["Console"].append(item[1])
                elif isinstance(item, tuple) and item[0] == "worker_state":
                    _, key, running = item
                    self.tabs["Uploader"].set_upload_running(key, running)
                elif isinstance(item, dict):
                    self._dispatch_workflow_event(item)
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_events)

    def _dispatch_workflow_event(self, event):
        event_type = event.get("type")
        overview = self.tabs["Overview"]
        if event_type == "stage":
            overview.set_stage(event.get("text", ""))
        elif event_type == "finished":
            overview.set_finished(event.get("ok", False), event.get("summary", ""))
            overview.set_running(False)





    def shutdown(self):
        if self._workflow and self._workflow.is_alive():
            self._workflow.stop()
        self._upload_manager.stop_all()


def enable_dpi_awareness():
    """Best-effort per-monitor DPI awareness (Windows only)."""
    if getattr(ctypes, "windll", None) is None:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run(root=None):
    enable_dpi_awareness()

    root = root or tk.Tk()
    root.withdraw()
    app = App(root)

    def boot():
        root.deiconify()


        from .first_run import maybe_show_first_run

        root.after(400, lambda: maybe_show_first_run(root))

    splash = Splash(root)
    if splash.shown:
        splash.wait_and_close(boot)
    else:
        boot()

    def on_close():
        app.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
