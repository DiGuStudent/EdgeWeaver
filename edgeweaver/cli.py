"""Headless command-line interface for EdgeWeaver.

The CLI is intended for scripts and AI agents: it builds a timing diagram
from a JSON description and writes any combination of .tim, EMF, SVG, PNG,
PDF, CSV and XML files without opening a window.

Run ``python3 -m edgeweaver.cli describe`` for the full Markdown reference
(also kept in docs/cli.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Must be set before a Qt platform plugin is loaded.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from .model import (  # noqa: E402
    CLOCK_TAIL,
    DATA_TAIL,
    LABEL_TAIL,
    SEPARATOR_REST,
    Arrow,
    Document,
    Label,
    Measurement,
    Row,
    TimeBreak,
    is_free_label_owner,
    make_clock_state,
    set_arrow_offset,
    set_arrow_pixel_offset,
)
from .renderer import ARROW_STYLE_NAMES, RenderOptions, arrow_kind_for_style  # noqa: E402
from .tim_format import TimFormatError, load_tim, save_tim  # noqa: E402

SEPARATOR_NODOT = "SEP_0.0.0.0.0.1.0.0.0.1."
SUPPORTED_SUFFIXES = (".tim", ".emf", ".svg", ".png", ".pdf", ".csv", ".xml")


class SpecError(ValueError):
    """Invalid JSON drawing description."""


_QT_APP = None


def _ensure_qt():
    # QApplication (not just QGuiApplication) keeps the CLI compatible with
    # GUI modules and tests that later create widgets in the same process.
    # The reference is kept module-global: PyQt destroys the application when
    # the last Python wrapper is collected.
    global _QT_APP
    from PyQt6.QtWidgets import QApplication

    _QT_APP = QApplication.instance()
    if _QT_APP is None:
        _QT_APP = QApplication([])
    return _QT_APP


def _int(spec: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = spec.get(key, default)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"'{key}' must be an integer") from exc
    if not lo <= value <= hi:
        raise SpecError(f"'{key}' must be between {lo} and {hi}")
    return value


def _state(value: str, slots: int, allowed: str, pad: str, where: str) -> str:
    text = str(value or "")
    bad = sorted({ch for ch in text if ch not in allowed})
    if bad:
        raise SpecError(f"{where}: unsupported state character(s) {''.join(bad)!r}; "
                        f"allowed: {allowed!r}")
    if len(text) < slots:
        text += pad * (slots - len(text))
    return text


def build_document(spec: dict) -> Document:
    """Create a Document from the JSON description."""
    if not isinstance(spec, dict):
        raise SpecError("the spec must be a JSON object")

    doc = Document()
    doc.version = str(spec.get("version", "011"))
    doc.slot_width = _int(spec, "slot_width", 20, 1, 400)
    doc.slots = _int(spec, "slots", 30, 1, 600)
    doc.signal_height = _int(spec, "signal_height", 16, 4, 400)
    doc.name_width = _int(spec, "name_width", 100, 20, 1000)

    rows_spec = spec.get("rows")
    if not isinstance(rows_spec, list) or not rows_spec:
        raise SpecError("'rows' must be a non-empty array")

    rows: list[Row] = []
    names: set[str] = set()
    signal_names: set[str] = set()
    for i, item in enumerate(rows_spec):
        if not isinstance(item, dict):
            raise SpecError(f"rows[{i}] must be an object")
        kind = str(item.get("type", item.get("kind", "signal"))).lower()
        name = str(item.get("name") or f"ROW{i + 1}")
        if name in names:
            raise SpecError(f"row name {name!r} is duplicated")
        if any(ch in name for ch in ".\t\r\n"):
            raise SpecError(f"row name {name!r} must not contain '.', tabs or newlines")
        names.add(name)
        where = f"rows[{i}] ({name})"

        if kind in ("separator", "sep"):
            dotted = bool(item.get("dotted", True))
            sep_rest = str(item.get("sep") or
                           (SEPARATOR_REST if dotted else SEPARATOR_NODOT))
            rows.append(Row(name, "separator", "", "", sep_rest=sep_rest))
            continue
        signal_names.add(name)

        if kind == "clock":
            period = int(item.get("period", 2))
            duty = float(item.get("duty", 0.5))
            start_low = bool(item.get("start_low", True))
            if "state" in item:
                state = _state(item["state"], doc.slots, "01", "0", where)
            else:
                state = make_clock_state(doc.slots, period, duty, start_low)
            row = Row(name, "clock", state, CLOCK_TAIL)
            row.clock_period = max(2, min(64, period))
            row.clock_duty = min(0.95, max(0.05, duty))
            row.clock_start_low = start_low
        elif kind in ("signal", "data", "bus"):
            is_bus = kind == "bus"
            state = _state(item.get("state", ""), doc.slots,
                           "01234Z" if is_bus else "01Z",
                           "4" if is_bus else "0", where)
            row = Row(name, "data", state, DATA_TAIL)
        else:
            raise SpecError(f"{where}: unknown row type {kind!r}")

        edge = str(item.get("edge", "ideal")).lower()
        if edge not in ("ideal", "slanted"):
            raise SpecError(f"{where}: edge must be 'ideal' or 'slanted'")
        row.edge_style = edge
        try:
            row.edge_width = max(0.0, min(40.0, float(item.get("edge_width", 6))))
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{where}: edge_width must be a number") from exc
        rows.append(row)

    doc.rows = rows

    for i, item in enumerate(spec.get("labels", [])):
        if not isinstance(item, dict):
            raise SpecError(f"labels[{i}] must be an object")
        where = f"labels[{i}]"
        try:
            x1 = int(item["x"])
            y1 = int(item["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"{where}: integer 'x' and 'y' are required") from exc
        x2 = int(item.get("x2", x1))
        y2 = int(item.get("y2", y1))
        text = str(item.get("text", ""))
        if any(ch in text for ch in ".\t\r\n"):
            raise SpecError(f"{where}: label text must not contain '.', tabs or newlines")
        owner = str(item.get("owner", ""))
        if not owner:
            owner = f"EWLabel*{i}*"
        elif owner not in names and not is_free_label_owner(owner):
            raise SpecError(f"{where}: owner must be a row name or 'EWLabel*N*'")
        doc.labels.append(Label(x1, y1, x2, y2, text, owner,
                                str(item.get("tail", LABEL_TAIL))))

    for i, item in enumerate(spec.get("arrows", [])):
        if not isinstance(item, dict):
            raise SpecError(f"arrows[{i}] must be an object")
        where = f"arrows[{i}]"
        try:
            src_signal = str(item["src_signal"])
            dst_signal = str(item["dst_signal"])
            src_cycle = int(item["src_cycle"])
            dst_cycle = int(item["dst_cycle"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"{where}: src_signal, src_cycle, dst_signal and "
                            f"dst_cycle are required") from exc
        for signal in (src_signal, dst_signal):
            if signal not in signal_names:
                raise SpecError(f"{where}: unknown signal {signal!r}")
        if not (0 <= src_cycle <= doc.slots and 0 <= dst_cycle <= doc.slots):
            raise SpecError(f"{where}: cycles must be between 0 and {doc.slots}")
        style = str(item.get("style", "bezier")).lower()
        if style not in {v.lower() for v in ARROW_STYLE_NAMES.values()}:
            raise SpecError(f"{where}: style must be one of "
                            f"{sorted(ARROW_STYLE_NAMES.values())}")
        arrow = Arrow(src_cycle, src_signal, dst_cycle, dst_signal,
                      arrow_kind_for_style(style), "0.0.1.0.0.0.")
        try:
            set_arrow_offset(arrow, float(item.get("offset", 0)))
            set_arrow_pixel_offset(arrow, float(item.get("dx", 0)),
                                   float(item.get("dy", 0)))
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{where}: offset/dx/dy must be numbers") from exc
        doc.arrows.append(arrow)

    for i, item in enumerate(spec.get("timebreaks", [])):
        if not isinstance(item, dict):
            raise SpecError(f"timebreaks[{i}] must be an object")
        try:
            signal = str(item["signal"])
            cycle = int(item["cycle"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"timebreaks[{i}]: signal and cycle are required") from exc
        if signal not in signal_names:
            raise SpecError(f"timebreaks[{i}]: unknown signal {signal!r}")
        if not 0 <= cycle <= doc.slots:
            raise SpecError(f"timebreaks[{i}]: cycle must be between 0 and {doc.slots}")
        doc.timebreaks.append(TimeBreak(cycle, signal))

    for i, item in enumerate(spec.get("measurements", [])):
        if not isinstance(item, dict):
            raise SpecError(f"measurements[{i}] must be an object")
        where = f"measurements[{i}]"
        try:
            src_signal = str(item["src_signal"])
            dst_signal = str(item["dst_signal"])
            src_cycle = int(item["src_cycle"])
            dst_cycle = int(item["dst_cycle"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpecError(f"{where}: src_signal, src_cycle, dst_signal and "
                            f"dst_cycle are required") from exc
        for signal in (src_signal, dst_signal):
            if signal not in signal_names:
                raise SpecError(f"{where}: unknown signal {signal!r}")
        if not (0 <= src_cycle <= doc.slots and 0 <= dst_cycle <= doc.slots):
            raise SpecError(f"{where}: cycles must be between 0 and {doc.slots}")
        if src_cycle == dst_cycle:
            raise SpecError(f"{where}: the two edges must be at different cycles")
        try:
            y_raw = item.get("y")
            y = None if y_raw is None else int(y_raw)
            dx = float(item.get("dx", 0.0))
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{where}: y/dx must be numbers") from exc
        color = str(item.get("color", "#000000"))
        from PyQt6.QtGui import QColor

        if not QColor(color).isValid():
            raise SpecError(f"{where}: invalid color {color!r}")
        suffix = str(item.get("suffix", "")).strip()
        if suffix.lower() in ("none", "null"):
            suffix = ""
        if suffix in ("us", "μs", "µs"):
            suffix = "µs"          # U+00B5 MICRO SIGN
        if suffix not in ("", "ns", "µs", "ms"):
            raise SpecError(f"{where}: suffix must be none, ns, µs (us) or ms")
        doc.measurements.append(Measurement(
            src_signal, src_cycle, dst_signal, dst_cycle,
            str(item.get("text", "")), y, dx, color, suffix))

    doc.ensure_arrays()
    for i, item in enumerate(spec.get("flood", [])):
        if not isinstance(item, dict):
            raise SpecError(f"flood[{i}] must be an object")
        where = f"flood[{i}]"
        row_ref = item.get("row", 0)
        if isinstance(row_ref, str):
            try:
                row_index = next(j for j, r in enumerate(doc.rows)
                                 if r.name == row_ref)
            except StopIteration as exc:
                raise SpecError(f"{where}: unknown row {row_ref!r}") from exc
        else:
            row_index = int(row_ref)
        if not 0 <= row_index < len(doc.rows):
            raise SpecError(f"{where}: row index out of range")
        start = int(item.get("start", 0))
        end = int(item.get("end", doc.slots))
        value = int(item.get("value", 1))
        if not (0 <= start < end <= doc.slots):
            raise SpecError(f"{where}: needs 0 <= start < end <= {doc.slots}")
        for slot in range(start, end):
            doc.flood[row_index][slot] = value

    doc.dirty = True
    doc.raw_lists = None
    return doc


def _load_spec(path: str) -> dict:
    if path == "-":
        text = sys.stdin.read()
        source = "stdin"
    else:
        source = path
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise SpecError(f"cannot read spec {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON in {source}: {exc}") from exc


def _export(doc: Document, path: Path, *, transparent: bool, png_scale: float):
    suffix = path.suffix.lower()
    if suffix == ".tim":
        save_tim(doc, path)
    elif suffix == ".svg":
        from .svg_export import export_svg

        export_svg(doc, path, RenderOptions(background=not transparent))
    elif suffix == ".emf":
        from .emf_export import export_emf

        export_emf(doc, path)
    elif suffix == ".png":
        from .exporters import export_png

        export_png(doc, path, png_scale)
    elif suffix == ".pdf":
        from .exporters import export_pdf

        export_pdf(doc, path)
    elif suffix == ".csv":
        from .exporters import export_csv

        export_csv(doc, path)
    elif suffix == ".xml":
        from .exporters import export_xml

        export_xml(doc, path)
    else:
        raise SpecError(f"unsupported output extension {suffix!r}; "
                        f"use one of {', '.join(SUPPORTED_SUFFIXES)}")
    return suffix[1:]


def _run(args) -> int:
    if args.command == "describe":
        print(_describe_markdown())
        return 0

    if args.command == "draw":
        doc = build_document(_load_spec(args.spec))
    else:
        try:
            doc = load_tim(args.input)
        except OSError as exc:
            raise SpecError(f"cannot read {args.input}: {exc}") from exc

    _ensure_qt()
    results = []
    for raw in args.out:
        path = Path(raw)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise SpecError(f"unsupported output extension for {path}; "
                            f"use one of {', '.join(SUPPORTED_SUFFIXES)}")
        fmt = _export(doc, path, transparent=args.transparent,
                      png_scale=args.png_scale)
        results.append({"path": str(path), "format": fmt,
                        "bytes": path.stat().st_size})

    if args.json:
        payload = {
            "ok": True,
            "document": {
                "rows": len(doc.rows),
                "slots": doc.slots,
                "slot_width": doc.slot_width,
                "signal_height": doc.signal_height,
                "name_width": doc.name_width,
                "content_width": doc.content_width,
                "content_height": doc.content_height,
                "measurements": len(doc.measurements),
            },
            "outputs": results,
        }
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        for item in results:
            print(f"wrote {item['path']} ({item['bytes']} bytes)")
    return 0


def _describe_markdown() -> str:
    doc = Path(__file__).resolve().parents[1] / "docs" / "cli.md"
    if doc.exists():
        return doc.read_text(encoding="utf-8")
    return ("# EdgeWeaver CLI\n\n"
            "Build timing diagrams from JSON: `python3 -m edgeweaver.cli draw "
            "SPEC.json --out OUT.svg`.\n"
            "Convert legacy files: `python3 -m edgeweaver.cli convert IN.tim "
            "--out OUT.emf`.\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgeweaver-cli",
        description="Headless timing-diagram builder and converter.")
    sub = parser.add_subparsers(dest="command", required=True)

    draw = sub.add_parser("draw", help="build a diagram from a JSON spec")
    draw.add_argument("spec", help="JSON spec path, or - for stdin")
    draw.add_argument("--out", action="append", required=True, metavar="PATH",
                      help="output file (repeatable); extension selects format: "
                           ".tim/.emf/.svg/.png/.pdf/.csv/.xml")
    draw.add_argument("--transparent", action="store_true",
                      help="SVG: omit the white background")
    draw.add_argument("--png-scale", type=float, default=1.0,
                      help="PNG raster scale (default 1.0)")
    draw.add_argument("--json", action="store_true",
                      help="print a JSON result instead of plain lines")

    conv = sub.add_parser("convert", help="convert an existing .tim file")
    conv.add_argument("input", help="input .tim file")
    conv.add_argument("--out", action="append", required=True, metavar="PATH",
                      help="output file (repeatable)")
    conv.add_argument("--transparent", action="store_true",
                      help="SVG: omit the white background")
    conv.add_argument("--png-scale", type=float, default=1.0,
                      help="PNG raster scale (default 1.0)")
    conv.add_argument("--json", action="store_true",
                      help="print a JSON result instead of plain lines")

    sub.add_parser("describe", help="print the Markdown CLI/spec reference")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (SpecError, TimFormatError, OSError, ValueError) as exc:
        if getattr(args, "json", False):
            json.dump({"ok": False, "error": str(exc)}, sys.stdout,
                      ensure_ascii=False)
            sys.stdout.write("\n")
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
