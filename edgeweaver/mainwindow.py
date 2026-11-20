"""Main window for EdgeWeaver."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QIcon,
    QKeySequence,
    QPixmap,
    QColor,
    QFont,
    QPainter,
    QUndoCommand,
    QUndoStack,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QToolBar,
)

from .canvas import TimingCanvas
from .dialogs import (AnnotationsDialog, ArrowDialog, DocSettingsDialog,
                      RowDialog, RowPropertiesDialog)
from .emf_export import export_emf
from .exporters import (
    export_csv,
    export_pdf,
    export_png,
    export_xml,
    import_csv,
    import_xml,
)
from .model import (
    CLOCK_TAIL,
    DATA_TAIL,
    Document,
    Row,
    SEPARATOR_REST,
    make_clock_state,
    set_arrow_offset,
)
from .renderer import ARROW_STYLE_NAMES, RenderOptions, Selection, arrow_style_name
from .svg_export import export_svg
from .tim_format import TimFormatError, load_tim, save_tim


class DocCommand(QUndoCommand):
    def __init__(self, window: "MainWindow", text: str, before: Document, after: Document):
        super().__init__(text)
        self.window = window
        self.before = before
        self.after = after

    def _apply(self, doc: Document):
        # Undo/redo must not forget the file that is currently being edited.
        doc.path = self.window.doc.path
        self.window.apply_document(doc, mark_dirty=True)

    def undo(self):
        self._apply(self.before.clone())

    def redo(self):
        self._apply(self.after.clone())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document.new()
        self.doc.dirty = False
        self.undo_stack = QUndoStack(self)
        self.render_options = RenderOptions()
        self.arrow_kind = 2
        self._current_tool = "select"
        self._syncing_cycles = False
        self._settings = QSettings("EdgeWeaver", "EdgeWeaver")
        self._toolbar_actions: dict[str, QAction] = {}

        self.canvas = TimingCanvas(self, self.doc)
        self.canvas.cursorMoved.connect(self._on_cursor_moved)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setCentralWidget(self.scroll)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.setAcceptDrops(True)
        self.resize(1100, 720)
        self.setWindowIcon(application_icon())
        self.apply_document(self.doc, mark_dirty=False)
        self.canvas.set_zoom(1.0)
        self._last_dir = str(self._settings.value("last_dir", str(Path.home())))

    # ------------------------------------------------------------------ UI setup
    def _build_actions(self):
        self.new_action = QAction("&New", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_document)

        self.open_action = QAction("&Open...", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(lambda: self.open_document())

        self.save_action = QAction("&Save", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_document)

        self.save_as_action = QAction("Save &As...", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_document_as)

        self.import_xml_action = QAction("Import Timing &XML...", self)
        self.import_xml_action.triggered.connect(lambda: self.import_document("xml"))
        self.import_csv_action = QAction("Import &CSV...", self)
        self.import_csv_action.triggered.connect(lambda: self.import_document("csv"))

        self.export_actions = {}
        for key, label in (("emf", "&EMF..."), ("svg", "&SVG..."),
                           ("png", "&PNG..."), ("pdf", "&PDF..."),
                           ("csv", "&CSV..."), ("xml", "Timing &XML...")):
            act = QAction(label, self)
            act.triggered.connect(lambda checked=False, k=key: self.export_document(k))
            self.export_actions[key] = act

        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)

        self.undo_action = self.undo_stack.createUndoAction(self, "&Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "&Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)

        self.delete_cells_action = QAction("Delete Cells", self)
        self.delete_cells_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_cells_action.triggered.connect(self.canvas.delete_selection)

        self.settings_action = QAction("Document &Settings...", self)
        self.settings_action.triggered.connect(self.document_settings)

        self.rename_action = QAction("&Rename Row...", self)
        self.rename_action.triggered.connect(lambda: self.rename_row(self._selected_row()))
        self.delete_row_action = QAction("Delete &Row", self)
        self.delete_row_action.triggered.connect(lambda: self.delete_row(self._selected_row()))

        self.annotations_action = QAction("&Annotations...", self)
        self.annotations_action.triggered.connect(self.edit_annotations)

        self.edit_arrow_action = QAction("Edit &Arrow...", self)
        self.edit_arrow_action.triggered.connect(self.edit_selected_arrow)

        self.row_props_action = QAction("&Signal/Clock Properties...", self)
        self.row_props_action.setShortcut(QKeySequence("F2"))
        self.row_props_action.triggered.connect(self.edit_selected_row_properties)

        self.zoom_in_action = QAction("Zoom &In", self)
        self.zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.zoom_in_action.triggered.connect(lambda: self.set_zoom(self.canvas.zoom * 1.25))
        self.zoom_out_action = QAction("Zoom &Out", self)
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.zoom_out_action.triggered.connect(lambda: self.set_zoom(self.canvas.zoom / 1.25))
        self.fit_action = QAction("&Fit to Window", self)
        self.fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_action.triggered.connect(self.fit_to_window)

        self.opt_grid = QAction("Show &Grid / Period Lines", self, checkable=True, checked=True)
        self.opt_grid.toggled.connect(self._update_render_options)
        self.opt_names = QAction("Show Signal &Names", self, checkable=True, checked=True)
        self.opt_names.toggled.connect(self._update_render_options)
        self.opt_divider = QAction("Show Name/&Waveform Divider", self,
                                   checkable=True, checked=True)
        self.opt_divider.toggled.connect(self._update_render_options)
        self.opt_bus_values = QAction("Show Bus &Values", self, checkable=True, checked=True)
        self.opt_bus_values.toggled.connect(self._update_render_options)
        self.opt_bounding = QAction("Show Bounding &Rectangle", self, checkable=True, checked=False)
        self.opt_bounding.toggled.connect(self._update_render_options)

        self.about_action = QAction("&About EdgeWeaver", self)
        self.about_action.triggered.connect(self.about)

    def _build_menus(self):
        m = self.menuBar()
        file_menu = m.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        imp = file_menu.addMenu("&Import")
        imp.addAction(self.import_xml_action)
        imp.addAction(self.import_csv_action)
        exp = file_menu.addMenu("&Export")
        for act in self.export_actions.values():
            exp.addAction(act)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = m.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.delete_cells_action)
        edit_menu.addAction(self.rename_action)
        edit_menu.addAction(self.delete_row_action)
        edit_menu.addAction(self.row_props_action)
        edit_menu.addAction(self.annotations_action)
        edit_menu.addAction(self.edit_arrow_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.settings_action)

        add_menu = m.addMenu("&Add")
        add_menu.addAction(self._make_action("Add &Clock...", lambda: self.add_row("clock")))
        add_menu.addAction(self._make_action("Add &Signal...", lambda: self.add_row("signal")))
        add_menu.addAction(self._make_action("Add &Bus...", lambda: self.add_row("bus")))
        add_menu.addAction(self._make_action("Insert Se&parator", lambda: self.add_row("separator")))
        add_menu.addSeparator()
        add_menu.addAction(self._make_action("Add &Text/Label...", lambda: self.set_tool("text")))
        add_menu.addAction(self._make_action("Add &Time Break...", lambda: self.set_tool("break")))
        add_menu.addAction(self._make_action("Add &Arrow...", lambda: self.set_tool("arrow")))
        style_menu = add_menu.addMenu("Arrow &Style")
        self.arrow_style_group = QActionGroup(self)
        self.arrow_style_actions = {}
        for kind, name in sorted(ARROW_STYLE_NAMES.items()):
            act = QAction(name, self, checkable=True)
            act.triggered.connect(lambda checked=False, k=kind: self.set_arrow_kind(k))
            self.arrow_style_group.addAction(act)
            style_menu.addAction(act)
            self.arrow_style_actions[kind] = act
        self.arrow_style_actions[self.arrow_kind].setChecked(True)

        view_menu = m.addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.fit_action)
        view_menu.addSeparator()
        view_menu.addAction(self.opt_grid)
        view_menu.addAction(self.opt_names)
        view_menu.addAction(self.opt_divider)
        view_menu.addAction(self.opt_bus_values)
        view_menu.addAction(self.opt_bounding)

        help_menu = m.addMenu("&Help")
        help_menu.addAction(self.about_action)

    def _make_action(self, text, slot) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        return act

    def _build_toolbar(self):
        tb = QToolBar("Tools", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_group = group
        tools = [
            ("select", "Select", "V", "Select cells"),
            ("high", "1", "H", "Draw high"),
            ("low", "0", "L", "Draw low"),
            ("z", "Z", "Z", "Draw high-impedance (Z) at mid-level"),
            ("bus", "Bus", "B", "Draw bus"),
            ("text", "Text", "T", "Place label text"),
            ("arrow", "Arrow", "A", "Draw relationship arrow"),
            ("break", "Break", "K", "Draw time break"),
            ("erase", "Erase", "E", "Erase cells"),
        ]
        for key, label, shortcut, tip in tools:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setToolTip(tip)
            act.setShortcut(QKeySequence(shortcut))
            act.setData(key)
            act.triggered.connect(lambda checked=False, k=key: self.set_tool(k))
            group.addAction(act)
            tb.addAction(act)
            self._toolbar_actions[key] = act
            if key == "select":
                act.setChecked(True)
        tb.addSeparator()
        tb.addWidget(QLabel("Arrow:"))
        self.arrow_style_combo = QComboBox()
        for kind, name in sorted(ARROW_STYLE_NAMES.items()):
            self.arrow_style_combo.addItem(name, kind)
        idx = self.arrow_style_combo.findData(self.arrow_kind)
        if idx >= 0:
            self.arrow_style_combo.setCurrentIndex(idx)
        self.arrow_style_combo.currentIndexChanged.connect(self._on_arrow_style_combo)
        tb.addWidget(self.arrow_style_combo)
        tb.addSeparator()
        tb.addWidget(QLabel("Cycles:"))
        self.cycles_spin = QSpinBox()
        self.cycles_spin.setRange(1, 300)
        self.cycles_spin.setValue(max(1, self.doc.slots // 2))
        self.cycles_spin.setToolTip(
            "Visible width in 2-slot clock cycles; changing it regenerates clocks")
        self.cycles_spin.valueChanged.connect(self._on_cycles_changed)
        tb.addWidget(self.cycles_spin)
        tb.addSeparator()
        tb.addAction(self.zoom_in_action)
        tb.addAction(self.zoom_out_action)
        tb.addAction(self.fit_action)

    def _build_statusbar(self):
        self.row_status = QLabel("Row: -   Slot: -")
        self.zoom_status = QLabel("Zoom: 100%")
        self.message_status = QLabel("")
        self.statusBar().addWidget(self.row_status, 1)
        self.statusBar().addPermanentWidget(self.message_status)
        self.statusBar().addPermanentWidget(self.zoom_status)

    # ------------------------------------------------------------------ document plumbing
    def apply_document(self, doc: Document, mark_dirty: bool = True):
        self.doc = doc
        self.canvas.set_document(doc)
        self.canvas.update()
        if mark_dirty:
            self.doc.dirty = True
        self._update_title()
        self._update_zoom_label()
        self._sync_cycles_spin()

    def push_edit(self, text: str, before: Document, after: Document):
        self.undo_stack.push(DocCommand(self, text, before, after))

    def _update_title(self):
        name = self.doc.path.name if self.doc.path else "Untitled"
        star = "*" if self.doc.dirty else ""
        self.setWindowTitle(f"{name}{star} - EdgeWeaver")

    def _update_zoom_label(self):
        self.zoom_status.setText(f"Zoom: {int(round(self.canvas.zoom * 100))}%")

    def _selected_row(self) -> int:
        if self.canvas.selection is not None:
            return self.canvas.selection.row
        return 0

    def _update_render_options(self):
        self.render_options.show_grid = self.opt_grid.isChecked()
        self.render_options.show_names = self.opt_names.isChecked()
        self.render_options.show_divider = self.opt_divider.isChecked()
        self.render_options.show_bus_values = self.opt_bus_values.isChecked()
        self.render_options.show_bounding_rect = self.opt_bounding.isChecked()
        self.canvas.update()

    # ------------------------------------------------------------------ file operations
    def _maybe_save(self) -> bool:
        if not self.doc.dirty:
            return True
        answer = QMessageBox.question(
            self, "Save Changes?",
            "Do you want to save your changes?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_document()
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return True

    def new_document(self):
        if not self._maybe_save():
            return
        doc = Document.new()
        doc.dirty = False
        doc.path = None
        self.undo_stack.clear()
        self.apply_document(doc, mark_dirty=False)
        self.canvas.set_zoom(1.0)
        self.scroll.horizontalScrollBar().setValue(0)
        self.scroll.verticalScrollBar().setValue(0)
        self.status_message("New document")

    def open_document(self, path: str | None = None):
        if not self._maybe_save():
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open Timing File", self._last_dir,
                "Timing files (*.tim);;All files (*.*)")
            if not path:
                return
        try:
            doc = load_tim(path)
        except (TimFormatError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Error", f"Could not open the file:\n{exc}")
            return
        self._last_dir = str(Path(path).parent)
        self._settings.setValue("last_dir", self._last_dir)
        self.undo_stack.clear()
        self.apply_document(doc, mark_dirty=False)
        self.canvas.set_zoom(1.0)
        self.scroll.horizontalScrollBar().setValue(0)
        self.scroll.verticalScrollBar().setValue(0)
        self.status_message(f"Opened {Path(path).name}")

    def save_document(self) -> bool:
        if self.doc.path is None:
            return self.save_document_as()
        try:
            save_tim(self.doc, self.doc.path)
        except (OSError, TimFormatError) as exc:
            QMessageBox.critical(self, "Error", f"Could not save the file:\n{exc}")
            return False
        self._update_title()
        self.status_message(f"Saved {self.doc.path.name}")
        return True

    def save_document_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Timing File",
            str(Path(self._last_dir) / (self.doc.path.name if self.doc.path else "untitled.tim")),
            "Timing files (*.tim);;All files (*.*)")
        if not path:
            return False
        if not path.lower().endswith(".tim"):
            path += ".tim"
        self.doc.path = Path(path)
        return self.save_document()

    def export_document(self, kind: str):
        if not self.doc.rows:
            QMessageBox.information(self, "Export", "There are no waveforms to export.")
            return
        filters = {
            "emf": ("Enhanced Metafile (*.emf)", ".emf"),
            "svg": ("Scalable Vector Graphics (*.svg)", ".svg"),
            "png": ("PNG image (*.png)", ".png"),
            "pdf": ("PDF document (*.pdf)", ".pdf"),
            "csv": ("CSV files (*.csv)", ".csv"),
            "xml": ("Timing XML (*.xml)", ".xml"),
        }
        label, ext = filters[kind]
        default = str(Path(self._last_dir) /
                      ((self.doc.path.stem if self.doc.path else "edgeweaver") + ext))
        path, _ = QFileDialog.getSaveFileName(self, f"Export {kind.upper()}", default, label)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            if kind == "emf":
                export_emf(self.doc, path, self.render_options)
            elif kind == "svg":
                export_svg(self.doc, path, self.render_options)
            elif kind == "png":
                export_png(self.doc, path, 1.0, self.render_options)
            elif kind == "pdf":
                export_pdf(self.doc, path, self.render_options)
            elif kind == "csv":
                export_csv(self.doc, path)
            elif kind == "xml":
                export_xml(self.doc, path)
        except Exception as exc:  # user-facing export failure
            QMessageBox.critical(self, "Export Error", str(exc))
            return
        self._last_dir = str(Path(path).parent)
        self._settings.setValue("last_dir", self._last_dir)
        self.status_message(f"Exported {Path(path).name}")

    def import_document(self, kind: str):
        if not self._maybe_save():
            return
        if kind == "xml":
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Timing XML", self._last_dir,
                "Timing XML (*.xml);;All files (*.*)")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import CSV", self._last_dir,
                "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        try:
            doc = import_xml(path) if kind == "xml" else import_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return
        doc.path = None
        doc.dirty = True
        self.undo_stack.clear()
        self.apply_document(doc, mark_dirty=True)
        self.canvas.set_zoom(1.0)
        self.status_message(f"Imported {Path(path).name}")

    # ------------------------------------------------------------------ row operations
    def _default_name(self, kind: str) -> str:
        if kind == "clock":
            base = "Clock"
        elif kind == "signal":
            base = "Default Signal"
        elif kind == "bus":
            base = "Default Bus"
        else:
            return "separator"
        names = {r.name for r in self.doc.rows}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def add_row(self, kind: str, index: int | None = None):
        dialog = RowDialog(kind, self._default_name(kind), self.doc.slots, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        name = values["name"] or self._default_name(kind)
        before = self.doc.clone()
        if kind == "clock":
            row = Row(name, "clock",
                      make_clock_state(self.doc.slots, values["period"], values["duty"]),
                      CLOCK_TAIL)
        elif kind == "bus":
            row = Row(name, "data", "4" * 600, DATA_TAIL)
        elif kind == "signal":
            row = Row(name, "data", "0" * 600, DATA_TAIL)
        else:
            row = Row("separator", "separator", "", "", sep_rest=SEPARATOR_REST)
        new_index = self.doc.add_row(row, index)
        self.push_edit(f"Add {kind}", before, self.doc.clone())
        self.canvas.selection = Selection(new_index, 0, 0)
        self.canvas.update()

    def rename_row(self, index: int):
        if not (0 <= index < len(self.doc.rows)):
            return
        old = self.doc.rows[index].name
        name, ok = QInputDialog.getText(self, "Rename Row", "Signal name:", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        before = self.doc.clone()
        if self.doc.rename_row(index, name.strip()):
            self.push_edit("Rename row", before, self.doc.clone())
            self.canvas.update()

    def delete_row(self, index: int):
        if not (0 <= index < len(self.doc.rows)):
            return
        row = self.doc.rows[index]
        answer = QMessageBox.question(
            self, "Delete Row",
            f"Delete the row “{row.name}” and its labels/arrows?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        before = self.doc.clone()
        self.doc.delete_row(index)
        self.push_edit("Delete row", before, self.doc.clone())
        self.canvas.update()

    def edit_selected_arrow(self):
        index = self.canvas.selected_arrow
        if index is None:
            self.status_message("Select an arrow on the canvas first")
            return
        self.edit_arrow(index)

    def edit_arrow(self, index: int):
        if not (0 <= index < len(self.doc.arrows)):
            self.status_message("Select a valid arrow first")
            return
        dialog = ArrowDialog(self.doc, index, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        before = self.doc.clone()
        arrow = self.doc.arrows[index]
        arrow.src_signal = values["src_signal"]
        arrow.src_cycle = values["src_cycle"]
        arrow.dst_signal = values["dst_signal"]
        arrow.dst_cycle = values["dst_cycle"]
        arrow.kind = values["kind"]
        set_arrow_offset(arrow, values["offset"])
        arrow.raw = None
        self.doc.touch()
        self.push_edit("Edit arrow", before, self.doc.clone())
        self.canvas.selected_arrow = index
        self.canvas.update()

    def delete_arrow(self, index: int):
        if not (0 <= index < len(self.doc.arrows)):
            return
        before = self.doc.clone()
        del self.doc.arrows[index]
        self.doc.touch()
        self.canvas.selected_arrow = None
        self.push_edit("Delete arrow", before, self.doc.clone())
        self.canvas.update()

    def edit_annotations(self):
        before = self.doc.clone()
        dialog = AnnotationsDialog(self.doc, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changed:
            self.push_edit("Edit annotations", before, dialog.doc)
            self.canvas.update()

    def document_settings(self):
        dialog = DocSettingsDialog(self.doc, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        before = self.doc.clone()
        old_slots = self.doc.slots
        self.doc.slot_width = values["slot_width"]
        self.doc.slots = values["slots"]
        self.doc.signal_height = values["signal_height"]
        self.doc.name_width = values["name_width"]
        if self.doc.slots != old_slots:
            self.doc.regenerate_clocks()
        self.doc.touch()
        self.push_edit("Document settings", before, self.doc.clone())

    # ------------------------------------------------------------------ view/tools
    def _on_arrow_style_combo(self, index: int):
        kind = self.arrow_style_combo.itemData(index)
        if kind is not None:
            self.set_arrow_kind(int(kind), sync_combo=False)

    def set_arrow_kind(self, kind: int, sync_combo: bool = True):
        self.arrow_kind = int(kind)
        if sync_combo and hasattr(self, "arrow_style_combo"):
            idx = self.arrow_style_combo.findData(self.arrow_kind)
            if idx >= 0 and idx != self.arrow_style_combo.currentIndex():
                self.arrow_style_combo.blockSignals(True)
                self.arrow_style_combo.setCurrentIndex(idx)
                self.arrow_style_combo.blockSignals(False)
        act = getattr(self, "arrow_style_actions", {}).get(self.arrow_kind)
        if act is not None:
            act.setChecked(True)
        self.status_message(f"New arrows: {arrow_style_name(self.arrow_kind)}")

    def _primary_clock_period(self) -> int:
        for row in self.doc.rows:
            if row.kind == "clock":
                return max(2, min(64, int(row.clock_period)))
        return 2

    def _sync_cycles_spin(self):
        if not hasattr(self, "cycles_spin"):
            return
        period = self._primary_clock_period()
        max_cycles = max(1, 600 // period)
        value = max(1, min(max_cycles, self.doc.slots // period))
        self._syncing_cycles = True
        try:
            self.cycles_spin.setRange(1, max_cycles)
            self.cycles_spin.setValue(value)
        finally:
            self._syncing_cycles = False

    def _on_cycles_changed(self, value: int):
        if self._syncing_cycles:
            return
        period = self._primary_clock_period()
        new_slots = max(period, min(600, int(value) * period))
        if new_slots == self.doc.slots:
            return
        before = self.doc.clone()
        self.doc.slots = new_slots
        self.doc.regenerate_clocks()
        self.push_edit(f"Set clock cycles ({value})", before, self.doc.clone())
        self.status_message(f"Clock cycles: {value}   ({new_slots} slots)")

    def edit_selected_row_properties(self):
        self.edit_row_properties(self._selected_row())

    def edit_row_properties(self, index: int):
        if not (0 <= index < len(self.doc.rows)):
            self.status_message("Select a row first")
            return
        dialog = RowPropertiesDialog(self.doc, index, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        row = self.doc.rows[index]
        name = values["name"]
        if name and name != row.name and not self.doc.rename_row(index, name):
            QMessageBox.warning(self, "Rename",
                                "That name is already in use or invalid.")
            return
        before = self.doc.clone()
        row = self.doc.rows[index]
        if row.kind in ("data", "clock") and not self.doc.is_bus(row):
            row.edge_style = values["edge_style"]
            row.edge_width = values["edge_width"]
            row.raw = None
        if row.kind == "clock":
            old = (row.clock_period, row.clock_duty, row.clock_start_low)
            new = (values["clock_period"], values["clock_duty"],
                   values["clock_start_low"])
            row.clock_period, row.clock_duty, row.clock_start_low = new
            if new != old:
                self.doc.regenerate_clocks(index)
                row = self.doc.rows[index]
        self.doc.touch()
        self.push_edit("Row properties", before, self.doc.clone())
        self.canvas.update()
        self.status_message(f"Updated {row.name}")

    def set_tool(self, tool: str):
        self._current_tool = tool
        self.canvas.set_tool(tool)
        for key, act in self._toolbar_actions.items():
            act.setChecked(key == tool)
        hints = {
            "select": "Select cells; drag to highlight; Del clears",
            "high": "Click/drag to draw high (1)",
            "low": "Click/drag to draw low (0)",
            "z": "Click/drag to draw high-impedance (Z) at mid-level",
            "bus": "Click/drag to draw bus (4)",
            "text": "Click to place a label",
            "arrow": f"Click source, then destination ({arrow_style_name(self.arrow_kind)})",
            "break": "Click to insert a time break at that slot",
            "erase": "Click/drag to erase to the default level",
        }
        self.status_message(hints.get(tool, ""))

    def set_zoom(self, zoom: float):
        self.canvas.set_zoom(zoom)
        self._update_zoom_label()

    def fit_to_window(self):
        vw = max(100, self.scroll.viewport().width() - 24)
        vh = max(100, self.scroll.viewport().height() - 24)
        zoom = min(vw / self.doc.content_width, vh / self.doc.content_height, 3.0)
        self.set_zoom(max(0.2, zoom))

    def status_message(self, text: str):
        self.message_status.setText(text)

    def _on_cursor_moved(self, row: int, slot: int):
        if 0 <= row < len(self.doc.rows):
            self.row_status.setText(f"Row: {self.doc.rows[row].name}   Slot: {slot}")
        else:
            self.row_status.setText("Row: -   Slot: -")

    # ------------------------------------------------------------------ misc
    def about(self):
        QMessageBox.about(
            self, "About EdgeWeaver",
            "<h3>EdgeWeaver</h3>"
            "<p>An independent Linux timing-diagram editor for legacy "
            "<code>.tim</code> timing files.</p>"
            "<p>Clean-room implementation; no third-party code, icons or "
            "bitmaps are used.</p>"
            "<p>Supported: .tim read/write (011/010), EMF/PNG/SVG/PDF/CSV/XML export, "
            "XML/CSV import, clocks, signals, buses, separators, labels, arrows, "
            "time breaks, Z state, edge styles, undo/redo.</p>")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".tim"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".tim"):
                self.open_document(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event):
        self._settings.setValue("last_dir", self._last_dir)
        if self._maybe_save():
            event.accept()
        else:
            event.ignore()


def application_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(QColor("#2f6fb0"))
    painter = QPainter(pm)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Arial")
    font.setPointSize(24)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "EW")
    painter.end()
    return QIcon(pm)
