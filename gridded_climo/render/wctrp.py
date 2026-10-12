"""Write a color band legend as a MAX (WxD) contour palette, `.wctrp`. The layout follows real MAX palettes exactly.

A palette is an XML file: a VQXML header (element count, unit ids), then one `contourElemN` per band in lexicographic tag
order (0, 1, 10, 100, ...). Bands are contiguous: every contourTo is the next band's contourFrom. A band with no upper limit
is written with contourTo 999 (as MAX does); `parse_wctrp` maps 999 back to "no limit", so palettes round-trip.
"""
from __future__ import annotations

import math

from .legend import normalize_legend, segments

VERSION = "7.7.0720.0008"
OPEN_TOP, OPEN_BOTTOM = 999.0, -999.0       # MAX writes 999 for "no upper limit"; -999 for no lower limit is the mirror (unverified)

# MAX unit context ids seen in real palettes (unitContextId). Others can be typed in.
UNIT_IDS = {"Precipitation (inches)": 2, "Temperature (°F)": 11}

_TEXTURE = ('<textureFile CN="classWxFileMediaRef"><m_name>Default</m_name>\n<m_relativePath>Default</m_relativePath>\n'
            "<mediaRoot>0</mediaRoot>\n<mediaType>0</mediaType>\n</textureFile>")


def fmt(v: float) -> str:
    """Compact number the way MAX writes them: `-80`, `20`, `0.0958763` (7 significant digits, never an exponent)."""
    s = format(v, ".7g")
    if "e" in s.lower():
        s = f"{v:.10f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def contiguous_bands(rows) -> list[list]:
    """[from, to, r, g, b, a] bands with no gaps or overlaps, as MAX needs. A gap becomes a fully transparent band, an
    overlap goes to the row with the larger From, and open ends become -999 / 999."""
    out = []
    for s in segments(rows):
        r, g, b, a = s.color or (0, 0, 0, 0)
        out.append([OPEN_BOTTOM if math.isinf(s.lo) else s.lo, OPEN_TOP if math.isinf(s.hi) else s.hi, r, g, b, a])
    return out


def wctrp_bytes(rows, unit_context_id: int = 2) -> bytes:
    bands = contiguous_bands(normalize_legend(rows))
    if not bands:
        raise ValueError("the legend has no rows to export")
    elems = {}
    for i, (lo, hi, r, g, b, a) in enumerate(bands):
        elems[f"contourElem{i}"] = (
            f'<contourElem{i} CN="classWxdContourPaletteChild"><contourFrom>{fmt(lo)}</contourFrom>\n'
            f"<contourTo>{fmt(hi)}</contourTo>\n<paletteEntryAlpha>{a}</paletteEntryAlpha>\n<paletteEntryBlue>{b}</paletteEntryBlue>\n"
            f"<paletteEntryGreen>{g}</paletteEntryGreen>\n<paletteEntryRed>{r}</paletteEntryRed>\n{_TEXTURE}\n</contourElem{i}>\n"
        )
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n<VQXML CN="classWxdContourPalette" VN="{VERSION}"><contourSize>{len(bands)}</contourSize>\n'
            f"<unitContextId>{int(unit_context_id)}</unitContextId>\n<unitSetId>Display</unitSetId>\n")
    return (head + "".join(elems[k] for k in sorted(elems)) + "</VQXML>\n").encode("utf-8")
