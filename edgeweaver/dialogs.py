"""Small modal dialogs."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
        self.break_list = QListWidget()
        tabs.addTab(self._make_tab(self.label_list, self._delete_labels), "Labels")
        tabs.addTab(self._make_tab(self.arrow_list, self._delete_arrows), "Arrows")
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
