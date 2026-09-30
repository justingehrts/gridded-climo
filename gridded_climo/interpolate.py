"""Station points -> regular lat/lon grid (inverse-distance weighting with a coverage limit)."""
from __future__ import annotations

import numpy as np
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
