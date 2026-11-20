"""Document model for EdgeWeaver.

The model follows the structure of legacy .tim timing files:

    CString "TIM"
    CString "011"
    int32 x4        [slot_width, slots, signal_height, 0]
    6 x string list
    int32 x9, CString x2, int32 x2
    N x int32[600]  flood fill values
    N x int32[600]  edge delay / non-ideal edge values
    int32 x2, int32 x9 (version 011)

Rows are stored as legacy text records.  The 600-character state string is the
actual waveform; the two integer arrays are auxiliary data.  Unknown fields are
kept verbatim so that loading and saving an untouched file is byte-identical.
"""

from __future__ import annotations

import copy
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

STATE_LEN = 600

# Slanted-edge marker stored at the end of the 600-cell delay array.
# Large magic value; normal delay data is small.
EDGE_MAGIC = 0x45444745  # b"EDGE"
EDGE_WIDTH_INDEX = 598
EDGE_MAGIC_INDEX = 599

# Free label owners look like "EWLabel*3*" (new) or an older two-letter prefix.
FREE_LABEL_RE = re.compile(r"^[A-Z]{2}Label\*(\d+)\*$")


def is_free_label_owner(owner: str) -> bool:
    return bool(FREE_LABEL_RE.match(owner or ""))
ROW_PITCH = 44          # vertical distance between signal rows (screen px)
TOP_MARGIN = 20         # first row top
NAME_X = 5
NAME_PAD = 5

DATA_TAIL = ".0.0.Arial.10.0.0.0.0.8421504.N/A.0.0.0.0.0."
CLOCK_TAIL = ".0.1.Arial.10.0.0.0.0.8421504.N/A.0.1.5.0.0."
SEPARATOR_REST = "SEP_0.0.1.0.0.1.0.0.0.1."
LABEL_TAIL = "     0.Arial.8.0.0.0.0."

BUS_CHARS = "234"
LOGIC_CHARS = "01"


def make_clock_state(slots: int = 30, period: int = 2, duty: float = 0.5,
                     start_low: bool = True) -> str:
    """Create a 600-character clock state string.

    One character is one half-clock slot; the visible clock period is
    ``period`` slots.  Legacy files use period=2, i.e. 0101...
    """
    period = max(2, int(period))
    high = max(1, min(period - 1, int(round(period * duty))))
    chars = []
    for i in range(STATE_LEN):
        if i < slots:
            phase = i % period
            if start_low:
                high_now = phase >= (period - high)
            else:
                high_now = phase < high
            chars.append("1" if high_now else "0")
        else:
            chars.append("0")
    return "".join(chars)


def infer_clock_params(state: str, slots: int) -> tuple[int, float, bool]:
    """Infer period/duty/start-low from a stored clock state string."""
    start_low = not (state or "0").startswith("1")
    text = (state or "0")[: max(4, min(int(slots), 96))]
    runs: list[tuple[str, int]] = []
    cur = text[0]
    n = 0
    for ch in text:
        if ch == cur:
            n += 1
        else:
            runs.append((cur, n))
            cur, n = ch, 1
    runs.append((cur, n))
    if len(runs) > 1:
        runs = runs[1:]  # the first run may be clipped by the left edge
    highs = [n for ch, n in runs if ch == "1"]
    lows = [n for ch, n in runs if ch == "0"]
    if highs and lows:
        high = int(statistics.median(highs))
        low = int(statistics.median(lows))
        period = high + low
        if 2 <= period <= 64 and high > 0 and low > 0:
            return period, high / period, start_low
    return 2, 0.5, start_low


@dataclass
class Row:
    name: str
    kind: str                 # 'data' | 'clock' | 'separator' | 'raw'
    state: str = ""
    tail: str = DATA_TAIL
    sep_rest: str = ""
    raw: str | None = None    # original record, used for byte-identical save
    # Clock parameters (also inferred from the state when loading).
    clock_period: int = 2
    clock_duty: float = 0.5
    clock_start_low: bool = True
    # Vertical (ideal) or slanted (non-ideal) transition edges.
    edge_style: str = "ideal"
    edge_width: float = 6.0

    def clone(self) -> "Row":
        return copy.deepcopy(self)

    def padded_state(self) -> str:
        s = self.state or ""
        if len(s) < STATE_LEN:
            s = s + "0" * (STATE_LEN - len(s))
        return s[:STATE_LEN]


@dataclass
class Label:
    x1: int
    y1: int
    x2: int
    y2: int
    text: str
    owner: str
    tail: str
    raw: str | None = None

    def clone(self) -> "Label":
        return copy.deepcopy(self)


@dataclass
class Arrow:
    # Records look like: 3.MC.3.SDOUT.2.0.43.1.0.0.0.
    # i.e. src_cycle, src_signal, dst_cycle, dst_signal, kind, tail
    src_cycle: int
    src_signal: str
    dst_cycle: int
    dst_signal: str
    kind: int
    tail: str
    raw: str | None = None

    def clone(self) -> "Arrow":
        return copy.deepcopy(self)


@dataclass
class TimeBreak:
    cycle: int
    signal: str
    raw: str | None = None

    def clone(self) -> "TimeBreak":
        return copy.deepcopy(self)


@dataclass
class Measurement:
    """Interval between two signal edges, drawn as guides + double arrow."""

    src_signal: str
    src_cycle: int
    dst_signal: str
    dst_cycle: int
    text: str = ""
    y: int | None = None          # dimension-line Y; None = middle of the rows
    dx: float = 0.0               # horizontal pixel offset
    color: str = "#000000"
    suffix: str = ""              # "", "ns", "µs" (U+00B5) or "ms"
    raw: str | None = None

    def clone(self) -> "Measurement":
        return copy.deepcopy(self)


@dataclass
class Document:
    magic: str = "TIM"
    version: str = "011"
    ints4: list[int] = field(default_factory=lambda: [20, 30, 16, 0])
    rows: list[Row] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    list3: list[str] = field(default_factory=list)
    list4: list[str] = field(default_factory=list)
    arrows: list[Arrow] = field(default_factory=list)
    timebreaks: list[TimeBreak] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    ints9: list[int] = field(default_factory=lambda: [100, 5, 30, 0, 0, 0, 0, 0, 0])
    cs: list[str] = field(default_factory=lambda: ["", ""])
    ints2: list[int] = field(default_factory=lambda: [1, 1])
    flood: list[list[int]] = field(default_factory=list)
    delay: list[list[int]] = field(default_factory=list)
    tail2: list[int] = field(default_factory=lambda: [1, 12])
    tail9: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 1065353216, 1, 1, 1])
    path: Path | None = None
    dirty: bool = False
    raw_lists: list[list[str]] | None = None
    trailing: bytes = b""

    # ------------------------------------------------------------------ geometry
    @property
    def slot_width(self) -> int:
        return max(1, int(self.ints4[0]))

    @slot_width.setter
    def slot_width(self, value: int) -> None:
        self.ints4[0] = max(1, int(value))

    @property
    def slots(self) -> int:
        return max(1, min(STATE_LEN, int(self.ints4[1])))

    @slots.setter
    def slots(self, value: int) -> None:
        self.ints4[1] = max(1, min(STATE_LEN, int(value)))

    @property
    def signal_height(self) -> int:
        return max(4, int(self.ints4[2]))

    @signal_height.setter
    def signal_height(self, value: int) -> None:
        self.ints4[2] = max(4, int(value))

    @property
    def name_width(self) -> int:
        return max(20, int(self.ints9[0]))

    @name_width.setter
    def name_width(self, value: int) -> None:
        self.ints9[0] = max(20, int(value))

    @property
    def wave_x0(self) -> int:
        return self.name_width + NAME_PAD

    @property
    def wave_width(self) -> int:
        return self.slot_width * self.slots

    @property
    def content_width(self) -> int:
        return self.wave_x0 + self.wave_width + 24

    @property
    def content_height(self) -> int:
        return TOP_MARGIN + len(self.rows) * ROW_PITCH + 24

    def row_top(self, index: int) -> int:
        return TOP_MARGIN + index * ROW_PITCH

    def row_height_for(self, index: int) -> int:
        return self.signal_height

    def is_bus(self, row: Row) -> bool:
        if row.kind != "data":
            return False
        return any(ch in BUS_CHARS for ch in row.padded_state()[: self.slots])

    def row_kind_name(self, row: Row) -> str:
        if row.kind == "separator":
            return "Separator"
        if row.kind == "clock":
            return "Clock"
        if row.kind == "raw":
            return "Raw"
        return "Bus" if self.is_bus(row) else "Signal"

    def slot_to_x(self, slot: float) -> float:
        return self.wave_x0 + slot * self.slot_width

    def cycle_to_x(self, cycle: float) -> float:
        # Arrows and time breaks store a boundary/edge index, not a slot centre.
        return self.wave_x0 + cycle * self.slot_width

    def x_to_slot(self, x: float) -> int:
        return int((x - self.wave_x0) // self.slot_width)

    def x_to_cycle(self, x: float) -> int:
        """Nearest grid boundary index (0..slots), used as the non-edge fallback."""
        return max(0, min(self.slots,
                          int((x - self.wave_x0) / self.slot_width + 0.5)))

    def row_edges(self, row_index: int) -> list[int]:
        """Boundary indices where the row's state changes (excluding 0/slots)."""
        if not (0 <= row_index < len(self.rows)):
            return []
        row = self.rows[row_index]
        if row.kind in ("separator", "raw"):
            return []
        state = row.padded_state()
        return [i for i in range(1, self.slots) if state[i] != state[i - 1]]

    def nearest_edge(self, row_index: int, x: float) -> tuple[int | None, float]:
        best = None
        best_dist = float("inf")
        for edge in self.row_edges(row_index):
            dist = abs(x - self.cycle_to_x(edge))
            if dist < best_dist:
                best, best_dist = edge, dist
        return best, best_dist

    def edge_kind(self, row_index: int, edge: int) -> str:
        if not (0 <= row_index < len(self.rows)) or edge <= 0 or edge >= self.slots:
            return ""
        state = self.rows[row_index].padded_state()
        before, after = state[edge - 1], state[edge]
        if before == after:
            return ""
        if before == "0" and after == "1":
            return "rising"
        if before == "1" and after == "0":
            return "falling"
        return "edge"

    def y_to_row(self, y: float) -> int:
        if not self.rows:
            return -1
        idx = int((y - TOP_MARGIN) // ROW_PITCH)
        return max(0, min(len(self.rows) - 1, idx))

    # ------------------------------------------------------------------ content
    def find_row(self, name: str) -> int:
        for i, row in enumerate(self.rows):
            if row.name == name:
                return i
        return -1

    def ensure_arrays(self) -> None:
        while len(self.flood) < len(self.rows):
            self.flood.append([0] * STATE_LEN)
        while len(self.delay) < len(self.rows):
            self.delay.append([0] * STATE_LEN)
        del self.flood[len(self.rows):]
        del self.delay[len(self.rows):]
        for arr in (self.flood, self.delay):
            for i, row in enumerate(arr):
                if len(row) < STATE_LEN:
                    row.extend([0] * (STATE_LEN - len(row)))
                elif len(row) > STATE_LEN:
                    del row[STATE_LEN:]

    def sync_edge_markers(self) -> None:
        """Mirror row.edge_style/width into the delay array sentinel cells."""
        self.ensure_arrays()
        for i, row in enumerate(self.rows):
            arr = self.delay[i]
            if row.edge_style == "slanted":
                arr[EDGE_WIDTH_INDEX] = max(0, min(40, int(round(row.edge_width))))
                arr[EDGE_MAGIC_INDEX] = EDGE_MAGIC
            elif arr[EDGE_MAGIC_INDEX] == EDGE_MAGIC:
                arr[EDGE_WIDTH_INDEX] = 0
                arr[EDGE_MAGIC_INDEX] = 0

    def load_edge_markers(self) -> None:
        """Read row edge style/width back from the delay array sentinel."""
        self.ensure_arrays()
        for i, row in enumerate(self.rows):
            arr = self.delay[i]
            if arr[EDGE_MAGIC_INDEX] == EDGE_MAGIC:
                row.edge_style = "slanted"
                row.edge_width = float(max(0, min(40, arr[EDGE_WIDTH_INDEX])))
            else:
                row.edge_style = "ideal"

    def touch(self) -> None:
        self.dirty = True
        self.raw_lists = None

    def clone(self) -> "Document":
        return copy.deepcopy(self)

    def regenerate_clocks(self, row_index: int | None = None) -> None:
        """Rebuild clock waveforms from their period/duty for the current width."""
        indices = range(len(self.rows)) if row_index is None else [row_index]
        for i in indices:
            if not (0 <= i < len(self.rows)):
                continue
            row = self.rows[i]
            if row.kind != "clock":
                continue
            period = max(2, min(64, int(row.clock_period)))
            duty = min(0.95, max(0.05, float(row.clock_duty)))
            row.state = make_clock_state(self.slots, period, duty,
                                         bool(row.clock_start_low))
            parts = (row.tail or CLOCK_TAIL).split(".")
            if len(parts) <= 13:
                row.tail = CLOCK_TAIL
                parts = row.tail.split(".")
            if len(parts) > 13:
                parts[13] = str(max(1, min(9, int(round(row.clock_duty * 10)))))
                row.tail = ".".join(parts)
            row.raw = None
        self.touch()

    # ------------------------------------------------------------------ editing
    def set_cells(self, row_index: int, start_slot: int, end_slot: int, char: str) -> bool:
        if not (0 <= row_index < len(self.rows)):
            return False
        row = self.rows[row_index]
        if row.kind == "separator":
            return False
        lo = max(0, min(start_slot, end_slot))
        hi = min(self.slots - 1, max(start_slot, end_slot))
        if hi < lo:
            return False
        state = list(row.padded_state())
        changed = False
        for i in range(lo, hi + 1):
            if state[i] != char:
                state[i] = char
                changed = True
        if changed:
            row.state = "".join(state)
            row.raw = None
            self.touch()
        return changed

    def clear_cells(self, row_index: int, start_slot: int, end_slot: int) -> bool:
        row = self.rows[row_index] if 0 <= row_index < len(self.rows) else None
        if row is None or row.kind == "separator":
            return False
        default = "4" if self.is_bus(row) else "0"
        return self.set_cells(row_index, start_slot, end_slot, default)

    def add_row(self, row: Row, index: int | None = None) -> int:
        if index is None or index < 0 or index > len(self.rows):
            index = len(self.rows)
        self.rows.insert(index, row)
        self.flood.insert(index, [0] * STATE_LEN)
        self.delay.insert(index, [0] * STATE_LEN)
        self.touch()
        return index

    def delete_row(self, index: int) -> bool:
        if not (0 <= index < len(self.rows)):
            return False
        row = self.rows.pop(index)
        if index < len(self.flood):
            self.flood.pop(index)
        if index < len(self.delay):
            self.delay.pop(index)
        # drop dependent annotations
        self.labels = [l for l in self.labels if l.owner != row.name]
        self.arrows = [a for a in self.arrows
                       if a.src_signal != row.name and a.dst_signal != row.name]
        self.timebreaks = [t for t in self.timebreaks if t.signal != row.name]
        self.touch()
        return True

    def rename_row(self, index: int, new_name: str) -> bool:
        new_name = new_name.strip()
        if not new_name or not (0 <= index < len(self.rows)):
            return False
        if self.find_row(new_name) not in (-1, index):
            return False
        old = self.rows[index].name
        if old == new_name:
            return False
        self.rows[index].name = new_name
        self.rows[index].raw = None
        for l in self.labels:
            if l.owner == old:
                l.owner = new_name
                l.raw = None
        for a in self.arrows:
            if a.src_signal == old:
                a.src_signal = new_name
                a.raw = None
            if a.dst_signal == old:
                a.dst_signal = new_name
                a.raw = None
        for t in self.timebreaks:
            if t.signal == old:
                t.signal = new_name
                t.raw = None
        self.touch()
        return True

    def add_label(self, label: Label) -> None:
        self.labels.append(label)
        self.touch()

    def add_arrow(self, arrow: Arrow) -> None:
        self.arrows.append(arrow)
        self.touch()

    def add_timebreak(self, tb: TimeBreak) -> None:
        self.timebreaks.append(tb)
        self.touch()

    def add_measurement(self, measurement: Measurement) -> None:
        self.measurements.append(measurement)
        self.touch()

    def next_free_label_id(self) -> int:
        used = set()
        for label in self.labels:
            m = FREE_LABEL_RE.match(label.owner or "")
            if m:
                used.add(int(m.group(1)))
        i = 0
        while i in used:
            i += 1
        return i

    # ------------------------------------------------------------------ factory
    @classmethod
    def new(cls) -> "Document":
        doc = cls()
        doc.rows = [
            Row("Clock", "clock", make_clock_state(30, 2, 0.5, start_low=True), CLOCK_TAIL),
            Row("Default Signal", "data", "0" * STATE_LEN, DATA_TAIL),
            Row("Default Bus", "data", "4" * STATE_LEN, DATA_TAIL),
        ]
        doc.flood = [[0] * STATE_LEN for _ in doc.rows]
        doc.delay = [[0] * STATE_LEN for _ in doc.rows]
        doc.ints4 = [20, 30, 16, 0]
        doc.ints9[0] = 110
        doc.dirty = True
        doc.raw_lists = None
        return doc


def set_arrow_offset(arrow: Arrow, value: float) -> None:
    """Replace the vertical bend/offset field in an arrow record."""
    parts = (arrow.tail or "").split(".")
    if len(parts) < 2 or parts == [""]:
        parts = ["0", "0"]
    parts[1] = str(int(round(value)))
    arrow.tail = ".".join(parts)
    arrow.raw = None


# EdgeWeaver extension: per-arrow pixel nudge, stored at the end of the arrow
# tail as "<dx_tenths>.<dy_tenths>.EWPIX".  Arrows without the marker keep the
# legacy tail byte-for-byte.
ARROW_PIXEL_MARK = "EWPIX"


def arrow_pixel_offset(arrow: Arrow) -> tuple[float, float]:
    """Return the (dx, dy) pixel nudge stored in the arrow tail."""
    parts = (arrow.tail or "").split(".")
    try:
        i = parts.index(ARROW_PIXEL_MARK)
    except ValueError:
        return 0.0, 0.0
    if i < 2:
        return 0.0, 0.0
    try:
        return float(parts[i - 2]) / 10.0, float(parts[i - 1]) / 10.0
    except ValueError:
        return 0.0, 0.0


def set_arrow_pixel_offset(arrow: Arrow, dx: float, dy: float) -> None:
    """Store a pixel nudge for *arrow*, preserving all legacy tail fields."""
    parts = [p for p in (arrow.tail or "").split(".")]
    if parts and parts[-1] == "":
        parts.pop()
    qx, qy = int(round(dx * 10.0)), int(round(dy * 10.0))
    try:
        i = parts.index(ARROW_PIXEL_MARK)
    except ValueError:
        i = -1
    if i >= 2:
        if qx == 0 and qy == 0:
            del parts[i - 2:i + 1]
        else:
            parts[i - 2:i] = [str(qx), str(qy)]
    elif qx or qy:
        parts += [str(qx), str(qy), ARROW_PIXEL_MARK]
    elif not parts:
        return
    arrow.tail = ".".join(parts) + "."
    arrow.raw = None
