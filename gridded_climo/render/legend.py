"""Numeric custom legends as color bands. Ported from geotiff-to-kmz (streamlit_app.py: normalize_legend, legend_records).

A legend is a list of rows ``[from, to, r, g, b, a]``: values from `from` up to (not including) `to` get that color.
`from` is None on the lowest row for "no lower limit", `to` is None on the highest for "no upper limit". Values in no
row are transparent. Where rows overlap, the row with the larger `from` wins. a = opacity (255 opaque, 0 transparent).

The older form ``[value, r, g, b, a]`` (value = lower bound, each band runs to the next row's value) is still accepted
everywhere; it is converted by `normalize_legend`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Row = list  # [from, to, r, g, b, a]


def _num(v):
    if v is None or v == "":
        return None
    f = float(v)
    return None if math.isnan(f) else f


def _channel(v, default: int) -> int:
    f = _num(v)
    return default if f is None else int(min(255, max(0, round(f))))


def normalize_legend(rows) -> list[Row]:
    """Clean `[from, to, r, g, b, a]` rows, sorted by from (a blank from first), from either row shape.
    A missing `to` becomes the next row's `from` (the highest row's stays open). A blank `from` survives only on the
    lowest row, and only if that row says where it stops (or it is the only row)."""
    parsed = []
    for r in rows:
        r = list(r)
        if len(r) == 5:           # legacy [value, r, g, b, a]
            frm, to, rest = r[0], None, r[1:]
        elif len(r) == 6:
            frm, to, rest = r[0], r[1], r[2:]
        else:
            raise ValueError(f"a legend row needs 5 or 6 values, got {len(r)}: {r}")
        parsed.append([_num(frm), _num(to), *(_channel(c, 0) for c in rest[:3]), _channel(rest[3], 255)])
    blank = [p for p in parsed if p[0] is None]
    keep_blank = blank[0] if blank and (blank[0][1] is not None or len(parsed) == 1) else None
    out = [p for p in parsed if p[0] is not None or p is keep_blank]
    out.sort(key=lambda p: -math.inf if p[0] is None else p[0])    # stable
    for i, p in enumerate(out):
        if p[1] is None and i + 1 < len(out):
            p[1] = out[i + 1][0]
    return out


@dataclass
class Segment:
    lo: float            # -inf = no lower limit
    hi: float            # +inf = no upper limit
    color: tuple[int, int, int, int] | None   # None = no row covers this stretch (transparent)


def segments(rows) -> list[Segment]:
    """The legend as consecutive non-overlapping stretches: gaps become color-less segments, overlaps go to the row with
    the larger `from`, and the stretches below the first row / above the last row that no row covers are dropped."""
    bands = normalize_legend(rows)
    if not bands:
        return []
    frm = [-math.inf if b[0] is None else b[0] for b in bands]
    to = [math.inf if b[1] is None else b[1] for b in bands]
    pts = sorted({v for v in frm + to if math.isfinite(v)})
    if not pts:
        pts = [0.0]
    edges = [-math.inf, *pts, math.inf]
    segs: list[tuple[float, float, int | None]] = []
    for lo, hi in zip(edges, edges[1:]):
        cover = [k for k in range(len(bands)) if frm[k] <= lo and to[k] >= hi]
        win = max(cover, key=lambda k: (frm[k], k)) if cover else None
        if segs and segs[-1][2] == win:
            segs[-1] = (segs[-1][0], hi, win)
        else:
            segs.append((lo, hi, win))
    while segs and segs[0][2] is None:
        segs.pop(0)
    while segs and segs[-1][2] is None:
        segs.pop()
    return [Segment(lo, hi, None if k is None else tuple(bands[k][2:6])) for lo, hi, k in segs]


def legend_records(rows) -> list[dict]:
    """JSON-safe dict rows (blank from/to are null) for the editor and settings export."""
    return [{"From": r[0], "To": r[1], "R": r[2], "G": r[3], "B": r[4], "Alpha": r[5]} for r in normalize_legend(rows)]


def rows_from_records(records) -> list[Row]:
    """Inverse of `legend_records` (also takes the editor's lowercase keys)."""
    out = []
    for rec in records:
        g = lambda *names: next((rec[n] for n in names if n in rec), None)
        out.append([g("From", "from", "Value"), g("To", "to"), g("R", "r"), g("G", "g"), g("B", "b"), g("Alpha", "a", "A")])
    return normalize_legend(out)
