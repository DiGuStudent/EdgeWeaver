"""CLI regression tests (headless)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edgeweaver import cli  # noqa: E402
from edgeweaver.tim_format import load_tim  # noqa: E402

SAMPLES = Path(os.environ.get(
    "EDGEWEAVER_SAMPLES", str(ROOT / "samples")))

SPEC = {
    "slot_width": 24,
    "slots": 16,
    "signal_height": 16,
    "name_width": 70,
    "rows": [
        {"name": "CLK", "type": "clock", "period": 2},
        {"name": "DATA", "type": "signal", "state": "0001111100001111",
         "edge": "slanted", "edge_width": 6},
        {"name": "BUS", "type": "bus", "state": "2223334444"},
        {"name": "SEP", "type": "separator", "dotted": True},
    ],
    "labels": [
        {"text": "tSU", "x": 80, "y": 40, "owner": "DATA"},
        {"text": "valid", "x": 300, "y": 150},
    ],
    "arrows": [
        {"src_signal": "CLK", "src_cycle": 3, "dst_signal": "DATA",
         "dst_cycle": 6, "style": "bezier", "offset": -10},
    ],
    "timebreaks": [{"signal": "DATA", "cycle": 8}],
    "bus_values": [{"row": "BUS", "start": 2, "end": 5, "text": "8h'1a"}],
    "measurements": [
        {"src_signal": "CLK", "src_cycle": 2, "dst_signal": "DATA",
         "dst_cycle": 6, "text": "tSU = 5 ns"},
    ],
    "flood": [{"row": "BUS", "start": 2, "end": 6}],
}


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_draw_tim_svg_json(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.json"
            spec.write_text(json.dumps(SPEC), encoding="utf-8")
            tim = Path(td) / "out.tim"
            svg = Path(td) / "out.svg"
            code, out, err = run(["draw", str(spec), "--out", str(tim),
                                  "--out", str(svg), "--json"])
            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["document"]["rows"], 4)
            self.assertEqual(payload["document"]["slots"], 16)
            self.assertEqual(payload["document"]["measurements"], 1)
            self.assertEqual(payload["document"]["bus_values"], 1)

            doc = load_tim(tim)
            self.assertEqual(doc.slots, 16)
            self.assertEqual(doc.slot_width, 24)
            self.assertEqual([r.name for r in doc.rows],
                             ["CLK", "DATA", "BUS", "SEP"])
            self.assertEqual(doc.rows[0].kind, "clock")
            self.assertTrue(doc.is_bus(doc.rows[2]))
            self.assertEqual(doc.rows[1].edge_style, "slanted")
            self.assertEqual(doc.arrows[0].kind, 2)
            self.assertEqual(doc.labels[0].owner, "DATA")
            self.assertEqual(doc.measurements[0].src_signal, "CLK")
            self.assertEqual(doc.measurements[0].dst_cycle, 6)
            self.assertEqual(doc.measurements[0].text, "tSU = 5 ns")
            self.assertEqual(doc.bus_values[0].text, "8h'1a")
            self.assertTrue(all(doc.flood[2][2:6]))

            text = svg.read_text(encoding="utf-8")
            self.assertIn("CLK", text)
            self.assertIn("tSU", text)
            self.assertIn("8h'1a", text)
            self.assertIn("<line", text)

    def test_other_outputs_and_transparency(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.json"
            spec.write_text(json.dumps(SPEC), encoding="utf-8")
            outs = {suffix: Path(td) / f"out.{suffix}"
                    for suffix in ("emf", "png", "pdf", "csv", "xml")}
            args = ["draw", str(spec)]
            for path in outs.values():
                args += ["--out", str(path)]
            code, out, err = run(args)
            self.assertEqual(code, 0, err)
            for path in outs.values():
                self.assertTrue(path.exists(), path)
                self.assertGreater(path.stat().st_size, 50, path)

            opaque = Path(td) / "opaque.svg"
            clear = Path(td) / "clear.svg"
            self.assertEqual(run(["draw", str(spec), "--out", str(opaque)])[0], 0)
            self.assertEqual(run(["draw", str(spec), "--out", str(clear),
                                  "--transparent"])[0], 0)
            self.assertIn('fill="#ffffff"', opaque.read_text(encoding="utf-8"))
            self.assertNotIn('fill="#ffffff"', clear.read_text(encoding="utf-8"))

    def test_measurement_style_fields(self):
        spec = json.loads(json.dumps(SPEC))
        spec["measurements"][0].update({
            "text": "建立时间 = 1.5", "suffix": "us",
            "y": 8, "dx": 3, "color": "#c00000"})
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spec.json"
            path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            tim = Path(td) / "out.tim"
            svg = Path(td) / "out.svg"
            code, out, err = run(["draw", str(path), "--out", str(tim),
                                  "--out", str(svg)])
            self.assertEqual(code, 0, err)
            measurement = load_tim(tim).measurements[0]
            self.assertEqual(measurement.text, "建立时间 = 1.5")
            self.assertEqual(measurement.suffix, "µs")
            self.assertEqual(measurement.y, 8)
            self.assertEqual(measurement.dx, 3.0)
            self.assertEqual(measurement.color, "#c00000")
            text = svg.read_text(encoding="utf-8")
            self.assertIn("建立时间 = 1.5 µs", text)
            self.assertIn('fill="#c00000"', text)

    def test_analog_row(self):
        spec = {
            "slot_width": 30,
            "slots": 4,
            "signal_height": 16,
            "name_width": 70,
            "rows": [
                {"name": "ADC", "type": "analog", "states": "AA10",
                 "samples": [0, 1, 0.5, 0.25], "min": 0, "max": 1},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "analog.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            tim = Path(td) / "analog.tim"
            svg = Path(td) / "analog.svg"
            code, out, err = run(["draw", str(path), "--out", str(tim),
                                  "--out", str(svg)])
            self.assertEqual(code, 0, err)
            doc = load_tim(tim)
            self.assertEqual(doc.rows[0].kind, "analog")
            self.assertEqual(doc.rows[0].state[:4], "AA10")
            self.assertEqual(doc.rows[0].samples, [0.0, 1.0, 0.5, 0.25])
            self.assertEqual(doc.rows[0].sample_min, 0.0)
            self.assertEqual(doc.rows[0].sample_max, 1.0)
            self.assertIn("<line", svg.read_text(encoding="utf-8"))

    def test_convert_existing_tim(self):
        src = SAMPLES / "2-3-2.tim"
        if not src.exists():
            self.skipTest("samples not available")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "converted.svg"
            code, stdout, err = run(["convert", str(src), "--out", str(out)])
            self.assertEqual(code, 0, err)
            self.assertTrue(out.exists())
            self.assertIn("CEB", out.read_text(encoding="utf-8"))

    def test_invalid_spec_reports_error(self):
        bad = json.loads(json.dumps(SPEC))
        bad["arrows"][0]["dst_signal"] = "NOPE"
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "bad.json"
            spec.write_text(json.dumps(bad), encoding="utf-8")
            code, out, err = run(["draw", str(spec), "--out",
                                  str(Path(td) / "x.svg")])
            self.assertEqual(code, 1)
            self.assertIn("unknown signal", err)
            self.assertFalse((Path(td) / "x.svg").exists())

    def test_describe(self):
        code, out, err = run(["describe"])
        self.assertEqual(code, 0, err)
        self.assertIn("EdgeWeaver CLI", out)
        self.assertIn("draw", out)


if __name__ == "__main__":
    unittest.main()
