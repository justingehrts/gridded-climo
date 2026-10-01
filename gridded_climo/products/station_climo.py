"""Station-based first/last-date climatology: per-station cross-year stat, interpolated to a grid.

Uses shipped per-station files (instant) when they exist and cover the requested years; otherwise asks ACIS directly
(one server-side request, ~15-30 s) so any threshold and any span of years works."""
from __future__ import annotations

import numpy as np

from ..interpolate import grid_for_bbox, idw, smooth
from ..precomputed import DATA_DIR
from ..registry import Metric
from ..stations import (extreme_years, fetch_station_thresholds, load_station_occurrence, station_path, station_stat)


def _covers(z: dict, normal_period) -> bool:
    ys = z["years"].astype(int)
    return ys.min() <= normal_period[0] and ys.max() >= normal_period[1]


def station_data(metric: Metric, bbox, normal_period, data_dir=DATA_DIR, client=None, margin_deg: float = 1.0):
    """-> (z dict, source 'shipped' | 'live')."""
    thr = metric.threshold
    if station_path(data_dir, metric.element, thr["op"], thr["value"], metric.direction).exists():
        z = load_station_occurrence(data_dir, metric.element, thr["op"], thr["value"], metric.direction)
        if _covers(z, normal_period):
            return z, "shipped"
    if client is None:
        raise FileNotFoundError(f"no shipped station data for {metric.name} covering {normal_period[0]}-{normal_period[1]}, "
                                "and live ACIS access is disabled")
    w, s, e, n = bbox
    wide = (w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg)  # stations just outside the map still inform its edges
    z = fetch_station_thresholds(client, wide, metric.element, thr["op"], thr["value"], metric.direction, metric.season,
                                 normal_period[0], normal_period[1])
    return z, "live"


def station_climatology(metric: Metric, bbox, normal_period, data_dir=DATA_DIR, cell_deg: float = 0.02, max_km: float = 80.0,
                        k: int = 12, smooth_km: float = 12.0, client=None):
    cy = metric.cross_year
    z, src = station_data(metric, bbox, normal_period, data_dir, client)
    lon, lat, val, n_valid, sids, names = station_stat(z, normal_period, cy["stat"], cy.get("p"))
    if cy["stat"] in ("min", "max"):  # show the record year in each station's tooltip
        yrs = extreme_years(z, normal_period, cy["stat"], station_stat.last_mask)
        names = np.array([f"{n} (record {y})" for n, y in zip(names, yrs)])
    grid = smooth(idw(lon, lat, val, grid_for_bbox(bbox, cell_deg), k=k, max_km=max_km), smooth_km)
    sm, sd = metric.season["start"]
    info = {"ref_month": sm, "ref_day": sd, "years": normal_period, "source": "station", "data_source": src,
            "points": {"lon": lon, "lat": lat, "value": val, "name": names, "n_years": n_valid}}
    return grid, info
