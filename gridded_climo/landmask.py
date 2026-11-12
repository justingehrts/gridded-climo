"""Large-water stencil: a shipped 0.01-degree raster (data/mask/water.npz, built by mask_build.py) marking oceans and big lakes
(the Great Lakes, Great Salt Lake and the like), used to blank map color over open water."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

MASK_PATH = Path(__file__).resolve().parent.parent / "data" / "mask" / "water.npz"
MASK_WEST, MASK_EAST, MASK_SOUTH, MASK_NORTH, MASK_STEP = -127.0, -65.0, 23.0, 52.0, 0.01


@lru_cache(maxsize=1)
def _load():
    if not MASK_PATH.exists():
        return None
    z = np.load(MASK_PATH, allow_pickle=False)
    water = np.unpackbits(z["bits"], axis=1)[:, : int(z["width"])].astype(bool)
    return water, float(z["west"]), float(z["north"]), float(z["step"])


def water_at(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """True where the point is large open water (False everywhere if no mask is shipped or the point is outside it)."""
    m = _load()
    lat, lon = np.asarray(lat), np.asarray(lon)
    if m is None:
        return np.zeros(lat.shape, bool)
    water, west, north, step = m
    r, c = np.floor((north - lat) / step).astype(int), np.floor((lon - west) / step).astype(int)
    inside = (r >= 0) & (r < water.shape[0]) & (c >= 0) & (c < water.shape[1])
    out = np.zeros(lat.shape, bool)
    out[inside] = water[r[inside], c[inside]]
    return out


def mask_grid(grid):
    """The grid with cells whose centers are large open water set to NaN."""
    h, w = grid.data.shape
    lat = grid.north - (np.arange(h) + 0.5) * grid.dy
    lon = grid.west + (np.arange(w) + 0.5) * grid.dx
    wat = water_at(lat[:, None] + 0 * lon[None, :], lon[None, :] + 0 * lat[:, None])
    if not wat.any():
        return grid
    return grid.with_data(np.where(wat, np.nan, grid.data))
