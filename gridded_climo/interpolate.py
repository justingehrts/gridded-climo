"""Station points -> regular lat/lon grid (inverse-distance weighting with a coverage limit)."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree

from .grid import Grid

KM_PER_DEG_LAT = 110.57


def grid_for_bbox(bbox, cell_deg: float = 0.02) -> Grid:
    w, s, e, n = bbox
    cols, rows = int(np.ceil((e - w) / cell_deg)), int(np.ceil((n - s) / cell_deg))
    return Grid(np.full((rows, cols), np.nan, "float32"), w, n, cell_deg, cell_deg)


def idw(lon, lat, values, template: Grid, k: int = 8, power: float = 2.0, max_km: float = 80.0) -> Grid:
    """IDW from the k nearest stations; cells with no station within `max_km` stay NaN (no extrapolation over
    data voids). Distances use a local equirectangular projection."""
    lon, lat, values = np.asarray(lon, float), np.asarray(lat, float), np.asarray(values, float)
    if len(values) == 0:
        raise ValueError("no stations with enough data to interpolate")
    h, w = template.data.shape
    cx = template.west + (np.arange(w) + 0.5) * template.dx
    cy = template.north - (np.arange(h) + 0.5) * template.dy
    gx, gy = np.meshgrid(cx, cy)
    lat0 = float(np.mean(cy))
    kx = KM_PER_DEG_LAT * np.cos(np.radians(lat0))
    tree = cKDTree(np.c_[lon * kx, lat * KM_PER_DEG_LAT])
    kk = min(k, len(values))
    dist, idx = tree.query(np.c_[gx.ravel() * kx, gy.ravel() * KM_PER_DEG_LAT], k=kk)
    dist, idx = dist.reshape(h, w, kk), idx.reshape(h, w, kk)
    if kk == 1:
        dist, idx = dist[..., None], idx[..., None]
    wgt = 1.0 / np.maximum(dist, 0.5) ** power  # 0.5 km floor avoids a bullseye at station locations
    wgt = np.where(dist <= max_km, wgt, 0.0)
    tot = wgt.sum(axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(tot > 0, (wgt * values[idx]).sum(axis=2) / tot, np.nan)
    return template.with_data(out)


def smooth(grid: Grid, sigma_km: float) -> Grid:
    """NaN-aware Gaussian smoothing (voids stay voids; valid cells only average other valid cells).
    Removes single-station bullseyes so the map contours cleanly on air."""
    if sigma_km <= 0:
        return grid
    cell_km = grid.dy * KM_PER_DEG_LAT
    ok = np.isfinite(grid.data)
    num = gaussian_filter(np.where(ok, grid.data, 0.0), sigma_km / cell_km, mode="nearest")
    den = gaussian_filter(ok.astype("float32"), sigma_km / cell_km, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(ok & (den > 1e-3), num / den, np.nan)
    return grid.with_data(out)


def adaptive_cell_deg(bbox, base: float = 0.02, max_cells: int = 400_000) -> float:
    """0.02 deg (~2 km) cells, coarsened only for very large areas so a big state doesn't make millions of cells."""
    w, s_, e, n = bbox
    cells = (e - w) * (n - s_) / base**2
    return base if cells <= max_cells else float(np.sqrt((e - w) * (n - s_) / max_cells))


def adaptive_max_km(lon, lat, base: float = 80.0, cap: float = 200.0) -> float:
    """How far from a station a map cell may be and still be colored: 80 km where stations are dense (Ohio), more where they
    are sparse (3x the typical gap between neighboring stations, up to 200 km), so the West isn't mostly blank."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    if len(lon) < 3:
        return base
    kx = KM_PER_DEG_LAT * np.cos(np.radians(float(np.mean(lat))))
    d, _ = cKDTree(np.c_[lon * kx, lat * KM_PER_DEG_LAT]).query(np.c_[lon * kx, lat * KM_PER_DEG_LAT], k=2)
    return float(min(cap, max(base, 3.0 * np.median(d[:, 1]))))
