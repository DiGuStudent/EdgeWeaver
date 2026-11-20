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
