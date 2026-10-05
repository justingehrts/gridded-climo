"""Regions: states (with a buffer) and what the pre-saved data covers.

State outlines come from ACIS (General/state), saved once in states.json. A state map gets a buffer so neighbors and the
surrounding area show: 10% of the state's longer side, never less than 0.75 deg (~80 km) nor more than 2 deg.
Pre-saved data (grid first/last dates, daily normals, per-station files) only covers config.DEFAULT_BBOX, so anything that
needs it is limited to that region; stations and storm snowfall work anywhere in the lower 48."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import DEFAULT_BBOX

BBox = tuple[float, float, float, float]  # west, south, east, north
BUFFER_FRAC, BUFFER_MIN, BUFFER_MAX = 0.10, 0.75, 2.0
CONUS_BOUNDS: BBox = (-125.5, 24.0, -66.0, 50.0)     # ACIS Grid 1 / NOHRSC extent, lower 48
PRESAVED_REGION: BBox = DEFAULT_BBOX
MIN_PRESAVED_COVER = 0.9      # a request mostly inside the pre-saved region is cropped to it; below this it's treated as outside
LIVE_VALUE_BUDGET = 12_000_000   # cells x days we're willing to pull live from ACIS per map (a full year over the default region is ~10M)
CELLS_PER_SQ_DEG = 24 * 24       # ACIS Grid 1 is 1/24 degree


@lru_cache(maxsize=1)
def states() -> dict[str, dict]:
    """{'OH': {'name': 'Ohio', 'bbox': [w, s, e, n]}, ...} for the lower 48 + DC."""
    return json.loads((Path(__file__).with_name("states.json")).read_text())


def state_names() -> dict[str, str]:
    """{'Ohio': 'OH', ...} sorted by name."""
    return {v["name"]: k for k, v in sorted(states().items(), key=lambda kv: kv[1]["name"])}


def buffer_deg(bbox: BBox) -> float:
    w, s, e, n = bbox
    return min(BUFFER_MAX, max(BUFFER_MIN, BUFFER_FRAC * max(e - w, n - s)))


def buffered_bbox(code: str) -> BBox:
    """The state's box plus its buffer on every side, kept inside the lower-48 data extent."""
    if code not in states():
        raise KeyError(f"unknown state '{code}'")
    w, s, e, n = states()[code]["bbox"]
    b = buffer_deg((w, s, e, n))
    cw, cs, ce, cn = CONUS_BOUNDS
    return (round(max(w - b, cw), 3), round(max(s - b, cs), 3), round(min(e + b, ce), 3), round(min(n + b, cn), 3))


def area_sq_deg(bbox: BBox) -> float:
    w, s, e, n = bbox
    return max(e - w, 0.0) * max(n - s, 0.0)


def intersection(a: BBox, b: BBox) -> BBox | None:
    w, s, e, n = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (w, s, e, n) if w < e and s < n else None


def coverage_fraction(bbox: BBox, region: BBox = PRESAVED_REGION) -> float:
    """Share of `bbox`'s area that lies inside `region`."""
    inter = intersection(bbox, region)
    return area_sq_deg(inter) / area_sq_deg(bbox) if inter and area_sq_deg(bbox) else 0.0


def presaved_bbox(bbox: BBox) -> BBox | None:
    """`bbox` cropped to the pre-saved region if (nearly) all of it is inside, else None (pre-saved data can't serve it)."""
    if coverage_fraction(bbox) < MIN_PRESAVED_COVER:
        return None
    return intersection(bbox, PRESAVED_REGION)


def max_live_days(bbox: BBox) -> int:
    """How many days of daily grids we'll pull live for this area (keeps big states from exhausting a hosted app's memory)."""
    cells = max(area_sq_deg(bbox) * CELLS_PER_SQ_DEG, 1.0)
    return int(LIVE_VALUE_BUDGET // cells)
