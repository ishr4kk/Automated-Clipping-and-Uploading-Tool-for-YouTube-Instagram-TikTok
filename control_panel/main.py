"""Entry point for the r4k auto Control Panel.

Run with ``pythonw control_panel/main.py`` (no console window) or
``python control_panel/main.py``. Any startup failure falls back to a
plain message box so errors are never silently swallowed.
"""

import sys
import tkinter as tk
import tkinter.messagebox as messagebox
from pathlib import Path

if __package__ in (None, ""):



    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from .app import run
except ImportError:
    from control_panel.app import run


def _fatal(title, message):
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


def main():
    try:
        run()
    except Exception as exc:
        _fatal("Control Panel failed to start", f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
