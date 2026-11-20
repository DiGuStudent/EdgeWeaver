"""Minimal SVG backend for EdgeWeaver exports."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .model import Document
from .renderer import RenderOptions, Selection, render_document


def _n(value: float) -> str:
    s = f"{float(value):.2f}"
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class SvgBackend:
    def __init__(self, width: float, height: float):
        self.width = width
        self.height = height
        self.elements: list[str] = []

    def line(self, x1, y1, x2, y2, color="#000000", width=1.0, dash=None):
        extra = f' stroke-dasharray="3,3"' if dash else ""
        self.elements.append(
            f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
            f'stroke="{color}" stroke-width="{_n(width)}"{extra}/>'
        )

    def rect(self, x, y, w, h, fill=None, stroke=None, width=1.0, rx=0.0):
        attrs = [f'x="{_n(x)}"', f'y="{_n(y)}"', f'width="{_n(w)}"', f'height="{_n(h)}"']
        if rx:
            attrs += [f'rx="{_n(rx)}"', f'ry="{_n(rx)}"']
        attrs.append(f'fill="{fill}"' if fill else 'fill="none"')
        if stroke:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{_n(width)}"']
        self.elements.append("<rect " + " ".join(attrs) + "/>")

    def text(self, x, y, text, size=10, family="Arial", color="#000000",
             anchor="start", bold=False):
        weight = ' font-weight="bold"' if bold else ""
        self.elements.append(
            f'<text x="{_n(x)}" y="{_n(y)}" font-family="{escape(family)}" '
            f'font-size="{_n(size)}pt" fill="{color}" text-anchor="{anchor}"{weight}>'
            f'{escape(text)}</text>'
        )

    def polygon(self, points, fill=None, stroke=None, width=1.0):
        pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in points)
        attrs = [f'points="{pts}"', f'fill="{fill}"' if fill else 'fill="none"']
        if stroke:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{_n(width)}"']
        self.elements.append("<polygon " + " ".join(attrs) + "/>")

    def cubic(self, p0, c1, c2, p1, stroke="#000000", width=1.0, fill=None):
        d = (f'M {_n(p0[0])},{_n(p0[1])} C {_n(c1[0])},{_n(c1[1])} '
             f'{_n(c2[0])},{_n(c2[1])} {_n(p1[0])},{_n(p1[1])}')
        attrs = [f'd="{d}"', f'fill="{fill}"' if fill else 'fill="none"',
                 f'stroke="{stroke}"', f'stroke-width="{_n(width)}"']
        self.elements.append("<path " + " ".join(attrs) + "/>")

    def document(self) -> str:
        head = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            '<!-- Created with EdgeWeaver -->',
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.0" '
            f'width="{_n(self.width)}" height="{_n(self.height)}" '
            f'viewBox="0 0 {_n(self.width)} {_n(self.height)}">',
        ]
        return "\n".join(head + self.elements + ["</svg>", ""])


def export_svg(doc: Document, path: str | Path, opts: RenderOptions | None = None,
               selection: Selection | None = None) -> Path:
    path = Path(path)
    backend = SvgBackend(doc.content_width, doc.content_height)
    render_document(backend, doc, opts, selection)
    path.write_text(backend.document(), encoding="utf-8")
    return path
