"""Iowa Environmental Mesonet: NWS Local Storm Reports (observed snowfall) for overlaying on storm-total maps.

https://mesonet.agron.iastate.edu/geojson/lsr.php?sts=...&ets=...&wfos=...  (GeoJSON; verified 2026-09)
"""
from __future__ import annotations

import datetime as dt

import requests

IEM_LSR_URL = "https://mesonet.agron.iastate.edu/geojson/lsr.php"
# WFOs whose county warning areas cover the default Ohio-centered region
REGION_WFOS = ("ILN", "CLE", "PBZ", "RLX", "IWX", "IND", "LMK", "DTX", "PAH", "JKL", "CTP", "BUF", "GRR", "ILX")


def fetch_snow_reports(start_utc: dt.datetime, end_utc: dt.datetime, bbox, wfos=REGION_WFOS, timeout: int = 40) -> dict:
    """-> dict(lon[], lat[], value[] inches, name[]) of SNOW reports inside bbox (west, south, east, north)."""
    r = requests.get(IEM_LSR_URL, params={"sts": f"{start_utc:%Y-%m-%dT%H:%MZ}", "ets": f"{end_utc:%Y-%m-%dT%H:%MZ}",
                                          "wfos": ",".join(wfos)}, timeout=timeout)
    r.raise_for_status()
    w, s, e, n = bbox
    out = {"lon": [], "lat": [], "value": [], "name": []}
    for f in r.json().get("features", []):
        p, (lo, la) = f["properties"], f["geometry"]["coordinates"][:2]
        if p.get("typetext") != "SNOW" or not (w <= lo <= e and s <= la <= n):
            continue
        try:
            mag = float(p["magnitude"])
        except (TypeError, ValueError):
            continue
        out["lon"].append(lo); out["lat"].append(la); out["value"].append(mag)
        out["name"].append(f"{p.get('city', '')} ({p.get('valid', '')[:16]}Z)")
    return out
