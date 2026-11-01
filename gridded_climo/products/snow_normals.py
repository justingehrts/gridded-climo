"""Average monthly / seasonal snowfall map: NCEI 1991-2020 station normals summed over whole months, interpolated to a grid."""
from __future__ import annotations

from ..interpolate import adaptive_cell_deg, adaptive_max_km, grid_for_bbox, idw, smooth
from ..precomputed import DATA_DIR
from ..regions import presaved_bbox
from ..snow_normals import fetch_snow_normals, load_shipped, window_sum


def snow_normal_window(bbox, months: list[int], client=None, data_dir=DATA_DIR, smooth_km: float = 3.0, margin_deg: float = 1.0):
    z, src = None, "live"
    if presaved_bbox(tuple(bbox)) is not None:
        z = load_shipped(data_dir)
        if z is not None:
            src, bbox = "shipped", presaved_bbox(tuple(bbox))
    if z is None:
        if client is None:
            raise FileNotFoundError("no shipped snowfall normals for this area, and live ACIS access is disabled")
        w, s, e, n = bbox
        z = fetch_snow_normals(client, (w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg))
    val, keep = window_sum(z, months)
    lon, lat = z["lon"][keep], z["lat"][keep]
    reach = adaptive_max_km(lon, lat)
    grid = smooth(idw(lon, lat, val, grid_for_bbox(bbox, adaptive_cell_deg(bbox)), k=8, power=3.0, max_km=reach), smooth_km)
    points = {"lon": lon, "lat": lat, "value": val, "name": z["name"][keep]}
    return grid, {"data_source": src, "reach_km": reach, "smooth_km": smooth_km, "points": points}
