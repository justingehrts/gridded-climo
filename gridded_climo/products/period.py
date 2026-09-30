"""Date-range products: single-period summaries, departure from normal, and same-dates-averaged-over-normal-period."""
from __future__ import annotations

import datetime as dt
import warnings

import numpy as np

from ..grid import Grid
from ..precomputed import DATA_DIR, actual_indices, load_normals, monthday_window
from ..registry import Metric

_REDUCERS = {"sum": np.nansum, "mean": np.nanmean, "max": np.nanmax, "min": np.nanmin}


def reduce_daily(daily: np.ndarray, how: str) -> np.ndarray:
    """(T,H,W) -> (H,W). All-NaN cells stay NaN (nansum would otherwise make them 0)."""
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = _REDUCERS[how](daily, axis=0)
    return np.where(np.isfinite(daily).any(axis=0), out, np.nan).astype("float32")


def weighted_reduce(stack: np.ndarray, weights: np.ndarray, how: str) -> np.ndarray:
    """Weighted sum or mean over axis 0 (NaN-aware: a cell's mean uses only the weights of valid days)."""
    w = weights[:, None, None] * np.isfinite(stack)
    total = np.nansum(stack * weights[:, None, None], axis=0)
    if how == "sum":
        return np.where(w.sum(axis=0) > 0, total, np.nan).astype("float32")
    if how == "mean":
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(w.sum(axis=0) > 0, total / w.sum(axis=0), np.nan).astype("float32")
    raise ValueError(f"'{how}' can't be computed from daily normals (only sum/mean)")


def normal_window_average(metric: Metric, bbox, start_md, end_md, normal_period, data_dir=DATA_DIR) -> tuple[Grid, dict]:
    """Same month/day window averaged over the normal period, from shipped daily normals."""
    normals, years, template = load_normals(data_dir, metric.element, normal_period)
    idx, w = monthday_window(start_md, end_md, years)
    out = weighted_reduce(normals[idx], w, metric.reduce)
    return template.with_data(out).clip(bbox), {"years": (int(years.min()), int(years.max()))}


def period_summary(metric: Metric, client, bbox, start: dt.date, end: dt.date, normal_period, data_dir=DATA_DIR, log=print) -> Grid:
    """One real date range from live ACIS daily grids; optionally minus the daily normals for the same days."""
    _, template, daily = client.daily(metric.element, bbox, start, end)
    value = reduce_daily(daily, metric.reduce)
    if metric.normal == "departure":
        normals, _, ntemplate = load_normals(data_dir, metric.element, normal_period)
        sel = normals[actual_indices(start, end)]
        rows, cols = ntemplate.window_of(template)
        value = value - weighted_reduce(sel[:, rows, cols], np.ones(len(sel), "float32"), metric.reduce)
    return template.with_data(value)
