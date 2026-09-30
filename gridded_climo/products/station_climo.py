"""Station-based first/last-date climatology: per-station cross-year stat, interpolated to a grid."""
from __future__ import annotations

from ..interpolate import grid_for_bbox, idw
from ..precomputed import DATA_DIR
from ..registry import Metric
from ..stations import load_station_occurrence, station_stat


def station_climatology(metric: Metric, bbox, normal_period, data_dir=DATA_DIR, cell_deg: float = 0.02, max_km: float = 80.0):
    thr, cy = metric.threshold, metric.cross_year
    z = load_station_occurrence(data_dir, metric.element, thr["op"], thr["value"], metric.direction)
    lon, lat, val, n_valid, sids, names = station_stat(z, normal_period, cy["stat"], cy.get("p"))
    grid = idw(lon, lat, val, grid_for_bbox(bbox, cell_deg), max_km=max_km)
    sm, sd = metric.season["start"]
    info = {"ref_month": sm, "ref_day": sd, "years": normal_period, "source": "station",
            "points": {"lon": lon, "lat": lat, "value": val, "name": names, "n_years": n_valid}}
    return grid, info
