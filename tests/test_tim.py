"""Format regression tests against the real legacy .tim samples."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edgeweaver.model import (Document, Row, Label, Arrow, TimeBreak,
                            BusValue, Measurement, EDGE_MAGIC)  # noqa: E402
from edgeweaver.tim_format import load_tim, save_tim, dumps_tim  # noqa: E402
from edgeweaver.exporters import export_csv, export_xml, import_csv, import_xml  # noqa: E402

SAMPLES = Path(os.environ.get(
    "EDGEWEAVER_SAMPLES", str(ROOT / "samples")))


def sample_files():
    if not SAMPLES.is_dir():
        raise unittest.SkipTest(f"sample directory not found: {SAMPLES}")
    files = sorted(SAMPLES.glob("*.tim"))
    if not files:
        raise unittest.SkipTest("no .tim samples")
    return files


class TimFormatTests(unittest.TestCase):
    def test_byte_identical_roundtrip(self):
        for path in sample_files():
            with self.subTest(path.name):
                doc = load_tim(path)
                data = dumps_tim(doc)
                self.assertEqual(path.read_bytes(), data)
                # second save after raw list cache is dropped must still match
                doc.raw_lists = None
                self.assertEqual(path.read_bytes(), dumps_tim(doc))

    def test_counts(self):
        expect = {
            "11111111.tim": (4, 0, 0, 0),
            "2-3-1.tim": (4, 7, 5, 3),
            "2-3-2.tim": (3, 5, 4, 3),
            "2-3-4.tim": (4, 5, 0, 0),
        }
        for path in sample_files():
            if path.name not in expect:
                continue
            doc = load_tim(path)
            got = (len(doc.rows), len(doc.labels), len(doc.arrows), len(doc.timebreaks))
            self.assertEqual(got, expect[path.name], path.name)

    def test_row_geometry(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        self.assertEqual(doc.slot_width, 30)
        self.assertEqual(doc.slots, 22)
        self.assertEqual(doc.signal_height, 16)
        self.assertEqual(doc.name_width, 52)
        self.assertEqual(doc.wave_x0, 57)
        self.assertTrue(doc.is_bus(doc.rows[2]))
        self.assertFalse(doc.is_bus(doc.rows[0]))

    def test_edit_and_new_rows_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        doc.set_cells(0, 2, 4, "1")
        doc.add_row(Row("EXTRA", "data", "0" * 600), None)
        doc.add_label(Label(10, 10, 70, 22, "hello", "EWLabel*9*", "     0.Arial.8.0.0.0.0."))
        doc.add_arrow(Arrow(1, "MC", 2, "SDOUT", 2, "0.0.1.0.0.0."))
        doc.add_timebreak(TimeBreak(5, "EXTRA"))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "edited.tim"
            save_tim(doc, out)
            again = load_tim(out)
            self.assertEqual(len(again.rows), 4)
            self.assertEqual(again.rows[0].state[:5], "00111")
            self.assertEqual(len(again.labels), 6)
            self.assertEqual(len(again.arrows), 5)
            self.assertEqual(len(again.timebreaks), 4)
            self.assertEqual(len(again.flood), 4)
            self.assertEqual(len(again.delay), 4)


    def test_edge_snap_model(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        self.assertEqual(doc.row_edges(0), [17])
        self.assertEqual(doc.edge_kind(0, 17), "rising")
        self.assertEqual(doc.cycle_to_x(17), 567.0)
        self.assertEqual(doc.slots, 22)
        self.assertEqual(doc.nearest_edge(0, 570.0), (17, 3.0))
        self.assertEqual(doc.x_to_cycle(doc.cycle_to_x(11)), 11)
        self.assertTrue(doc.row_edges(2))   # SDOUT bus transitions


    def test_edge_marker_and_z_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        row = doc.rows[0]
        row.state = "Z" + row.padded_state()[1:]
        row.edge_style = "slanted"
        row.edge_width = 8
        row.raw = None
        doc.touch()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "marker.tim"
            save_tim(doc, out)
            back = load_tim(out)
            self.assertEqual(back.rows[0].state[0], "Z")
            self.assertEqual(back.rows[0].edge_style, "slanted")
            self.assertEqual(back.rows[0].edge_width, 8.0)
            self.assertEqual(back.delay[0][599], EDGE_MAGIC)
            self.assertEqual(back.delay[0][598], 8)
            back.rows[0].edge_style = "ideal"
            back.rows[0].raw = None
            back.touch()
            out2 = Path(td) / "ideal.tim"
            save_tim(back, out2)
            ideal_back = load_tim(out2)
            self.assertEqual(ideal_back.rows[0].edge_style, "ideal")
            self.assertEqual(ideal_back.delay[0][599], 0)

    def test_clock_regeneration(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        doc.slots = 40
        doc.regenerate_clocks()
        self.assertEqual(doc.slots, 40)
        clock = doc.rows[1]
        self.assertIn("1", clock.state[22:40])
        clock.clock_period = 4
        clock.clock_duty = 0.5
        clock.clock_start_low = True
        doc.regenerate_clocks(1)
        self.assertEqual(clock.state[:8], "00110011")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "clock.tim"
            save_tim(doc, out)
            back = load_tim(out)
            self.assertEqual(back.slots, 40)
            self.assertEqual(back.rows[1].state[:8], "00110011")
            self.assertEqual(back.rows[1].clock_period, 4)
            self.assertEqual(back.rows[1].clock_duty, 0.5)
            self.assertTrue(back.rows[1].clock_start_low)

    def test_new_document_roundtrip(self):
        doc = Document.new()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "new.tim"
            save_tim(doc, out)
            again = load_tim(out)
            self.assertEqual(len(again.rows), 3)
            self.assertEqual(again.rows[0].kind, "clock")
            self.assertEqual(again.rows[1].kind, "data")
            self.assertEqual(again.ints4[:3], [20, 30, 16])

    def test_analog_extension_roundtrip(self):
        doc = Document()
        doc.slots = 4
        doc.rows = [Row("ADC", "analog", "0" * 600, "")]
        row = doc.rows[0]
        row.samples = [0.0, 1.0, 0.5, 0.25]
        row.sample_min = -1.0
        row.sample_max = 3.0
        doc.ensure_arrays()
        doc.touch()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analog.tim"
            save_tim(doc, path)
            back = load_tim(path)
            self.assertEqual(len(back.rows), 1)
            self.assertEqual(back.rows[0].kind, "analog")
            self.assertEqual(back.rows[0].samples, [0.0, 1.0, 0.5, 0.25])
            self.assertEqual(back.rows[0].sample_min, -1.0)
            self.assertEqual(back.rows[0].sample_max, 3.0)
            data = path.read_bytes()
            save_tim(back, path)
            self.assertEqual(path.read_bytes(), data)

    def test_bus_value_extension_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        bus = next(row for row in doc.rows if doc.is_bus(row))
        doc.add_bus_value(BusValue(bus.name, 0, 3, "8h'1a"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bus.tim"
            save_tim(doc, path)
            back = load_tim(path)
            self.assertEqual(len(back.bus_values), 1)
            value = back.bus_values[0]
            self.assertEqual((value.row, value.start, value.end, value.text),
                             (bus.name, 0, 3, "8h'1a"))
            data = path.read_bytes()
            save_tim(back, path)
            self.assertEqual(path.read_bytes(), data)

    def test_measurement_extension_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        doc.add_measurement(Measurement("CEB", 3, "MC", 7,
                                        "建立时间 = 1.5",
                                        12, 2.0, "#c00000", "µs"))
        doc.list3.append("KEEP-ME")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "measure.tim"
            save_tim(doc, path)
            back = load_tim(path)
            self.assertEqual(len(back.measurements), 1)
            measurement = back.measurements[0]
            self.assertEqual((measurement.src_signal, measurement.src_cycle,
                              measurement.dst_signal, measurement.dst_cycle),
                             ("CEB", 3, "MC", 7))
            self.assertEqual(measurement.text, "建立时间 = 1.5")
            self.assertEqual(measurement.suffix, "µs")
            self.assertEqual(measurement.y, 12)
            self.assertEqual(measurement.dx, 2.0)
            self.assertEqual(measurement.color, "#c00000")
            self.assertIn("KEEP-ME", back.list3)
            data = path.read_bytes()
            save_tim(back, path)
            self.assertEqual(path.read_bytes(), data)


class InterchangeTests(unittest.TestCase):
    def test_xml_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-4.tim")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.xml"
            export_xml(doc, path)
            back = import_xml(path)
            self.assertEqual(len(back.rows), len(doc.rows))
            self.assertEqual(back.rows[0].name, doc.rows[0].name)
            self.assertEqual(back.rows[2].state[: doc.slots], doc.rows[2].state[: doc.slots])
            self.assertEqual(len(back.labels), 5)
            self.assertEqual(len(back.timebreaks), 0)

    def test_csv_roundtrip(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.csv"
            export_csv(doc, path)
            back = import_csv(path)
            self.assertEqual(len(back.rows), len(doc.rows))
            self.assertEqual(back.rows[0].name, doc.rows[0].name)
            self.assertEqual(back.rows[0].state[: doc.slots], doc.rows[0].state[: doc.slots])
            self.assertEqual(back.slots, doc.slots)


if __name__ == "__main__":
    unittest.main()
