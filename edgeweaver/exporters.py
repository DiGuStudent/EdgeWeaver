"""Image and interchange exporters/importers."""

from __future__ import annotations

import csv
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QSizeF
from PyQt6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter

from .model import (
    DATA_TAIL,
    Document,
    LABEL_TAIL,
    STATE_LEN,
    Label,
    Row,
    TimeBreak,
)
from .renderer import QtBackend, RenderOptions, Selection, render_document


def _render(painter: QPainter, doc: Document, opts: RenderOptions | None,
            scale: float = 1.0):
    if scale != 1.0:
        painter.scale(scale, scale)
    render_document(QtBackend(painter), doc, opts)


def export_png(doc: Document, path: str | Path, scale: float = 1.0,
               opts: RenderOptions | None = None) -> Path:
    path = Path(path)
    w = max(1, int(math.ceil(doc.content_width * scale)))
    h = max(1, int(math.ceil(doc.content_height * scale)))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    _render(painter, doc, opts, scale)
    painter.end()
    if not image.save(str(path), "PNG"):
        raise OSError(f"could not write {path}")
    return path


def export_pdf(doc: Document, path: str | Path,
               opts: RenderOptions | None = None) -> Path:
    path = Path(path)
    w = doc.content_width
    h = doc.content_height
    writer = QPdfWriter(str(path))
    writer.setResolution(96)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setPageSize(QPageSize(QSizeF(w * 72.0 / 96.0, h * 72.0 / 96.0),
                                 QPageSize.Unit.Point, "EdgeWeaver"))
    painter = QPainter(writer)
    _render(painter, doc, opts)
    painter.end()
    return path


def export_csv(doc: Document, path: str | Path) -> Path:
    path = Path(path)
    slots = doc.slots
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["Signal"] + [str(i) for i in range(slots)])
        for row in doc.rows:
            if row.kind == "separator":
                continue
            wr.writerow([row.name] + list(row.padded_state()[:slots]))
    return path


def export_xml(doc: Document, path: str | Path) -> Path:
    path = Path(path)
    root = ET.Element("waveform")
    x0 = doc.wave_x0
    sw = doc.slot_width
    for ri, row in enumerate(doc.rows):
        if row.kind == "separator":
            continue
        sig = ET.SubElement(root, "signal", {"name": row.name})
        ET.SubElement(sig, "data", {"value": row.padded_state()[: doc.slots]})
        for label in doc.labels:
            if label.owner != row.name:
                continue
            cycle = max(0, int(round((label.x1 - x0) / sw - 0.5)))
            ET.SubElement(sig, "text", {"cycle": str(cycle), "value": label.text})
        flood = doc.flood[ri] if ri < len(doc.flood) else []
        for i in range(doc.slots):
            value = flood[i] if i < len(flood) else 0
            if value:
                ET.SubElement(sig, "flood", {"cycle": str(i), "value": str(value)})
        for tb in doc.timebreaks:
            if tb.signal == row.name:
                ET.SubElement(sig, "timebreak", {"cycle": str(tb.cycle)})
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)
    return path


def import_xml(path: str | Path) -> Document:
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "waveform":
        # accept a bare <signals> container too
        if root.tag != "signals":
            raise ValueError("not a Timing XML waveform")
    doc = Document()
    doc.rows = []
    doc.labels = []
    doc.timebreaks = []
    doc.flood = []
    doc.delay = []
    max_slots = 1
    for sig in root.findall("signal"):
        name = sig.get("name") or f"Signal {len(doc.rows) + 1}"
        data_el = sig.find("data")
        value = data_el.get("value", "") if data_el is not None else ""
        max_slots = max(max_slots, min(STATE_LEN, len(value)))
        state = value + "0" * max(0, STATE_LEN - len(value))
        row = Row(name, "data", state[:STATE_LEN], DATA_TAIL)
        doc.rows.append(row)
        flood = [0] * STATE_LEN
        for fl in sig.findall("flood"):
            try:
                i = int(fl.get("cycle", "0"))
                v = int(fl.get("value", "0"))
            except ValueError:
                continue
            if 0 <= i < STATE_LEN:
                flood[i] = v
        doc.flood.append(flood)
        doc.delay.append([0] * STATE_LEN)
        for tb in sig.findall("timebreak"):
            try:
                cycle = int(tb.get("cycle", "0"))
            except ValueError:
                continue
            doc.timebreaks.append(TimeBreak(cycle, name))
    doc.ints4 = [20, max(1, max_slots), 16, 0]
    longest = max((len(r.name) for r in doc.rows), default=6)
    doc.ints9 = [max(60, longest * 7 + 12), 5, max(1, max_slots), 0, 0, 0, 0, 0, 0]
    # labels need row geometry, so create them after rows exist
    for sig in root.findall("signal"):
        name = sig.get("name") or ""
        ri = doc.find_row(name)
        if ri < 0:
            continue
        y = doc.row_top(ri) + doc.signal_height - 2.0
        for tx in sig.findall("text"):
            try:
                cycle = int(tx.get("cycle", "0"))
            except ValueError:
                cycle = 0
            text = tx.get("value", "")
            x = doc.wave_x0 + cycle * doc.slot_width
            doc.labels.append(Label(int(x), int(y), int(x + 60), int(y + 12),
                                    text, name, LABEL_TAIL))
    doc.ints9[0] = max(doc.ints9[0], 60)
    doc.dirty = True
    doc.raw_lists = None
    return doc


def import_csv(path: str | Path) -> Document:
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("empty CSV")
    start = 0
    if rows[0] and rows[0][0].strip().lower() in ("signal", "name", "signal name"):
        start = 1
    doc = Document()
    doc.rows = []
    doc.labels = []
    doc.arrows = []
    doc.timebreaks = []
    doc.flood = []
    doc.delay = []
    max_slots = 1
    for rec in rows[start:]:
        if not rec or not rec[0].strip():
            continue
        name = rec[0].strip()
        values = [v.strip() for v in rec[1:] if v.strip()]
        max_slots = max(max_slots, min(STATE_LEN, len(values)))
        state = "".join(values)[:STATE_LEN]
        state = state + "0" * (STATE_LEN - len(state))
        doc.rows.append(Row(name, "data", state, DATA_TAIL))
        doc.flood.append([0] * STATE_LEN)
        doc.delay.append([0] * STATE_LEN)
    doc.ints4 = [20, max(1, max_slots), 16, 0]
    longest = max((len(r.name) for r in doc.rows), default=6)
    doc.ints9 = [max(60, longest * 7 + 12), 5, max(1, max_slots), 0, 0, 0, 0, 0, 0]
    doc.dirty = True
    doc.raw_lists = None
    return doc
