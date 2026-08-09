"""First-run welcome popup with the "Please follow" social buttons.

Shows once: after Continue is pressed a flag file (control_panel/state/
first_run.json) is written so later starts go straight to the main window.
A failure to read/write the flag must never block the app, so every access
degrades to the default (show the popup).
"""

import json
import tkinter as tk
from webbrowser import open as open_url

from . import config
from .widgets import AccentLabel, MutedLabel, RoundedButton, SectionLabel, theme, ui_font


LINK_ICONS = {
    "Instagram": "instagram",
    "GitHub": "github",
    "Discord": "discord",
}


def is_first_run():
    """True when the welcome popup has never been dismissed."""
    try:
        data = json.loads(config.FIRST_RUN_STATE.read_text(encoding="utf-8"))
        return data.get("seen") is not True
    except (OSError, ValueError):
        return True


def mark_seen():
    """Record that the welcome popup was dismissed (best effort)."""
    try:
        config.FIRST_RUN_STATE.parent.mkdir(parents=True, exist_ok=True)
        config.FIRST_RUN_STATE.write_text(json.dumps({"seen": True}), encoding="utf-8")
    except OSError:
        pass


class FirstRunDialog:
    """Modal welcome window: greeting + "Please follow" social buttons."""

    def __init__(self, root, on_done=None):
        self.on_done = on_done or (lambda: None)
        self.window = tk.Toplevel(root)
        self.window.title("Welcome")
        self.window.configure(bg=theme.FIELD)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)

        panel = tk.Frame(
            self.window,
            bg=theme.FIELD,
            highlightbackground=theme.ACCENT,
            highlightthickness=2,
        )
        panel.pack(fill="both", expand=True)

        AccentLabel(panel, text="Welcome to r4k auto", bg=theme.FIELD, size=20).pack(pady=(26, 4))
        MutedLabel(
            panel,
            "Create videos and upload them to TikTok, YouTube and Instagram automatically.",
            size=9,
            bg=theme.FIELD,
        ).pack()
        tk.Frame(panel, bg=theme.BORDER, height=1).pack(fill="x", padx=32, pady=(16, 14))

        SectionLabel(panel, text="Please follow", size=11, bg=theme.FIELD).pack()
        MutedLabel(
            panel,
            "Stay updated on new features and content:",
            size=8,
            bg=theme.FIELD,
        ).pack(pady=(1, 10))

        links = tk.Frame(panel, bg=theme.FIELD)
        links.pack()
        for name, url in config.INFO_LINKS:
            RoundedButton(
                links,
                text=name,
                icon=LINK_ICONS.get(name, "globe"),
                command=lambda target=url: open_url(target),
                bg=theme.PANEL,
                fg=theme.TEXT,
                hover_bg=theme.ACCENT,
                radius=12,
                width=118,
                height=38,
                font=ui_font(10, "bold"),
            ).pack(side="left", padx=6)

        continue_button = RoundedButton(
            panel,
            text="Continue",
            icon="arrow",
            command=self._finish,
            bg=theme.ACCENT,
            hover_bg=theme.ACCENT_DARK,
            radius=12,
            width=170,
            height=44,
            font=ui_font(11, "bold"),
        )
        continue_button.pack(pady=(18, 26))

        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = (self.window.winfo_screenwidth() - width) // 2
        y = (self.window.winfo_screenheight() - height) // 2
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.protocol("WM_DELETE_WINDOW", self._finish)
        try:
            self.window.grab_set()
        except Exception:
            pass

    def _finish(self):
        mark_seen()
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            if self.window.winfo_exists():
                self.window.destroy()
        except Exception:
            pass
        self.on_done()


def maybe_show_first_run(root, on_done=None):
    """Show the welcome popup once; return the dialog, or None if already seen."""
    if not is_first_run():
        if on_done:
            on_done()
        return None
    return FirstRunDialog(root, on_done=on_done)
