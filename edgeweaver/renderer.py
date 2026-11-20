"""Document renderer.

Geometry is back-end independent: QtBackend paints to a QPainter (screen, PNG,
PDF) and SvgBackend (svg_export.py) emits SVG.  All back ends share the same
layout constants:

* first row top = 20 px, row pitch = 44 px
* waveform x0 = name_width + 5
* one state character = one half-clock slot = slot_width px
* signal high/low = row top / row top + signal_height
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtCore import Qt

from .model import (
    Arrow,
    Document,
    LABEL_TAIL,
    NAME_PAD,
    NAME_X,
    ROW_PITCH,
    TOP_MARGIN,
    Label,
    Measurement,
    Row,
    TimeBreak,
    arrow_pixel_offset,
)


@dataclass
class RenderOptions:
    background: bool = True
    show_grid: bool = True
    show_names: bool = True
    show_bus_values: bool = True
    show_divider: bool = False
    show_bounding_rect: bool = False
    show_logo: bool = False
    period_lines: bool = True


@dataclass
class Selection:
    row: int
    start: int
    end: int

    def normalized(self) -> "Selection":
        lo, hi = sorted((self.start, self.end))
        return Selection(self.row, lo, hi)


# --------------------------------------------------------------------------- Qt backend
class QtBackend:
    def __init__(self, painter: QPainter):
        self.p = painter
        self.p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    def _pen(self, color: str, width: float, dash: str | None) -> QPen:
        pen = QPen(QColor(color))
        pen.setWidthF(max(0.1, width))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        if dash == "dot":
            pen.setStyle(Qt.PenStyle.DotLine)
        elif dash == "dash":
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def line(self, x1, y1, x2, y2, color="#000000", width=1.0, dash=None):
        self.p.setPen(self._pen(color, width, dash))
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        self.p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, rx=0.0):
        pen = self._pen(stroke, width, None) if stroke else Qt.PenStyle.NoPen
        self.p.setPen(pen if stroke else QPen(Qt.PenStyle.NoPen))
        self.p.setBrush(QBrush(QColor(fill)) if fill else Qt.BrushStyle.NoBrush)
        if rx:
            self.p.drawRoundedRect(QRectF(x, y, w, h), rx, rx)
        else:
            self.p.drawRect(QRectF(x, y, w, h))

    def text(self, x, y, text, size=10, family="Arial", color="#000000",
             anchor="start", bold=False):
        font = QFont(family or "Arial")
        font.setPointSizeF(max(1.0, float(size)))
        font.setBold(bold)
        self.p.setFont(font)
        self.p.setPen(QPen(QColor(color)))
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        if anchor != "start":
            adv = QFontMetricsF(font).horizontalAdvance(text)
            if anchor == "middle":
                x -= adv / 2.0
            elif anchor == "end":
                x -= adv
        self.p.drawText(QPointF(x, y), text)

    def polygon(self, points: Sequence[tuple[float, float]], fill=None,
                stroke=None, width=1.0):
        self.p.setPen(self._pen(stroke, width, None) if stroke else QPen(Qt.PenStyle.NoPen))
        self.p.setBrush(QBrush(QColor(fill)) if fill else Qt.BrushStyle.NoBrush)
        self.p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))

    def cubic(self, p0, c1, c2, p1, stroke="#000000", width=1.0, fill=None):
        path = QPainterPath(QPointF(*p0))
        path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p1))
        self.p.setPen(self._pen(stroke, width, None))
        self.p.setBrush(QBrush(QColor(fill)) if fill else Qt.BrushStyle.NoBrush)
        self.p.drawPath(path)


# --------------------------------------------------------------------------- helpers
def _runs(state: str, slots: int) -> Iterable[tuple[int, int, str]]:
    """Yield (start, end_exclusive, char) runs over the visible slots."""
    if slots <= 0:
        return
    prev = state[0] if state else "0"
    start = 0
    for i in range(1, slots + 1):
        cur = state[i] if i < slots and i < len(state) else None
        if cur != prev:
            yield start, i, prev
            start = i
            prev = cur if cur is not None else prev
    if start < slots:
        yield start, slots, prev


def _label_font(label: Label) -> tuple[str, float]:
    fields = (label.tail or LABEL_TAIL).split(".")
    family = fields[1] if len(fields) > 1 and fields[1] else "Arial"
    try:
        size = float(fields[2]) if len(fields) > 2 else 8.0
    except ValueError:
        size = 8.0
    return family, max(4.0, size)


def arrow_offset(arrow: Arrow) -> float:
    parts = (arrow.tail or "").split(".")
    try:
        return float(parts[1]) if len(parts) > 1 else 0.0
    except ValueError:
        return 0.0


# The legacy format stores a numeric style in the 5th arrow field.  The exact
# original mapping is not fully documented; these four values cover the four
# arrow tools.  Unknown values keep the historical Bezier rendering.
ARROW_STYLE_NAMES = {0: "Straight", 1: "Angled", 2: "Bezier", 3: "Floating"}
_ARROW_STYLE_KINDS = {"straight": 0, "angled": 1, "bezier": 2, "floating": 3}


def arrow_style(kind: int) -> str:
    return {0: "straight", 1: "angled", 2: "bezier", 3: "floating"}.get(int(kind), "bezier")


def arrow_style_name(kind: int) -> str:
    return ARROW_STYLE_NAMES.get(int(kind), f"Type {int(kind)} (Bezier)")


def arrow_kind_for_style(name: str) -> int:
    return _ARROW_STYLE_KINDS.get(name, 2)


def _arrow_head(b, tip, direction, color="#000000", size=8.0):
    import math
    dx, dy = direction
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    px, py = -uy, ux
    base = (tip[0] - ux * size, tip[1] - uy * size)
    p1 = (base[0] + px * size * 0.45, base[1] + py * size * 0.45)
    p2 = (base[0] - px * size * 0.45, base[1] - py * size * 0.45)
    b.polygon([tip, p1, p2], fill=color, stroke=color, width=0.8)


@dataclass
class ArrowGeometry:
    style: str
    src: tuple[float, float]
    dst: tuple[float, float]
    c1: tuple[float, float]
    c2: tuple[float, float]
    bend: tuple[float, float]
    segments: list[tuple[tuple[float, float], tuple[float, float]]]


def cubic_point(p0, c1, c2, p1, t: float) -> tuple[float, float]:
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3.0 * mt * mt * t
    c = 3.0 * mt * t * t
    d = t * t * t
    return (a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0],
            a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1])


def arrow_geometry(doc: Document, arrow: Arrow) -> ArrowGeometry | None:
    si = doc.find_row(arrow.src_signal)
    di = doc.find_row(arrow.dst_signal)
    if si < 0 or di < 0:
        return None
    sy = doc.row_top(si) + doc.signal_height / 2.0
    dy = doc.row_top(di) + doc.signal_height / 2.0
    sx = doc.cycle_to_x(max(0, arrow.src_cycle))
    dx = doc.cycle_to_x(max(0, arrow.dst_cycle))
    off = arrow_offset(arrow)
    style = arrow_style(arrow.kind)
    ox, oy = arrow_pixel_offset(arrow)

    def shifted(point):
        return (point[0] + ox, point[1] + oy)

    if style == "bezier":
        if si == di:
            cy = min(sy, dy) - 30.0 - off * 0.25
            c1 = (sx + 18.0, cy)
            c2 = (dx - 18.0, cy)
        else:
            mid = (sy + dy) / 2.0 + off * 0.5
            c1 = (sx + (dx - sx) * 0.25, mid)
            c2 = (sx + (dx - sx) * 0.75, mid)
        samples = [cubic_point((sx, sy), c1, c2, (dx, dy), i / 32.0)
                   for i in range(33)]
        segments = [(shifted(a), shifted(b))
                    for a, b in zip(samples, samples[1:])]
        return ArrowGeometry(style, shifted((sx, sy)), shifted((dx, dy)),
                             shifted(c1), shifted(c2),
                             shifted(samples[16]), segments)

    if style == "angled":
        elbow_y = (sy + dy) / 2.0 + off * 0.5
        p1 = (sx, elbow_y)
        p2 = (dx, elbow_y)
        segments = [(shifted(a), shifted(b))
                    for a, b in (((sx, sy), p1), (p1, p2), (p2, (dx, dy)))]
        return ArrowGeometry(style, shifted((sx, sy)), shifted((dx, dy)),
                             shifted(p1), shifted(p2),
                             shifted(((sx + dx) / 2.0, elbow_y)), segments)

    # straight / floating: a straight line shifted vertically by the offset
    shift = off * 0.25
    sx2, sy2 = sx, sy + shift
    dx2, dy2 = dx, dy + shift
    if style == "floating":
        import math
        length = math.hypot(dx2 - sx2, dy2 - sy2)
        gap = min(8.0, max(0.0, length / 3.0))
        if length > 1e-6:
            ux, uy = (dx2 - sx2) / length, (dy2 - sy2) / length
            sx2, sy2 = sx2 + ux * gap, sy2 + uy * gap
            dx2, dy2 = dx2 - ux * gap, dy2 - uy * gap
    segments = [(shifted((sx2, sy2)), shifted((dx2, dy2)))]
    return ArrowGeometry(style, shifted((sx2, sy2)), shifted((dx2, dy2)),
                         shifted((sx2, sy2)), shifted((dx2, dy2)),
                         shifted(((sx2 + dx2) / 2.0, (sy2 + dy2) / 2.0)),
                         segments)


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    import math
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    if denom <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def arrow_distance(geom: ArrowGeometry, x: float, y: float, samples: int = 32) -> float:
    best = float("inf")
    for (ax, ay), (bx, by) in geom.segments:
        best = min(best, _point_segment_distance(x, y, ax, ay, bx, by))
    return best


def arrow_handle(geom: ArrowGeometry, x: float, y: float,
                 tol: float = 9.0) -> str | None:
    import math
    candidates = [
        ("src", math.hypot(x - geom.src[0], y - geom.src[1])),
        ("dst", math.hypot(x - geom.dst[0], y - geom.dst[1])),
        ("bend", math.hypot(x - geom.bend[0], y - geom.bend[1])),
    ]
    name, dist = min(candidates, key=lambda item: item[1])
    return name if dist <= tol else None


# --------------------------------------------------------------------------- drawing
def wave_level_y(ch: str, top: float, height: float) -> float:
    """Logic level: 1=high, 0=low, Z=mid (high-impedance)."""
    if ch == "1":
        return top
    if ch == "Z":
        return top + height / 2.0
    return top + height


def digital_segments(row: Row, doc: Document, top: float):
    """Return the waveform polyline segments, honouring Z and edge style."""
    x0 = doc.wave_x0
    sw = doc.slot_width
    h = doc.signal_height
    slots = doc.slots
    state = row.padded_state()
    slant = 0.0
    if row.edge_style == "slanted":
        slant = max(0.0, min(float(row.edge_width), sw * 0.8))
    segments = []
    prev = state[0]
    prev_y = wave_level_y(prev, top, h)
    cur_x = x0
    for i in range(1, slots + 1):
        cur = state[i] if i < slots else None
        if cur is None:
            end_x = x0 + slots * sw
            if end_x > cur_x:
                segments.append(((cur_x, prev_y), (end_x, prev_y)))
            break
        if cur == prev:
            continue
        boundary = x0 + i * sw
        new_y = wave_level_y(cur, top, h)
        if slant > 0.0:
            half = slant / 2.0
            left, right = boundary - half, boundary + half
            if left > cur_x:
                segments.append(((cur_x, prev_y), (left, prev_y)))
            segments.append(((left, prev_y), (right, new_y)))
            cur_x = right
        else:
            if boundary > cur_x:
                segments.append(((cur_x, prev_y), (boundary, prev_y)))
            segments.append(((boundary, prev_y), (boundary, new_y)))
            cur_x = boundary
        prev = cur
        prev_y = new_y
    return segments


def draw_digital(b, row: Row, doc: Document, top: float):
    for start, end in digital_segments(row, doc, top):
        b.line(start[0], start[1], end[0], end[1],
               color="#000000", width=1.0)


def draw_analog(b, row: Row, doc: Document, top: float):
    """Continuous sample waveform scaled into the row height."""
    samples = row.samples
    if not samples:
        return
    low = float(row.sample_min)
    high = float(row.sample_max)
    span = high - low if high != low else 1.0
    h = doc.signal_height
    x0 = doc.wave_x0
    sw = doc.slot_width
    points = []
    for index in range(min(doc.slots, len(samples))):
        value = max(low, min(high, float(samples[index])))
        x = x0 + (index + 0.5) * sw
        y = top + h * (1.0 - (value - low) / span)
        points.append((x, y))
    for start, end in zip(points, points[1:]):
        b.line(start[0], start[1], end[0], end[1],
               color="#000000", width=1.0)


def _subtract_ranges(intervals, cuts):
    """Return *intervals* with all *cuts* removed (half-open ranges)."""
    result = list(intervals)
    for cut_start, cut_end in cuts:
        updated = []
        for start, end in result:
            if cut_end <= start or cut_start >= end:
                updated.append((start, end))
                continue
            if start < cut_start:
                updated.append((start, cut_start))
            if cut_end < end:
                updated.append((cut_end, end))
        result = updated
    return result


def draw_bus(b, row: Row, doc: Document, top: float, opts: RenderOptions):
    x0 = doc.wave_x0
    sw = doc.slot_width
    h = doc.signal_height
    mid = top + h / 2.0
    state = row.padded_state()
    runs = list(_runs(state, doc.slots))
    overrides = [value for value in doc.bus_values
                 if value.row == row.name and value.text]
    # rails and hatching per run; high-Z is a single line at the midpoint
    for start, end, ch in runs:
        xa, xb = x0 + start * sw, x0 + end * sw
        if ch == "Z":
            b.line(xa, mid, xb, mid, color="#000000", width=1.0)
        else:
            b.line(xa, top, xb, top, color="#000000", width=1.0)
            b.line(xa, top + h, xb, top + h, color="#000000", width=1.0)
            # diagonal hatching, clipped analytically to the run
            step = 9.0
            x = xa - h
            while x < xb:
                cx0 = max(x, xa)
                cx1 = min(x + h, xb)
                if cx1 > cx0:
                    b.line(cx0, top + (cx0 - x), cx1, top + (cx1 - x),
                           color="#c8c8c8", width=0.8)
                x += step
        inside_override = any(value.start < start < value.end
                              for value in overrides)
        if start > 0 and not inside_override:
            slant = 0.0
            if row.edge_style == "slanted":
                slant = max(0.0, min(float(row.edge_width), sw * 0.8))
            if slant > 0.0:
                # Two different bus values cross like an X.
                half = slant / 2.0
                b.line(xa - half, top, xa + half, top + h,
                       color="#000000", width=1.0)
                b.line(xa - half, top + h, xa + half, top,
                       color="#000000", width=1.0)
            else:
                b.line(xa, top, xa, top + h, color="#000000", width=1.0)
        if ch == "Z":
            continue
        # Inserting a value over a sub-range splits the run's default label
        # around the override: one remaining part (two segments) at an edge,
        # two remaining parts (three segments) in the middle.
        gaps = _subtract_ranges(
            [(start, end)],
            [(max(start, value.start), min(end, value.end))
             for value in overrides
             if value.start < end and value.end > start])
        if opts.show_bus_values:
            for gap_start, gap_end in gaps:
                cx = (x0 + (gap_start + gap_end) / 2.0 * sw)
                b.text(cx, top + h * 0.5 + 3.0, ch, size=7.0,
                       family="Arial", color="#808080", anchor="middle")
        # visible separators at the inserted value's boundaries
        slant = (max(0.0, min(float(row.edge_width), sw * 0.8))
                 if row.edge_style == "slanted" else 0.0)
        for value in overrides:
            for edge in (value.start, value.end):
                if start < edge < end:
                    ex = x0 + edge * sw
                    if slant > 0.0:
                        half = slant / 2.0
                        b.line(ex - half, top, ex + half, top + h,
                               color="#000000", width=1.0)
                        b.line(ex - half, top + h, ex + half, top,
                               color="#000000", width=1.0)
                    else:
                        b.line(ex, top, ex, top + h,
                               color="#000000", width=1.0)


BUS_VALUE_COLOR = "#404040"


def draw_bus_value(b, value, doc: Document):
    """Draw a custom bus text override over its slot range."""
    ri = doc.find_row(value.row)
    if ri < 0 or not value.text:
        return
    row = doc.rows[ri]
    if row.kind == "separator" or not doc.is_bus(row):
        return
    start = max(0, min(doc.slots, int(value.start)))
    end = max(start, min(doc.slots, int(value.end)))
    if end <= start:
        return
    top = doc.row_top(ri)
    cx = (doc.slot_to_x(start) + doc.slot_to_x(end)) / 2.0
    b.text(cx, top + doc.signal_height * 0.5 + 3.0, value.text,
           size=8.0, family="Arial", color=BUS_VALUE_COLOR, anchor="middle")


def draw_separator(b, row: Row, doc: Document, top: float):
    x0, x1 = doc.wave_x0, doc.wave_x0 + doc.wave_width
    y = top + ROW_PITCH / 2.0 - 6.0
    dotted = False
    parts = (row.sep_rest or "").split(".")
    if len(parts) > 2:
        dotted = parts[2] == "1"
    b.line(x0, y, x1, y, color="#606060", width=1.0, dash="dot" if dotted else None)


def draw_label(b, label: Label, row_names: set[str]):
    if not label.text:
        return
    family, size = _label_font(label)
    b.text(label.x1, label.y1, label.text, size=size, family=family, color="#000000")


def draw_arrow(b, arrow: Arrow, doc: Document):
    geom = arrow_geometry(doc, arrow)
    if geom is None:
        return
    if geom.style == "bezier":
        b.cubic(geom.src, geom.c1, geom.c2, geom.dst, stroke="#000000", width=1.0)
        direction = (geom.dst[0] - geom.c2[0], geom.dst[1] - geom.c2[1])
    else:
        for start, end in geom.segments:
            b.line(start[0], start[1], end[0], end[1],
                   color="#000000", width=1.0)
        direction = (geom.dst[0] - geom.src[0], geom.dst[1] - geom.src[1])
        for start, end in reversed(geom.segments):
            dx, dy = end[0] - start[0], end[1] - start[1]
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                direction = (dx, dy)
                break
    _arrow_head(b, geom.dst, direction)


def draw_timebreak(b, tb: TimeBreak, doc: Document):
    ri = doc.find_row(tb.signal)
    if ri < 0:
        return
    x = doc.cycle_to_x(max(0, tb.cycle))
    top = doc.row_top(ri)
    h = doc.signal_height
    # double zig-zag break symbol
    for dx in (-2.0, 2.0):
        b.line(x + dx - 3.0, top, x + dx + 3.0, top + h / 2.0,
               color="#000000", width=1.0)
        b.line(x + dx + 3.0, top + h / 2.0, x + dx - 3.0, top + h,
               color="#000000", width=1.0)


MEASURE_COLOR = "#000000"


@dataclass
class MeasurementGeometry:
    x1: float
    x2: float
    anchor_top: float
    anchor_bottom: float
    y: float
    top: float
    bottom: float


def measurement_geometry(doc: Document,
                         measurement: Measurement) -> MeasurementGeometry | None:
    """Resolve a measurement to screen coordinates.

    ``y`` is the dimension line; when unset it sits at the middle of the two
    signal rows.  The guide lines always reach from the signal rows to ``y``,
    so raising/lowering the dimension line makes them taller/shorter.
    """
    si = doc.find_row(measurement.src_signal)
    di = doc.find_row(measurement.dst_signal)
    if si < 0 or di < 0:
        return None
    dx = float(measurement.dx or 0.0)
    x1 = doc.cycle_to_x(max(0, measurement.src_cycle)) + dx
    x2 = doc.cycle_to_x(max(0, measurement.dst_cycle)) + dx
    anchor_top = min(doc.row_top(si), doc.row_top(di))
    anchor_bottom = max(doc.row_top(si), doc.row_top(di)) + doc.signal_height
    default_y = (anchor_top + anchor_bottom) / 2.0
    y = float(measurement.y) if measurement.y is not None else default_y
    return MeasurementGeometry(x1, x2, anchor_top, anchor_bottom, y,
                               min(anchor_top, y), max(anchor_bottom, y))


def measurement_text(measurement: Measurement) -> str:
    text = (measurement.text or "").strip()
    suffix = (measurement.suffix or "").strip()
    if suffix:
        return f"{text} {suffix}".strip()
    return text


def _measurement_text_width(text: str) -> float:
    """Rough 9 pt text width; CJK glyphs are about 1.4x ASCII."""
    return sum(9.0 if ord(ch) > 0x2E7F else 6.5 for ch in text)


def draw_measurement(b, measurement: Measurement, doc: Document):
    """Dashed guides with an adaptive double-headed dimension arrow."""
    geom = measurement_geometry(doc, measurement)
    span = 0.0 if geom is None else abs(geom.x2 - geom.x1)
    if geom is None or span < 1.0:
        return
    color = measurement.color or MEASURE_COLOR
    # Dashed extension lines; the dimension line itself stays solid.
    b.line(geom.x1, geom.top, geom.x1, geom.bottom,
           color=color, width=1.0, dash="dash")
    b.line(geom.x2, geom.top, geom.x2, geom.bottom,
           color=color, width=1.0, dash="dash")
    b.line(geom.x1, geom.y, geom.x2, geom.y, color=color, width=1.0)
    label = measurement_text(measurement)
    head = 6.0
    needed = _measurement_text_width(label) + 2 * head + (8.0 if label else 4.0)
    if span >= needed:
        # Room inside: tips on the guides, triangles inside, pointing outward.
        _arrow_head(b, (geom.x1, geom.y), (-1.0, 0.0), color=color, size=head)
        _arrow_head(b, (geom.x2, geom.y), (1.0, 0.0), color=color, size=head)
    else:
        # Too narrow: tips on the guides, triangles outside, pointing inward.
        _arrow_head(b, (geom.x1, geom.y), (1.0, 0.0), color=color, size=head)
        _arrow_head(b, (geom.x2, geom.y), (-1.0, 0.0), color=color, size=head)
    if label:
        b.text((geom.x1 + geom.x2) / 2.0, geom.y - 5.0, label,
               size=9.0, family="Arial", color=color, anchor="middle")


def render_document(b, doc: Document, opts: RenderOptions | None = None,
                    selection: Selection | None = None):
    opts = opts or RenderOptions()
    w, h = doc.content_width, doc.content_height
    if opts.background:
        b.rect(0, 0, w, h, fill="#ffffff")
    bottom = TOP_MARGIN + len(doc.rows) * ROW_PITCH
    if opts.show_grid:
        # one dotted line per full clock period (two slots)
        if opts.period_lines:
            for s in range(0, doc.slots + 1, 2):
                x = doc.wave_x0 + s * doc.slot_width
                b.line(x, TOP_MARGIN, x, bottom, color="#e4e4e4", width=0.8, dash="dot")
        for i in range(len(doc.rows) + 1):
            y = TOP_MARGIN + i * ROW_PITCH
            b.line(0, y, w - 1, y, color="#f0f0f0", width=0.8)
    # vertical divider between names and waveforms
    if opts.show_divider:
        b.line(doc.wave_x0 - NAME_PAD / 2.0, TOP_MARGIN,
               doc.wave_x0 - NAME_PAD / 2.0, bottom, color="#d0d0d0", width=0.8)

    # flood fills live behind the waveforms
    for i, row in enumerate(doc.rows):
        if i >= len(doc.flood):
            break
        arr = doc.flood[i]
        top = doc.row_top(i)
        start = None
        for s in range(doc.slots):
            val = arr[s] if s < len(arr) else 0
            if val and start is None:
                start = s
            elif not val and start is not None:
                b.rect(doc.slot_to_x(start), top,
                       (s - start) * doc.slot_width, doc.signal_height,
                       fill="#fff0a8")
                start = None
        if start is not None:
            b.rect(doc.slot_to_x(start), top,
                   (doc.slots - start) * doc.slot_width, doc.signal_height,
                   fill="#fff0a8")

    for i, row in enumerate(doc.rows):
        top = doc.row_top(i)
        if opts.show_names:
            b.text(NAME_X, top + doc.signal_height - 2.0, row.name,
                   size=10.0, family="Arial", color="#000000")
        if row.kind == "separator":
            draw_separator(b, row, doc, top)
        elif row.kind == "analog":
            draw_analog(b, row, doc, top)
        elif doc.is_bus(row):
            draw_bus(b, row, doc, top, opts)
        elif row.kind in ("data", "clock", "raw"):
            draw_digital(b, row, doc, top)

    if opts.show_bus_values:
        for value in doc.bus_values:
            draw_bus_value(b, value, doc)

    for label in doc.labels:
        draw_label(b, label, {r.name for r in doc.rows})
    for arrow in doc.arrows:
        draw_arrow(b, arrow, doc)
    for tb in doc.timebreaks:
        draw_timebreak(b, tb, doc)
    for measurement in doc.measurements:
        draw_measurement(b, measurement, doc)

    if selection is not None and doc.rows:
        sel = selection.normalized()
        if 0 <= sel.row < len(doc.rows):
            x = doc.slot_to_x(sel.start)
            sw = (sel.end - sel.start + 1) * doc.slot_width
            y = doc.row_top(sel.row)
            b.rect(x, y - 2, sw, doc.signal_height + 4,
                   fill="#d7e9ff", stroke="#4a90d9", width=1.0)

    if opts.show_bounding_rect:
        b.rect(0.5, TOP_MARGIN - 0.5, w - 1, len(doc.rows) * ROW_PITCH + 1,
               fill=None, stroke="#808080", width=1.0)
    if opts.show_logo:
        b.text(w - 8, h - 6, "EdgeWeaver", size=7, family="Arial",
               color="#909090", anchor="end")
