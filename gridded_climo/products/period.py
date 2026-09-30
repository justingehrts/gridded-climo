"""Single date-range summaries (sum/mean/max/min), optionally as departure from the normal period."""
from __future__ import annotations

import datetime as dt

import warnings

import numpy as np

from ..grid import Grid
from ..registry import Metric

_REDUCERS = {"sum": np.nansum, "mean": np.nanmean, "max": np.nanmax, "min": np.nanmin}


def reduce_daily(daily: np.ndarray, how: str) -> np.ndarray:
    """(T,H,W) -> (H,W). All-NaN cells stay NaN (nansum would otherwise make them 0)."""
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = _REDUCERS[how](daily, axis=0)
    return np.where(np.isfinite(daily).any(axis=0), out, np.nan).astype("float32")


def _shift_year(d: dt.date, year: int) -> dt.date:
    try:
        return d.replace(year=year)
    except ValueError:  # Feb 29 in a non-leap year
        return d.replace(year=year, day=28)


def period_summary(metric: Metric, client, bbox, start: dt.date, end: dt.date, normal_period, log=print) -> Grid:
    _, template, daily = client.daily(metric.element, bbox, start, end)
    value = reduce_daily(daily, metric.reduce)
    if metric.normal == "departure":
        # Computed client-side from the same daily grids: GridData's "normal" param returned
        # raw values in testing, so we don't rely on it.
        clim = []
        for y in range(normal_period[0], normal_period[1] + 1):
            s, e = _shift_year(start, y), _shift_year(end, y + (end.year - start.year))
            clim.append(reduce_daily(client.daily(metric.element, bbox, s, e)[2], metric.reduce))
            log(f"  normal {y}")
        value = value - np.nanmean(np.stack(clim), axis=0)
    return template.with_data(value)
