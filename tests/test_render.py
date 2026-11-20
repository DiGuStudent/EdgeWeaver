"""Rendering/export regression tests (headless)."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from edgeweaver.emf_export import export_emf  # noqa: E402
from edgeweaver.exporters import export_pdf, export_png  # noqa: E402
from edgeweaver.svg_export import export_svg  # noqa: E402
from edgeweaver.model import NAME_PAD, Document, Row, make_clock_state  # noqa: E402
from edgeweaver.tim_format import load_tim, save_tim  # noqa: E402
from edgeweaver.renderer import arrow_geometry, digital_segments, wave_level_y  # noqa: E402

SAMPLES = Path(os.environ.get(
    "EDGEWEAVER_SAMPLES", str(ROOT / "samples")))


def sample_files():
    if not SAMPLES.is_dir():
        raise unittest.SkipTest(f"sample directory not found: {SAMPLES}")
    files = sorted(SAMPLES.glob("*.tim"))
    if not files:
        raise unittest.SkipTest("no .tim samples")
    return files


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exports(self):
        for path in sample_files():
            with self.subTest(path.name):
                doc = load_tim(path)
                with tempfile.TemporaryDirectory() as td:
                    png = Path(td) / "out.png"
                    svg = Path(td) / "out.svg"
                    pdf = Path(td) / "out.pdf"
                    emf = Path(td) / "out.emf"
                    export_png(doc, png, 1.0)
                    export_svg(doc, svg)
                    export_pdf(doc, pdf)
                    export_emf(doc, emf)
                    self.assertGreater(png.stat().st_size, 1000)
                    self.assertGreater(svg.stat().st_size, 1000)
                    self.assertGreater(pdf.stat().st_size, 1000)
                    self.assertGreater(emf.stat().st_size, 1000)
                    self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
                    text = svg.read_text(encoding="utf-8")
                    self.assertIn("<svg", text)
                    self.assertIn("<line", text)
                    for row in doc.rows:
                        if row.kind != "separator":
                            self.assertIn(row.name, text)
                    im = QImage(str(png))
                    self.assertGreater(im.width(), 100)
                    self.assertGreater(im.height(), 100)



    def test_svg_transparent_background(self):
        from edgeweaver.renderer import RenderOptions

        doc = load_tim(SAMPLES / "2-3-2.tim")
        with tempfile.TemporaryDirectory() as td:
            opaque = Path(td) / "opaque.svg"
            clear = Path(td) / "clear.svg"
            export_svg(doc, opaque)
            export_svg(doc, clear, RenderOptions(background=False))
            opaque_text = opaque.read_text(encoding="utf-8")
            clear_text = clear.read_text(encoding="utf-8")
        self.assertIn('fill="#ffffff"', opaque_text)
        self.assertNotIn('fill="#ffffff"', clear_text)
        self.assertIn("<svg", clear_text)
        self.assertIn("<line", clear_text)

    def test_measurement_geometry_and_text(self):
        from edgeweaver.model import Measurement
        from edgeweaver.renderer import draw_measurement

        class Backend:
            def __init__(self):
                self.lines = []
                self.polygons = []
                self.texts = []

            def line(self, x1, y1, x2, y2, **kw):
                self.lines.append((x1, y1, x2, y2, kw))

            def polygon(self, points, **kw):
                self.polygons.append((points, kw))

            def text(self, x, y, s, **kw):
                self.texts.append((x, y, s, kw))

        doc = load_tim(SAMPLES / "2-3-2.tim")
        measurement = Measurement("CEB", 3, "MC", 7, "tSU = 5 ns")
        backend = Backend()
        draw_measurement(backend, measurement, doc)

        x1 = doc.cycle_to_x(3)
        x2 = doc.cycle_to_x(7)
        top = min(doc.row_top(0), doc.row_top(1))
        bottom = max(doc.row_top(0), doc.row_top(1)) + doc.signal_height
        mid = (top + bottom) / 2.0

        verticals = [(a, b, c, d, kw) for a, b, c, d, kw in backend.lines
                     if abs(a - c) < 0.01 and abs(b - d) > 10]
        self.assertEqual(len(verticals), 2)
        self.assertTrue(all(kw.get("dash") == "dash" for *_, kw in verticals))
        self.assertTrue(any(
            abs(a - x1) < 0.01 and abs(c - x1) < 0.01
            and abs(b - top) < 0.01 and abs(d - bottom) < 0.01
            for a, b, c, d, _ in backend.lines))
        self.assertTrue(any(
            abs(a - x1) < 0.01 and abs(c - x2) < 0.01
            and abs(b - mid) < 0.01 and abs(d - mid) < 0.01
            for a, b, c, d, _ in backend.lines))
        self.assertEqual(len(backend.polygons), 2)      # double-headed arrow
        # wide interval: tips on the guides, bodies inside -> outward
        left, right = backend.polygons
        self.assertAlmostEqual(left[0][0][0], x1)
        self.assertAlmostEqual(right[0][0][0], x2)
        self.assertGreater(left[0][1][0], x1)           # body inside
        self.assertLess(right[0][1][0], x2)
        self.assertEqual(len(backend.texts), 1)
        self.assertEqual(backend.texts[0][2], "tSU = 5 ns")
        self.assertAlmostEqual(backend.texts[0][0], (x1 + x2) / 2.0)

    def test_measurement_narrow_interval_arrows_outside(self):
        from edgeweaver.model import Measurement
        from edgeweaver.renderer import draw_measurement

        class Backend:
            def __init__(self):
                self.polygons = []

            def line(self, *args, **kwargs):
                pass

            def polygon(self, points, **kw):
                self.polygons.append(points)

            def text(self, *args, **kwargs):
                pass

        doc = load_tim(SAMPLES / "2-3-2.tim")
        # 1 slot wide, with text that does not fit inside
        measurement = Measurement("CEB", 3, "MC", 4, "t = 5 µs")
        backend = Backend()
        draw_measurement(backend, measurement, doc)
        x1 = doc.cycle_to_x(3)
        x2 = doc.cycle_to_x(4)
        left, right = backend.polygons
        self.assertAlmostEqual(left[0][0], x1)
        self.assertAlmostEqual(right[0][0], x2)
        self.assertLess(left[1][0], x1)                 # body outside
        self.assertGreater(right[1][0], x2)

    def test_measurement_height_color_and_dx(self):
        from edgeweaver.model import Measurement
        from edgeweaver.renderer import draw_measurement, measurement_geometry

        class Backend:
            def __init__(self):
                self.lines = []
                self.polygons = []
                self.texts = []

            def line(self, x1, y1, x2, y2, **kw):
                self.lines.append((x1, y1, x2, y2, kw))

            def polygon(self, points, **kw):
                self.polygons.append((points, kw))

            def text(self, x, y, s, **kw):
                self.texts.append((x, y, s, kw))

        doc = load_tim(SAMPLES / "2-3-2.tim")
        measurement = Measurement("CEB", 3, "MC", 7, "t = 5",
                                  y=8, dx=5, color="#c00000", suffix="µs")
        geom = measurement_geometry(doc, measurement)
        self.assertEqual(geom.y, 8)
        self.assertEqual(geom.top, 8)                   # guide grows upward
        self.assertEqual(geom.bottom,
                         doc.row_top(1) + doc.signal_height)
        self.assertAlmostEqual(geom.x1, doc.cycle_to_x(3) + 5)

        backend = Backend()
        draw_measurement(backend, measurement, doc)
        self.assertTrue(backend.lines)
        for *_, kw in backend.lines:
            self.assertEqual(kw.get("color"), "#c00000")
        self.assertEqual(backend.texts[0][2], "t = 5 µs")
        self.assertEqual(backend.texts[0][3].get("color"), "#c00000")
        self.assertAlmostEqual(backend.texts[0][1], 8 - 5)

    def test_arrow_boundary_geometry(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        arrow = doc.arrows[0]
        geom = arrow_geometry(doc, arrow)
        self.assertIsNotNone(geom)
        self.assertEqual(geom.src[0],
                         doc.wave_x0 + arrow.src_cycle * doc.slot_width)
        self.assertEqual(geom.src[0], 147.0)

    def test_arrow_styles(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        expected = ["straight", "angled", "bezier", "floating"]
        with tempfile.TemporaryDirectory() as td:
            for kind, style in enumerate(expected):
                doc.arrows[0].kind = kind
                doc.arrows[0].raw = None
                doc.touch()
                geom = arrow_geometry(doc, doc.arrows[0])
                self.assertIsNotNone(geom)
                self.assertEqual(geom.style, style)
                self.assertGreaterEqual(len(geom.segments), 1)
                png = Path(td) / f"arrow_{kind}.png"
                export_png(doc, png, 1.0)
                self.assertGreater(png.stat().st_size, 1000)
            out = Path(td) / "styles.tim"
            save_tim(doc, out)
            back = load_tim(out)
            self.assertEqual([a.kind for a in back.arrows], [3, 2, 2, 2])


    def test_z_state_and_slanted_edges(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        row = doc.rows[0]
        top = doc.row_top(0)
        mid = top + doc.signal_height / 2
        self.assertEqual(wave_level_y("Z", top, doc.signal_height), mid)
        row.state = "Z" + row.padded_state()[1:]
        row.raw = None
        doc.touch()
        segs = digital_segments(row, doc, top)
        self.assertTrue(any(abs(a[1] - mid) < 0.01 and abs(b[1] - mid) < 0.01
                            for a, b in segs))

        row.state = "0" * 17 + "1" * 5 + row.padded_state()[22:]
        row.edge_style = "ideal"
        row.raw = None
        doc.touch()
        ideal = digital_segments(row, doc, top)
        self.assertFalse(any(abs(a[0] - b[0]) > 1 and abs(a[1] - b[1]) > 1
                             for a, b in ideal))

        row.edge_style = "slanted"
        row.edge_width = 8
        row.raw = None
        doc.touch()
        slanted = digital_segments(row, doc, top)
        self.assertTrue(any(abs(a[0] - b[0]) > 1 and abs(a[1] - b[1]) > 1
                            for a, b in slanted))
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "zslant.png"
            export_png(doc, png, 1.0)
            self.assertGreater(png.stat().st_size, 1000)

    def test_bus_high_z_is_midline(self):
        from edgeweaver.renderer import RenderOptions, draw_bus

        class Backend:
            def __init__(self):
                self.lines = []
                self.texts = []

            def line(self, x1, y1, x2, y2, **kw):
                self.lines.append((x1, y1, x2, y2, kw))

            def text(self, x, y, s, **kw):
                self.texts.append((x, y, s, kw))

        doc = load_tim(SAMPLES / "2-3-2.tim")
        bus_index = next(i for i, r in enumerate(doc.rows) if doc.is_bus(r))
        row = doc.rows[bus_index]
        top = doc.row_top(bus_index)
        h = doc.signal_height
        mid = top + h / 2.0
        row.state = "4" * 5 + "Z" * 5 + "4" * 590
        row.raw = None
        doc.touch()

        b = Backend()
        draw_bus(b, row, doc, top, RenderOptions())
        zx0 = doc.wave_x0 + 5 * doc.slot_width
        zx1 = doc.wave_x0 + 10 * doc.slot_width

        # The high-Z span is one horizontal line at the midpoint.
        self.assertTrue(any(
            abs(x1 - zx0) < 0.01 and abs(x2 - zx1) < 0.01
            and abs(y1 - mid) < 0.01 and abs(y2 - mid) < 0.01
            for x1, y1, x2, y2, _ in b.lines))
        # No bus rails and no value text inside the high-Z span.
        def overlaps_z(x1, x2):
            return max(x1, x2) > zx0 + 0.5 and min(x1, x2) < zx1 - 0.5

        self.assertFalse(any(
            overlaps_z(x1, x2) and abs(y1 - y2) < 0.01
            and (abs(y1 - top) < 0.01 or abs(y1 - (top + h)) < 0.01)
            for x1, y1, x2, y2, _ in b.lines))
        self.assertFalse(any(s == "Z" for _, _, s, _ in b.texts))

    def test_name_waveform_divider_toggle(self):
        from edgeweaver.renderer import RenderOptions, render_document

        class Backend:
            def __init__(self):
                self.lines = []

            def line(self, x1, y1, x2, y2, **kw):
                self.lines.append((x1, y1, x2, y2, kw))

            def rect(self, *args, **kwargs):
                pass

            def polygon(self, *args, **kwargs):
                pass

            def cubic(self, *args, **kwargs):
                pass

            def text(self, *args, **kwargs):
                pass

        doc = load_tim(SAMPLES / "2-3-2.tim")
        divider_x = doc.wave_x0 - NAME_PAD / 2.0

        def drawn(show):
            b = Backend()
            render_document(b, doc, RenderOptions(show_divider=show))
            return any(abs(x1 - divider_x) < 0.01
                       and abs(x2 - divider_x) < 0.01
                       for x1, y1, x2, y2, _ in b.lines)

        self.assertTrue(drawn(True))
        self.assertFalse(drawn(False))

    def test_bus_value_override_text(self):
        from edgeweaver.model import BusValue
        from edgeweaver.renderer import RenderOptions, render_document

        class Backend:
            def __init__(self):
                self.texts = []

            def line(self, *args, **kwargs):
                pass

            def rect(self, *args, **kwargs):
                pass

            def polygon(self, *args, **kwargs):
                pass

            def cubic(self, *args, **kwargs):
                pass

            def text(self, x, y, s, **kw):
                self.texts.append(s)

        doc = load_tim(SAMPLES / "2-3-2.tim")
        bus = next(row for row in doc.rows if doc.is_bus(row))
        doc.bus_values.append(BusValue(bus.name, 0, doc.slots, "8h'1a"))
        backend = Backend()
        render_document(backend, doc, RenderOptions())
        self.assertIn("8h'1a", backend.texts)
        # default single-character bus labels are suppressed by the override
        self.assertFalse(any(text in ("2", "3", "4") for text in backend.texts))

    def test_bus_value_insert_splits_run(self):
        from edgeweaver.model import BusValue, DATA_TAIL, Document, Row
        from edgeweaver.renderer import RenderOptions, render_document

        class Backend:
            def __init__(self):
                self.lines = []
                self.texts = []

            def line(self, x1, y1, x2, y2, **kw):
                self.lines.append((x1, y1, x2, y2, kw))

            def rect(self, *args, **kwargs):
                pass

            def polygon(self, *args, **kwargs):
                pass

            def cubic(self, *args, **kwargs):
                pass

            def text(self, x, y, s, **kw):
                self.texts.append(s)

        doc = Document()
        doc.slots = 12
        doc.slot_width = 30
        doc.name_width = 70
        doc.signal_height = 16
        doc.rows = [Row("BUS", "data", "4" * 12, DATA_TAIL)]
        doc.ensure_arrays()
        doc.bus_values = [BusValue("BUS", 4, 6, "8h'1a")]

        backend = Backend()
        render_document(backend, doc, RenderOptions())
        # original run survives on both sides; inserted text sits in between
        self.assertEqual(backend.texts.count("4"), 2)
        self.assertIn("8h'1a", backend.texts)
        x4 = doc.slot_to_x(4)
        x6 = doc.slot_to_x(6)
        top = doc.row_top(0)
        bottom = top + doc.signal_height
        verticals = [(a, b) for a, b, c, d, _ in backend.lines
                     if abs(a - c) < 0.01 and abs(b - top) < 0.01
                     and abs(d - bottom) < 0.01]
        self.assertTrue(any(abs(x - x4) < 0.01 for x, _ in verticals))
        self.assertTrue(any(abs(x - x6) < 0.01 for x, _ in verticals))

        # an override spanning several runs hides their internal boundaries
        doc.rows[0].state = "223344" + "0" * 6
        doc.rows[0].raw = None
        doc.bus_values = [BusValue("BUS", 1, 5, "16h'abcd")]
        backend = Backend()
        render_document(backend, doc, RenderOptions())
        x2 = doc.slot_to_x(2)
        x4 = doc.slot_to_x(4)
        x1 = doc.slot_to_x(1)
        x5 = doc.slot_to_x(5)
        verticals = [(a, b) for a, b, c, d, _ in backend.lines
                     if abs(a - c) < 0.01 and abs(b - top) < 0.01
                     and abs(d - bottom) < 0.01]
        self.assertFalse(any(abs(x - x2) < 0.01 for x, _ in verticals))
        self.assertFalse(any(abs(x - x4) < 0.01 for x, _ in verticals))
        self.assertTrue(any(abs(x - x1) < 0.01 for x, _ in verticals))
        self.assertTrue(any(abs(x - x5) < 0.01 for x, _ in verticals))

    def test_pixel_geometry_2_3_2(self):
        doc = load_tim(SAMPLES / "2-3-2.tim")
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "out.png"
            export_png(doc, png, 1.0)
            im = QImage(str(png))

            def dark(x, y):
                c = im.pixelColor(int(x), int(y))
                return max(c.red(), c.green(), c.blue()) < 128

            # wave_x0=57, slot_width=30, rows 20/64/108, height 16
            # CEB: slots 0..16 low, 17.. high
            self.assertTrue(dark(72, 36))     # CEB low at slot 0
            self.assertFalse(dark(72, 20))
            self.assertTrue(dark(582, 20))    # CEB high at slot 17
            self.assertFalse(dark(582, 36))
            # MC clock: 000101..., high at slots 3 and 5
            self.assertTrue(dark(162, 64))
            self.assertTrue(dark(222, 64))
            self.assertTrue(dark(102, 80))
            # SDOUT bus rails
            self.assertTrue(dark(72, 108))
            self.assertTrue(dark(72, 124))


EMF_HEADER_FORMAT = "<II4i4iIIIIHHIIIiiii"


def emf_header(data: bytes):
    return struct.unpack_from(EMF_HEADER_FORMAT, data, 0)


def emf_records(data: bytes):
    off = emf_header(data)[1]
    while off < len(data):
        kind, size = struct.unpack_from("<II", data, off)
        yield off, kind, size
        off += size


def emf_texts(data: bytes):
    out = []
    for off, kind, size in emf_records(data):
        if kind != 84:  # EMR_EXTTEXTOUTW
            continue
        # EMRTEXT starts at offset 36: ptlReference(8), nChars(4), offString(4)
        nchars, offstr = struct.unpack_from("<II", data, off + 44)
        out.append(data[off + offstr:off + offstr + nchars * 2].decode("utf-16le"))
    return out


class EmfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _document(self) -> Document:
        doc = Document()
        doc.ints4 = [20, 30, 16, 0]
        doc.ints9 = [80, 5, 30, 0, 0, 0, 0, 0, 0]
        doc.rows = [
            Row("时钟", "clock", make_clock_state(30, 2, 0.5)),
            Row("数据", "data", "0" * 15 + "1" * 15),
        ]
        doc.flood = [[0] * 600 for _ in doc.rows]
        doc.delay = [[0] * 600 for _ in doc.rows]
        return doc

    def test_emf_structure_and_unicode(self):
        doc = self._document()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.emf"
            export_emf(doc, path)
            data = path.read_bytes()
        self.assertEqual(data[:4], b"\x01\x00\x00\x00")
        hdr = emf_header(data)
        self.assertEqual(hdr[0], 1)
        self.assertGreaterEqual(hdr[1], 108)           # ENHMETAHEADER 108 + description
        self.assertEqual(hdr[10], 0x464D4520)          # " EMF"
        self.assertEqual(hdr[11], 0x00010000)          # version 1
        self.assertEqual(hdr[12], len(data))           # nBytes
        self.assertEqual(hdr[17], 108)                 # offDescription follows the header
        self.assertGreater(hdr[16], 0)                 # nDescription is in characters
        desc_bytes = data[108:108 + hdr[16] * 2]
        self.assertEqual(hdr[16], len("EdgeWeaver") + 1)
        self.assertTrue(desc_bytes.decode("utf-16-le").startswith("EdgeWeaver"))
        records = list(emf_records(data))
        # First record starts where the header record says it does.
        self.assertEqual(struct.unpack_from("<I", data, hdr[1])[0], 18)  # SETBKMODE
        self.assertEqual(len(records), hdr[13] - 1)    # excluding the header record
        self.assertEqual(records[-1][1], 14)           # EMF_EOF
        self.assertEqual(records[-1][0] + records[-1][2], len(data))
        with_fonts = 0
        for off, kind, size in records:
            self.assertGreaterEqual(size, 8)
            self.assertEqual(size % 4, 0)
            self.assertLessEqual(off + size, len(data))
            if kind == 37:  # EMR_SELECTOBJECT
                handle = struct.unpack_from("<I", data, off + 8)[0]
                if not handle & 0x80000000:
                    self.assertLess(handle, hdr[14])
            elif kind == 82:  # EMR_EXTCREATEFONTINDIRECTW
                with_fonts += 1
                self.assertEqual(size, 332)            # ihFont + EXTLOGFONTW (320)
            elif kind == 84:  # EMR_EXTTEXTOUTW
                nchars, offstr, offdx = struct.unpack_from(
                    "<III", data, off + 44)
                self.assertEqual(offstr, 76)           # 8 + 16 + 4 + 4 + 4 + 40
                self.assertEqual(offdx, 0)              # no spacing array
                self.assertLessEqual(offstr + nchars * 2, size)
                # EMRTEXT fields are in spec order: bounds at 8, gmode at 24.
                self.assertEqual(struct.unpack_from("<I", data, off + 24)[0], 1)
        self.assertGreater(with_fonts, 0)
        texts = emf_texts(data)
        self.assertIn("时钟", texts)
        self.assertIn("数据", texts)
        self.assertEqual(hdr[19], doc.content_width)
        self.assertEqual(hdr[20], doc.content_height)
        # 96 dpi frame: 1 px = 2540/96 hundredths of a millimetre
        self.assertEqual(hdr[8], round(doc.content_width * 2540 / 96))
        self.assertEqual(hdr[9], round(doc.content_height * 2540 / 96))
        # px -> mm on the source device, consistent with the frame
        self.assertEqual(hdr[21], round(doc.content_width * 25.4 / 96))
        self.assertEqual(hdr[22], round(doc.content_height * 25.4 / 96))


if __name__ == "__main__":
    unittest.main()
