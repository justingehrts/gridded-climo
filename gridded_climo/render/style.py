"""Style + data range -> the concrete color bands, legend, and GDAL color table that get rendered."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from ..binning import calendar_bins, custom_bins, parse_custom_starts
from ..registry import Style
from .legend import normalize_legend, segments
from .palettes import sample_colors
from .ramps import color_table, get_cmap

Color = tuple[int, int, int, int]


@dataclass
class Resolved:
    table: list[tuple[float, int, int, int, int]]   # gdaldem color-relief rows
    vmin: float
    vmax: float
    smooth: bool
    edges: list[float] | None = None                 # discrete bands (date bins / custom legend): len n+1
    labels: list[str] | None = None                  # len n
    colors: list[Color] | None = None                # len n
    seed_rows: list[list] | None = None              # numeric maps: [[from, to, r, g, b, a], ...] to start the legend editor from


def data_range(tif: str | Path, style: Style | None = None) -> tuple[float, float, float, float]:
    """(min, max, p2, p98) of the raster's valid cells."""
    with rasterio.open(tif) as src:
        a = src.read(1, masked=True).compressed()
    if a.size == 0:
        raise ValueError("raster has no valid data to render (all NoData)")
    lo, hi = np.percentile(a, [2, 98])
    return float(a.min()), float(a.max()), float(lo), float(hi)


def auto_range(rng: tuple[float, float, float, float], style: Style) -> tuple[float, float]:
    if style.vmin is not None and style.vmax is not None:
        return style.vmin, style.vmax
    _, _, lo, hi = rng
    if style.symmetric:
        m = max(abs(lo), abs(hi)) or 1.0
        return -m, m
    return (style.vmin if style.vmin is not None else lo), (style.vmax if style.vmax is not None else hi)


def _ramp_colors(style: Style, n: int) -> list[Color]:
    cmap = get_cmap(style)
    return [(*(int(x * 255) for x in cmap((i + 0.5) / n)[:3]), 255) for i in range(n)]


def band_table(edges: list[float], colors: list[Color], hide_below: float | None = None,
               open_bottom: bool = False, closed_top: bool = False) -> list[tuple[float, int, int, int, int]]:
    """Flat color per band [edge_i, edge_i+1). By default values past the last edge keep the last color and values before
    the first edge are transparent; `open_bottom` drops that leading transparent row (the caller put the first edge below
    the data, so nothing is lost), and `closed_top` makes values at or past the last edge transparent."""
    eps = (edges[-1] - edges[0]) * 1e-6 or 1e-6
    rows: list[tuple[float, int, int, int, int]] = [] if open_bottom else [(edges[0] - eps, 0, 0, 0, 0)]
    for i, c in enumerate(colors):
        last = i + 1 == len(colors)
        rows += [(edges[i], *c), (edges[i + 1] - eps if (not last or closed_top) else edges[i + 1], *c)]
    if closed_top:
        rows.append((edges[-1], 0, 0, 0, 0))
    return rows


def date_bins(style: Style, rng, ref: tuple[int, int]):
    vmin, vmax = rng[0], rng[1]
    if style.date_mode == "custom":
        return custom_bins(parse_custom_starts(style.custom_starts), vmin, vmax, *ref)
    return calendar_bins(style.date_mode, vmin, vmax, *ref)


def bin_colors_for(style: Style, labels: list[str]) -> list[Color]:
    """Palette (imported) or ramp colors by position, then manual per-bin overrides by label."""
    n = len(labels)
    if style.palette:
        base = [tuple(c) if len(c) == 4 else (*c[:3], 255) for c in sample_colors([[0, *c] for c in style.palette], n)]
    else:
        base = _ramp_colors(style, n)
    ov = style.bin_colors or {}
    return [tuple(ov[l]) if l in ov and len(ov[l]) == 4 else c for l, c in zip(labels, base)]


def resolve(style: Style, tif: str | Path, ref: tuple[int, int] | None = None) -> Resolved:
    rng = data_range(tif, style)
    # 1) calendar bins for first/last-date maps
    if ref is not None and style.date_mode != "auto":
        bins = date_bins(style, rng, ref)
        colors = bin_colors_for(style, bins.labels)
        return Resolved(band_table(bins.edges, colors), bins.edges[0], bins.edges[-1], False, bins.edges, bins.labels, colors)
    # 2) numeric custom legend: bands [from, to) (see legend.py). Not for date maps: numeric thresholds mean nothing there.
    if style.legend_rows and ref is None:
        bands = normalize_legend(style.legend_rows)
        if len(bands) < 2:
            raise ValueError("a custom legend needs at least two rows")
        if style.mode == "smooth":      # a color stop at each row's lower bound (an open bottom starts at the data minimum)
            vals = [rng[0] if b[0] is None else b[0] for b in bands]
            table = [(v, *b[2:6]) for v, b in zip(vals, bands)]
            return Resolved(table, vals[0], vals[-1], True, None, None, None)
        segs = segments(bands)
        if not segs:
            raise ValueError("the custom legend colors nothing")
        open_bottom, closed_top = math.isinf(segs[0].lo), math.isfinite(segs[-1].hi)
        edges = [s.lo for s in segs] + [segs[-1].hi]
        if open_bottom:
            edges[0] = min(rng[0], segs[0].hi if math.isfinite(segs[0].hi) else rng[0]) - 1.0
        if not closed_top:
            edges[-1] = max(rng[1], segs[-1].lo if math.isfinite(segs[-1].lo) else rng[1]) + 1e-6
        colors = [s.color or (0, 0, 0, 0) for s in segs]
        labels = [f"below {s.hi:g}" if math.isinf(s.lo) else f"{s.lo:g}+" if math.isinf(s.hi) else f"{s.lo:g}–{s.hi:g}" for s in segs]
        return Resolved(band_table(edges, colors, open_bottom=open_bottom, closed_top=closed_top), edges[0], edges[-1],
                        False, edges, labels, colors)
    # 3) automatic equal-width steps / smooth ramp
    vmin, vmax = auto_range(rng, style)
    if vmax <= vmin:
        vmax = vmin + 1.0
    table = color_table(style, vmin, vmax)
    seed = None
    if style.mode == "stepped" and not style.palette:
        n = max(int(style.steps), 1)
        ev = [float(v) for v in np.linspace(vmin, vmax, n + 1)]
        seed = [[ev[i], ev[i + 1] if i + 1 < n else None, *c] for i, c in enumerate(_ramp_colors(style, n))]
    if style.palette and style.mode == "stepped":     # imported palette recolors the automatic steps
        n = max(int(style.steps), 1)
        edges = list(np.linspace(vmin, vmax, n + 1))
        colors = [tuple(c) for c in sample_colors([[0, *c] for c in style.palette], n)]
        return Resolved(band_table(edges, colors), vmin, vmax, False, edges,
                        [f"{edges[i]:g}–{edges[i + 1]:g}" for i in range(n)], colors)
    return Resolved(table, vmin, vmax, style.mode == "smooth", seed_rows=seed)
