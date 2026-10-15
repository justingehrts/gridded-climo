"""Color ramps and color-relief tables. Extracted from geotiff-to-kmz (streamlit_app.py: RAMPS, run_pipeline)."""
from __future__ import annotations

import matplotlib as mpl
import numpy as np

from ..registry import Style

# Grouped the way matplotlib's own colormap reference groups them: Diverging ramps have a neutral midpoint (right for data
# that crosses a baseline, e.g. departures), Sequential ramps only increase, Miscellaneous is everything else.
RAMP_CATEGORIES = {
    "Diverging": {"RdYlBu": "RdYlBu", "Cool-Warm": "coolwarm", "Spectral": "Spectral", "BrBG": "BrBG"},
    "Perceptually Uniform Sequential": {"Viridis": "viridis", "Plasma": "plasma", "Inferno": "inferno", "Magma": "magma", "Cividis": "cividis"},
    "Sequential": {"Blues": "Blues", "Greens": "Greens", "Purples": "Purples", "YlOrRd": "YlOrRd", "YlGnBu": "YlGnBu"},
    "Miscellaneous": {"NWS Spectral": "nipy_spectral", "Terrain": "terrain", "Jet": "jet"},
}
# label -> matplotlib name, for every ramp. "coolwarm" is kept as a second name for Cool-Warm because metrics.yaml and saved
# presets use it.
RAMPS = {**{label: name for group in RAMP_CATEGORIES.values() for label, name in group.items()}, "coolwarm": "coolwarm"}


def ramp_label(name: str) -> str:
    """The dropdown label for a ramp given by label or matplotlib name (e.g. "coolwarm" -> "Cool-Warm")."""
    if name in RAMPS and name != "coolwarm":
        return name
    return next((label for group in RAMP_CATEGORIES.values() for label, n in group.items() if n == RAMPS.get(name, name)), name)


def get_cmap(style: Style):
    name = RAMPS.get(style.ramp, style.ramp)
    if style.reverse:
        name += "_r"
    return mpl.colormaps[name]


def color_table(style: Style, vmin: float, vmax: float) -> list[tuple[float, int, int, int, int]]:
    """[(value, r, g, b, a)] ascending, for gdaldem color-relief with linear interpolation.
    Stepped: `steps` equal-width bins over [vmin, vmax), each a flat color (two stops per bin, so
    bin edges match the legend; values >= vmax keep the top color). Smooth: 100 interpolated stops."""
    if not vmax > vmin:
        vmax = vmin + 1.0
    cmap = get_cmap(style)
    rgb = lambda f: tuple(int(x * 255) for x in cmap(f)[:3])
    eps = (vmax - vmin) * 1e-6
    rows: list[tuple[float, int, int, int, int]] = []
    if style.mode == "stepped":
        n = max(int(style.steps), 1)
        edges = np.linspace(vmin, vmax, n + 1)
        for i in range(n):
            r, g, b = rgb((i + 0.5) / n)
            rows += [(float(edges[i]), r, g, b, 255), (float(edges[i + 1] - eps), r, g, b, 255)]
        rows[-1] = (float(edges[-1]), *rows[-1][1:])
    else:
        for i, v in enumerate(np.linspace(vmin, vmax, 100)):
            rows.append((float(v), *rgb(i / 99), 255))
    if style.hide_below is not None:
        hb = style.hide_below
        kept = [r for r in rows if r[0] >= hb]
        if not kept:
            raise ValueError(f"hide_below={hb} is above the whole color range")
        first = kept[0]
        rows = [(hb - eps, 0, 0, 0, 0), (max(hb, first[0]) if first[0] > hb else hb, *first[1:])] + [r for r in kept if r[0] > hb]
    return rows
