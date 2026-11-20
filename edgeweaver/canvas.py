"""Interactive timing-diagram canvas."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QColorDialog, QInputDialog, QMenu, QWidget

from .dialogs import MeasurementDialog
from .model import (
    Arrow,
    Document,
    LABEL_TAIL,
    Label,
    Measurement,
    TimeBreak,
    arrow_pixel_offset,
    set_arrow_offset,
    set_arrow_pixel_offset,
)
from .renderer import (
    ArrowGeometry,
    QtBackend,
    RenderOptions,
    Selection,
    arrow_distance,
    arrow_geometry,
    arrow_handle,
    arrow_offset,
    arrow_style,
    arrow_style_name,
    measurement_geometry,
    measurement_text,
    render_document,
)

TOOL_CURSORS = {
    "select": Qt.CursorShape.ArrowCursor,
    "high": Qt.CursorShape.CrossCursor,
    "low": Qt.CursorShape.CrossCursor,
    "bus": Qt.CursorShape.CrossCursor,
    "z": Qt.CursorShape.CrossCursor,
    "text": Qt.CursorShape.IBeamCursor,
    "arrow": Qt.CursorShape.CrossCursor,
    "break": Qt.CursorShape.CrossCursor,
    "measure": Qt.CursorShape.CrossCursor,
    "erase": Qt.CursorShape.CrossCursor,
}

DRAW_TOOLS = {"high", "low", "bus", "z", "erase"}
ARROW_BLUE = QColor("#2f6fb0")


class TimingCanvas(QWidget):
    cursorMoved = pyqtSignal(int, int)

    def __init__(self, window, doc: Document):
        super().__init__()
        self.window = window
        self.doc = doc
        self.zoom = 1.0
        self.tool = "select"
        self.selection: Selection | None = None
        self.selected_arrow: int | None = None
        self.selected_measurement: int | None = None
        self._anchor: tuple[int, int] | None = None
        self._drag_row: int | None = None
        self._drag_start = 0
        self._drag_end = 0
        self._drag_char = "0"
        self._edit_before: Document | None = None
        self._drag_changed = False
        self._arrow_src: tuple[int, int] | None = None
        self._measure_src: tuple[int, int] | None = None
        # measurement dragging
        self._drag_measure: int | None = None
        self._drag_measure_edit: Document | None = None
        self._drag_measure_y0 = 0.0
        self._drag_measure_orig_y = 0.0
        self._measure_changed = False
        self._hover: tuple[int, int] | None = None
        # arrow dragging
        self._drag_arrow: int | None = None
        self._drag_mode: str | None = None
        self._drag_orig: dict | None = None
        self._arrow_changed = False
        self._snap_guide: tuple[int, float, str] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(TOOL_CURSORS["select"])
        self._update_size()

    # ------------------------------------------------------------------ state
    def set_document(self, doc: Document) -> None:
        self.doc = doc
        self.selection = None
        self.selected_arrow = None
        self.selected_measurement = None
        self._arrow_src = None
        self._measure_src = None
        self._drag_measure = None
        self._drag_measure_edit = None
        self._measure_changed = False
        self._hover = None
        self._snap_guide = None
        self._drag_arrow = None
        self._drag_mode = None
        self._edit_before = None
        self._update_size()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.2, min(5.0, float(zoom)))
        self._update_size()
        self.update()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._arrow_src = None
        self._measure_src = None
        self._drag_measure = None
        self._drag_measure_edit = None
        self._measure_changed = False
        self._snap_guide = None
        self._drag_arrow = None
        self._drag_mode = None
        if tool != "select":
            self.selected_arrow = None
            self.selected_measurement = None
        self.setCursor(TOOL_CURSORS.get(tool, Qt.CursorShape.ArrowCursor))
        self.update()

    def _update_size(self) -> None:
        w = max(200, int(self.doc.content_width * self.zoom))
        h = max(120, int(self.doc.content_height * self.zoom))
        self.setFixedSize(w, h)

    def _options(self) -> RenderOptions:
        return getattr(self.window, "render_options", RenderOptions())

    # ------------------------------------------------------------------ geometry
    def _map(self, pos) -> tuple[int, int, float, float]:
        x = pos.x() / self.zoom
        y = pos.y() / self.zoom
        row = self.doc.y_to_row(y)
        slot = self.doc.x_to_slot(x)
        slot = max(0, min(self.doc.slots - 1, slot))
        return row, slot, x, y

    def _arrow_tolerance(self, screen_px: float) -> float:
        return screen_px / max(self.zoom, 0.01)

    def _arrow_at(self, x: float, y: float) -> int | None:
        best = None
        best_dist = self._arrow_tolerance(6.0)
        for i, arrow in enumerate(self.doc.arrows):
            geom = arrow_geometry(self.doc, arrow)
            if geom is None:
                continue
            dist = arrow_distance(geom, x, y)
            if dist <= best_dist:
                best, best_dist = i, dist
        return best

    def _selected_geometry(self) -> ArrowGeometry | None:
        if self.selected_arrow is None or not (0 <= self.selected_arrow < len(self.doc.arrows)):
            return None
        return arrow_geometry(self.doc, self.doc.arrows[self.selected_arrow])

    def _select_arrow_status(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self.doc.arrows)):
            return
        a = self.doc.arrows[index]
        self.window.status_message(
            f"Arrow {index} ({arrow_style_name(a.kind)}): "
            f"{a.src_signal}[{a.src_cycle}] -> "
            f"{a.dst_signal}[{a.dst_cycle}]  —  drag end handles, drag middle"
            f" to bend/move, Del removes"
        )

    def _measurement_at(self, x: float, y: float) -> int | None:
        for i, measurement in enumerate(self.doc.measurements):
            geom = measurement_geometry(self.doc, measurement)
            if geom is None:
                continue
            if (abs(y - geom.y) <= 5
                    and min(geom.x1, geom.x2) - 4 <= x <= max(geom.x1, geom.x2) + 4):
                return i
            for gx in (geom.x1, geom.x2):
                if abs(x - gx) <= 4 and geom.top - 4 <= y <= geom.bottom + 4:
                    return i
            label = measurement_text(measurement)
            if label:
                cx = (geom.x1 + geom.x2) / 2.0
                half = max(8.0, 6.5 * len(label) / 2.0)
                if abs(y - (geom.y - 11.0)) <= 9 and abs(x - cx) <= half:
                    return i
        return None

    def _edit_measurement(self, index: int) -> None:
        if not (0 <= index < len(self.doc.measurements)):
            return
        measurement = self.doc.measurements[index]
        result = MeasurementDialog.ask(self, measurement.text,
                                       measurement.suffix)
        if result is None or result == (measurement.text, measurement.suffix):
            return
        text, suffix = result
        before = self.doc.clone()
        measurement.text = text
        measurement.suffix = suffix
        self.doc.touch()
        self.window.push_edit("Edit measurement", before, self.doc.clone())
        self.update()

    def _choose_measure_color(self, index: int) -> None:
        if not (0 <= index < len(self.doc.measurements)):
            return
        measurement = self.doc.measurements[index]
        color = QColorDialog.getColor(QColor(measurement.color or "#000000"),
                                      self, "Measurement Color")
        if not color.isValid() or color.name() == (measurement.color or "#000000"):
            return
        before = self.doc.clone()
        measurement.color = color.name()
        self.doc.touch()
        self.window.push_edit("Measurement color", before, self.doc.clone())
        self.update()

    def _begin_measure_drag(self, index: int, mouse_y: float) -> None:
        if not (0 <= index < len(self.doc.measurements)):
            return
        geom = measurement_geometry(self.doc, self.doc.measurements[index])
        if geom is None:
            return
        self.selected_measurement = index
        self.selected_arrow = None
        self.selection = None
        self._drag_measure = index
        self._drag_measure_edit = self.doc.clone()
        self._drag_measure_y0 = mouse_y
        self._drag_measure_orig_y = geom.y
        self._measure_changed = False
        self.window.status_message(
            "Drag up/down to move the measurement; Esc cancels, Del removes")

    def _update_measure_drag(self, mouse_y: float) -> None:
        if self._drag_measure is None:
            return
        if not (0 <= self._drag_measure < len(self.doc.measurements)):
            return
        measurement = self.doc.measurements[self._drag_measure]
        new_y = self._drag_measure_orig_y + (mouse_y - self._drag_measure_y0)
        new_y = max(16.0, min(self.doc.content_height - 4.0, new_y))
        if abs(new_y - self._drag_measure_orig_y) < 0.5:
            return
        measurement.y = int(round(new_y))
        self.doc.touch()
        self._measure_changed = True

    def _finish_measure_drag(self) -> None:
        if (self._drag_measure is not None and self._drag_measure_edit is not None
                and self._measure_changed):
            index = self._drag_measure
            self.window.push_edit("Move measurement", self._drag_measure_edit,
                                  self.doc.clone())
            self.selected_measurement = index
        self._drag_measure = None
        self._drag_measure_edit = None
        self._measure_changed = False
        self.window.status_message("")

    def _cancel_measure_drag(self) -> None:
        if self._drag_measure is not None and self._drag_measure_edit is not None:
            revert = self._drag_measure_edit.clone()
            self._drag_measure = None
            self._drag_measure_edit = None
            self._measure_changed = False
            self.window.apply_document(revert, mark_dirty=bool(revert.dirty))

    def _delete_measurement(self, index: int) -> None:
        if not (0 <= index < len(self.doc.measurements)):
            return
        before = self.doc.clone()
        del self.doc.measurements[index]
        self.doc.touch()
        self.selected_measurement = None
        self.window.push_edit("Delete measurement", before, self.doc.clone())
        self.window.status_message("")
        self.update()

    def _snap_arrow_cycle(self, row: int, x: float) -> tuple[int, str]:
        """Snap arrow endpoints to the nearest signal edge, else to the grid."""
        grid = self.doc.x_to_cycle(x)
        if not (0 <= row < len(self.doc.rows)):
            return grid, "grid"
        if self.doc.rows[row].kind in ("separator", "raw"):
            return grid, "grid"
        edge, dist = self.doc.nearest_edge(row, x)
        tol = min(12.0 / max(self.zoom, 0.01), self.doc.slot_width * 0.75)
        if edge is not None and dist <= tol:
            return edge, (self.doc.edge_kind(row, edge) or "edge")
        return grid, "grid"

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.scale(self.zoom, self.zoom)
        render_document(QtBackend(painter), self.doc, self._options(), self.selection)

        # selected arrow overlay and handles
        geom = self._selected_geometry()
        if geom is not None:
            pen = QPen(ARROW_BLUE)
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(*geom.src))
            path.cubicTo(QPointF(*geom.c1), QPointF(*geom.c2), QPointF(*geom.dst))
            painter.drawPath(path)
            painter.setPen(QPen(ARROW_BLUE, 1.5))
            painter.setBrush(QColor("#ffffff"))
            for pt in (geom.src, geom.dst):
                painter.drawEllipse(QPointF(*pt), 4.5, 4.5)
            painter.setBrush(ARROW_BLUE)
            painter.drawEllipse(QPointF(*geom.bend), 4.5, 4.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        if (self.selected_measurement is not None
                and 0 <= self.selected_measurement < len(self.doc.measurements)):
            geom = measurement_geometry(
                self.doc, self.doc.measurements[self.selected_measurement])
            if geom is not None:
                pen = QPen(ARROW_BLUE)
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(
                    min(geom.x1, geom.x2) - 3, geom.top - 3,
                    abs(geom.x2 - geom.x1) + 6, geom.bottom - geom.top + 6))

        if self._snap_guide is not None:
            grow, gx, gkind = self._snap_guide
            if 0 <= grow < len(self.doc.rows):
                pen = QPen(ARROW_BLUE)
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.0)
                painter.setPen(pen)
                top = self.doc.row_top(grow)
                bottom = top + self.doc.signal_height
                painter.drawLine(QPointF(gx, top - 4), QPointF(gx, bottom + 4))
                font = painter.font()
                font.setPointSizeF(7.0)
                painter.setFont(font)
                painter.drawText(QPointF(gx + 3, top - 3),
                                 {"rising": "rising edge", "falling": "falling edge",
                                  "edge": "edge", "grid": "grid"}.get(gkind, gkind))
                painter.setFont(font)

        # arrow source marker (Add Arrow tool)
        if self._arrow_src is not None and 0 <= self._arrow_src[0] < len(self.doc.rows):
            row, slot = self._arrow_src
            x = self.doc.cycle_to_x(slot)
            y = self.doc.row_top(row) + self.doc.signal_height / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.blue)
            painter.drawEllipse(QPointF(x, y), 3.5, 3.5)

        # hover column
        if self._hover is not None:
            row, slot = self._hover
            if 0 <= row < len(self.doc.rows):
                x = self.doc.slot_to_x(slot)
                pen = QPen(Qt.GlobalColor.gray)
                pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, self.doc.row_top(row) - 2),
                                 QPointF(x, self.doc.row_top(row) + self.doc.signal_height + 2))
        painter.end()

    # ------------------------------------------------------------------ editing helpers
    def _begin_edit(self) -> None:
        if self._edit_before is None:
            self._edit_before = self.doc.clone()

    def _finish_edit(self, text: str) -> None:
        if self._edit_before is not None and self._drag_changed:
            self.window.push_edit(text, self._edit_before, self.doc.clone())
        self._edit_before = None
        self._drag_row = None
        self._drag_changed = False

    def _pmap(self, e):
        return self._map(e.position())

    # ------------------------------------------------------------------ arrow drag
    def _begin_arrow_drag(self, index: int, mode: str, row: int, slot: int,
                          x: float, y: float) -> None:
        if not (0 <= index < len(self.doc.arrows)):
            return
        self._begin_edit()
        arrow = self.doc.arrows[index]
        self._drag_arrow = index
        self._drag_mode = mode
        self._arrow_changed = False
        self._drag_orig = {
            "src_cycle": arrow.src_cycle,
            "dst_cycle": arrow.dst_cycle,
            "src_signal": arrow.src_signal,
            "dst_signal": arrow.dst_signal,
            "src_row": self.doc.find_row(arrow.src_signal),
            "dst_row": self.doc.find_row(arrow.dst_signal),
            "offset": arrow_offset(arrow),
            "row": row,
            "slot": slot,
            "x": x,
            "y": y,
        }

    def _update_arrow_drag(self, row: int, slot: int, x: float, y: float) -> None:
        if self._drag_arrow is None or self._drag_orig is None:
            return
        if not (0 <= self._drag_arrow < len(self.doc.arrows)):
            return
        arrow = self.doc.arrows[self._drag_arrow]
        orig = self._drag_orig
        mode = self._drag_mode
        changed = False
        if mode in ("src", "dst"):
            if (0 <= row < len(self.doc.rows)
                    and self.doc.rows[row].kind not in ("separator", "raw")):
                cycle, edge_kind = self._snap_arrow_cycle(row, x)
                self._snap_guide = (row, self.doc.cycle_to_x(cycle),
                                    edge_kind or "grid")
                if mode == "src":
                    if (arrow.src_signal != self.doc.rows[row].name
                            or arrow.src_cycle != cycle):
                        arrow.src_signal = self.doc.rows[row].name
                        arrow.src_cycle = cycle
                        changed = True
                else:
                    if (arrow.dst_signal != self.doc.rows[row].name
                            or arrow.dst_cycle != cycle):
                        arrow.dst_signal = self.doc.rows[row].name
                        arrow.dst_cycle = cycle
                        changed = True
        elif mode == "bend":
            dy = y - orig["y"]
            style = arrow_style(arrow.kind)
            if style == "bezier":
                # handle-to-offset ratios derived from the cubic control points
                if orig["src_row"] == orig["dst_row"]:
                    new_offset = orig["offset"] - dy * 5.3333
                else:
                    new_offset = orig["offset"] + dy * 2.6667
            elif style == "angled":
                new_offset = orig["offset"] + dy * 2.0
            else:  # straight / floating
                new_offset = orig["offset"] + dy * 4.0
            new_offset = max(-999.0, min(999.0, new_offset))
            if int(round(new_offset)) != int(round(orig["offset"])):
                set_arrow_offset(arrow, new_offset)
                self.doc.touch()
                changed = True
        elif mode == "move":
            self._snap_guide = None
            dcycle = self.doc.x_to_cycle(x) - self.doc.x_to_cycle(orig["x"])
            drow = row - orig["row"]
            if dcycle:
                arrow.src_cycle = max(0, min(self.doc.slots,
                                             orig["src_cycle"] + dcycle))
                arrow.dst_cycle = max(0, min(self.doc.slots,
                                             orig["dst_cycle"] + dcycle))
                changed = True
            if drow:
                sr = orig["src_row"] + drow
                dr = orig["dst_row"] + drow
                if (0 <= sr < len(self.doc.rows) and 0 <= dr < len(self.doc.rows)
                        and self.doc.rows[sr].kind != "separator"
                        and self.doc.rows[dr].kind != "separator"):
                    arrow.src_signal = self.doc.rows[sr].name
                    arrow.dst_signal = self.doc.rows[dr].name
                    changed = True
            if changed:
                self.doc.touch()
        if changed:
            arrow.raw = None
            self._arrow_changed = True
            self._select_arrow_status(self._drag_arrow)

    def _finish_arrow_drag(self) -> None:
        if self._edit_before is not None and self._arrow_changed:
            self.window.push_edit("Edit arrow", self._edit_before, self.doc.clone())
        self._edit_before = None
        self._drag_arrow = None
        self._drag_mode = None
        self._drag_orig = None
        self._arrow_changed = False
        self._snap_guide = None

    def _cancel_arrow_drag(self) -> None:
        if self._drag_arrow is not None and self._edit_before is not None:
            revert = self._edit_before.clone()
            self._edit_before = None
            self._drag_arrow = None
            self._drag_mode = None
            self._drag_orig = None
            self._arrow_changed = False
            self._snap_guide = None
            self.window.apply_document(revert, mark_dirty=bool(revert.dirty))

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._context_menu(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        row, slot, x, y = self._pmap(event)
        if row < 0 or row >= len(self.doc.rows):
            return
        self.setFocus()
        if self.tool == "select":
            # 1) handles of the currently selected arrow
            geom = self._selected_geometry()
            if geom is not None:
                handle = arrow_handle(geom, x, y, self._arrow_tolerance(9.0))
                if handle is not None:
                    self._begin_arrow_drag(self.selected_arrow, handle, row, slot, x, y)
                    self.update()
                    return
            # 2) an arrow under the cursor
            idx = self._arrow_at(x, y)
            if idx is not None:
                self.selected_arrow = idx
                self.selected_measurement = None
                self.selection = None
                self._begin_arrow_drag(idx, "move", row, slot, x, y)
                self._select_arrow_status(idx)
                self.update()
                return
            # 2b) a measurement annotation
            measure = self._measurement_at(x, y)
            if measure is not None:
                self._begin_measure_drag(measure, y)
                self.update()
                return
            # 3) cells
            self.selected_arrow = None
            self.selected_measurement = None
            self.selection = Selection(row, slot, slot)
            self._anchor = (row, slot)
            self.update()
        elif self.tool in ("high", "low", "bus", "z"):
            self._begin_edit()
            self._drag_row = row
            self._drag_start = slot
            self._drag_end = slot
            self._drag_char = {"high": "1", "low": "0", "bus": "4", "z": "Z"}[self.tool]
            if self.doc.set_cells(row, slot, slot, self._drag_char):
                self._drag_changed = True
            self.selection = Selection(row, slot, slot)
            self.update()
        elif self.tool == "erase":
            self._begin_edit()
            self._drag_row = row
            self._drag_start = slot
            self._drag_end = slot
            self._drag_char = "4" if self.doc.is_bus(self.doc.rows[row]) else "0"
            if self.doc.set_cells(row, slot, slot, self._drag_char):
                self._drag_changed = True
            self.selection = Selection(row, slot, slot)
            self.update()
        elif self.tool == "text":
            text, ok = QInputDialog.getText(self, "Add Label", "Label text:")
            if ok and text.strip():
                before = self.doc.clone()
                lid = self.doc.next_free_label_id()
                label = Label(int(x), int(y), int(x + 60), int(y + 12),
                              text.strip(), f"EWLabel*{lid}*", LABEL_TAIL)
                self.doc.add_label(label)
                self.window.push_edit("Add label", before, self.doc.clone())
                self.update()
        elif self.tool == "arrow":
            cycle, edge_kind = self._snap_arrow_cycle(row, x)
            if self._arrow_src is None:
                self._arrow_src = (row, cycle)
                self._snap_guide = (row, self.doc.cycle_to_x(cycle),
                                    edge_kind or "grid")
                self.window.status_message(
                    f"Arrow source: {self.doc.rows[row].name}[{cycle}]"
                    f"{' (' + edge_kind + ')' if edge_kind != 'grid' else ''}"
                    " — select the destination (Esc to cancel)")
                self.update()
            else:
                sr, ss = self._arrow_src
                if sr != row or ss != cycle:
                    before = self.doc.clone()
                    src_name = self.doc.rows[sr].name
                    dst_name = self.doc.rows[row].name
                    kind = getattr(self.window, "arrow_kind", 2)
                    self.doc.add_arrow(Arrow(ss, src_name, cycle, dst_name, kind,
                                             "0.0.1.0.0.0."))
                    self.window.push_edit("Add arrow", before, self.doc.clone())
                self._arrow_src = None
                self._snap_guide = None
                self.window.status_message("")
                self.update()
        elif self.tool == "measure":
            if self.doc.rows[row].kind in ("separator", "raw"):
                self.window.status_message("Measurements need a signal row")
                return
            cycle, edge_kind = self._snap_arrow_cycle(row, x)
            if self._measure_src is None:
                self._measure_src = (row, cycle)
                self._snap_guide = (row, self.doc.cycle_to_x(cycle),
                                    edge_kind or "grid")
                self.window.status_message(
                    f"Measure start: {self.doc.rows[row].name}[{cycle}]"
                    f"{' (' + edge_kind + ')' if edge_kind != 'grid' else ''}"
                    " — click the second edge (Esc to cancel)")
                self.update()
            else:
                sr, sc = self._measure_src
                if cycle != sc:
                    result = MeasurementDialog.ask(self)
                    if result is not None:
                        text, suffix = result
                        before = self.doc.clone()
                        src_name = self.doc.rows[sr].name
                        dst_name = self.doc.rows[row].name
                        self.doc.add_measurement(Measurement(
                            src_name, sc, dst_name, cycle, text,
                            suffix=suffix))
                        self.window.push_edit("Add measurement", before,
                                              self.doc.clone())
                else:
                    self.window.status_message(
                        "The two edges are at the same time; pick another edge")
                self._measure_src = None
                self._snap_guide = None
                self.window.status_message("")
                self.update()
        elif self.tool == "break":
            cycle = self.doc.x_to_cycle(x)
            before = self.doc.clone()
            changed = False
            for r in self.doc.rows:
                if r.kind == "separator":
                    continue
                if not any(t.signal == r.name and t.cycle == cycle
                           for t in self.doc.timebreaks):
                    self.doc.add_timebreak(TimeBreak(cycle, r.name))
                    changed = True
            if changed:
                self.window.push_edit("Add time break", before, self.doc.clone())
            self.update()

    def mouseMoveEvent(self, event):
        row, slot, x, y = self._pmap(event)
        self._hover = (row, slot) if row >= 0 else None
        self.cursorMoved.emit(row, slot)
        if self._drag_measure is not None:
            self._update_measure_drag(y)
            self.update()
            return
        if self._drag_arrow is not None:
            self._update_arrow_drag(row, slot, x, y)
            self.update()
            return
        if self.tool == "arrow" and row >= 0:
            cycle, edge_kind = self._snap_arrow_cycle(row, x)
            self._snap_guide = (row, self.doc.cycle_to_x(cycle),
                                edge_kind or "grid")
        elif self.tool == "measure" and self._measure_src is not None:
            pass  # keep the start-edge guide
        else:
            self._snap_guide = None
        if self._anchor is not None and self.tool == "select":
            self.selection = Selection(self._anchor[0], self._anchor[1], slot)
            self.update()
        elif self._drag_row is not None and self.tool in DRAW_TOOLS:
            if slot != self._drag_end:
                self._drag_end = slot
                if self.doc.set_cells(self._drag_row, self._drag_start, slot,
                                      self._drag_char):
                    self._drag_changed = True
                self.selection = Selection(self._drag_row, self._drag_start, slot)
                self.update()
        else:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_measure is not None:
            self._finish_measure_drag()
            self.update()
            return
        if self._drag_arrow is not None:
            self._finish_arrow_drag()
            self.update()
        elif self._anchor is not None and self.tool == "select":
            self._anchor = None
            self.update()
        elif self._drag_row is not None:
            self._finish_edit("Edit waveform cells")
            self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            self.window.set_zoom(self.zoom * factor)
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        key = event.key()
        if (key in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                    Qt.Key.Key_Up, Qt.Key.Key_Down)
                and self.selected_measurement is not None):
            index = self.selected_measurement
            if not (0 <= index < len(self.doc.measurements)):
                super().keyPressEvent(event)
                return
            measurement = self.doc.measurements[index]
            geom = measurement_geometry(self.doc, measurement)
            if geom is None:
                super().keyPressEvent(event)
                return
            step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            before = self.doc.clone()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                base = float(measurement.y) if measurement.y is not None else geom.y
                base += -step if key == Qt.Key.Key_Up else step
                measurement.y = int(round(max(
                    16.0, min(self.doc.content_height - 4.0, base))))
                y_value, x_value = measurement.y, float(measurement.dx or 0.0)
            else:
                measurement.dx = float(measurement.dx or 0.0) + \
                    (-step if key == Qt.Key.Key_Left else step)
                y_value = geom.y
                x_value = measurement.dx
            self.doc.touch()
            self.window.push_edit("Nudge measurement", before, self.doc.clone())
            self.selected_measurement = index
            self.window.status_message(
                f"Measurement: y={y_value:.0f}, dx={x_value:+.0f} px")
            self.update()
            event.accept()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                     Qt.Key.Key_Up, Qt.Key.Key_Down) and self.selected_arrow is not None:
            if not (0 <= self.selected_arrow < len(self.doc.arrows)):
                super().keyPressEvent(event)
                return
            step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            ax = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(key, 0.0)
            ay = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(key, 0.0)
            index = self.selected_arrow
            before = self.doc.clone()
            arrow = self.doc.arrows[index]
            ox, oy = arrow_pixel_offset(arrow)
            set_arrow_pixel_offset(arrow, ox + ax, oy + ay)
            self.doc.touch()
            self.window.push_edit("Nudge arrow", before, self.doc.clone())
            # QUndoStack.push() re-applies the document and clears the canvas
            # selection; keep the arrow selected for repeated nudges.
            self.selected_arrow = index
            self.window.status_message(
                f"Arrow offset: {ox + ax:+.0f}, {oy + ay:+.0f} px")
            self.update()
            event.accept()
        elif key == Qt.Key.Key_Delete:
            self.delete_selection()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            if self._drag_measure is not None:
                self._cancel_measure_drag()
            if self._drag_arrow is not None:
                self._cancel_arrow_drag()
            self._arrow_src = None
            self._measure_src = None
            self._snap_guide = None
            self.selected_arrow = None
            self.selected_measurement = None
            self.selection = None
            self.window.status_message("")
            self.update()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        row, slot, x, y = self._pmap(event)
        idx = self._arrow_at(x, y)
        if idx is not None:
            self.selected_arrow = idx
            self.window.edit_arrow(idx)
            event.accept()
            return
        measure = self._measurement_at(x, y)
        if measure is not None:
            self._edit_measurement(measure)
            event.accept()
            return
        if row >= 0 and x < self.doc.wave_x0:
            self.window.rename_row(row)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ actions
    def delete_selection(self) -> None:
        if self.selected_measurement is not None:
            idx = self.selected_measurement
            if 0 <= idx < len(self.doc.measurements):
                before = self.doc.clone()
                del self.doc.measurements[idx]
                self.doc.touch()
                self.selected_measurement = None
                self.window.push_edit("Delete measurement", before,
                                      self.doc.clone())
                self.window.status_message("")
                self.update()
            return
        if self.selected_arrow is not None:
            idx = self.selected_arrow
            if 0 <= idx < len(self.doc.arrows):
                before = self.doc.clone()
                del self.doc.arrows[idx]
                self.doc.touch()
                self.selected_arrow = None
                self.window.push_edit("Delete arrow", before, self.doc.clone())
                self.window.status_message("")
                self.update()
            return
        if self.selection is None:
            return
        sel = self.selection.normalized()
        before = self.doc.clone()
        if self.doc.clear_cells(sel.row, sel.start, sel.end):
            self.window.push_edit("Clear cells", before, self.doc.clone())
            self.update()

    def _context_menu(self, event):
        row, slot, x, y = self._pmap(event)
        idx = self._arrow_at(x, y)
        measure = None if idx is not None else self._measurement_at(x, y)
        menu = QMenu(self)
        if idx is not None:
            self.selected_arrow = idx
            self.update()
            menu.addAction("Edit Arrow...", lambda: self.window.edit_arrow(idx))
            menu.addAction("Delete Arrow", lambda: self.window.delete_arrow(idx))
            menu.addSeparator()
            menu.addAction("Add Arrow from here...", lambda: self.window.set_tool("arrow"))
            menu.addSeparator()
        elif measure is not None:
            self.selected_measurement = measure
            self.selected_arrow = None
            self.selection = None
            self.update()
            menu.addAction("Edit Measurement Text...",
                           lambda: self._edit_measurement(measure))
            menu.addAction("Measurement Color...",
                           lambda: self._choose_measure_color(measure))
            menu.addAction("Delete Measurement",
                           lambda: self._delete_measurement(measure))
            menu.addSeparator()
        if row < 0:
            menu.addAction("Document Settings...", self.window.document_settings)
        else:
            menu.addAction("Rename Row...", lambda: self.window.rename_row(row))
            menu.addAction("Signal/Clock Properties...",
                           lambda: self.window.edit_row_properties(row))
            menu.addAction("Delete Row", lambda: self.window.delete_row(row))
            menu.addSeparator()
            menu.addAction("Add Clock Below", lambda: self.window.add_row("clock", row + 1))
            menu.addAction("Add Signal Below", lambda: self.window.add_row("signal", row + 1))
            menu.addAction("Add Bus Below", lambda: self.window.add_row("bus", row + 1))
            menu.addAction("Insert Separator Below", lambda: self.window.add_row("separator", row + 1))
            menu.addSeparator()
            menu.addAction("Document Settings...", self.window.document_settings)
        menu.exec(event.globalPosition().toPoint())
