"""Small modal dialogs."""

from __future__ import annotations

import re

from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

DUTY_CHOICES = [
    ("10/90", 0.1),
    ("20/80", 0.2),
    ("30/70", 0.3),
    ("40/60", 0.4),
    ("50/50", 0.5),
    ("60/40", 0.6),
    ("70/30", 0.7),
    ("80/20", 0.8),
    ("90/10", 0.9),
]


class RowDialog(QDialog):
    def __init__(self, kind: str, default_name: str, doc_slots: int, parent=None):
        super().__init__(parent)
        self.kind = kind
        titles = {
            "clock": "Add Clock",
            "signal": "Add Signal",
            "bus": "Add Bus",
            "separator": "Insert Separator",
        }
        self.setWindowTitle(titles.get(kind, "Add Row"))
        self.setModal(True)
        form = QFormLayout(self)

        self.name_edit = QLineEdit(default_name)
        form.addRow("Name:", self.name_edit)

        self.period_spin = None
        self.duty_combo = None
        if kind == "clock":
            self.period_spin = QSpinBox()
            self.period_spin.setRange(2, max(2, min(64, doc_slots)))
            self.period_spin.setValue(2)
            form.addRow("Period (slots):", self.period_spin)
            self.duty_combo = QComboBox()
            for label, _ in DUTY_CHOICES:
                self.duty_combo.addItem(label)
            form.addRow("Duty cycle:", self.duty_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        duty = 0.5
        if self.duty_combo is not None:
            duty = DUTY_CHOICES[max(0, self.duty_combo.currentIndex())][1]
        return {
            "name": self.name_edit.text().strip(),
            "period": self.period_spin.value() if self.period_spin else 2,
            "duty": duty,
        }


class DocSettingsDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document Settings")
        self.setModal(True)
        form = QFormLayout(self)
        self.slot_width = QSpinBox()
        self.slot_width.setRange(1, 400)
        self.slot_width.setValue(doc.slot_width)
        self.slots = QSpinBox()
        self.slots.setRange(2, 600)
        self.slots.setValue(doc.slots)
        self.height = QSpinBox()
        self.height.setRange(4, 200)
        self.height.setValue(doc.signal_height)
        self.name_width = QSpinBox()
        self.name_width.setRange(20, 600)
        self.name_width.setValue(doc.name_width)
        form.addRow("Slot width (px):", self.slot_width)
        form.addRow("Visible slots:", self.slots)
        form.addRow("Signal height (px):", self.height)
        form.addRow("Name column (px):", self.name_width)
        self.info = QLabel()
        form.addRow(self.info)
        self.slot_width.valueChanged.connect(self._update_info)
        self.slots.valueChanged.connect(self._update_info)
        self._update_info()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_info(self):
        self.info.setText(f"Waveform width: {self.slot_width.value() * self.slots.value()} px")

    def values(self) -> dict:
        return {
            "slot_width": self.slot_width.value(),
            "slots": self.slots.value(),
            "signal_height": self.height.value(),
            "name_width": self.name_width.value(),
        }


class AnnotationsDialog(QDialog):
    """List and delete labels, arrows and time breaks."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc.clone()
        self.changed = False
        self.setWindowTitle("Annotations")
        self.resize(600, 440)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.label_list = QListWidget()
        self.arrow_list = QListWidget()
        self.measure_list = QListWidget()
        self.break_list = QListWidget()
        tabs.addTab(self._make_tab(self.label_list, self._delete_labels), "Labels")
        tabs.addTab(self._make_tab(self.arrow_list, self._delete_arrows), "Arrows")
        tabs.addTab(self._make_measure_tab(), "Measurements")
        tabs.addTab(self._make_tab(self.break_list, self._delete_breaks), "Time Breaks")
        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _make_tab(self, listw: QListWidget, slot) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(listw, 1)
        btn = QPushButton("Delete Selected")
        btn.clicked.connect(slot)
        v.addWidget(btn)
        return w

    def _make_measure_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self.measure_list, 1)
        row = QHBoxLayout()
        edit = QPushButton("Edit Text...")
        edit.clicked.connect(self._edit_measure)
        color = QPushButton("Color...")
        color.clicked.connect(self._color_measure)
        delete = QPushButton("Delete Selected")
        delete.clicked.connect(self._delete_measure)
        row.addWidget(edit)
        row.addWidget(color)
        row.addWidget(delete)
        v.addLayout(row)
        return w

    def _refresh(self):
        self.label_list.clear()
        for label in self.doc.labels:
            self.label_list.addItem(
                f"{label.text!r}   owner={label.owner or 'free'}   @({label.x1},{label.y1})")
        self.arrow_list.clear()
        for arrow in self.doc.arrows:
            self.arrow_list.addItem(
                f"{arrow.src_signal}[{arrow.src_cycle}] -> "
                f"{arrow.dst_signal}[{arrow.dst_cycle}]   type {arrow.kind}")
        self.measure_list.clear()
        for measurement in self.doc.measurements:
            label = f"{measurement.text} {measurement.suffix}".strip()
            self.measure_list.addItem(
                f"{label!r}   {measurement.src_signal}"
                f"[{measurement.src_cycle}] -> {measurement.dst_signal}"
                f"[{measurement.dst_cycle}]")
        self.break_list.clear()
        for tb in self.doc.timebreaks:
            self.break_list.addItem(f"cycle {tb.cycle}   @ {tb.signal}")

    def _deleted(self):
        self.changed = True
        self.doc.touch()
        self._refresh()

    def _delete_labels(self):
        row = self.label_list.currentRow()
        if 0 <= row < len(self.doc.labels):
            del self.doc.labels[row]
            self.label_list.setCurrentRow(min(row, len(self.doc.labels) - 1))
            self._deleted()

    def _delete_arrows(self):
        row = self.arrow_list.currentRow()
        if 0 <= row < len(self.doc.arrows):
            del self.doc.arrows[row]
            self.arrow_list.setCurrentRow(min(row, len(self.doc.arrows) - 1))
            self._deleted()

    def _delete_breaks(self):
        row = self.break_list.currentRow()
        if 0 <= row < len(self.doc.timebreaks):
            del self.doc.timebreaks[row]
            self.break_list.setCurrentRow(min(row, len(self.doc.timebreaks) - 1))
            self._deleted()

    def _edit_measure(self):
        row = self.measure_list.currentRow()
        if not 0 <= row < len(self.doc.measurements):
            return
        measurement = self.doc.measurements[row]
        result = MeasurementDialog.ask(self, measurement.text,
                                       measurement.suffix)
        if result is None:
            return
        text, suffix = result
        if (text, suffix) != (measurement.text, measurement.suffix):
            measurement.text = text
            measurement.suffix = suffix
            self._deleted()

    def _color_measure(self):
        row = self.measure_list.currentRow()
        if not 0 <= row < len(self.doc.measurements):
            return
        measurement = self.doc.measurements[row]
        from PyQt6.QtGui import QColor

        color = QColorDialog.getColor(QColor(measurement.color or "#000000"),
                                      self, "Measurement Color")
        if color.isValid() and color.name() != (measurement.color or "#000000"):
            measurement.color = color.name()
            self._deleted()

    def _delete_measure(self):
        row = self.measure_list.currentRow()
        if 0 <= row < len(self.doc.measurements):
            del self.doc.measurements[row]
            self.measure_list.setCurrentRow(
                min(row, len(self.doc.measurements) - 1))
            self._deleted()


class BusValueDialog(QDialog):
    """Edit the text shown inside a bus segment.

    ``Content`` is the displayed text (free manual entry).  ``Format`` can
    generate a width/base literal such as ``2b'11``, ``8d'10`` or ``8h'1a``
    from ``Width`` and ``Value``.
    """

    FORMATS = (("Manual", ""), ("Binary", "b"),
               ("Decimal", "d"), ("Hex", "h"))

    def __init__(self, parent=None, text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Bus Value")
        self._result = text
        self._literal = re.compile(r"^(\d+)([bdh])'([0-9a-fA-F]+)$")
        form = QFormLayout(self)
        self.content_edit = QLineEdit(text)
        self.format_combo = QComboBox()
        for label, value in self.FORMATS:
            self.format_combo.addItem(label, value)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 64)
        self.width_spin.setValue(8)
        self.value_edit = QLineEdit()
        form.addRow("Content:", self.content_edit)
        form.addRow("Format:", self.format_combo)
        form.addRow("Width:", self.width_spin)
        form.addRow("Value:", self.value_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.format_combo.currentIndexChanged.connect(self._update_enabled)
        self._update_enabled()
        self._parse_literal(text)

    def _update_enabled(self) -> None:
        manual = self.format_combo.currentData() == ""
        self.width_spin.setEnabled(not manual)
        self.value_edit.setEnabled(not manual)

    def _parse_literal(self, text: str) -> None:
        match = self._literal.match(text.strip())
        if match is None:
            return
        width, base, value = match.groups()
        index = self.format_combo.findData(base)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
            self.width_spin.setValue(max(1, min(64, int(width))))
            self.value_edit.setText(value)
            self._update_enabled()

    def _formatted(self) -> str | None:
        base = self.format_combo.currentData()
        if not base:
            return self.content_edit.text().strip()
        value = self.value_edit.text().strip()
        if not value:
            return self.content_edit.text().strip()
        if base == "b" and any(ch not in "01" for ch in value):
            QMessageBox.warning(self, "Bus Value",
                                "Binary value must contain only 0 and 1.")
            return None
        if base == "d" and not value.isdigit():
            QMessageBox.warning(self, "Bus Value",
                                "Decimal value must contain digits only.")
            return None
        if base == "h" and any(ch not in "0123456789abcdefABCDEF" for ch in value):
            QMessageBox.warning(self, "Bus Value",
                                "Hex value must contain 0-9/a-f only.")
            return None
        return f"{self.width_spin.value()}{base}'{value.lower()}"

    def accept(self) -> None:
        text = self._formatted()
        if text is None:
            return
        self._result = text
        super().accept()

    def result_text(self) -> str:
        return self._result

    @classmethod
    def ask(cls, parent, text: str = "") -> str | None:
        dialog = cls(parent, text)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_text()
        return None


class MeasurementDialog(QDialog):
    """Edit a measurement's text and unit suffix."""

    SUFFIXES = (("none", ""), ("ns", "ns"), ("µs", "µs"), ("ms", "ms"))

    def __init__(self, parent=None, text: str = "", suffix: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Measurement")
        form = QFormLayout(self)
        self.text_edit = QLineEdit(text)
        self.suffix_combo = QComboBox()
        for label, value in self.SUFFIXES:
            self.suffix_combo.addItem(label, value)
        index = self.suffix_combo.findData(suffix)
        self.suffix_combo.setCurrentIndex(max(0, index))
        form.addRow("Text:", self.text_edit)
        form.addRow("Suffix:", self.suffix_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str]:
        return self.text_edit.text().strip(), self.suffix_combo.currentData()

    @classmethod
    def ask(cls, parent, text: str = "",
            suffix: str = "") -> tuple[str, str] | None:
        dialog = cls(parent, text, suffix)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.values()
        return None


class ArrowDialog(QDialog):
    """Precise editor for an arrow's endpoints and bend offset."""

    def __init__(self, doc, index: int, parent=None):
        super().__init__(parent)
        from .renderer import ARROW_STYLE_NAMES, arrow_offset
        if not (0 <= index < len(doc.arrows)):
            raise ValueError("invalid arrow index")
        self.doc = doc
        self.index = index
        arrow = doc.arrows[index]
        self.setWindowTitle(f"Edit Arrow {index}")
        self.setModal(True)
        form = QFormLayout(self)
        names = [r.name for r in doc.rows if r.kind != "separator"]
        for name in (arrow.src_signal, arrow.dst_signal):
            if name not in names:
                names.append(name)

        self.src_combo = QComboBox()
        self.src_combo.addItems(names)
        if arrow.src_signal in names:
            self.src_combo.setCurrentText(arrow.src_signal)
        self.src_cycle = QSpinBox()
        self.src_cycle.setRange(0, max(0, doc.slots))
        self.src_cycle.setValue(max(0, min(doc.slots, arrow.src_cycle)))

        self.dst_combo = QComboBox()
        self.dst_combo.addItems(names)
        if arrow.dst_signal in names:
            self.dst_combo.setCurrentText(arrow.dst_signal)
        self.dst_cycle = QSpinBox()
        self.dst_cycle.setRange(0, max(0, doc.slots))
        self.dst_cycle.setValue(max(0, min(doc.slots, arrow.dst_cycle)))

        self.style_combo = QComboBox()
        for kind, name in sorted(ARROW_STYLE_NAMES.items()):
            self.style_combo.addItem(f"{kind} — {name}", kind)
        if arrow.kind not in ARROW_STYLE_NAMES:
            self.style_combo.addItem(f"{arrow.kind} — Type {arrow.kind} (Bezier)", arrow.kind)
        idx = self.style_combo.findData(arrow.kind)
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(-999, 999)
        self.offset_spin.setValue(int(round(arrow_offset(arrow))))

        form.addRow("Source signal:", self.src_combo)
        self.src_info = QLabel()
        self.dst_info = QLabel()
        form.addRow("Source cycle/edge:", self.src_cycle)
        form.addRow("", self.src_info)
        form.addRow("Destination signal:", self.dst_combo)
        form.addRow("Destination cycle/edge:", self.dst_cycle)
        form.addRow("", self.dst_info)
        form.addRow("Arrow style:", self.style_combo)
        form.addRow("Bend offset:", self.offset_spin)
        form.addRow(QLabel("Tip: you can also drag the arrow ends/handle on the canvas."))
        self.src_combo.currentTextChanged.connect(self._update_edge_info)
        self.dst_combo.currentTextChanged.connect(self._update_edge_info)
        self.src_cycle.valueChanged.connect(self._update_edge_info)
        self.dst_cycle.valueChanged.connect(self._update_edge_info)
        self._update_edge_info()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _edge_label(self, signal: str, cycle: int) -> str:
        ri = self.doc.find_row(signal)
        if ri < 0:
            return ""
        kind = self.doc.edge_kind(ri, cycle)
        if kind == "rising":
            return f"cycle {cycle}: rising edge (0 → 1)"
        if kind == "falling":
            return f"cycle {cycle}: falling edge (1 → 0)"
        if kind == "edge":
            return f"cycle {cycle}: signal/bus transition"
        return f"cycle {cycle}: no signal edge (grid boundary)"

    def _update_edge_info(self):
        if hasattr(self, "src_info"):
            self.src_info.setText(
                self._edge_label(self.src_combo.currentText(), self.src_cycle.value()))
            self.dst_info.setText(
                self._edge_label(self.dst_combo.currentText(), self.dst_cycle.value()))

    def values(self) -> dict:
        return {
            "src_signal": self.src_combo.currentText(),
            "src_cycle": self.src_cycle.value(),
            "dst_signal": self.dst_combo.currentText(),
            "dst_cycle": self.dst_cycle.value(),
            "kind": int(self.style_combo.currentData()),
            "offset": self.offset_spin.value(),
        }



class RowPropertiesDialog(QDialog):
    """Per-row properties: name, edge style, and clock parameters."""

    def __init__(self, doc, index: int, parent=None):
        super().__init__(parent)
        if not (0 <= index < len(doc.rows)):
            raise ValueError("invalid row index")
        self.doc = doc
        self.index = index
        row = doc.rows[index]
        self.setWindowTitle(
            "Clock Properties" if row.kind == "clock"
            else "Signal Properties" if row.kind == "data"
            else "Row Properties")
        self.setModal(True)
        form = QFormLayout(self)

        self.name_edit = QLineEdit(row.name)
        form.addRow("Name:", self.name_edit)

        self.edge_combo = None
        self.edge_width = None
        is_bus = row.kind == "data" and doc.is_bus(row)
        if row.kind in ("data", "clock") and not is_bus:
            self.edge_combo = QComboBox()
            self.edge_combo.addItem("Vertical (ideal)", "ideal")
            self.edge_combo.addItem("Slanted (non-ideal)", "slanted")
            idx = self.edge_combo.findData(row.edge_style)
            self.edge_combo.setCurrentIndex(max(0, idx))
            self.edge_width = QSpinBox()
            self.edge_width.setRange(0, 40)
            self.edge_width.setValue(int(round(row.edge_width)))
            self.edge_width.setSuffix(" px")
            form.addRow("Transition edge:", self.edge_combo)
            form.addRow("Slant width:", self.edge_width)

        self.period_spin = None
        self.duty_combo = None
        self.start_low = None
        if row.kind == "clock":
            self.period_spin = QSpinBox()
            self.period_spin.setRange(2, max(2, min(64, doc.slots)))
            self.period_spin.setValue(max(2, min(64, int(row.clock_period))))
            self.duty_combo = QComboBox()
            best = 0
            best_delta = 1e9
            for i, (label, duty) in enumerate(DUTY_CHOICES):
                self.duty_combo.addItem(label)
                if abs(duty - row.clock_duty) < best_delta:
                    best, best_delta = i, abs(duty - row.clock_duty)
            self.duty_combo.setCurrentIndex(best)
            self.start_low = QCheckBox("Start with low level")
            self.start_low.setChecked(bool(row.clock_start_low))
            form.addRow("Clock period (slots):", self.period_spin)
            form.addRow("Duty cycle:", self.duty_combo)
            form.addRow("", self.start_low)
            form.addRow(QLabel("Applying clock properties regenerates the clock waveform."))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        duty = 0.5
        if self.duty_combo is not None:
            duty = DUTY_CHOICES[max(0, self.duty_combo.currentIndex())][1]
        return {
            "name": self.name_edit.text().strip(),
            "edge_style": self.edge_combo.currentData() if self.edge_combo else "ideal",
            "edge_width": self.edge_width.value() if self.edge_width else 6,
            "clock_period": self.period_spin.value() if self.period_spin else 2,
            "clock_duty": duty,
            "clock_start_low": self.start_low.isChecked() if self.start_low else True,
        }
