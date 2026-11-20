"""Enhanced Metafile (EMF) export backend.

EMF is a vector format that office suites and drawing applications embed
directly, so it is a convenient way to put a crisp, resizable timing diagram
into a document.

The implementation writes GDI EMF records itself (no libEMF, no Windows API,
no QtSvg): lines, rectangles, polygons, cubic Beziers and Unicode text.
Coordinates are logical pixels at 96 dpi, matching the on-screen renderer and
the PNG/PDF exports.  The header's frame rectangle (rclFrame) is the picture
rectangle converted to 0.01 mm.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PyQt6.QtGui import QColor

from .model import Document
from .renderer import RenderOptions, Selection, render_document

# --------------------------------------------------------------------------- EMF constants
EMR_HEADER = 1
EMR_POLYBEZIER = 2
EMR_POLYGON = 3
EMR_EOF = 14
EMR_SETBKMODE = 18
EMR_SETPOLYFILLMODE = 19
EMR_SETTEXTALIGN = 22
EMR_SETTEXTCOLOR = 24
EMR_MOVETOEX = 27
EMR_SELECTOBJECT = 37
EMR_CREATEPEN = 38
EMR_CREATEBRUSHINDIRECT = 39
EMR_RECTANGLE = 43
EMR_ROUNDRECT = 44
EMR_LINETO = 54
EMR_EXTCREATEFONTINDIRECTW = 82
EMR_EXTTEXTOUTW = 84

TRANSPARENT = 1
ALTERNATE = 1

PS_SOLID = 0
PS_DASH = 1
PS_DOT = 2

BS_SOLID = 0

TA_LEFT = 0
TA_RIGHT = 2
TA_CENTER = 6
TA_BASELINE = 24

STOCK_NULL_BRUSH = 0x80000000 | 5
STOCK_NULL_PEN = 0x80000000 | 8

EMF_SIGNATURE = 0x464D4520  # " EMF"
EMF_VERSION = 0x00010000
EMF_DESCRIPTION = "EdgeWeaver"
DPI = 96.0
HUNDREDTH_MM_PER_INCH = 2540.0

# ENHMETAHEADER is 108 bytes (88 base + pixel-format fields + szlMicrometers).
# The optional description follows immediately and is included in nSize; the
# first record starts at nSize.
HEADER_BASE_SIZE = 108
_HEADER_FMT = "<II4i4iIIIIHHIIIiiii"   # 88 bytes
_PIXEL_FMT = "<III"                     # cbPixelFormat, offPixelFormat, bOpenGL
_MICROMETERS_FMT = "<ii"                # szlMicrometers


def _colorref(color: str) -> int:
    c = QColor(color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def _p(value: float) -> int:
    return int(round(float(value)))


def _align4(n: int) -> int:
    return (n + 3) & ~3


class EmfBackend:
    """Draw through the same interface as QtBackend/SvgBackend."""

    def __init__(self, width: float, height: float):
        self.width = max(1, _p(width))
        self.height = max(1, _p(height))
        self.records: list[bytes] = []
        self.max_handle = 0
        self._pens: dict[tuple[int, int, int], int] = {}
        self._brushes: dict[int, int] = {}
        self._fonts: dict[tuple[str, float, bool], int] = {}
        self._pen: int | None = None
        self._brush: int | None = None
        self._font: int | None = None
        self._text_color: int | None = None
        self._align: int | None = None
        # Standard initial state: transparent text background and alternate
        # polygon fill mode.
        self._record(EMR_SETBKMODE, struct.pack("<I", TRANSPARENT))
        self._record(EMR_SETPOLYFILLMODE, struct.pack("<I", ALTERNATE))

    # ---------------------------------------------------------------- record plumbing
    def _record(self, kind: int, payload: bytes) -> None:
        size = 8 + len(payload)
        if size % 4:
            raise ValueError(f"EMF record {kind} is not DWORD aligned ({size})")
        self.records.append(struct.pack("<II", kind, size) + payload)

    def _new_handle(self) -> int:
        self.max_handle += 1
        if self.max_handle >= 0xFFFF:
            raise ValueError("too many EMF objects")
        return self.max_handle

    def _select(self, handle: int, slot: str) -> None:
        if getattr(self, f"_{slot}") == handle:
            return
        self._record(EMR_SELECTOBJECT, struct.pack("<I", handle))
        setattr(self, f"_{slot}", handle)

    def _pen_handle(self, color: str, width: float, dash: str | None) -> int:
        width_px = max(1, _p(width if width >= 1.0 else 1.0))
        style = PS_SOLID
        if dash == "dot":
            style = PS_DOT
        elif dash == "dash":
            style = PS_DASH
        key = (style, width_px, _colorref(color))
        handle = self._pens.get(key)
        if handle is None:
            handle = self._new_handle()
            # EMRCREATEPEN: ihPen + LOGPEN{style, POINTL width, COLORREF}
            self._record(EMR_CREATEPEN,
                         struct.pack("<IIiiI", handle, style, width_px, 0, key[2]))
            self._pens[key] = handle
        return handle

    def _brush_handle(self, color: str) -> int:
        rgb = _colorref(color)
        handle = self._brushes.get(rgb)
        if handle is None:
            handle = self._new_handle()
            # LOGBRUSH: style, color, hatch
            self._record(EMR_CREATEBRUSHINDIRECT,
                         struct.pack("<IIII", handle, BS_SOLID, rgb, 0))
            self._brushes[rgb] = handle
        return handle

    def _font_handle(self, family: str, size: float, bold: bool) -> int:
        key = (family or "Arial", float(size), bool(bold))
        handle = self._fonts.get(key)
        if handle is None:
            handle = self._new_handle()
            face = key[0].encode("utf-16-le")[:62]
            face += b"\x00\x00" * (32 - len(face) // 2)
            # LOGFONTW: negative height = character height in logical units.
            # Charset 1 (DEFAULT_CHARSET) keeps Unicode/CJK text intact.
            height = -max(1, _p(key[1] * DPI / 72.0))
            logfont = struct.pack(
                "<iiiii8B",
                height, 0, 0, 0,
                700 if key[2] else 400,
                0, 0, 0,
                1,          # DEFAULT_CHARSET
                0, 0, 0, 0,  # out/clip precision, quality, pitch&family
            ) + face
            # EXTLOGFONTW tail: full name (64 WCHAR), style (32 WCHAR),
            # version, style size, match, reserved, vendor id, culture, PANOSE.
            logfont += b"\x00" * (128 + 64 + 16 + 4 + 4 + 10)
            logfont += b"\x00" * (320 - len(logfont))
            self._record(EMR_EXTCREATEFONTINDIRECTW,
                         struct.pack("<I", handle) + logfont)
            self._fonts[key] = handle
        return handle

    def _apply_pen(self, color: str | None, width: float, dash: str | None) -> None:
        if color is None:
            self._select(STOCK_NULL_PEN, "pen")
        else:
            self._select(self._pen_handle(color, width, dash), "pen")

    def _apply_brush(self, fill: str | None) -> None:
        if fill is None:
            self._select(STOCK_NULL_BRUSH, "brush")
        else:
            self._select(self._brush_handle(fill), "brush")

    # ---------------------------------------------------------------- backend API
    def line(self, x1, y1, x2, y2, color="#000000", width=1.0, dash=None):
        self._apply_pen(color, width, dash)
        self._apply_brush(None)
        self._record(EMR_MOVETOEX, struct.pack("<ii", _p(x1), _p(y1)))
        self._record(EMR_LINETO, struct.pack("<ii", _p(x2), _p(y2)))

    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, rx=0.0):
        left, top = _p(x), _p(y)
        right, bottom = _p(x + w), _p(y + h)
        if right <= left or bottom <= top:
            return
        self._apply_pen(stroke, width, None)
        self._apply_brush(fill)
        if rx:
            self._record(EMR_ROUNDRECT,
                         struct.pack("<iiiiii", left, top, right, bottom,
                                     _p(rx * 2), _p(rx * 2)))
        else:
            self._record(EMR_RECTANGLE,
                         struct.pack("<iiii", left, top, right, bottom))

    def polygon(self, points, fill=None, stroke=None, width=1.0):
        pts = [(_p(px), _p(py)) for px, py in points]
        if len(pts) < 2:
            return
        self._apply_pen(stroke, width, None)
        self._apply_brush(fill)
        xs = [pt[0] for pt in pts]
        ys = [pt[1] for pt in pts]
        payload = struct.pack("<iiiiI", min(xs), min(ys), max(xs), max(ys), len(pts))
        payload += b"".join(struct.pack("<ii", px, py) for px, py in pts)
        self._record(EMR_POLYGON, payload)

    def cubic(self, p0, c1, c2, p1, stroke="#000000", width=1.0, fill=None):
        self._apply_pen(stroke, width, None)
        self._apply_brush(fill)
        pts = [p0, c1, c2, p1]
        xs = [_p(pt[0]) for pt in pts]
        ys = [_p(pt[1]) for pt in pts]
        payload = struct.pack("<iiiiI", min(xs), min(ys), max(xs), max(ys), len(pts))
        payload += b"".join(struct.pack("<ii", px, py) for px, py in zip(xs, ys))
        self._record(EMR_POLYBEZIER, payload)

    def text(self, x, y, text, size=10, family="Arial", color="#000000",
             anchor="start", bold=False):
        if not text:
            return
        self._select(self._font_handle(family, size, bold), "font")
        rgb = _colorref(color)
        if self._text_color != rgb:
            self._record(EMR_SETTEXTCOLOR, struct.pack("<I", rgb))
            self._text_color = rgb
        align = {"start": TA_LEFT, "middle": TA_CENTER, "end": TA_RIGHT}.get(
            anchor, TA_LEFT) | TA_BASELINE
        if self._align != align:
            self._record(EMR_SETTEXTALIGN, struct.pack("<I", align))
            self._align = align

        encoded = text.encode("utf-16-le")
        n_chars = len(encoded) // 2
        off_string = 76                      # 8 header + 68 fixed EMRTEXT prefix
        pad = (4 - (off_string + len(encoded)) % 4) % 4
        string_field = encoded + b"\x00" * pad
        # Bounds are advisory; viewers use the anchor point and the font.
        bounds = self._text_bounds(x, y, text, size, family, anchor)
        payload = struct.pack(
            "<iiiiIff",                     # Bounds POINTL x4, iGraphicsMode, exScale, eyScale
            *bounds, 1, 2540.0 / DPI, 2540.0 / DPI,
        )
        payload += struct.pack(
            "<iiIIIiiiiI",                  # ptlReference, nChars, offString, fOptions, rcl, offDx
            _p(x), _p(y),
            n_chars, off_string, 0,
            0, 0, -1, -1,                   # rcl (unused for non-clipped text)
            0,                              # offDx: no explicit spacing array
        )
        payload += string_field
        self._record(EMR_EXTTEXTOUTW, payload)

    @staticmethod
    def _text_bounds(x, y, text, size, family, anchor):
        size_px = max(1.0, float(size) * DPI / 72.0)
        try:
            from PyQt6.QtGui import QFont, QFontMetricsF, QGuiApplication
            if QGuiApplication.instance() is not None:
                font = QFont(family or "Arial")
                font.setPointSizeF(max(1.0, float(size)))
                fm = QFontMetricsF(font)
                adv = fm.horizontalAdvance(text)
                asc, desc = fm.ascent(), fm.descent()
            else:
                raise RuntimeError("no QGuiApplication")
        except Exception:
            adv = size_px * 0.6 * len(text)
            asc, desc = size_px * 0.8, size_px * 0.2
        left = float(x)
        if anchor == "middle":
            left -= adv / 2.0
        elif anchor == "end":
            left -= adv
        return (_p(math.floor(left)), _p(math.floor(y - asc)),
                _p(math.ceil(left + adv)), _p(math.ceil(y + desc)))

    # ---------------------------------------------------------------- file assembly
    def document(self) -> bytes:
        body = b"".join(self.records)

        desc = (EMF_DESCRIPTION + "\x00").encode("utf-16-le")
        n_desc = len(desc) // 2          # ENHMETAHEADER counts UTF-16 characters
        n_size = _align4(HEADER_BASE_SIZE + len(desc))
        desc_block = desc + b"\x00" * (n_size - HEADER_BASE_SIZE - len(desc))

        frame_right = _p(self.width * HUNDREDTH_MM_PER_INCH / DPI)
        frame_bottom = _p(self.height * HUNDREDTH_MM_PER_INCH / DPI)
        device_mm_w = _p(self.width * 25.4 / DPI)
        device_mm_h = _p(self.height * 25.4 / DPI)
        micrometers_w = _p(self.width * 25400.0 / DPI)
        micrometers_h = _p(self.height * 25400.0 / DPI)
        eof = struct.pack("<IIIII", EMR_EOF, 20, 0, 16, 20)
        n_bytes = n_size + len(body) + len(eof)
        n_records = len(self.records) + 2       # header + EOF

        header = struct.pack(
            _HEADER_FMT,
            EMR_HEADER, n_size,
            0, 0, self.width - 1, self.height - 1,
            0, 0, frame_right, frame_bottom,
            EMF_SIGNATURE, EMF_VERSION, n_bytes, n_records,
            self.max_handle + 1, 0,
            n_desc, HEADER_BASE_SIZE, 0,
            self.width, self.height, device_mm_w, device_mm_h,
        )
        header += struct.pack(_PIXEL_FMT, 0, 0, 0)
        header += struct.pack(_MICROMETERS_FMT, micrometers_w, micrometers_h)
        assert len(header) == HEADER_BASE_SIZE
        return header + desc_block + body + eof


def export_emf(doc: Document, path: str | Path, opts: RenderOptions | None = None,
               selection: Selection | None = None) -> Path:
    """Write *doc* as an Enhanced Metafile."""
    path = Path(path)
    backend = EmfBackend(doc.content_width, doc.content_height)
    render_document(backend, doc, opts, selection)
    path.write_bytes(backend.document())
    return path
