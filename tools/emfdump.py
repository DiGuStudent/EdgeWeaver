#!/usr/bin/env python3
"""EMF record dumper for ground-truth analysis (MS-EMF field offsets)."""
import struct
import sys

TYPES = {
    1: "HEADER", 2: "POLYBEZIER", 3: "POLYGON", 4: "POLYLINE", 5: "POLYBEZIERTO",
    6: "POLYLINETO", 7: "POLYPOLYLINE", 8: "POLYPOLYGON", 9: "SETWINDOWEXTEX",
    10: "SETWINDOWORGEX", 11: "SETVIEWPORTEXTEX", 12: "SETVIEWPORTORGEX",
    13: "SETBRUSHORGEX", 14: "EOF", 15: "SETPIXELV", 16: "SETMAPPERFLAGS",
    17: "SETMAPMODE", 18: "SETBKMODE", 19: "SETPOLYFILLMODE", 20: "SETROP2",
    21: "SETSTRETCHBLTMODE", 22: "SETTEXTALIGN", 23: "SETCOLORADJUSTMENT",
    24: "SETTEXTCOLOR", 25: "SETBKCOLOR", 26: "OFFSETCLIPRGN", 27: "MOVETOEX",
    28: "SETMETARGN", 29: "EXCLUDECLIPRECT", 30: "INTERSECTCLIPRECT",
    31: "SCALEVIEWPORTEXTEX", 32: "SCALEWINDOWEXTEX", 33: "SAVEDC", 34: "RESTOREDC",
    35: "SETWORLDTRANSFORM", 36: "MODIFYWORLDTRANSFORM", 37: "SELECTOBJECT",
    38: "CREATEPEN", 39: "CREATEBRUSHINDIRECT", 40: "DELETEOBJECT",
    41: "ANGLEARC", 42: "ELLIPSE", 43: "RECTANGLE", 44: "ROUNDRECT", 45: "ARC",
    46: "CHORD", 47: "PIE", 48: "SELECTPALETTE", 49: "CREATEPALETTE",
    50: "SETPALETTEENTRIES", 51: "RESIZEPALETTE", 52: "REALIZEPALETTE",
    53: "EXTFLOODFILL", 54: "LINETO", 55: "ARCTO", 56: "POLYDRAW",
    57: "SETARCDIRECTION", 58: "SETMITERLIMIT", 59: "BEGINPATH", 60: "ENDPATH",
    61: "CLOSEFIGURE", 62: "FILLPATH", 63: "STROKEANDFILLPATH", 64: "STROKEPATH",
    65: "FLATTENPATH", 66: "WIDENPATH", 67: "SELECTCLIPPATH", 68: "ABORTPATH",
    70: "GDICOMMENT", 71: "FILLRGN", 72: "FRAMERGN", 73: "INVERTRGN",
    74: "PAINTRGN", 75: "EXTSELECTCLIPRGN", 76: "BITBLT", 77: "STRETCHBLT",
    78: "MASKBLT", 79: "PLGBLT", 80: "SETDIBITSTODEVICE", 81: "STRETCHDIBITS",
    82: "EXTCREATEFONTINDIRECTW", 83: "EXTTEXTOUTA", 84: "EXTTEXTOUTW",
    85: "POLYBEZIER16", 86: "POLYGON16", 87: "POLYLINE16", 88: "POLYBEZIERTO16",
    89: "POLYLINETO16", 90: "POLYPOLYLINE16", 91: "POLYPOLYGON16",
    92: "POLYDRAW16", 93: "CREATEMONOBRUSH", 94: "CREATEDIBPATTERNBRUSHPT",
    95: "EXTCREATEPEN", 96: "POLYTEXTOUTA", 97: "POLYTEXTOUTW", 98: "SETICMMODE",
    99: "SETICMPROFILEA", 100: "SETICMPROFILEW", 101: "CREATECOLORSPACE",
    102: "SETCOLORSPACE", 103: "DELETECOLORSPACE", 104: "GLSRECORD",
    105: "GLSBOUNDEDRECORD", 106: "PIXELFORMAT", 107: "DRAWESCAPE",
    108: "EXTESCAPE", 109: "STARTDOC", 110: "SMALLTEXTOUT",
    111: "FORCEUFIMAPPING", 112: "NAMEDESCAPE", 114: "COLORMATCHTOTARGETW",
    115: "CREATECOLORSPACEW",
}

PEN_STYLES = {0: "PS_SOLID", 1: "PS_DASH", 2: "PS_DOT", 3: "PS_DASHDOT",
              4: "PS_DASHDOTDOT", 5: "PS_NULL", 6: "PS_INSIDEFRAME"}


def cstr(b):
    return b.split(b"\0", 1)[0].decode("latin1", "replace")


def wstr(b):
    s = b
    if len(s) % 2:
        s = s[:-1]
    return s.decode("utf-16-le", "replace").split("\0", 1)[0]


def decode_header(b):
    (iType, nSize, rclLeft, rclTop, rclRight, rclBottom,
     frLeft, frTop, frRight, frBottom, sig, ver, nBytes, nRecords,
     nHandles, sRes, nDesc, offDesc, nPal,
     devW, devH, mmW, mmH) = struct.unpack_from("<IIiiiiiiiiIIIIHHIIIiiii", b, 0)
    h = {
        "type": iType, "size": nSize,
        "bounds_px": (rclLeft, rclTop, rclRight, rclBottom),
        "frame_01mm": (frLeft, frTop, frRight, frBottom),
        "signature": hex(sig), "version": hex(ver),
        "bytes": nBytes, "records": nRecords, "handles": nHandles,
        "nDesc": nDesc, "offDesc": offDesc, "nPalEntries": nPal,
        "device_px": (devW, devH), "device_mm": (mmW, mmH),
    }
    if nDesc:
        # ENHMETAHEADER.nDescription counts UTF-16 characters, not bytes.
        raw = b[offDesc:offDesc + nDesc * 2]
        h["description_raw"] = raw
        h["description"] = raw.decode("utf-16-le", "replace").split("\0", 1)[0]
    return h


def decode_record(kind, b):
    if kind == 1:
        return ""
    if kind in (9, 10, 11, 12):
        x, y = struct.unpack_from("<ii", b, 8)
        return f"{x},{y}"
    if kind == 17:
        return f"iMode={struct.unpack_from('<I', b, 8)[0]}"
    if kind in (18, 19, 20, 21, 98):
        return f"value={struct.unpack_from('<I', b, 8)[0]}"
    if kind in (22,):
        return f"align=0x{struct.unpack_from('<I', b, 8)[0]:X}"
    if kind in (24, 25):
        return f"color=0x{struct.unpack_from('<I', b, 8)[0]:08X}"
    if kind == 15:
        x, y, c = struct.unpack_from("<iiI", b, 8)
        return f"({x},{y}) 0x{c:08X}"
    if kind == 27:
        x, y = struct.unpack_from("<ii", b, 8)
        return f"({x},{y})"
    if kind == 54:
        x, y = struct.unpack_from("<ii", b, 8)
        return f"({x},{y})"
    if kind in (37, 40):
        return f"ihObject=0x{struct.unpack_from('<I', b, 8)[0]:X}"
    if kind == 38:  # EMRCREATEPEN: ih, LOGPEN{style, x, color}
        ih, style, w, color = struct.unpack_from("<IIII", b, 8)
        r, g, bl = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        return f"ih=0x{ih:X} style={PEN_STYLES.get(style, style)} width={w} color=({r},{g},{bl})"
    if kind == 39:  # EMRCREATEBRUSHINDIRECT
        ih, style, color, hatch = struct.unpack_from("<IIII", b, 8)
        r, g, bl = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        return f"ih=0x{ih:X} style={style} color=({r},{g},{bl}) hatch={hatch}"
    if kind == 95:  # EMR_EXTCREATEPEN: ih, offBmi,cbBmi,offBits,cbBits, EXTLOGPEN
        ih, offBmi, cbBmi, offBits, cbBits = struct.unpack_from("<IIIII", b, 8)
        style, w, brushStyle, color, hatch, nEnt = struct.unpack_from("<IIIIII", b, 28)
        r, g, bl = color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF
        return (f"ih=0x{ih:X} style={style} width={w} brushStyle={brushStyle} "
                f"color=({r},{g},{bl}) hatch={hatch} nEnt={nEnt} "
                f"bmi=({offBmi},{cbBmi}) bits=({offBits},{cbBits})")
    if kind == 82:  # ih at 8, EXTLOGFONTW at 12
        ih = struct.unpack_from("<I", b, 8)[0]
        lf = b[12:]
        height, width, esc, orient, weight = struct.unpack_from("<lllll", lf, 0)
        italic, underline, strikeout, charset, outp, clipp, quality, pitchfam = struct.unpack_from("<8B", lf, 20)
        face = wstr(lf[28:28 + 64])
        full = wstr(lf[92:92 + 128])
        style_name = wstr(lf[220:220 + 64])
        return (f"ih=0x{ih:X} h={height} w={width} esc={esc} orient={orient} "
                f"weight={weight} italic={italic} underline={underline} strikeout={strikeout} "
                f"charset={charset} quality={quality} pitchfam=0x{pitchfam:02X} "
                f"face='{face}' full='{full}' style='{style_name}'")
    if kind in (83, 84):
        # EMRTEXT begins at 36: ptlRef(8), nChars, offString, fOptions, rcl(16), offDx
        x, y = struct.unpack_from("<ii", b, 36)
        nChars, offStr, opts = struct.unpack_from("<III", b, 44)
        rcl = struct.unpack_from("<iiii", b, 56)
        offDx = struct.unpack_from("<I", b, 72)[0]
        if kind == 84:
            text = wstr(b[offStr:offStr + nChars * 2])
        else:
            text = b[offStr:offStr + nChars].decode("latin1", "replace")
        gmode = struct.unpack_from("<I", b, 24)[0]
        return (f"pt=({x},{y}) n={nChars} opts=0x{opts:X} offStr={offStr} offDx={offDx} "
                f"gm={gmode} rcl={rcl} text={text!r}")
    if kind == 43:
        return f"rect={struct.unpack_from('<iiii', b, 8)}"
    if kind == 42:
        return f"ellipse={struct.unpack_from('<iiii', b, 8)}"
    if kind == 7:
        nPolys, nPts = struct.unpack_from("<II", b, 8)
        return f"nPolys={nPolys} nPts={nPts}"
    if kind == 8:
        bb = struct.unpack_from("<iiii", b, 8)
        nPolys, nPts = struct.unpack_from("<II", b, 24)
        return f"bounds={bb} nPolys={nPolys} nPts={nPts}"
    if kind in (2, 3, 4, 5, 6, 85, 86, 87, 88, 89):
        bb = struct.unpack_from("<iiii", b, 8)
        nPts = struct.unpack_from("<I", b, 24)[0]
        return f"bounds={bb} nPts={nPts}"
    if kind in (90, 91):
        bb = struct.unpack_from("<iiii", b, 8)
        nPolys, nPts = struct.unpack_from("<II", b, 24)
        return f"bounds={bb} nPolys={nPolys} nPts={nPts}"
    if kind == 76:  # EMRBITBLT
        bb = struct.unpack_from("<iiii", b, 8)
        xd, yd, xsr, ysr, cxs, cys, offBmi, cbBmi, offBits, cbBits, usage, rop = struct.unpack_from("<iiiiiiIIIIII", b, 24)
        return (f"bounds={bb} dest=({xd},{yd}) src=({xsr},{ysr}) srcSize={cxs}x{cys} "
                f"bmi=({offBmi},{cbBmi}) bits=({offBits},{cbBits}) usage={usage} rop=0x{rop:X}")
    if kind == 70:
        nData = struct.unpack_from("<I", b, 8)[0]
        data = b[12:12 + nData]
        if data[:4] == b"EMF+":
            return f"nData={nData} EMF+ comment len={int.from_bytes(data[4:8], 'little')}"
        return f"nData={nData} data={data[:48]!r}"
    if kind == 14:
        nPal, offPal = struct.unpack_from("<II", b, 8)
        return f"nPalEntries={nPal} offPalEntries={offPal}"
    return ""


def main():
    path = sys.argv[1]
    full = "--full" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    data = open(path, "rb").read()
    hdr = decode_header(data)
    print(f"== {path} ==")
    for k, v in hdr.items():
        print(f"  {k}: {v}")
    off = hdr["size"]
    total = len(data)
    n = 0
    counts = {}
    while off + 8 <= total:
        kind, size = struct.unpack_from("<II", data, off)
        if size < 8 or off + size > total:
            print(f"!! bad record at 0x{off:X}: type={kind} size={size}")
            break
        n += 1
        counts[kind] = counts.get(kind, 0) + 1
        if full or n <= (limit or 60):
            extra = decode_record(kind, data[off:off + size])
            print(f"{n:4d} @0x{off:06X} {TYPES.get(kind, kind):<22} nSize={size:<6} {extra}")
        off += size
        if kind == 14:
            break
    print(f"-- records parsed: {n}; trailing bytes: {total - off}")
    print("-- counts:", {TYPES.get(k, k): v for k, v in sorted(counts.items())})


if __name__ == "__main__":
    main()
