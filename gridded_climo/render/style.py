"""Style + data range -> the concrete color bands, legend, and GDAL color table that get rendered."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from ..binning import calendar_bins, custom_bins, parse_custom_starts
from ..registry import Style
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
    seed_rows: list[list] | None = None              # numeric maps: [[lower, r, g, b, a], ...] to start the legend editor from


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


def band_table(edges: list[float], colors: list[Color], hide_below: float | None = None) -> list[tuple[float, int, int, int, int]]:
    """Flat color per band [edge_i, edge_i+1); values past the last edge keep the last color, values before the
    first edge are transparent."""
    eps = (edges[-1] - edges[0]) * 1e-6 or 1e-6
    rows: list[tuple[float, int, int, int, int]] = [(edges[0] - eps, 0, 0, 0, 0)]
    for i, c in enumerate(colors):
        rows += [(edges[i], *c), (edges[i + 1] - eps if i + 1 < len(colors) else edges[i + 1], *c)]
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
    # 2) numeric custom legend (value = lower bound of its band). Not for date maps: numeric thresholds mean nothing there.
    if style.legend_rows and ref is None:
        rows = sorted((list(r) for r in style.legend_rows), key=lambda r: r[0])
        if len(rows) < 2:
            raise ValueError("a custom legend needs at least two rows")
        vals = [r[0] for r in rows]
        colors = [tuple(int(x) for x in r[1:5]) if len(r) > 4 else (*(int(x) for x in r[1:4]), 255) for r in rows]
        top = max(rng[1], vals[-1]) + 1e-6
        edges = vals + [top]
        labels = [f"{vals[i]:g}–{vals[i + 1]:g}" for i in range(len(vals) - 1)] + [f"{vals[-1]:g}+"]
        if style.mode == "smooth":
            table = [(v, *c) for v, c in zip(vals, colors)]
            return Resolved(table, vals[0], vals[-1], True, None, None, None)
        return Resolved(band_table(edges, colors), vals[0], top, False, edges, labels, colors)
    # 3) automatic equal-width steps / smooth ramp
    vmin, vmax = auto_range(rng, style)
    if vmax <= vmin:
        vmax = vmin + 1.0
    table = color_table(style, vmin, vmax)
    seed = None
    if style.mode == "stepped" and not style.palette:
        n = max(int(style.steps), 1)
        seed = [[float(v), *c] for v, c in zip(np.linspace(vmin, vmax, n + 1)[:-1], _ramp_colors(style, n))]
    if style.palette and style.mode == "stepped":     # imported palette recolors the automatic steps
        n = max(int(style.steps), 1)
        edges = list(np.linspace(vmin, vmax, n + 1))
        colors = [tuple(c) for c in sample_colors([[0, *c] for c in style.palette], n)]
        return Resolved(band_table(edges, colors), vmin, vmax, False, edges,
                        [f"{edges[i]:g}–{edges[i + 1]:g}" for i in range(n)], colors)
    return Resolved(table, vmin, vmax, style.mode == "smooth", seed_rows=seed)
