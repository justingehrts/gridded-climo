"""Local time zones for map cells: a shipped 0.05-degree grid of IANA zone names (data/tz/tzgrid.npz, built by tz_build.py), with
UTC offsets (DST included) from stdlib zoneinfo for any date."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

TZ_PATH = Path(__file__).resolve().parent.parent / "data" / "tz" / "tzgrid.npz"
TZ_WEST, TZ_EAST, TZ_SOUTH, TZ_NORTH, TZ_STEP = -127.0, -65.0, 23.0, 52.0, 0.05


@lru_cache(maxsize=1)
def _load():
    z = np.load(TZ_PATH, allow_pickle=False)
    return z["idx"], [str(n) for n in z["names"]], float(z["west"]), float(z["north"]), float(z["step"])


def covered(bbox) -> bool:
    w, s, e, n = bbox
    return w >= TZ_WEST and e <= TZ_EAST and s >= TZ_SOUTH and n <= TZ_NORTH


def zone_index(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Zone index (into the returned names) for each lat/lon (arrays of the same shape)."""
    idx, names, west, north, step = _load()
    r = np.clip(((north - np.asarray(lat)) / step).astype(int), 0, idx.shape[0] - 1)
    c = np.clip(((np.asarray(lon) - west) / step).astype(int), 0, idx.shape[1] - 1)
    return idx[r, c].astype(int), names


def utc_offset_minutes(zone: str, day: dt.date) -> int:
    """UTC offset (minutes, DST included) in force at local noon on `day`."""
    return int(ZoneInfo(zone).utcoffset(dt.datetime.combine(day, dt.time(12))).total_seconds() // 60)


def offset_grid(lat: np.ndarray, lon: np.ndarray, day: dt.date) -> np.ndarray:
    """UTC offset in minutes for every cell on `day`."""
    zi, names = zone_index(lat, lon)
    table = np.array([utc_offset_minutes(n, day) for n in names], "float32")
    return table[zi]
