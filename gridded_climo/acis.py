"""RCC-ACIS GridData client + request builder.

Findings (tested live, 2026-09): GridData does NOT support first_*/last_* reduce codes
("elem_0: firstlast"), and snow/snwd are not available on any grid. cnt_*/sum/mean/max/min
reduces do work. So threshold-crossing dates are computed client-side from daily grids.
"""
from __future__ import annotations

import datetime as dt
from typing import Sequence

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cache import Cache
from .grid import Grid

MISSING = -999
SCALE = 100  # int16 storage scale (temps are whole degrees; pcpn is hundredths of an inch)
GRID1_ELEMENTS = {"mint", "maxt", "pcpn"}


class ACISError(RuntimeError):
    pass


def build_grid_request(element: str, bbox: Sequence[float], sdate: str, edate: str, grid: int = 1) -> dict:
    """(element, region, period) -> ACIS GridData JSON params (daily values, with lat/lon meta)."""
    if grid == 1 and element not in GRID1_ELEMENTS:
        raise ACISError(f"element '{element}' is not available on ACIS Grid 1 (have: {sorted(GRID1_ELEMENTS)})")
    return {
        "bbox": ",".join(f"{v:g}" for v in bbox),
        "sdate": sdate,
        "edate": edate,
        "grid": str(grid),
        "elems": [{"name": element}],
        "meta": ["ll"],
    }


class ACISClient:
    def __init__(self, base_url: str, cache: Cache | None = None, timeout: int = 300):
        self.base_url, self.cache, self.timeout = base_url.rstrip("/"), cache, timeout
        self.session = requests.Session()
        retry = Retry(total=8, backoff_factor=5, backoff_max=300, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None,
                      respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def post(self, endpoint: str, params: dict) -> dict:
        r = self.session.post(f"{self.base_url}/{endpoint}", json=params, timeout=self.timeout)
        r.raise_for_status()
        out = r.json()
        if isinstance(out, dict) and "error" in out:
            raise ACISError(f"{endpoint} {out['error']}  (request: {params})")
        return out

    def _fetch_chunk(self, element, bbox, sdate, edate, grid):
        out = self.post("GridData", build_grid_request(element, bbox, sdate, edate, grid))
        lat, lon = np.array(out["meta"]["lat"]), np.array(out["meta"]["lon"])
        rows = out["data"]
        arr = np.array([r[1] for r in rows], dtype="float32")  # (T, H, W)
        arr[arr <= MISSING] = np.nan
        dates = np.array([r[0] for r in rows])
        stored = np.where(np.isfinite(arr), np.rint(arr * SCALE), np.iinfo("int16").min).astype("int16")
        return {"stored": stored, "dates": dates, "lat": lat, "lon": lon}

    def daily(self, element: str, bbox: Sequence[float], start: dt.date, end: dt.date, grid: int = 1):
        """Daily grids for [start, end] -> (dates[T] as datetime64[D], Grid template, data[T,H,W] float32).

        Pulled in calendar-quarter chunks (Jan-Mar, Apr-Jun, ...) so that windows with different
        start days (Jul 1 seasons, Jan 1 seasons, custom ranges) share cached chunks. Chunks that
        are not yet complete (end within the last few days) are fetched but never cached."""
        parts = []
        for c_start, c_end in quarter_chunks(start, end):
            req = build_grid_request(element, bbox, c_start.isoformat(), c_end.isoformat(), grid)
            fetch = lambda a=c_start, b=c_end: self._fetch_chunk(element, bbox, a.isoformat(), b.isoformat(), grid)
            complete = c_end < dt.date.today() - dt.timedelta(days=5)
            parts.append(self.cache.get_or_compute("acis_daily_v1", req, fetch) if (self.cache and complete) else fetch())
        stored = np.concatenate([p["stored"] for p in parts])
        data = np.where(stored == np.iinfo("int16").min, np.nan, stored.astype("float32") / SCALE).astype("float32")
        dates = np.concatenate([p["dates"] for p in parts]).astype("datetime64[D]")
        keep = (dates >= np.datetime64(start)) & (dates <= np.datetime64(end))
        data, dates = data[keep], dates[keep]
        template = Grid.from_centers(np.zeros(data.shape[1:], "float32"), parts[0]["lat"], parts[0]["lon"])
        lat0 = parts[0]["lat"]
        if lat0.shape[0] > 1 and lat0[0, 0] < lat0[-1, 0]:
            data = data[:, ::-1]  # Grid.from_centers flips south-up input; keep the stack north-up too
        return dates, template, data


def derive(element: str, tmax: np.ndarray, tmin: np.ndarray) -> np.ndarray:
    """Daily avg temp / degree days from daily max and min (ACIS conventions: HDD/CDD base 65; GDD base 50 with max capped at 86 and min floored at 50)."""
    if element == "avgt":
        return ((tmax + tmin) / 2).astype("float32")
    if element in ("hdd", "cdd"):
        avg = (tmax + tmin) / 2
        return np.maximum(0, 65 - avg if element == "hdd" else avg - 65).astype("float32")
    if element == "gdd":
        return np.maximum(0, (np.minimum(tmax, 86) + np.maximum(tmin, 50)) / 2 - 50).astype("float32")
    raise ValueError(element)


def daily_any(client, element: str, bbox, start: dt.date, end: dt.date):
    """Like client.daily, but also serves derived elements (avgt, hdd, cdd, gdd)."""
    if element not in ("avgt", "hdd", "cdd", "gdd"):
        return client.daily(element, bbox, start, end)
    dates, template, tmax = client.daily("maxt", bbox, start, end)
    _, _, tmin = client.daily("mint", bbox, start, end)
    return dates, template, derive(element, tmax, tmin)


def quarter_chunks(start: dt.date, end: dt.date):
    """Calendar-quarter-aligned (start, end) chunks covering [start, end] (full quarters, not clipped)."""
    y, q = start.year, (start.month - 1) // 3
    while True:
        c_start = dt.date(y, 3 * q + 1, 1)
        if c_start > end:
            return
        nxt = dt.date(y + (q == 3), 1 if q == 3 else 3 * q + 4, 1)
        yield c_start, nxt - dt.timedelta(days=1)
        y, q = (y + 1, 0) if q == 3 else (y, q + 1)
