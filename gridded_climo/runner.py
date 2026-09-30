"""Execute a Metric/Query and return a renderable result. The single code path used by the CLI and Streamlit."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from .acis import ACISClient
from .cache import Cache
from .config import Settings
from .grid import Grid
from .nohrsc import NOHRSC
from .precomputed import DATA_DIR
from .products.climatology import climatology
from .products.period import normal_window_average, period_summary
from .query import Query, metric_from_query
from .registry import Metric, Style


@dataclass
class Result:
    grid: Grid
    name: str
    style: Style
    label_fmt: Callable[[float], str] | None
    slug: str
    note: str = ""
    points: dict | None = None  # station markers for the preview (station method)


def _to_date(d) -> dt.date:
    return d.date() if isinstance(d, dt.datetime) else d


def run_metric(metric: Metric, st: Settings, start=None, end=None, method: str = "auto", data_dir=DATA_DIR,
               allow_live: bool = True, log=print, reports: bool = False) -> Result:
    cache = Cache(st.cache_dir)
    client = ACISClient(st.acis_base_url, cache) if allow_live else None  # None = shipped data only
    name, label_fmt, note, points = metric.title or metric.name, None, "", None

    if metric.kind == "climatology":
        grid, info = climatology(metric, client, st.bbox, st.normal_period, data_dir, log)
        ref = dt.date(2001, info["ref_month"], info["ref_day"])  # non-leap reference year
        label_fmt = lambda v: (ref + dt.timedelta(days=int(round(v)))).strftime("%b %-d")
        name += f" ({info['years'][0]}-{info['years'][1]})"
        points = info.get("points")
        if info["source"] == "station":
            note = f"Station-based: {len(points['value'])} stations interpolated (IDW + 12 km smoothing, 80 km max)"
        else:
            note = "ACIS Grid 1 (precomputed)" if info["source"] == "precomputed" else "ACIS Grid 1, computed live"
    elif metric.kind == "period":
        if not (start and end):
            raise ValueError("period metrics need a start and end")
        s, e = _to_date(start), _to_date(end)
        if metric.normal == "average":
            grid, info = normal_window_average(metric, st.bbox, (s.month, s.day), (e.month, e.day), st.normal_period, data_dir)
            name += f" ({s:%b %-d}–{e:%b %-d}, {info['years'][0]}-{info['years'][1]} average)"
        else:
            if client is None:
                raise RuntimeError("live ACIS access is disabled")
            grid = period_summary(metric, client, st.bbox, s, e, st.normal_period, data_dir, log)
            name += f" ({s} to {e})" + (f", vs {st.normal_period[0]}-{st.normal_period[1]} normal" if metric.normal else "")
    elif metric.kind == "storm":
        if not (start and end):
            raise ValueError("storm metrics need a start and end time")
        s, e = (x if isinstance(x, dt.datetime) else dt.datetime.combine(x, dt.time()) for x in (start, end))
        grid, used = NOHRSC(st.nohrsc_base_url, cache).storm_total(s, e, st.bbox, method)
        name += f" ({s:%b %-d %HZ} – {e:%b %-d %HZ}, NOHRSC)"
        note = f"NOHRSC method: {used}"
        label_fmt = lambda v: f'{v:g}"'
        if reports:
            import numpy as np
            from .iem import fetch_snow_reports
            try:
                pts = fetch_snow_reports(s, e, st.bbox)
                points = {k: np.array(v) for k, v in pts.items()}
                note += f"; {len(pts['value'])} NWS snow reports (IEM)"
            except Exception as ex:  # overlay is optional: never fail the map over it
                note += f"; storm reports unavailable ({type(ex).__name__})"
    else:
        raise ValueError(metric.kind)
    return Result(grid, name, metric.style, label_fmt, metric.name, note, points)


def run_query(q: Query, st: Settings | None = None, data_dir=DATA_DIR, allow_live: bool = True, log=print) -> Result:
    st = st or Settings()
    st = Settings(bbox=st.bbox, normal_period=q.normal_period, cache_dir=st.cache_dir,
                  acis_base_url=st.acis_base_url, nohrsc_base_url=st.nohrsc_base_url)
    return run_metric(metric_from_query(q), st, q.start, q.end, q.extra.get("method", "auto"), data_dir, allow_live, log,
                      reports=bool(q.extra.get("reports")))
