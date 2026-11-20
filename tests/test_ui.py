"""Headless UI smoke tests."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgeweaver.mainwindow import MainWindow  # noqa: E402
from edgeweaver.tim_format import load_tim  # noqa: E402

SAMPLES = Path(os.environ.get(
    "EDGEWEAVER_SAMPLES", str(ROOT / "samples")))


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        if not (SAMPLES / "2-3-2.tim").exists():
            raise unittest.SkipTest("samples not available")
        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.app.processEvents()

    def tearDown(self):
        self.win.undo_stack.clear()
        self.win.doc.dirty = False
        self.win.close()

    def test_open_edit_undo_save(self):
        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "copy.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            self.assertEqual(len(self.win.doc.rows), 3)
            self.assertEqual(self.win.canvas.width(), 741)
            self.assertEqual(self.win.canvas.height(), 176)

            before = self.win.doc.clone()
            self.win.doc.set_cells(0, 0, 2, "1")
            self.win.push_edit("test", before, self.win.doc.clone())
            self.assertEqual(self.win.doc.rows[0].state[:3], "111")
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.rows[0].state[:3], "000")
            self.win.undo_stack.redo()
            self.assertEqual(self.win.doc.rows[0].state[:3], "111")

            # saving through the window must stay byte-identical when untouched
            self.win.doc.dirty = False   # avoid the modal save prompt in headless mode
            self.win.open_document(str(copy))
            self.assertTrue(self.win.save_document())
            self.assertEqual(src.read_bytes(), copy.read_bytes())


    def test_arrow_select_drag_delete(self):
        from edgeweaver.renderer import arrow_geometry, arrow_offset

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "arrows.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            geom = arrow_geometry(doc, doc.arrows[0])
            self.assertIsNotNone(geom)

            def point(x, y):
                return QPoint(int(x * canvas.zoom), int(y * canvas.zoom))

            # click the bend handle to select
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point(*geom.bend))
            self.assertEqual(canvas.selected_arrow, 0)

            # drag the bend up; offset must change and enter the undo stack
            old_offset = arrow_offset(doc.arrows[0])
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point(*geom.bend))
            QTest.mouseMove(canvas, point(geom.bend[0], geom.bend[1] - 20))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                               pos=point(geom.bend[0], geom.bend[1] - 20))
            self.assertNotEqual(arrow_offset(self.win.doc.arrows[0]), old_offset)
            self.assertEqual(self.win.undo_stack.undoText(), "Edit arrow")
            self.win.undo_stack.undo()
            self.assertEqual(arrow_offset(self.win.doc.arrows[0]), old_offset)

            # drag the source endpoint to another signal/slot
            geom = arrow_geometry(self.win.doc, self.win.doc.arrows[0])
            target_x = self.win.doc.cycle_to_x(6)
            target_y = self.win.doc.row_top(0) + self.win.doc.signal_height / 2
            canvas.selected_arrow = 0
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point(*geom.src))
            QTest.mouseMove(canvas, point(target_x, target_y))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                               pos=point(target_x, target_y))
            self.assertEqual(self.win.doc.arrows[0].src_signal,
                             self.win.doc.rows[0].name)
            self.assertEqual(self.win.doc.arrows[0].src_cycle, 6)
            self.win.undo_stack.undo()

            # Delete removes the selected arrow; undo restores it
            count = len(self.win.doc.arrows)
            canvas.selected_arrow = 0
            QTest.keyClick(canvas, Qt.Key.Key_Delete)
            self.assertEqual(len(self.win.doc.arrows), count - 1)
            self.assertEqual(self.win.undo_stack.undoText(), "Delete arrow")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.arrows), count)


    def test_arrow_keyboard_pixel_nudge(self):
        from edgeweaver.model import arrow_pixel_offset
        from edgeweaver.renderer import arrow_geometry

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "nudge.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            canvas.selected_arrow = 0
            canvas.setFocus()

            def src():
                # Undo/redo and push_edit replace the document object, so
                # always read the current one.
                doc = self.win.doc
                return arrow_geometry(doc, doc.arrows[0]).src

            start = src()

            QTest.keyClick(canvas, Qt.Key.Key_Right)
            self.app.processEvents()
            moved = src()
            self.assertAlmostEqual(moved[0] - start[0], 1.0)
            self.assertAlmostEqual(moved[1] - start[1], 0.0)

            QTest.keyClick(canvas, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
            self.app.processEvents()
            moved = src()
            self.assertAlmostEqual(moved[0] - start[0], 1.0)
            self.assertAlmostEqual(moved[1] - start[1], -10.0)
            self.assertEqual(arrow_pixel_offset(self.win.doc.arrows[0]),
                             (1.0, -10.0))
            self.assertEqual(self.win.undo_stack.undoText(), "Nudge arrow")

            # the offset survives a save/reload cycle
            self.assertTrue(self.win.save_document())
            back = load_tim(copy)
            self.assertEqual(arrow_pixel_offset(back.arrows[0]), (1.0, -10.0))
            self.assertAlmostEqual(arrow_geometry(back, back.arrows[0]).src[1],
                                   start[1] - 10.0)

            # both nudges are undoable
            self.win.undo_stack.undo()
            self.win.undo_stack.undo()
            self.assertEqual(arrow_pixel_offset(self.win.doc.arrows[0]),
                             (0.0, 0.0))

    def test_selection_context_levels(self):
        from edgeweaver.renderer import Selection

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "levels.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas

            cases = [("1", 0, 3), ("0", 17, 19), ("Z", 5, 7), ("4", 8, 10)]
            for char, start, end in cases:
                canvas.selection = Selection(0, start, end)
                canvas.apply_selection_char(char)
                self.assertEqual(self.win.doc.rows[0].state[start:end + 1],
                                 char * (end - start + 1))
                self.assertEqual(self.win.undo_stack.undoText(),
                                 "Set selection")
                self.win.undo_stack.undo()

    def test_add_analog_row(self):
        from unittest.mock import patch

        from edgeweaver.dialogs import AnalogDialog

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "analog.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            count = len(self.win.doc.rows)
            with patch.object(AnalogDialog, "ask", return_value={
                    "name": "ADC", "samples": [0.0, 1.0, 0.5],
                    "min": 0.0, "max": 1.0}):
                self.win.add_analog_row()
            row = self.win.doc.rows[-1]
            self.assertEqual(len(self.win.doc.rows), count + 1)
            self.assertEqual(row.kind, "analog")
            self.assertEqual(row.samples, [0.0, 1.0, 0.5])
            self.assertEqual(self.win.undo_stack.undoText(), "Add analog")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.rows), count)

    def test_analog_random_selection_and_digital(self):
        from edgeweaver.model import DATA_TAIL, Row
        from edgeweaver.renderer import Selection

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "analog_random.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            doc = self.win.doc
            slots = doc.slots
            row = Row("ADC", "analog", "A" * slots + "0" * (600 - slots),
                      DATA_TAIL)
            row.samples = [0.5] * slots
            row.sample_min = 0.0
            row.sample_max = 1.0
            index = doc.add_row(row)
            canvas = self.win.canvas
            canvas.selection = Selection(index, 2, 5)
            canvas.fill_analog_random(index, 2, 5)
            row = self.win.doc.rows[index]
            self.assertEqual(row.state[2:6], "AAAA")
            self.assertTrue(all(0.0 <= value <= 1.0 for value in row.samples[2:6]))
            self.assertTrue(any(abs(value - 0.5) > 1e-9
                                for value in row.samples[2:6]))
            self.assertEqual(self.win.undo_stack.undoText(), "Random analog")

            canvas.selection = Selection(index, 2, 5)
            canvas.apply_selection_char("0")
            self.assertEqual(self.win.doc.rows[index].state[2:6], "0000")
            self.assertEqual(self.win.undo_stack.undoText(), "Set selection")

    def test_bus_transition_edge_style(self):
        from edgeweaver.dialogs import RowPropertiesDialog

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "bus_edge.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            bus_index = next(i for i, row in enumerate(self.win.doc.rows)
                             if self.win.doc.is_bus(row))
            self.win.doc.rows[bus_index].edge_width = 0
            self.win.set_row_edge_style(bus_index, "slanted")
            self.assertEqual(self.win.doc.rows[bus_index].edge_width, 6.0)
            self.assertEqual(self.win.doc.rows[bus_index].edge_style, "slanted")
            self.assertEqual(self.win.undo_stack.undoText(), "Transition edge")
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.rows[bus_index].edge_style, "ideal")

            dialog = RowPropertiesDialog(self.win.doc, bus_index)
            self.assertIsNotNone(dialog.edge_combo)
            dialog.deleteLater()

    def test_bus_value_double_click_and_selection(self):
        from unittest.mock import patch

        from edgeweaver.dialogs import BusValueDialog
        from edgeweaver.renderer import Selection

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "bus_values.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            bus_index = next(i for i, row in enumerate(doc.rows)
                             if doc.is_bus(row))
            bus_name = doc.rows[bus_index].name

            slot = 20
            x = doc.slot_to_x(slot) + 5
            y = doc.row_top(bus_index) + doc.signal_height / 2
            with patch.object(BusValueDialog, "ask", return_value="8h'1a"):
                QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton,
                                  pos=QPoint(int(x), int(y)))
            values = self.win.doc.bus_values
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0].row, bus_name)
            self.assertEqual(values[0].text, "8h'1a")
            self.assertEqual(self.win.undo_stack.undoText(), "Edit bus value")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.bus_values), 0)

            canvas.selection = Selection(bus_index, 18, 20)
            with patch.object(BusValueDialog, "ask", return_value="2b'11"):
                canvas._edit_bus_value(bus_name, 18, 21, "4")
            self.assertEqual(self.win.doc.bus_values[0].text, "2b'11")
            self.assertEqual(self.win.undo_stack.undoText(), "Edit bus value")
            canvas._clear_bus_value(bus_name, 18, 21)
            self.assertEqual(len(self.win.doc.bus_values), 0)
            self.assertEqual(self.win.undo_stack.undoText(), "Clear bus value")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.bus_values), 1)

    def test_measure_tool_creates_measurement(self):
        from unittest.mock import patch

        from edgeweaver.dialogs import MeasurementDialog

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "measure.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            self.win.set_tool("measure")

            with patch.object(MeasurementDialog, "ask",
                              return_value=("建立时间 = 5", "ns")):
                a = QPoint(int(doc.cycle_to_x(3)),
                           int(doc.row_top(0) + doc.signal_height / 2))
                b = QPoint(int(doc.cycle_to_x(6)),
                           int(doc.row_top(1) + doc.signal_height / 2))
                QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=a)
                QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=b)

            measurements = self.win.doc.measurements
            self.assertEqual(len(measurements), 1)
            self.assertEqual(measurements[0].src_signal, doc.rows[0].name)
            self.assertEqual(measurements[0].src_cycle, 3)
            self.assertEqual(measurements[0].dst_signal, doc.rows[1].name)
            self.assertEqual(measurements[0].dst_cycle, 6)
            self.assertEqual(measurements[0].text, "建立时间 = 5")
            self.assertEqual(measurements[0].suffix, "ns")
            self.assertEqual(self.win.undo_stack.undoText(), "Add measurement")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.measurements), 0)

    def test_measurement_select_and_delete(self):
        from edgeweaver.model import Measurement

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "measure_select.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            doc.arrows.clear()
            doc.add_measurement(Measurement("CEB", 3, "MC", 7, "t = 5 ns"))
            canvas.update()

            x = (doc.cycle_to_x(3) + doc.cycle_to_x(7)) / 2.0
            y = (doc.row_top(0) + doc.row_top(1) + doc.signal_height) / 2.0
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=QPoint(int(x), int(y)))
            self.assertEqual(canvas.selected_measurement, 0)

            QTest.keyClick(canvas, Qt.Key.Key_Delete)
            self.assertEqual(len(self.win.doc.measurements), 0)
            self.assertEqual(self.win.undo_stack.undoText(),
                             "Delete measurement")
            self.win.undo_stack.undo()
            self.assertEqual(len(self.win.doc.measurements), 1)

    def test_measurement_height_drag_keyboard_color(self):
        from unittest.mock import patch

        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog

        from edgeweaver.model import Measurement
        from edgeweaver.renderer import measurement_geometry

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "measure_move.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            doc.arrows.clear()
            doc.add_measurement(Measurement("CEB", 3, "MC", 7, "t"))
            canvas.update()

            cx = (doc.cycle_to_x(3) + doc.cycle_to_x(7)) / 2.0
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=QPoint(int(cx), 50))
            self.assertEqual(canvas.selected_measurement, 0)

            QTest.keyClick(canvas, Qt.Key.Key_Up)
            self.assertEqual(self.win.doc.measurements[0].y, 49)
            self.assertEqual(self.win.undo_stack.undoText(), "Nudge measurement")
            QTest.keyClick(canvas, Qt.Key.Key_Up,
                           Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(self.win.doc.measurements[0].y, 39)
            QTest.keyClick(canvas, Qt.Key.Key_Right)
            self.assertEqual(self.win.doc.measurements[0].dx, 1.0)
            # raise it above the signal rows: the guide lines grow upward
            QTest.keyClick(canvas, Qt.Key.Key_Up,
                           Qt.KeyboardModifier.ShiftModifier)
            QTest.keyClick(canvas, Qt.Key.Key_Up,
                           Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(self.win.doc.measurements[0].y, 19)

            geom = measurement_geometry(self.win.doc,
                                        self.win.doc.measurements[0])
            self.assertEqual(geom.top, 19)
            self.assertEqual(geom.bottom,
                             self.win.doc.row_top(1) + self.win.doc.signal_height)

            # drag the dimension line down by 40 px
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                             pos=QPoint(int(cx) + 1, 19))
            QTest.mouseMove(canvas, QPoint(int(cx) + 1, 59))
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                               pos=QPoint(int(cx) + 1, 59))
            self.assertEqual(self.win.doc.measurements[0].y, 59)
            self.assertEqual(self.win.undo_stack.undoText(), "Move measurement")
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.measurements[0].y, 19)

            with patch.object(QColorDialog, "getColor",
                              return_value=QColor("#c00000")):
                canvas._choose_measure_color(0)
            self.assertEqual(self.win.doc.measurements[0].color, "#c00000")
            self.assertEqual(self.win.undo_stack.undoText(), "Measurement color")

    def test_arrow_snaps_to_signal_edges(self):
        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "edges.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            self.assertEqual(canvas._snap_arrow_cycle(0, doc.cycle_to_x(17) + 3),
                             (17, "rising"))
            self.assertEqual(canvas._snap_arrow_cycle(0, doc.cycle_to_x(11))[1],
                             "grid")

            def point(x, y):
                return QPoint(int(x), int(y))

            count = len(doc.arrows)
            self.win.set_tool("arrow")
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=point(doc.cycle_to_x(17) + 2, doc.row_top(0) + 5))
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=point(doc.cycle_to_x(4) + 2, doc.row_top(2) + 5))
            self.assertEqual(len(self.win.doc.arrows), count + 1)
            arrow = self.win.doc.arrows[-1]
            self.assertEqual((arrow.src_signal, arrow.src_cycle),
                             (doc.rows[0].name, 17))
            self.assertEqual((arrow.dst_signal, arrow.dst_cycle),
                             (doc.rows[2].name, 4))


    def test_clock_cycles_spin(self):
        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "cycles.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            self.assertEqual(self.win.cycles_spin.value(), 11)
            self.win.cycles_spin.setValue(20)
            self.assertEqual(self.win.doc.slots, 40)
            self.assertIn("1", self.win.doc.rows[1].state[22:40])
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.slots, 22)
            self.assertEqual(self.win.cycles_spin.value(), 11)

    def test_z_tool(self):
        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "z.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            canvas = self.win.canvas
            doc = self.win.doc
            old = doc.rows[0].state[0]
            self.win.set_tool("z")
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=QPoint(int(doc.slot_to_x(0) + 5),
                                        int(doc.row_top(0) + 5)))
            self.assertEqual(self.win.doc.rows[0].state[0], "Z")
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.rows[0].state[0], old)

    def test_row_properties_wiring(self):
        from PyQt6.QtWidgets import QDialog
        import edgeweaver.mainwindow as mw

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "props.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            self.assertEqual(self.win.doc.rows[0].edge_style, "ideal")

            class FakeDialog:
                def __init__(self, *args, **kwargs):
                    pass

                def exec(self):
                    return QDialog.DialogCode.Accepted

                def values(self):
                    return {"name": "CEB", "edge_style": "slanted",
                            "edge_width": 8, "clock_period": 2,
                            "clock_duty": 0.5, "clock_start_low": True}

            old = mw.RowPropertiesDialog
            mw.RowPropertiesDialog = FakeDialog
            try:
                self.win.edit_row_properties(0)
            finally:
                mw.RowPropertiesDialog = old
            self.assertEqual(self.win.doc.rows[0].edge_style, "slanted")
            self.assertEqual(self.win.doc.rows[0].edge_width, 8)
            self.win.undo_stack.undo()
            self.assertEqual(self.win.doc.rows[0].edge_style, "ideal")

    def test_row_properties_dialog_values(self):
        from edgeweaver.dialogs import RowPropertiesDialog

        src = SAMPLES / "2-3-2.tim"
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "dialog.tim"
            shutil.copyfile(src, copy)
            self.win.open_document(str(copy))
            dialog = RowPropertiesDialog(self.win.doc, 1)
            values = dialog.values()
            self.assertEqual(values["name"], "MC")
            self.assertEqual(values["edge_style"], "ideal")
            self.assertEqual(values["clock_period"], 2)
            self.assertEqual(values["clock_duty"], 0.5)
            self.assertTrue(values["clock_start_low"])

    def test_add_row_and_settings(self):
        # modal dialogs are not exercised headless; exercise the model path
        before = self.win.doc.clone()
        from edgeweaver.model import Row
        idx = self.win.doc.add_row(Row("S2", "data", "0" * 600))
        self.win.push_edit("add", before, self.win.doc.clone())
        self.assertEqual(len(self.win.doc.rows), 4)
        self.win.undo_stack.undo()
        self.assertEqual(len(self.win.doc.rows), 3)

        before = self.win.doc.clone()
        self.win.doc.slots = 40
        self.win.doc.touch()
        self.win.push_edit("settings", before, self.win.doc.clone())
        self.assertEqual(self.win.doc.slots, 40)
        self.assertEqual(self.win.canvas.width(), self.win.doc.wave_x0 + 40 * self.win.doc.slot_width + 24)


if __name__ == "__main__":
    unittest.main()
