"""Station-based first/last threshold dates (ACIS MultiStnData) + shipped per-station results.

ACIS's server-side yearly first/last reduce ignores season_start (returns calendar-year dates), so, as with
grids, daily values are pulled per season and scanned client-side.

data/stations/<element>_<op><value>_<direction>.npz
    sids[S], lon[S], lat[S], name[S], years[Y] int16, offsets[Y,S] int16 (days since season start;
    NO_CROSS = season valid but threshold never met; INVALID = too much missing data to call)
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import numpy as np

from .acis import ACISClient
from .precomputed import DATA_DIR
from .products.climatology import crossing_offset, season_window

NO_CROSS = -32767
INVALID = -32768
MAX_MISSING_FRAC = 0.10
_NUM = re.compile(r"^-?\d+(\.\d+)?")


def station_path(data_dir: Path, element: str, op: str, value: float, direction: str) -> Path:
    return Path(data_dir) / "stations" / f"{element}_{op}{value:g}_{direction}.npz"


def parse_value(raw, element: str) -> float:
    """ACIS daily cell -> float. M = missing; T = trace (0 for thresholding); trailing flags dropped.
    For snow, 'A' (multi-day accumulation) is treated as missing so one big total can't fake a daily amount."""
    v = raw[0] if isinstance(raw, (list, tuple)) else raw
    v = str(v).strip()
    if v in ("M", "", "S"):
        return np.nan
    if v == "T":
        return 0.0
    if element == "snow" and v.endswith("A"):
        return np.nan
    m = _NUM.match(v)
    return float(m.group()) if m else np.nan


def fetch_season(client: ACISClient, bbox, element: str, start: dt.date, end: dt.date):
    """-> dict(sids[S], lon[S], lat[S], name[S], data[T,S] float32). Cached per request when the client has a cache."""
    params = {"bbox": ",".join(f"{v:g}" for v in bbox), "sdate": start.isoformat(), "edate": end.isoformat(),
              "elems": [{"name": element, "interval": "dly", "duration": "dly"}], "meta": ["name", "ll", "sids"]}

    def fetch():
        out = client.post("MultiStnData", params)
        rows = [s for s in out["data"] if s["meta"].get("ll") and s["meta"].get("sids")]
        data = np.array([[parse_value(v, element) for v in s["data"]] for s in rows], dtype="float32").T
        stored = np.where(np.isfinite(data), np.rint(data * 100), np.iinfo("int16").min).astype("int16")
        return {"sids": np.array([s["meta"]["sids"][0] for s in rows]), "lon": np.array([s["meta"]["ll"][0] for s in rows]),
                "lat": np.array([s["meta"]["ll"][1] for s in rows]), "name": np.array([s["meta"].get("name", "") for s in rows]),
                "stored": stored}

    complete = end < dt.date.today() - dt.timedelta(days=5)
    arrays = client.cache.get_or_compute("acis_stn_v1", params, fetch) if (client.cache and complete) else fetch()
    data = np.where(arrays["stored"] == np.iinfo("int16").min, np.nan, arrays["stored"].astype("float32") / 100).astype("float32")
    return {**{k: arrays[k] for k in ("sids", "lon", "lat", "name")}, "data": data}


def station_offsets(data: np.ndarray, op: str, value: float, direction: str) -> np.ndarray:
    """data[T,S] -> int16 [S]: day offset of first/last crossing, NO_CROSS, or INVALID (too many missing days)."""
    valid = np.isfinite(data).mean(axis=0) >= 1 - MAX_MISSING_FRAC
    off = crossing_offset(data[:, :, None], op, value, direction)[:, 0]
    return np.where(~valid, INVALID, np.where(np.isfinite(off), off, NO_CROSS)).astype("int16")


def build_station_occurrence(client, bbox, element, op, direction, thresholds, season, y0=1950, data_dir=DATA_DIR, log=print):
    """One MultiStnData pull per season, all thresholds at once. Resumable like the grid builder."""
    paths = {t: station_path(data_dir, element, op, t, direction) for t in thresholds}
    done = set()
    if all(p.exists() for p in paths.values()):
        done = set.intersection(*(set(np.load(p)["years"].astype(int).tolist()) for p in paths.values()))
    todo = [y for y in range(y0, dt.date.today().year + 1)
            if season_window(season, y)[1] < dt.date.today() - dt.timedelta(days=5) and y not in done]
    if not todo:
        log(f"stations {element} {op} {direction}: up to date")
        return
    per_year = {}
    for y in todo:
        s, e = season_window(season, y)
        d = fetch_season(client, bbox, element, s, e)
        per_year[y] = (d, {t: station_offsets(d["data"], op, t, direction) for t in thresholds})
        log(f"  stations {element} {op} {direction} {y}: {len(d['sids'])} stations")
    for t, p in paths.items():
        old = np.load(p, allow_pickle=False) if p.exists() else None
        sids = list(old["sids"]) if old is not None else []
        index = {s: i for i, s in enumerate(sids)}
        meta = {"lon": list(old["lon"]) if old is not None else [], "lat": list(old["lat"]) if old is not None else [],
                "name": list(old["name"]) if old is not None else []}
        for y in todo:
            d = per_year[y][0]
            for j, sid in enumerate(d["sids"]):
                if sid not in index:
                    index[sid] = len(sids); sids.append(sid)
                    for k in meta:
                        meta[k].append(d[k][j])
        years = sorted(set(todo) | (set(old["years"].astype(int).tolist()) if old is not None else set()))
        table = np.full((len(years), len(sids)), INVALID, "int16")
        if old is not None:
            for i, y in enumerate(old["years"].astype(int)):
                table[years.index(y), : old["offsets"].shape[1]] = old["offsets"][i]
        for y in todo:
            d, offs = per_year[y]
            cols = [index[s] for s in d["sids"]]
            table[years.index(y), cols] = offs[t]
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.stem + ".tmp.npz")  # atomic replace: a reader never sees a half-written file
        np.savez_compressed(tmp, sids=np.array(sids), lon=np.array(meta["lon"], "float32"), lat=np.array(meta["lat"], "float32"),
                            name=np.array(meta["name"]), years=np.array(years, "int16"), offsets=table,
                            season_start=season["start"], season_end=season["end"])
        tmp.replace(p)
    log(f"stations {element} {op} {direction}: wrote {len(thresholds)} files ({len(todo)} new years)")


def load_station_occurrence(data_dir, element, op, value, direction):
    p = station_path(Path(data_dir), element, op, value, direction)
    if not p.exists():
        raise FileNotFoundError(f"no station data at {p} (run `gridded-climo precompute --stations`)")
    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def station_stat(z: dict, normal_period: tuple[int, int], stat: str, p: float | None = None,
                 min_valid_frac: float = 0.67, min_cross_frac: float = 0.5):
    """Per-station cross-year stat of first/last day offsets. -> (lon, lat, value, n_valid_years, sids, names).

    A station needs valid (enough-data) seasons in >= min_valid_frac of the period's years, and the threshold
    crossed in >= min_cross_frac of those valid seasons (a station that rarely reaches the threshold has no
    meaningful 'average date')."""
    years = z["years"].astype(int)
    want = np.arange(normal_period[0], normal_period[1] + 1)
    sel = np.isin(years, want)
    if sel.sum() < len(want):
        miss = sorted(set(want.tolist()) - set(years.tolist()))
        raise ValueError(f"station data covers {years.min()}-{years.max()}; normal period needs {miss[0]}-{miss[-1]} too")
    off = z["offsets"][sel].astype("float32")
    valid = off != INVALID
    crossed = valid & (off != NO_CROSS)
    off = np.where(crossed, off, np.nan)
    n_valid, n_cross = valid.sum(axis=0), crossed.sum(axis=0)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        val = {"mean": lambda: np.nanmean(off, axis=0), "median": lambda: np.nanmedian(off, axis=0),
               "percentile": lambda: np.nanpercentile(off, p, axis=0),
               "min": lambda: np.nanmin(off, axis=0), "max": lambda: np.nanmax(off, axis=0)}[stat]()
    ok = (n_valid >= max(1, min(min_valid_frac * len(want), 25))) & (n_cross >= min_cross_frac * np.maximum(n_valid, 1)) & np.isfinite(val)
    station_stat.last_mask = ok  # exposed for extreme_years(); valid until the next call
    return z["lon"][ok], z["lat"][ok], val[ok].astype("float32"), n_valid[ok], z["sids"][ok], z["name"][ok]


def extreme_years(z: dict, normal_period: tuple[int, int], stat: str, keep: np.ndarray) -> np.ndarray:
    """For stat min/max: the (first) year each kept station set its record. `keep` is the boolean mask station_stat used."""
    years = z["years"].astype(int)
    sel = np.isin(years, np.arange(normal_period[0], normal_period[1] + 1))
    off = z["offsets"][sel].astype("float32")
    off = np.where((off != INVALID) & (off != NO_CROSS), off, np.nan)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        idx = np.nanargmin(off, axis=0) if stat == "min" else np.nanargmax(off, axis=0)
    return years[sel][idx][keep]


# ---------------------------------------------------------------------------------------------------------------
# Server-side threshold search (the request shape xmACIS uses). Verified 2026-10: matches the local daily scan above
# on 12,855 station-years with 0 differences, and returns every station for every season in ONE request (~12-25 s).
#   interval [1,0,0] + duration "std" + season_start "MM-DD" + reduce {reduce: "first_le_32", add: "value,mcnt"}
#   sdate/edate are the *season-end* dates of the first/last season (std = season-to-date as of each yearly step)
#   cell = [date | "M", value | "M", missing_day_count]; "M" with a small count = threshold never reached,
#   "M" with a count near the season length = station has no data.
# GridData does NOT accept first/last reduces ("firstlast" error), so the grid method keeps the daily scan.
# ---------------------------------------------------------------------------------------------------------------
def _threshold_code(element: str, op: str, value: float, direction: str) -> str:
    v = f"{value:.1f}" if element in ("snow", "pcpn", "snwd") else f"{int(round(value))}"
    return f"{direction}_{op}_{v}"


def threshold_request(bbox, element, op, value, direction, season, y0: int, y1: int) -> dict:
    (sm, sd) = season["start"]
    return {"bbox": ",".join(f"{v:g}" for v in bbox),
            "sdate": season_window(season, y0)[1].isoformat(), "edate": season_window(season, y1)[1].isoformat(),
            "elems": [{"name": element, "interval": [1, 0, 0], "duration": "std", "season_start": f"{sm:02d}-{sd:02d}",
                       "reduce": {"reduce": _threshold_code(element, op, value, direction), "add": "value,mcnt"}}],
            "meta": ["name", "ll", "sids"]}


def parse_threshold_response(out: dict, season: dict, y0: int, y1: int) -> dict:
    """-> dict(sids, lon, lat, name, years[Y] int16, offsets[Y,S] int16) in the shipped-file format."""
    rows = [r for r in out["data"] if r["meta"].get("ll") and r["meta"].get("sids")]
    years = list(range(y0, y1 + 1))
    table = np.full((len(years), len(rows)), INVALID, "int16")
    for j, r in enumerate(rows):
        if len(r["data"]) != len(years):
            raise ValueError(f"ACIS returned {len(r['data'])} seasons for {len(years)} requested ({r['meta'].get('name')})")
        for i, (cell,) in enumerate(r["data"]):
            date, _, mcnt = cell
            start, end = season_window(season, years[i])
            if mcnt / ((end - start).days + 1) > MAX_MISSING_FRAC:
                continue                                    # too much missing data to call (also: station has no data)
            table[i, j] = NO_CROSS if date == "M" else (dt.date.fromisoformat(date) - start).days
    return {"sids": np.array([r["meta"]["sids"][0] for r in rows]), "lon": np.array([r["meta"]["ll"][0] for r in rows], "float32"),
            "lat": np.array([r["meta"]["ll"][1] for r in rows], "float32"),
            "name": np.array([r["meta"].get("name", "") for r in rows]), "years": np.array(years, "int16"), "offsets": table}


def last_complete_season(season: dict, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    y = today.year
    while season_window(season, y)[1] >= today - dt.timedelta(days=5):
        y -= 1
    return y


def fetch_station_thresholds(client: ACISClient, bbox, element, op, value, direction, season, y0, y1=None) -> dict:
    """One MultiStnData request for all stations/seasons in [y0, y1] (y1 defaults to the last complete season)."""
    y1 = y1 or last_complete_season(season)
    req = threshold_request(bbox, element, op, value, direction, season, y0, y1)
    out = client.post("MultiStnData", req)
    z = parse_threshold_response(out, season, y0, y1)
    z["season_start"], z["season_end"] = np.array(season["start"]), np.array(season["end"])
    return z


def build_station_occurrence_server(client, bbox, element, op, direction, thresholds, season, y0=1950, data_dir=DATA_DIR, log=print):
    """Write data/stations/<...>.npz for each threshold from one server-side request each (idempotent: rewrites the file)."""
    for t in thresholds:
        z = fetch_station_thresholds(client, bbox, element, op, t, direction, season, y0)
        p = station_path(data_dir, element, op, t, direction)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.stem + ".tmp.npz")
        np.savez_compressed(tmp, **z)
        tmp.replace(p)
        log(f"stations {element} {op}{t:g} {direction}: {z['offsets'].shape[1]} stations x {z['offsets'].shape[0]} seasons ({z['years'][0]}-{z['years'][-1]})")
