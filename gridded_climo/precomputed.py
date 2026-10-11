"""Reader/writer for the shipped precomputed data (Streamlit Cloud has no time for live multi-decade pulls).

data/occurrence/<element>_<op><value>_<direction>.npz
    years[Y] int16, offsets[Y,H,W] int16 (days since season start; -32768 = never crossed),
    west/north/dx/dy (grid), season_start/season_end [m, d]
data/normals/<element>_<y0>-<y1>.npz
    normals[366,H,W] int16 (x100; index = day of a leap year, Jan 1 = 0; Feb 29 = leap years only),
    years[...] (the normal period's years), west/north/dx/dy
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np

from .grid import Grid

NAN16 = np.iinfo("int16").min
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def occurrence_path(data_dir: Path, element: str, op: str, value: float, direction: str) -> Path:
    return Path(data_dir) / "occurrence" / f"{element}_{op}{value:g}_{direction}.npz"


def normals_path(data_dir: Path, element: str, period: tuple[int, int]) -> Path:
    return Path(data_dir) / "normals" / f"{element}_{period[0]}-{period[1]}.npz"


def has_occurrence(data_dir, element, op, value, direction) -> bool:
    return occurrence_path(Path(data_dir), element, op, value, direction).exists()


def _template(z) -> Grid:
    return Grid(np.zeros((z["offsets"].shape[1:] if "offsets" in z.files else z["normals"].shape[1:]), "float32"),
                float(z["west"]), float(z["north"]), float(z["dx"]), float(z["dy"]))


def load_occurrence(data_dir, element, op, value, direction):
    """-> (years[Y], offsets[Y,H,W] float32 with NaN, template Grid)."""
    p = occurrence_path(Path(data_dir), element, op, value, direction)
    if not p.exists():
        raise FileNotFoundError(f"no precomputed data at {p} (run `gridded-climo precompute`)")
    with np.load(p) as z:
        off = z["offsets"].astype("float32")
        off[z["offsets"] == NAN16] = np.nan
        return z["years"].astype(int), off, _template(z)


def load_normals(data_dir, element, period):
    """-> (normals[366,H,W] float32, years[...], template Grid)."""
    p = normals_path(Path(data_dir), element, period)
    if not p.exists():
        raise FileNotFoundError(f"no daily normals at {p} for {period[0]}-{period[1]} (run `gridded-climo precompute --normals`)")
    with np.load(p) as z:
        arr = z["normals"].astype("float32") / 100.0
        arr[z["normals"] == NAN16] = np.nan
        return arr, z["years"].astype(int), _template(z)


_LEAP_REF = dt.date(2000, 1, 1)  # leap year: index = day offset from Jan 1


def doy_index(d: dt.date) -> int:
    return (dt.date(2000, d.month, d.day) - _LEAP_REF).days


def actual_indices(start: dt.date, end: dt.date) -> np.ndarray:
    """Normal-array indices for each real calendar day in [start, end] (Feb 29 only when it really occurs)."""
    n = (end - start).days + 1
    return np.array([doy_index(start + dt.timedelta(days=i)) for i in range(n)])


def monthday_window(start_md: tuple[int, int], end_md: tuple[int, int], years: np.ndarray):
    """Indices + weights for a month/day window (may wrap the new year) averaged over the normal period.
    Feb 29 is weighted by the fraction of leap years in the period."""
    (sm, sd), (em, ed) = start_md, end_md
    cur = dt.date(2000, sm, sd)  # walk month-days in a leap year so Feb 29 is visited
    days = []
    while True:
        days.append(cur)
        if (cur.month, cur.day) == (em, ed):
            break
        cur = dt.date(2000, 1, 1) if (cur.month, cur.day) == (12, 31) else cur + dt.timedelta(days=1)
        if len(days) > 366:
            raise ValueError("bad month/day window")
    leap = np.mean([(y % 4 == 0 and y % 100 != 0) or y % 400 == 0 for y in years])
    idx = np.array([doy_index(x) for x in days])
    w = np.array([leap if (x.month, x.day) == (2, 29) else 1.0 for x in days])
    return idx, w


def shipped_years(data_dir=DATA_DIR) -> dict[str, tuple[int, int] | None]:
    """Year coverage of the shipped data ({'grid': (y0, y1), 'station': (y0, y1)}; None if absent), read from one file each."""
    out = {}
    for kind, path in (("grid", Path(data_dir) / "occurrence" / "mint_le32_first.npz"),
                       ("station", Path(data_dir) / "stations" / "mint_le32_first.npz")):
        try:
            with np.load(path) as z:
                ys = z["years"]
            out[kind] = (int(ys.min()), int(ys.max()))
        except (OSError, KeyError):
            out[kind] = None
    return out
