"""Offline builder for the data shipped in data/ (run locally or in a session with network access).

Resumable: daily ACIS pulls are cached per calendar quarter, and finished occurrence files are
extended (not rebuilt) when new years become available.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .acis import ACISClient, quarter_chunks
from .precomputed import NAN16, DATA_DIR, doy_index, normals_path, occurrence_path
from .products.climatology import crossing_offset, season_window
from .query import MENU, default_season

FIRST_YEAR = 1950  # ACIS Grid 1 starts 1950


def season_complete(season: dict, year: int, today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    return season_window(season, year)[1] < today - dt.timedelta(days=5)


def prefetch(client: ACISClient, element: str, bbox, start: dt.date, end: dt.date, workers: int = 3, log=print):
    """Warm the cache for every calendar quarter in [start, end] using a few parallel workers."""
    chunks = [c for c in quarter_chunks(start, end) if c[1] < dt.date.today() - dt.timedelta(days=5)]  # incomplete quarters are never cached
    done = 0

    def one(c):
        client.daily(element, bbox, c[0], c[1])
        return c

    with ThreadPoolExecutor(workers) as ex:
        for c in ex.map(one, chunks):
            done += 1
            if done % 20 == 0 or done == len(chunks):
                log(f"  prefetch {element}: {done}/{len(chunks)} quarters (through {c[1]})")


def _save_occurrence(path: Path, years, offsets, template, season):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.where(np.isfinite(offsets), offsets, NAN16).astype("int16")
    tmp = path.with_name(path.stem + ".tmp.npz")   # atomic replace: a reader never sees a half-written file
    np.savez_compressed(tmp, years=np.asarray(years, "int16"), offsets=arr, west=template.west, north=template.north,
                        dx=template.dx, dy=template.dy, season_start=season["start"], season_end=season["end"])
    tmp.replace(path)


def build_occurrence(client, bbox, element, op, direction, thresholds, y0=FIRST_YEAR, data_dir=DATA_DIR, log=print):
    """Per-year first/last crossing offsets for every threshold in `thresholds` (one daily pull per season)."""
    season = default_season(op, direction)
    paths = {t: occurrence_path(data_dir, element, op, t, direction) for t in thresholds}
    have = {}
    for t, p in paths.items():
        if p.exists():
            with np.load(p) as z:
                have[t] = (z["years"].astype(int).tolist(), z["offsets"])
    done_years = set.intersection(*(set(v[0]) for v in have.values())) if len(have) == len(thresholds) else set()
    todo = [y for y in range(y0, dt.date.today().year + 1) if season_complete(season, y) and y not in done_years]
    if not todo:
        log(f"{element} {op} {direction}: up to date")
        return
    stacks, template = {t: {} for t in thresholds}, None
    for y in todo:
        s, e = season_window(season, y)
        _, tmpl, daily = client.daily(element, bbox, s, e)
        template = template or tmpl
        for t in thresholds:
            stacks[t][y] = crossing_offset(daily, op, t, direction)
        log(f"  {element} {op} {direction} {y}")
    for t in thresholds:
        years = sorted(set(stacks[t]) | (set(have[t][0]) if t in have and done_years else set()))
        old = dict(zip(have[t][0], have[t][1])) if t in have else {}
        rows = [stacks[t][y] if y in stacks[t] else np.where(old[y] == NAN16, np.nan, old[y]).astype("float32") for y in years]
        _save_occurrence(paths[t], years, np.stack(rows), template, season)
    log(f"{element} {op} {direction}: wrote {len(thresholds)} files ({len(todo)} new years)")


def build_normals(client, bbox, element, period=(1991, 2020), data_dir=DATA_DIR, log=print):
    """366-day mean-by-calendar-day grids over `period` (Feb 29 averaged over leap years only)."""
    path = normals_path(data_dir, element, period)
    if path.exists():
        log(f"{path.name}: exists")
        return
    total, count, template = None, None, None
    for y in range(period[0], period[1] + 1):
        dates, tmpl, daily = client.daily(element, bbox, dt.date(y, 1, 1), dt.date(y, 12, 31))
        template = template or tmpl
        if total is None:
            total = np.zeros((366,) + daily.shape[1:], "float64")
            count = np.zeros_like(total, dtype="int16")
        idx = np.array([doy_index(d.astype(object)) for d in dates])
        ok = np.isfinite(daily)
        total[idx] += np.where(ok, daily, 0)
        count[idx] += ok
        log(f"  normals {element} {y}")
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / count, np.nan)
    stored = np.where(np.isfinite(mean), np.rint(mean * 100), NAN16).astype("int16")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, normals=stored, years=np.arange(period[0], period[1] + 1, dtype="int16"), west=template.west,
                        north=template.north, dx=template.dx, dy=template.dy)
    log(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")


def run_precompute(client, bbox, elements=("mint", "maxt"), normals=("mint", "maxt", "pcpn"), period=(1991, 2020),
                   y0=FIRST_YEAR, data_dir=DATA_DIR, workers=3, log=print):
    today = dt.date.today()
    need: dict[str, tuple[int, int]] = {}
    for el in set(elements) | set(normals):
        need[el] = (y0 if el in elements else period[0], today.year if el in elements else period[1])
    for el, (a, b) in need.items():
        prefetch(client, el, bbox, dt.date(a, 1, 1), min(dt.date(b, 12, 31), today), workers, log)
    for (el, op), thresholds in MENU.items():
        if el in elements:
            for direction in ("first", "last"):
                build_occurrence(client, bbox, el, op, direction, thresholds, y0, data_dir, log)
    for el in normals:
        build_normals(client, bbox, el, period, data_dir, log)


def run_precompute_stations(client, bbox, elements=("mint", "maxt", "snow"), y0=FIRST_YEAR, data_dir=DATA_DIR, log=print,
                            only_missing: bool = False):
    """Server-side threshold search: one request per (element, op, direction, threshold) covering every station and season."""
    from .query import STATION_MENU
    from .stations import build_station_occurrence_server
    for (el, op), thresholds in STATION_MENU.items():
        if el in elements:
            for direction in ("first", "last"):
                build_station_occurrence_server(client, bbox, el, op, direction, thresholds, default_season(op, direction, el),
                                                y0, data_dir, log, only_missing)


def prune_unlisted(data_dir=DATA_DIR, log=print) -> int:
    """Delete pre-saved occurrence/station files whose threshold is no longer in MENU / STATION_MENU. Returns the count removed."""
    import re
    from .query import MENU, STATION_MENU
    pat = re.compile(r"^(?P<el>[a-z]+)_(?P<op>le|ge)(?P<v>-?[\d.]+)_(?:first|last)\.npz$")
    removed = 0
    for sub, menu in (("occurrence", MENU), ("stations", STATION_MENU)):
        for f in sorted((Path(data_dir) / sub).glob("*.npz")):
            m = pat.match(f.name)
            if not m or float(m["v"]) not in {float(x) for x in menu.get((m["el"], m["op"]), ())}:
                f.unlink(); removed += 1
    log(f"pruned {removed} files no longer in the threshold menus")
    return removed
