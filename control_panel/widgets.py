"""Reusable theme-aware widgets for the control panel.

Tk's Button has no rounded-corner support, so RoundedButton is a
Canvas-drawn button with a drop shadow, hover glow, pressed offset and
optional vector icons. All widgets use the module-level font family so
the whole UI switches to the Relidux font in one place.
"""

import tkinter as tk

from .config import Theme


theme = Theme()


FONT_FAMILY = "Segoe UI"


def set_font_family(family):
    global FONT_FAMILY
    if family:
        FONT_FAMILY = family


def ui_font(size=10, weight="normal"):
    if weight in ("bold", "italic", "bold italic"):
        return (FONT_FAMILY, size, weight)
    return (FONT_FAMILY, size)


def shadow_color(base, amount=0.55):
    """Darken a hex color for use as a drop shadow."""
    base = base.lstrip("#")
    r, g, b = (int(base[i : i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * amount), int(g * amount), int(b * amount))


class RoundedButton(tk.Canvas):
    """A rounded, hover-aware button drawn on a canvas.

    Supported icons: play, stop, wrench, trash, plus, refresh, none.
    """

    def __init__(
        self,
        master,
        text,
        command=None,
        *,
        icon=None,
        radius=12,
        bg=None,
        fg=None,
        hover_bg=None,
        hover_fg=None,
        pressed_bg=None,
        shadow=True,
        font=None,
        width=None,
        height=None,
        state="normal",
    ):
        self._radius = radius
        self._bg = bg or theme.PANEL
        self._fg = fg or theme.TEXT
        self._hover_bg = hover_bg or theme.ACCENT
        self._hover_fg = hover_fg or theme.TEXT
        self._pressed_bg = pressed_bg or theme.ACCENT_DARK
        self._font = font or ui_font(10, "bold")
        self._command = command
        self._state = state
        self._icon = icon
        self._shadow = shadow
        self._hover = False
        self._pressed = False
        self._text = text
        self._last_w = self._last_h = 0

        width = width if width is not None else 140
        height = height if height is not None else 42
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=master.cget("bg"),
        )

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", self._on_configure)



    def _on_configure(self, _e):
        """Redraw only when the canvas actually changed size.

        Without this guard every layout pass (initial pack, tab switches,
        window resizing) re-draws the whole button dozens of times,
        causing visible flicker and tearing on Windows.
        """
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 and h <= 1:
            return
        if w == self._last_w and h == self._last_h:
            return
        self._last_w, self._last_h = w, h
        self._draw()

    def _palette(self):
        fill, fg = self._bg, self._fg
        if self._state == "disabled":
            return theme.DISABLED, theme.COMMENT
        if self._pressed:
            return self._pressed_bg, self._hover_fg
        if self._hover:
            return self._hover_bg, self._hover_fg
        return fill, fg

    def _draw(self):
        w = self.winfo_width()
        h = self.winfo_height()



        if w <= 1:
            w = int(self["width"])
        if h <= 1:
            h = int(self["height"])
        radius = min(self._radius, w // 2, h // 2)
        fill, fg = self._palette()

        self.delete("all")


        if self._shadow and self._state != "disabled":
            offset = 1 if self._pressed else 3
            self.create_polygon(
                *self._rounded_points(offset + 1, offset + 2, w - 2, h + offset, radius),
                smooth=True,
                fill=shadow_color(fill),
                outline="",
            )


        self.create_polygon(
            *self._rounded_points(1, 1, w - 1, h - 1, radius),
            smooth=True,
            fill=fill,
            outline="",
        )


        if self._hover and self._state != "disabled" and not self._pressed:
            self.create_polygon(
                *self._rounded_points(2, 2, w - 2, h - 2, radius),
                smooth=True,
                outline=fg,
                width=1,
                fill="",
            )

        text_x = w // 2
        if self._icon:
            icon_size = max(10, int(h * 0.34))
            icon_x = 26
            icon_y = h // 2
            self._draw_icon(icon_x, icon_y, icon_size, fg)
            text_x = w // 2 + 10

        self.create_text(
            text_x, (h // 2) + (1 if self._pressed else 0), text=self._text, fill=fg, font=self._font
        )

    def _rounded_points(self, x1, y1, x2, y2, radius):
        return [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]

    def _draw_icon(self, x, y, size, fill):
        half = size / 2
        if self._icon == "play":
            self.create_polygon(
                x - half * 0.45, y - half, x - half * 0.45, y + half, x + half * 0.85, y,
                fill=fill, outline="",
            )
        elif self._icon == "stop":
            self.create_rectangle(
                x - half * 0.8, y - half * 0.8, x + half * 0.8, y + half * 0.8,
                fill=fill, outline="",
            )
        elif self._icon == "wrench":
            self.create_rectangle(x + half * 0.15, y - half * 0.45, x + half * 0.75, y + half * 0.45, fill=fill, outline="")
            self.create_oval(x - half * 0.65, y - half * 0.65, x + half * 0.35, y + half * 0.65, fill=fill, outline="")
        elif self._icon == "trash":
            self.create_rectangle(x - half * 0.6, y - half * 0.25, x + half * 0.6, y + half * 0.7, fill=fill, outline="")
            self.create_rectangle(x - half * 0.8, y - half * 0.85, x + half * 0.8, y - half * 0.55, fill=fill, outline="")
            self.create_rectangle(x - half * 0.25, y - half * 1.2, x + half * 0.25, y - half * 0.8, fill=fill, outline="")
        elif self._icon == "plus":
            self.create_rectangle(x - half * 0.2, y - half, x + half * 0.2, y + half, fill=fill, outline="")
            self.create_rectangle(x - half, y - half * 0.2, x + half, y + half * 0.2, fill=fill, outline="")
        elif self._icon == "refresh":
            self.create_arc(x - half, y - half, x + half, y + half, start=30, extent=240, style="arc", outline=fill, width=max(2, int(half * 0.3)))
            self.create_polygon(x + half * 0.6, y - half * 0.15, x + half * 1.05, y - half * 0.5, x + half * 0.85, y - half * 0.05, fill=fill, outline="")
        elif self._icon == "instagram":
            self.create_rectangle(x - half, y - half, x + half, y + half, outline=fill, width=max(2, int(half * 0.28)))
            self.create_oval(x - half * 0.45, y - half * 0.45, x + half * 0.45, y + half * 0.45, outline=fill, width=max(2, int(half * 0.28)))
            self.create_oval(x + half * 0.55, y - half * 0.55, x + half * 0.85, y - half * 0.25, fill=fill, outline="")
        elif self._icon == "github":
            self.create_oval(x - half * 0.95, y - half * 0.95, x + half * 0.95, y + half * 0.95, fill=fill, outline="")
            self.create_oval(x - half * 0.35, y - half * 0.3, x + half * 0.35, y + half * 0.55, fill=fill, outline="")
            self.create_rectangle(x - half * 0.75, y - half * 0.05, x - half * 0.2, y + half * 0.75, fill=fill, outline="")
            self.create_rectangle(x + half * 0.2, y - half * 0.05, x + half * 0.75, y + half * 0.75, fill=fill, outline="")
        elif self._icon == "discord":
            self.create_oval(x - half * 0.9, y - half * 0.9, x + half * 0.9, y + half * 0.9, outline=fill, width=max(2, int(half * 0.28)))
            self.create_oval(x - half * 0.45, y - half * 0.3, x - half * 0.05, y + half * 0.1, fill=fill, outline="")
            self.create_oval(x + half * 0.05, y - half * 0.3, x + half * 0.45, y + half * 0.1, fill=fill, outline="")
        elif self._icon == "globe":
            self.create_oval(x - half, y - half, x + half, y + half, outline=fill, width=max(2, int(half * 0.28)))
            self.create_oval(x - half * 0.5, y - half, x + half * 0.5, y + half, outline=fill, width=max(1, int(half * 0.18)))
            self.create_line(x - half, y, x + half, y, fill=fill, width=max(1, int(half * 0.18)))
            self.create_line(x, y - half, x, y + half, fill=fill, width=max(1, int(half * 0.18)))
        elif self._icon == "arrow":
            self.create_line(x - half, y, x + half, y, fill=fill, width=max(2, int(half * 0.3)))
            self.create_line(x + half * 0.3, y - half * 0.45, x + half, y, fill=fill, width=max(2, int(half * 0.3)))
            self.create_line(x + half * 0.3, y + half * 0.45, x + half, y, fill=fill, width=max(2, int(half * 0.3)))



    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _on_press(self, _e):
        if self._state == "disabled":
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _e):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if self._state == "disabled":
            return
        if was_pressed and self._command is not None:
            self._command()

    def set_text(self, text):
        self._text = text
        self._draw()

    def set_icon(self, icon):
        self._icon = icon
        self._draw()

    def set_command(self, command):
        self._command = command

    def set_state(self, state):
        """state: 'normal' or 'disabled'."""
        self._state = state
        self._draw()


class Card(tk.Frame):
    """Flat panel with a subtle border - the app's primary grouping unit."""

    def __init__(self, master, *, bg=None, border_color=None, padx=16, pady=14):
        border_color = border_color or theme.BORDER
        super().__init__(
            master,
            bg=bg or theme.PANEL,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
        )
        self.inner = tk.Frame(self, bg=self.cget("bg"))
        self.inner.pack(fill="both", expand=True, padx=padx, pady=pady)


class SectionLabel(tk.Label):
    """Bold uppercase section heading."""

    def __init__(self, master, text, *, bg=None, fg=None, font=None, size=10):
        super().__init__(
            master,
            text=text,
            bg=bg or master.cget("bg"),
            fg=fg or theme.TEXT,
            font=font or ui_font(size, "bold"),
        )


class MutedLabel(tk.Label):
    """Secondary/tertiary text label."""

    def __init__(self, master, text, *, bg=None, fg=None, font=None, size=9):
        super().__init__(
            master,
            text=text,
            bg=bg or master.cget("bg"),
            fg=fg or theme.TEXT_DIM,
            font=font or ui_font(size),
        )


class AccentLabel(tk.Label):
    """Primary purple label (e.g. the author name on the splash)."""

    def __init__(self, master, text, *, bg=None, fg=None, font=None, size=16):
        super().__init__(
            master,
            text=text,
            bg=bg or master.cget("bg"),
            fg=fg or theme.ACCENT,
            font=font or ui_font(size, "bold"),
        )


class IconDot(tk.Canvas):
    """Small colored rounded badge used next to platform labels."""

    def __init__(self, master, color, size=12):
        super().__init__(master, width=size, height=size, highlightthickness=0, bd=0, bg=master.cget("bg"))
        self.create_oval(1, 1, size - 1, size - 1, fill=color, outline="")
