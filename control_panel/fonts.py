"""Relidux font loading for the control panel.

Tkinter cannot load fonts from arbitrary files, so the font is registered
for this process with the Windows GDI (AddFontResourceExW, private mode —
it is not installed system-wide and disappears when the app exits).
The discovered family name is then handed to the widgets layer.

If the font file is missing or registration fails, the UI silently
falls back to the default family (Segoe UI).
"""

import struct
import tkinter.font as tkfont
from pathlib import Path

from .config import FONT_PATH, FALLBACK_FONT_FAMILY
from .widgets import FONT_FAMILY, set_font_family

FR_PRIVATE = 0x10

_EXPECTED_FAMILY = "Relidux"


def _parse_family_name(path):
    """Extract the family name (nameID 1, Unicode BMP) from a sfnt font."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 16:
        return None
    try:
        num_tables = struct.unpack(">H", data[4:6])[0]
        pos = 12
        name_offset = name_length = None
        for _ in range(num_tables):
            tag = data[pos : pos + 4].decode("latin1")
            offset, length = struct.unpack(">II", data[pos + 8 : pos + 16])
            if tag == "name":
                name_offset, name_length = offset, length
                break
            pos += 16
        if name_offset is None:
            return None
        raw = data[name_offset : name_offset + name_length]
        count, str_off = struct.unpack(">HH", raw[2:6])
        for i in range(count):
            pid, _eid, _lid, nid, length, soff = struct.unpack(
                ">HHHHHH", raw[6 + 12 * i : 6 + 12 * i + 12]
            )
            if nid != 1:
                continue
            value = raw[str_off + soff : str_off + soff + length]
            if _eid == 1:
                return value.decode("utf-16-be", "replace")
            if pid == 1:
                return value.decode("latin1", "replace")
    except (struct.error, UnicodeDecodeError):
        return None
    return None


def register_font(root):
    """Register the Relidux font for this process.

    Returns the usable family name ('' on failure so callers can detect
    failure). The UI keeps its fallback family when the font is unusable.
    """
    path = Path(FONT_PATH)
    if not path.is_file():
        return ""

    known = set(tkfont.families(root))
    registered = False
    try:
        import ctypes

        handle = ctypes.windll.gdi32.AddFontResourceExW(
            str(path), FR_PRIVATE, 0
        )
        if handle != 0:
            registered = True
    except Exception:
        registered = False

    family = ""
    if registered:
        new_families = set(tkfont.families(root)) - known
        family = next(
            (name for name in new_families if _EXPECTED_FAMILY.lower() in name.lower()),
            None,
        ) or (next(iter(new_families), None) if new_families else None)
    if not family:
        parsed = _parse_family_name(path)
        if parsed and parsed.lower() == _EXPECTED_FAMILY.lower():
            family = parsed
    if not family:
        return ""

    set_font_family(family)
    return family


def default_font_family():
    return FALLBACK_FONT_FAMILY
