"""Reader/writer for legacy .tim timing files.

Layout validated against four real files.  Strings use counted-string encoding:
one length byte, or 0xFF followed by a little-endian WORD for strings of 255
bytes or more.
"""

from __future__ import annotations

import io
import os
import re
import struct
from pathlib import Path

from .model import (
    Arrow,
    CLOCK_TAIL,
    DATA_TAIL,
    Document,
    LABEL_TAIL,
    Label,
    Row,
    SEPARATOR_REST,
    STATE_LEN,
    TimeBreak,
    infer_clock_params,
    is_free_label_owner,
)

TAB5 = "\t\t\t\t\t"
DATA_PREFIX = "DATA_0_."
CLOCK_PREFIX = "CLK_0_."

# The legacy format is ANSI-oriented.  Chinese Windows stores text as GBK;
# Western Windows stores it as a single-byte codepage.  Files are read with a
# byte-preserving latin-1 mapping, then display fields are re-decoded here.
TEXT_ENCODING = os.environ.get("EDGEWEAVER_TEXT_ENCODING", "gb18030")


class TimFormatError(Exception):
    pass


def _display_text(value: str) -> str:
    if not any(ord(ch) > 127 for ch in value):
        return value
    try:
        return value.encode("latin1").decode(TEXT_ENCODING)
    except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
        return value


def _encode_text(value: str) -> bytes:
    try:
        return value.encode("latin1")
    except UnicodeEncodeError:
        try:
            return value.encode(TEXT_ENCODING)
        except (UnicodeEncodeError, LookupError):
            return value.encode("latin1", "replace")


# --------------------------------------------------------------------------- io helpers
def _read_exact(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise TimFormatError("unexpected end of file")
    return data


def _read_counted(f) -> str:
    b = _read_exact(f, 1)[0]
    if b == 0xFF:
        n = struct.unpack("<H", _read_exact(f, 2))[0]
    else:
        n = b
    return _read_exact(f, n).decode("latin1")


def _write_counted(out, value: str) -> None:
    data = _encode_text(value)
    n = len(data)
    if n < 0xFF:
        out.write(bytes((n,)))
    else:
        if n > 0xFFFF:
            raise TimFormatError("string too long for .tim format")
        out.write(b"\xff" + struct.pack("<H", n))
    out.write(data)


def _read_i32(f) -> int:
    return struct.unpack("<i", _read_exact(f, 4))[0]


def _write_i32(out, value: int) -> None:
    out.write(struct.pack("<i", int(value)))


# --------------------------------------------------------------------------- parsing
def _parse_row(record: str) -> Row:
    if TAB5 in record:
        name, rest = record.split(TAB5, 1)
    elif "\t" in record:
        name, rest = record.split("\t", 1)
        rest = rest.lstrip("\t")
    else:
        name, rest = record, ""
    name = _display_text(name.strip())
    if rest.startswith(DATA_PREFIX):
        body = rest[len(DATA_PREFIX):]
        state = body[:STATE_LEN]
        tail = body[STATE_LEN:]
        if len(state) < STATE_LEN:
            state = state + "0" * (STATE_LEN - len(state))
        return Row(name or "Signal", "data", state, tail or DATA_TAIL, raw=record)
    if rest.startswith(CLOCK_PREFIX):
        body = rest[len(CLOCK_PREFIX):]
        state = body[:STATE_LEN]
        tail = body[STATE_LEN:]
        if len(state) < STATE_LEN:
            state = state + "0" * (STATE_LEN - len(state))
        return Row(name or "Clock", "clock", state, tail or CLOCK_TAIL, raw=record)
    if rest.startswith("SEP_"):
        return Row(name or "separator", "separator", "", "", sep_rest=rest, raw=record)
    return Row(name or "Row", "raw", "", "", sep_rest=rest, raw=record)


_OWNER_RE = re.compile(r"\.([^.]+)\.")


def _parse_label(record: str, row_names: set[str]) -> Label:
    parts = record.split(".", 4)
    if len(parts) < 5:
        return Label(0, 0, 0, 0, record, "", "", raw=record)
    try:
        x1, y1, x2, y2 = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return Label(0, 0, 0, 0, record, "", "", raw=record)
    rem = parts[4]
    best = None
    for m in _OWNER_RE.finditer(rem):
        token = _display_text(m.group(1))
        if token in row_names or is_free_label_owner(token):
            best = (m, token)
    if best is None:
        return Label(x1, y1, x2, y2, _display_text(rem), "", "", raw=record)
    m, owner = best
    text = _display_text(rem[:m.start()])
    tail = rem[m.end():]
    return Label(x1, y1, x2, y2, text, owner, tail, raw=record)


def _parse_arrow(record: str) -> Arrow | None:
    parts = record.split(".")
    if len(parts) < 5:
        return None
    try:
        src_cycle = int(parts[0])
        dst_cycle = int(parts[2])
        kind = int(parts[4])
    except ValueError:
        return None
    tail = ".".join(parts[5:])
    return Arrow(src_cycle, _display_text(parts[1]), dst_cycle,
                 _display_text(parts[3]), kind, tail, raw=record)


def _parse_timebreak(record: str) -> TimeBreak | None:
    parts = record.split(".")
    if len(parts) < 2:
        return None
    try:
        cycle = int(parts[0])
    except ValueError:
        return None
    return TimeBreak(cycle, _display_text(parts[1]), raw=record)


def load_tim(path: str | Path) -> Document:
    path = Path(path)
    with path.open("rb") as f:
        magic = _read_counted(f)
        version = _read_counted(f)
        if "TIM" not in magic:
            raise TimFormatError("This is not a valid .tim timing file.")
        ints4 = [_read_i32(f) for _ in range(4)]
        lists: list[list[str]] = []
        for _ in range(6):
            n = _read_i32(f)
            if n < 0 or n > 100000:
                raise TimFormatError("invalid list size")
            lists.append([_read_counted(f) for _ in range(n)])
        ints9 = [_read_i32(f) for _ in range(9)]
        cs = [_read_counted(f), _read_counted(f)]
        ints2 = [_read_i32(f) for _ in range(2)]

        rows = [_parse_row(s) for s in lists[0]]
        n_rows = len(rows)
        flood = [[_read_i32(f) for _ in range(STATE_LEN)] for _ in range(n_rows)]
        delay = [[_read_i32(f) for _ in range(STATE_LEN)] for _ in range(n_rows)]
        tail2 = [_read_i32(f) for _ in range(2)]
        tail9 = [_read_i32(f) for _ in range(9)] if "010" not in version else []
        trailing = f.read()

    names = {r.name for r in rows}
    labels = [_parse_label(s, names) for s in lists[1]]
    arrows = [a for a in (_parse_arrow(s) for s in lists[4]) if a is not None]
    timebreaks = [t for t in (_parse_timebreak(s) for s in lists[5]) if t is not None]

    doc = Document(
        magic=magic,
        version=version,
        ints4=ints4,
        rows=rows,
        labels=labels,
        list3=list(lists[2]),
        list4=list(lists[3]),
        arrows=arrows,
        timebreaks=timebreaks,
        ints9=ints9,
        cs=cs,
        ints2=ints2,
        flood=flood,
        delay=delay,
        tail2=tail2,
        tail9=tail9,
        path=path,
        dirty=False,
        raw_lists=lists,
        trailing=trailing,
    )
    doc.ensure_arrays()
    doc.load_edge_markers()
    for row in doc.rows:
        if row.kind == "clock":
            row.clock_period, row.clock_duty, row.clock_start_low = \
                infer_clock_params(row.state, doc.slots)
    return doc


# --------------------------------------------------------------------------- writing
def _serialize_row(row: Row) -> str:
    if row.raw is not None:
        return row.raw
    prefix = f"{row.name}{TAB5}"
    if row.kind == "separator":
        return prefix + (row.sep_rest or SEPARATOR_REST)
    state = row.padded_state()
    tail = row.tail or DATA_TAIL
    if row.kind == "clock":
        if not tail.startswith("."):
            tail = CLOCK_TAIL
        return prefix + CLOCK_PREFIX + state + tail
    if not tail.startswith("."):
        tail = DATA_TAIL
    return prefix + DATA_PREFIX + state + tail


def _serialize_label(label: Label) -> str:
    if label.raw is not None:
        return label.raw
    tail = label.tail if label.tail else LABEL_TAIL
    return f"{label.x1}.{label.y1}.{label.x2}.{label.y2}.{label.text}.{label.owner}.{tail}"


def _serialize_arrow(arrow: Arrow) -> str:
    if arrow.raw is not None:
        return arrow.raw
    return (f"{arrow.src_cycle}.{arrow.src_signal}."
            f"{arrow.dst_cycle}.{arrow.dst_signal}.{arrow.kind}.{arrow.tail}")


def _serialize_timebreak(tb: TimeBreak) -> str:
    if tb.raw is not None:
        return tb.raw
    return f"{tb.cycle}.{tb.signal}."


def dumps_tim(doc: Document) -> bytes:
    doc.ensure_arrays()
    doc.sync_edge_markers()
    out = io.BytesIO()

    _write_counted(out, doc.magic or "TIM")
    _write_counted(out, doc.version or "011")
    ints4 = list(doc.ints4) + [0, 0, 0, 0]
    for v in ints4[:4]:
        _write_i32(out, v)

    if doc.raw_lists is not None and not doc.dirty:
        lists = doc.raw_lists
    else:
        lists = [
            [_serialize_row(r) for r in doc.rows],
            [_serialize_label(l) for l in doc.labels],
            list(doc.list3),
            list(doc.list4),
            [_serialize_arrow(a) for a in doc.arrows],
            [_serialize_timebreak(t) for t in doc.timebreaks],
        ]

    for lst in lists:
        _write_i32(out, len(lst))
        for s in lst:
            _write_counted(out, s)

    ints9 = list(doc.ints9) + [0] * 9
    for v in ints9[:9]:
        _write_i32(out, v)
    cs = list(doc.cs) + ["", ""]
    _write_counted(out, cs[0])
    _write_counted(out, cs[1])
    ints2 = list(doc.ints2) + [1, 1]
    _write_i32(out, ints2[0])
    _write_i32(out, ints2[1])

    n = len(doc.rows)
    for arr in (doc.flood, doc.delay):
        for i in range(n):
            row = arr[i] if i < len(arr) else []
            for j in range(STATE_LEN):
                _write_i32(out, row[j] if j < len(row) else 0)

    tail2 = list(doc.tail2) + [1, 12]
    _write_i32(out, tail2[0])
    _write_i32(out, tail2[1])
    if "010" not in doc.version:
        tail9 = list(doc.tail9)
        if len(tail9) < 9:
            tail9 += [0] * (9 - len(tail9))
        for v in tail9[:9]:
            _write_i32(out, v)
    out.write(doc.trailing)
    return out.getvalue()


def save_tim(doc: Document, path: str | Path) -> Path:
    path = Path(path)
    data = dumps_tim(doc)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    doc.path = path
    doc.dirty = False
    doc.raw_lists = None  # next save can serialize the current objects
    return path
