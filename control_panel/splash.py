"""Splash screen: shows src/author.png for 2 seconds, then fades out.

Gracefully degrades: if the image is missing or fails to load, the splash
is skipped entirely and the caller proceeds to the main window.
"""

import tkinter as tk

from . import config
from .widgets import AccentLabel, theme, ui_font

SPLASH_MS = 2000
FADE_STEP_MS = 20
FADE_STEP_ALPHA = 0.05


class Splash:
    def __init__(self, root):
        """Show a modal splash over the (hidden) root window.

        If the splash cannot be shown, ``root`` is left withdrawn — the
        caller decides whether to deiconify it.
        """
        self.root = root
        self.window = None
        self._shown = False

        try:
            if not config.SPLASH_IMAGE.is_file():
                return
            image = tk.PhotoImage(file=str(config.SPLASH_IMAGE))
            self.window = tk.Toplevel(root)
            self.window.overrideredirect(True)
            self.window.attributes("-topmost", True)

            bg = theme.FIELD
            panel = tk.Frame(self.window, bg=bg, highlightbackground=theme.ACCENT, highlightthickness=2)
            panel.pack(fill="both", expand=True)

            image_label = tk.Label(panel, image=image, bg=bg)
            image_label.image = image
            image_label.pack(padx=16, pady=(16, 8))

            AccentLabel(panel, text="ishr4k._", bg=bg, size=18).pack(pady=(0, 16))

            self.window.update_idletasks()
            width = self.window.winfo_reqwidth()
            height = self.window.winfo_reqheight()
            x = (self.window.winfo_screenwidth() - width) // 2
            y = (self.window.winfo_screenheight() - height) // 2
            self.window.geometry(f"{width}x{height}+{x}+{y}")

            self._shown = True
        except Exception:


            self.window = None
            self._shown = False

    @property
    def shown(self):
        return self._shown

    def wait_and_close(self, on_done):
        """Hold the splash for SPLASH_MS, fade out, then call on_done()."""
        if not self._shown:
            on_done()
            return
        self.root.after(SPLASH_MS, lambda: self._fade(on_done))

    def _fade(self, on_done):
        alpha = self.window.attributes("-alpha")
        alpha -= FADE_STEP_ALPHA
        if alpha <= 0:
            self._close(on_done)
            return
        self.window.attributes("-alpha", max(alpha, 0.0))
        self.root.after(FADE_STEP_MS, lambda: self._fade(on_done))

    def _close(self, on_done):
        if self.window is not None:
            self.window.destroy()
            self.window = None
        on_done()
