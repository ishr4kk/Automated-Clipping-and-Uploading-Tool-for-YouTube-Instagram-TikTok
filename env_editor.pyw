import ctypes
import os
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
from datetime import datetime

BG = "#242424"
BG_PANEL = "#2b2b2b"
BG_FIELD = "#1a1a1a"
ACCENT = "#7200A3"
ACCENT_DARK = "#5a0085"
TEXT = "#e8e8e8"
TEXT_DIM = "#8a8a8a"
COMMENT = "#6d6d6d"
BORDER = "#3a3a3a"
OK = "#6fdc8c"
ERROR = "#ff6b6b"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
FONT_PATH = os.path.join(PROJECT_ROOT, "src", "Relidux.otf")
AUTHOR_IMG_PATH = os.path.join(PROJECT_ROOT, "src", "author.png")
AUTHOR_TEXT = "ishr4k._"
DEFAULT_CAPTION = r"C:\Users\USER\Documents\automation\r4k auto\user-assets\caption.png"

CUT_OPTIONS = [("Starting", "starting"), ("Anywhere", "anywhere"), ("End", "end")]

FR_PRIVATE = 0x10

SECTIONS = [
    ("AI · OpenRouter", [
        ("OPENROUTER_API_KEY", "API key (https://openrouter.ai/keys)", "secret"),
        ("OPENROUTER_MODEL", "Video/image model for scene analysis", "text"),
        ("OPENROUTER_FRAME_MODEL", "Fallback frame model", "text"),
    ]),
    ("Source Channels", [
        ("AUTO_VIDEO_CHANNELS", "YouTube channels where videos are found", "list"),
    ]),
    ("Music", [
        ("BACKGROUND_MUSIC_PLAYLISTS", "YouTube playlists where songs are found", "list"),
        ("BACKGROUND_MUSIC_ENABLED", "Background music on/off", "bool"),
        ("BACKGROUND_MUSIC_VOLUME", "Music volume relative to video audio (0.0 - 1.0)", "float"),
    ]),
    ("Caption Image", [
        ("AUTO_VIDEO_CAPTION_IMAGE", "Overlay below the clip", "caption"),
    ]),
    ("Video Cutting", [
        ("VIDEO_CUT", "How do you want the video to be cut?", "cut"),
        ("VIDEO_LENGTH_SECONDS", "Video Length (Seconds)", "spin"),
    ]),
    ("Platform Sessions", [
        ("TIKTOKSESSIONID", "TikTok session id", "secret"),
        ("INSTAGRAMSESSIONID", "Instagram session id", "secret"),
    ]),
    ("Tuning", [
        ("AUTO_VIDEO_MAX_ENTRIES", "Max channel catalog entries per run", "int"),
        ("AUTO_VIDEO_MAX_DOWNLOAD_HEIGHT", "Cap downloaded source height", "int"),
    ]),
]


class EnvEditor:
    def __init__(self, root):
        self.root = root
        self.dirty = False
        self.fields = {}
        self.list_widgets = {}
        self.bool_widgets = {}
        self.cut_widgets = {}
        self.photo = None

        self._load_font()
        self._build_ui()
        self._bind_keys()
        self.load()



    def _load_font(self):
        self.font_family = "Segoe UI"
        if os.path.isfile(FONT_PATH):
            try:
                ctypes.windll.gdi32.AddFontResourceExW(FONT_PATH, FR_PRIVATE, 0)
                self.font_family = next(
                    (f for f in tkfont.families(self.root) if "relidux" in f.lower()),
                    self.font_family,
                )
            except Exception:
                pass
        self.f_small = tkfont.Font(family=self.font_family, size=9)
        self.f_body = tkfont.Font(family=self.font_family, size=10)
        self.f_body_bold = tkfont.Font(family=self.font_family, size=10, weight="bold")
        self.f_title = tkfont.Font(family=self.font_family, size=14, weight="bold")
        self.f_status = tkfont.Font(family=self.font_family, size=9)

    def _load_author_image(self):
        try:
            from PIL import Image, ImageDraw, ImageTk

            size = 40
            img = Image.open(AUTHOR_IMG_PATH).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            img.putalpha(mask)
            self.photo = ImageTk.PhotoImage(img)
        except Exception:
            self.photo = None



    def _build_ui(self):
        self._load_author_image()
        self.root.title("r4k auto — Environment Editor")
        self.root.configure(bg=BG)
        self.root.geometry("860x740")
        self._center_window()

        self.top = tk.Frame(self.root, bg=BG)
        self.top.pack(fill="x")

        tk.Label(self.top, text="Environment Editor", bg=BG, fg=TEXT, font=self.f_title).pack(
            side="left", padx=(18, 0), pady=(12, 0)
        )
        tk.Label(self.top, text=".env", bg=BG, fg=ACCENT, font=self.f_body_bold).pack(
            side="left", padx=(10, 0), pady=(16, 0)
        )

        author = tk.Frame(self.top, bg=BG)
        author.pack(side="right", padx=(0, 18), pady=(8, 0))
        if self.photo is not None:
            tk.Label(author, image=self.photo, bg=BG).pack(side="left", padx=(0, 8))
        tk.Label(author, text=AUTHOR_TEXT, bg=BG, fg=ACCENT, font=self.f_body_bold).pack(side="left")

        bar = tk.Frame(self.top, bg=ACCENT, height=3)
        bar.pack(fill="x", pady=(10, 0))

        self.toolbar = tk.Frame(self.root, bg=BG_PANEL)
        self.toolbar.pack(fill="x")

        self.btn_save = self._accent_button(self.toolbar, "Save  (Ctrl+S)", self.save)
        self.btn_save.pack(side="left", padx=(14, 6), pady=10)
        self.btn_reload = self._ghost_button(self.toolbar, "Reload", self.reload)
        self.btn_reload.pack(side="left", padx=6, pady=10)

        tk.Label(
            self.toolbar, text=ENV_PATH, bg=BG_PANEL, fg=TEXT_DIM, font=self.f_status
        ).pack(side="right", padx=14, pady=10)

        self._build_form()

        self.status = tk.Frame(self.root, bg=BG_PANEL)
        self.status.pack(fill="x", side="bottom")
        self.status_msg = tk.Label(
            self.status, text="Ready", bg=BG_PANEL, fg=TEXT_DIM, font=self.f_status
        )
        self.status_msg.pack(side="left", padx=14, pady=6)
        self.status_time = tk.Label(
            self.status, text="", bg=BG_PANEL, fg=TEXT_DIM, font=self.f_status
        )
        self.status_time.pack(side="right", padx=14, pady=6)
        self._tick_clock()

    def _build_form(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.scroll = tk.Scrollbar(
            body,
            command=self.canvas.yview,
            bg=BG_PANEL,
            troughcolor=BG,
            activebackground=ACCENT,
            relief="flat",
            borderwidth=0,
        )
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.form = tk.Frame(self.canvas, bg=BG)
        self.form_id = self.canvas.create_window((0, 0), window=self.form, anchor="nw")

        def on_form_configure(_e):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def on_canvas_configure(e):
            self.canvas.itemconfigure(self.form_id, width=e.width)

        self.form.bind("<Configure>", on_form_configure)
        self.canvas.bind("<Configure>", on_canvas_configure)

        for section_title, field_specs in SECTIONS:
            self._add_section(section_title)
            for key, hint, kind in field_specs:
                self._add_field(key, hint, kind)

        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"),
        )

    def _add_section(self, title):
        frame = tk.Frame(self.form, bg=BG)
        frame.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(frame, text=title, bg=BG, fg=ACCENT, font=self.f_body_bold).pack(anchor="w")
        tk.Frame(self.form, bg=BORDER, height=1).pack(fill="x", padx=22)

    def _add_field(self, key, hint, kind):
        outer = tk.Frame(self.form, bg=BG)
        outer.pack(fill="x", padx=22, pady=(8, 0))

        tk.Label(outer, text=key, bg=BG, fg=TEXT_DIM, font=self.f_small).pack(anchor="w")

        if kind == "list":
            self._add_list_field(outer, key, hint)
        elif kind == "bool":
            self._add_bool_field(outer, key)
        elif kind == "cut":
            self._add_cut_field(outer, key, hint)
        elif kind == "spin":
            self._add_spin_field(outer, key, hint)
        elif kind == "caption":
            self._add_entry_field(outer, key, hint, extra=DEFAULT_CAPTION)
        else:
            secret = kind == "secret"
            self._add_entry_field(outer, key, hint, secret=secret)

    def _add_entry_field(self, outer, key, hint, secret=False, extra=None):
        row = tk.Frame(outer, bg=BG)
        row.pack(fill="x", pady=(2, 0))

        var = tk.StringVar()
        self.fields[key] = var
        entry = tk.Entry(
            row,
            textvariable=var,
            bg=BG_FIELD,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=self.f_body,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
        entry.bind("<KeyRelease>", self._mark_dirty)

        if secret:
            entry.configure(show="\u2022")
            toggle = self._tiny_button(row, "Show", self._make_toggle(entry))
            toggle.pack(side="left")

        if extra:
            tk.Label(
                outer,
                text=f"Leave empty to use the default: {extra}",
                bg=BG,
                fg=COMMENT,
                font=self.f_small,
            ).pack(anchor="w", pady=(4, 0))

    def _add_list_field(self, outer, key, hint):
        self.list_widgets[key] = {"rows": [], "entry_vars": []}
        panel = tk.Frame(outer, bg=BG)
        panel.pack(fill="x", pady=(4, 0))
        self.list_widgets[key]["panel"] = panel

        for _ in range(2):
            self._add_list_row(key)

        add = self._ghost_button(outer, "+  Add", lambda: self._add_list_row(key))
        add.pack(anchor="w", pady=(6, 2))

        def remove(row_widgets):
            panel_vars = self.list_widgets[key]["entry_vars"]
            for i, var in enumerate(panel_vars):
                if var is row_widgets[1]:
                    del panel_vars[i]
                    break
            for w in row_widgets[0]:
                w.destroy()
            self.list_widgets[key]["rows"] = [
                r for r in self.list_widgets[key]["rows"] if r is not row_widgets
            ]
            if not self.list_widgets[key]["rows"]:
                self._add_list_row(key)
            self._mark_dirty()

        self.list_widgets[key]["remove"] = remove

    def _add_list_row(self, key):
        spec = self.list_widgets[key]
        var = tk.StringVar()
        spec["entry_vars"].append(var)
        row = tk.Frame(spec["panel"], bg=BG)
        row.pack(fill="x", pady=(0, 6))
        entry = tk.Entry(
            row,
            textvariable=var,
            bg=BG_FIELD,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=self.f_body,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
        entry.bind("<KeyRelease>", self._mark_dirty)
        remove = self._tiny_button(row, "\u2715", lambda w=(row, var): spec["remove"](w))
        remove.pack(side="left")
        spec["rows"].append(([row], var))

    def _add_bool_field(self, outer, key):
        state = {"value": True}
        self.bool_widgets[key] = state
        row = tk.Frame(outer, bg=BG)
        row.pack(anchor="w", pady=(4, 0))

        def make_button(label, value):
            btn = tk.Button(
                row,
                text=label,
                command=lambda: self._set_bool(key, value, buttons),
                relief="flat",
                borderwidth=0,
                padx=18,
                pady=4,
                cursor="hand2",
                font=self.f_body_bold,
            )
            return btn

        buttons = [make_button("On", True), make_button("Off", False)]
        buttons[0].pack(side="left")
        buttons[1].pack(side="left", padx=(6, 0))
        self._set_bool(key, state["value"], buttons)

    def _set_bool(self, key, value, buttons):
        state = self.bool_widgets[key]
        if state["value"] == value and not state.get("buttons"):
            state["buttons"] = buttons
            state["value"] = value
        else:
            state["value"] = value
        for btn, val in zip(buttons, [True, False]):
            if val == value:
                btn.configure(bg=ACCENT, fg="white", activebackground=ACCENT_DARK, activeforeground="white")
            else:
                btn.configure(bg=BG_PANEL, fg=TEXT_DIM, activebackground=BORDER, activeforeground=TEXT)
        self._mark_dirty()

    def _add_cut_field(self, outer, key, hint):
        state = {"value": None, "buttons": []}
        self.cut_widgets[key] = state

        if hint:
            tk.Label(outer, text=hint, bg=BG, fg=COMMENT, font=self.f_small).pack(
                anchor="w", pady=(2, 4)
            )

        row = tk.Frame(outer, bg=BG)
        row.pack(anchor="w", pady=(2, 0))

        for label, value in CUT_OPTIONS:
            btn = tk.Button(
                row,
                text=label,
                command=lambda v=value: self._set_cut(key, v),
                relief="flat",
                borderwidth=0,
                padx=18,
                pady=4,
                cursor="hand2",
                font=self.f_body_bold,
            )
            btn.pack(side="left", padx=(0, 6))
            state["buttons"].append((btn, value))

    def _set_cut(self, key, value):
        state = self.cut_widgets[key]
        state["value"] = value
        for btn, val in state["buttons"]:
            if val == value:
                btn.configure(bg=ACCENT, fg="white", activebackground=ACCENT_DARK, activeforeground="white")
            else:
                btn.configure(bg=BG_PANEL, fg=TEXT_DIM, activebackground=BORDER, activeforeground=TEXT)
        self._mark_dirty()

    def _validate_positive_int_key(self, proposed):
        return proposed == "" or proposed.isdigit()

    def _add_spin_field(self, outer, key, hint):
        if hint:
            tk.Label(outer, text=hint, bg=BG, fg=COMMENT, font=self.f_small).pack(
                anchor="w", pady=(2, 4)
            )

        var = tk.StringVar()
        self.fields[key] = var

        vcmd = (self.root.register(self._validate_positive_int_key), "%P")
        spin = tk.Spinbox(
            outer,
            from_=1,
            to=999999,
            increment=1,
            textvariable=var,
            validate="key",
            validatecommand=vcmd,
            bg=BG_FIELD,
            fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=self.f_body,
            buttonbackground=BG_PANEL,
            buttoncursor="hand2",
        )
        spin.pack(fill="x", ipady=5, padx=(0, 6))
        spin.bind("<KeyRelease>", self._mark_dirty)



    def _accent_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command,
            bg=ACCENT, fg="white", activebackground=ACCENT_DARK, activeforeground="white",
            relief="flat", borderwidth=0, padx=16, pady=6, cursor="hand2",
            font=self.f_body_bold,
        )

    def _ghost_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command,
            bg=BG_PANEL, fg=TEXT, activebackground=BORDER, activeforeground="white",
            relief="flat", borderwidth=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=BORDER,
            padx=14, pady=6, cursor="hand2", font=self.f_body,
        )

    def _tiny_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command,
            bg=BG_PANEL, fg=TEXT_DIM, activebackground=ACCENT, activeforeground="white",
            relief="flat", borderwidth=0, padx=10, pady=4, cursor="hand2",
            font=self.f_body_bold,
        )

    def _make_toggle(self, entry):
        def toggle():
            if entry.cget("show"):
                entry.configure(show="")
            else:
                entry.configure(show="\u2022")
            self._mark_dirty()

        return toggle



    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _bind_keys(self):
        self.root.bind("<Control-s>", lambda _e: self.save())

    def _mark_dirty(self, _e=None):
        self.dirty = True
        self._set_status("Unsaved changes", ACCENT)



    def parse_env(self, content):
        values = {}
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                i += 1
                continue
            key, _, rest = line.partition("=")
            key = key.strip()
            val = rest.strip()
            if val.startswith('"'):
                if val.count('"') == 1:
                    parts = [val]
                    while not val.endswith('"'):
                        i += 1
                        if i >= len(lines):
                            break
                        val = lines[i].strip()
                        parts.append(val)
                    val = "\n".join(parts)[1:-1]
                else:
                    val = val[1:-1]
            values[key] = val
            i += 1
        return values

    def serialize_env(self, values):
        def clean_items(raw):
            if isinstance(raw, str):
                raw = raw.split(",")
            return [v.strip() for v in raw if v.strip()]

        channels = ",".join(clean_items(values["AUTO_VIDEO_CHANNELS"]))
        playlists = ",".join(clean_items(values["BACKGROUND_MUSIC_PLAYLISTS"]))

        def multiline(joined):
            if not joined:
                return '""'
            items = joined.split(",")
            return '"' + ",\n".join(items) + '"'

        return f"""# ============================================================
#  Auto movie-clip video pipeline — environment configuration
#  This file is maintained by env_editor.py.
# ============================================================

# ---------- AI (OpenRouter) ----------
# Required. Get a key at https://openrouter.ai/keys
OPENROUTER_API_KEY={values["OPENROUTER_API_KEY"]}

# Video/image-capable model used for scene analysis.
OPENROUTER_MODEL={values["OPENROUTER_MODEL"]}

# Frame-image fallback model (used when the main model rejects video parts).
OPENROUTER_FRAME_MODEL={values["OPENROUTER_FRAME_MODEL"]}

# ---------- Source channels (videos are found here) ----------
# One channel per line; every line MUST end with a comma.
AUTO_VIDEO_CHANNELS={multiline(channels)}

# ---------- Music playlists (songs are found here) ----------
# One playlist per line; every line MUST end with a comma.
BACKGROUND_MUSIC_PLAYLISTS={multiline(playlists)}
BACKGROUND_MUSIC_ENABLED={str(values["BACKGROUND_MUSIC_ENABLED"]).lower()}
BACKGROUND_MUSIC_VOLUME={values["BACKGROUND_MUSIC_VOLUME"]}

# ---------- Caption image ----------
# Empty = default: {DEFAULT_CAPTION}
AUTO_VIDEO_CAPTION_IMAGE={values["AUTO_VIDEO_CAPTION_IMAGE"]}

# ---------- Video cutting ----------
# Where the generated clip is taken from: starting | anywhere | end.
VIDEO_CUT={values["VIDEO_CUT"]}
# Exact duration of the generated clip in seconds (positive integer).
VIDEO_LENGTH_SECONDS={values["VIDEO_LENGTH_SECONDS"]}

# ---------- Platform sessions ----------
# TikTok session id used when uploading.
TIKTOKSESSIONID={values["TIKTOKSESSIONID"]}
# Instagram session id used when uploading.
INSTAGRAMSESSIONID={values["INSTAGRAMSESSIONID"]}

# ---------- Tuning ----------
AUTO_VIDEO_MAX_ENTRIES={values["AUTO_VIDEO_MAX_ENTRIES"]}
AUTO_VIDEO_MAX_DOWNLOAD_HEIGHT={values["AUTO_VIDEO_MAX_DOWNLOAD_HEIGHT"]}
"""



    def load(self):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            content = ""
        except OSError as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        values = self.parse_env(content)
        for key in list(self.fields):
            self.fields[key].set(values.get(key, ""))
        for key, spec in self.list_widgets.items():
            items = [i.strip() for i in values.get(key, "").split(",") if i.strip()]
            for w in list(spec["rows"]):
                for widg in w[0]:
                    widg.destroy()
                spec["rows"].remove(w)
            spec["entry_vars"] = []
            for item in items or [""]:
                self._add_list_row(key)
            for var, item in zip(spec["entry_vars"], items or [""]):
                var.set(item)
        for key, state in self.bool_widgets.items():
            state["value"] = values.get(key, "true") == "true"
            if state.get("buttons"):
                self._set_bool(key, state["value"], state["buttons"])
        for key, state in self.cut_widgets.items():
            val = (values.get(key) or "starting").strip().lower()
            if val not in [v for _, v in CUT_OPTIONS]:
                val = "starting"
            state["value"] = val
            if state["buttons"]:
                self._set_cut(key, val)
        self.dirty = False
        self._set_status("Loaded from disk", TEXT_DIM)

    def _validate(self, values):
        try:
            int(values["AUTO_VIDEO_MAX_ENTRIES"] or "0")
            int(values["AUTO_VIDEO_MAX_DOWNLOAD_HEIGHT"] or "0")
            float(values["BACKGROUND_MUSIC_VOLUME"] or "0")
        except ValueError as exc:
            raise ValueError(f"Number field is not valid: {exc}")

        cut = (values.get("VIDEO_CUT") or "").strip().lower()
        allowed = [v for _, v in CUT_OPTIONS]
        if cut not in allowed:
            raise ValueError(
                f"VIDEO_CUT must be one of: {', '.join(v for _, v in CUT_OPTIONS)}. Got: {cut or '(empty)'}"
            )

        raw_length = (values.get("VIDEO_LENGTH_SECONDS") or "").strip()
        if not raw_length.isdigit() or int(raw_length) <= 0:
            raise ValueError(
                "VIDEO_LENGTH_SECONDS must be a positive integer (e.g. 30)."
            )

    def save(self):
        values = {
            key: var.get().strip()
            for key, var in self.fields.items()
        }
        for key, spec in self.list_widgets.items():
            values[key] = ",".join(v.get().strip() for v in spec["entry_vars"] if v.get().strip())
        for key, state in self.bool_widgets.items():
            values[key] = "true" if state["value"] else "false"
        for key, state in self.cut_widgets.items():
            values[key] = state["value"]

        try:
            self._validate(values)
        except ValueError as exc:
            self._set_status(str(exc), ERROR)
            messagebox.showerror("Invalid value", str(exc))
            return False

        try:
            with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.serialize_env(values))
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))
            return False

        self.dirty = False
        self._set_status("Saved \u2713", OK)
        return True

    def reload(self):
        if self.dirty:
            ok = messagebox.askyesno(
                "Discard changes",
                "You have unsaved changes. Discard them and reload from disk?",
            )
            if not ok:
                return
        self.load()



    def _set_status(self, message, color):
        if not hasattr(self, "status_msg"):
            return
        self.status_msg.config(text=message, fg=color)
        self.root.after(5000, self._dim_status)

    def _dim_status(self):
        if not self.dirty:
            self.status_msg.config(fg=TEXT_DIM)

    def _tick_clock(self):
        self.status_time.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def on_close(self):
        if self.dirty:
            result = messagebox.askyesnocancel("Unsaved changes", "Save changes before closing?")
            if result is None:
                return
            if result and not self.save():
                return
        self.root.destroy()


def main():
    root = tk.Tk()
    app = EnvEditor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
