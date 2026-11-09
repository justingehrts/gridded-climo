"""Storm-total snowfall without NOHRSC: ACIS station snowfall summed over calendar days, blended with NWS local storm reports.

For storms before NOHRSC's analyses begin (Oct 2008), or any time you want station numbers instead."""
from __future__ import annotations

import datetime as dt

import numpy as np

from ..interpolate import adaptive_cell_deg, adaptive_max_km, grid_for_bbox, idw, smooth
from ..snow_normals import fetch_snow_total

LSR_DEDUP_KM = 10.0     # a report this close to a station is dropped (the station's measurement wins)
LSR_MAX_DAYS = 31       # nationwide LSR requests get large; longer windows use stations only


def _km(lon1, lat1, lon2, lat2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


def blend(stations: dict, reports: dict | None, dedup_km: float = LSR_DEDUP_KM) -> dict:
    """Station totals plus those storm reports that are not within dedup_km of a station -> points dict (+ counts)."""
    lon, lat, val = (np.asarray(stations[k], "float64") for k in ("lon", "lat", "obs"))
    names = [f'{n} ({o:g}" station)' for n, o in zip(stations["name"], np.round(val, 1))]
    n_lsr = 0
    if reports and len(reports["value"]):
        rl, ra = np.asarray(reports["lon"], "float64"), np.asarray(reports["lat"], "float64")
        far = np.ones(len(rl), bool)
        if len(lon):
            far = np.array([_km(x, y, lon, lat).min() > dedup_km for x, y in zip(rl, ra)])
        n_lsr = int(far.sum())
        lon, lat = np.concatenate([lon, rl[far]]), np.concatenate([lat, ra[far]])
        rv = np.asarray(reports["value"], "float64")[far]
        val = np.concatenate([val, rv])
        names += [f'{n} ({v:g}" report)' for n, v in zip(np.asarray(reports["name"])[far], rv)]
    return {"lon": lon, "lat": lat, "value": val, "name": np.array(names, dtype=str), "n_stations": len(stations["obs"]), "n_reports": n_lsr}


def snow_station_total_map(bbox, start: dt.date, end: dt.date, client, reports: bool = True, smooth_km: float = 3.0,
                           margin_deg: float = 1.0, fetch_reports=None):
    if client is None:
        raise RuntimeError("live ACIS access is disabled")
    w, s, e, n = bbox
    st = fetch_snow_total(client, (w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg), start, end)
    rep, lsr_note = None, ""
    if reports:
        if (end - start).days + 1 > LSR_MAX_DAYS:
            lsr_note = f"storm reports skipped (windows over {LSR_MAX_DAYS} days use stations only)"
        else:
            try:
                if fetch_reports is None:
                    from ..iem import fetch_snow_reports as fetch_reports
                rep = fetch_reports(dt.datetime.combine(start, dt.time()), dt.datetime.combine(end + dt.timedelta(days=1), dt.time()),
                                    (w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg), wfos=None)
            except Exception as ex:      # optional: never fail the map over it
                lsr_note = f"storm reports unavailable ({type(ex).__name__})"
    pts = blend(st, rep)
    if len(pts["value"]) == 0:
        raise ValueError("no stations or storm reports reported snowfall for these dates")
    reach = adaptive_max_km(pts["lon"], pts["lat"])
    grid = smooth(idw(pts["lon"], pts["lat"], pts["value"], grid_for_bbox(bbox, adaptive_cell_deg(bbox)), k=8, power=3.0, max_km=reach), smooth_km)
    return grid, {"reach_km": reach, "smooth_km": smooth_km, "points": {k: pts[k] for k in ("lon", "lat", "value", "name")},
                  "n_stations": pts["n_stations"], "n_reports": pts["n_reports"], "lsr_note": lsr_note}
