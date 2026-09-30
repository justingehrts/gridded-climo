"""NOHRSC National Gridded Snowfall Analysis (sfav2): plain-HTTP GeoTIFFs, EPSG:4326, 0.04 deg,
values in INCHES, -99999 = missing (verified 2026-09).

  season-to-date: {base}/YYYYMM/sfav2_CONUS_<seasonstart YYYYMMDDHH>_to_<end YYYYMMDDHH>.tif  (00Z/12Z ends)
  6-hour:         {base}/YYYYMM/sfav2_CONUS_6h_<YYYYMMDDHH>.tif                               (00/06/12/18Z)
  (also 24h_/48h_/72h_). YYYYMM is the month of the END time.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import requests

from .cache import Cache
from .grid import Grid

MISSING = -99999.0


def season_start(t: dt.datetime) -> dt.datetime:
    """Water-year start used in file names: Sep 30 12Z."""
    y = t.year if t >= dt.datetime(t.year, 9, 30, 12) else t.year - 1
    return dt.datetime(y, 9, 30, 12)


def season_total_url(base: str, end: dt.datetime) -> str:
    return f"{base}/{end:%Y%m}/sfav2_CONUS_{season_start(end):%Y%m%d%H}_to_{end:%Y%m%d%H}.tif"


def six_hour_url(base: str, end: dt.datetime) -> str:
    return f"{base}/{end:%Y%m}/sfav2_CONUS_6h_{end:%Y%m%d%H}.tif"


def snap(t: dt.datetime, step_hours: int, how: str = "nearest") -> dt.datetime:
    base = t.replace(minute=0, second=0, microsecond=0)
    secs = (base - base.replace(hour=0)).total_seconds() + (t - base).total_seconds()
    step = step_hours * 3600
    n = {"down": secs // step, "up": -(-secs // step)}.get(how, round(secs / step))
    return base.replace(hour=0) + dt.timedelta(seconds=n * step)


class NOHRSC:
    def __init__(self, base_url: str, cache: Cache, timeout: int = 120):
        self.base_url, self.cache, self.timeout = base_url.rstrip("/"), cache, timeout

    def fetch(self, url: str) -> Path:
        dest = self.cache.file("nohrsc", url.rsplit("/", 1)[-1])
        if not dest.exists():
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 404:
                raise FileNotFoundError(f"NOHRSC has no file at {url}")
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
        return dest

    def grid(self, url: str, bbox) -> Grid:
        return Grid.from_geotiff(self.fetch(url), nodata_extra=(MISSING,)).clip(bbox)

    def storm_total(self, start: dt.datetime, end: dt.datetime, bbox, method: str = "auto") -> tuple[Grid, str]:
        """Snowfall (inches) accumulated over [start, end] UTC. Returns (grid, method_used).

        difference: season-to-date(end) - season-to-date(start); endpoints snap to 00Z/12Z.
        sum6h: sum of 6-hourly grids; endpoints snap to 00/06/12/18Z. Used when the window
        spans a water-year boundary (or by request).
        """
        if end <= start:
            raise ValueError("storm end must be after start")
        same_season = season_start(start) == season_start(end)
        if method == "auto":
            method = "difference" if same_season else "sum6h"
        if method == "difference":
            e = snap(end, 12)
            s = snap(start, 12)
            if s >= e:
                raise ValueError(f"window collapses to nothing after snapping to 00Z/12Z ({s} -> {e}); use method='sum6h'")
            end_g = self.grid(season_total_url(self.base_url, e), bbox)
            if s <= season_start(e):
                return end_g, method
            start_g = self.grid(season_total_url(self.base_url, s), bbox)
            return end_g.with_data(np.maximum(end_g.data - start_g.data, 0)), method
        if method == "sum6h":
            s, e = snap(start, 6), snap(end, 6)
            if s >= e:
                raise ValueError(f"window collapses to nothing after snapping to 6-hour steps ({s} -> {e})")
            t, total, template = s + dt.timedelta(hours=6), None, None
            while t <= e:
                g = self.grid(six_hour_url(self.base_url, t), bbox)
                template = template or g
                total = g.data if total is None else np.nansum([total, g.data], axis=0)
                t += dt.timedelta(hours=6)
            return template.with_data(total), method
        raise ValueError(f"unknown method '{method}'")
