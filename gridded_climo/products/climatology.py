"""Multi-year threshold-crossing climatology, computed client-side from cached daily ACIS grids."""
from __future__ import annotations

import datetime as dt
import operator

import warnings

import numpy as np

from ..grid import Grid
from ..registry import Metric

_OPS = {"le": operator.le, "lt": operator.lt, "ge": operator.ge, "gt": operator.gt}


def crossing_offset(daily: np.ndarray, op: str, value: float, direction: str) -> np.ndarray:
    """(T,H,W) daily values -> (H,W) float offset (days from window start) of the first/last
    day where `daily <op> value`; NaN where it never happens. NaN inputs never satisfy the test."""
    with np.errstate(invalid="ignore"):
        hit = _OPS[op](daily, value) & np.isfinite(daily)
    t = hit.shape[0]
    idx = np.argmax(hit, axis=0) if direction == "first" else t - 1 - np.argmax(hit[::-1], axis=0)
    return np.where(hit.any(axis=0), idx, np.nan).astype("float32")


def season_window(season: dict, year: int) -> tuple[dt.date, dt.date]:
    (sm, sd), (em, ed) = season["start"], season["end"]
    start = dt.date(year, sm, sd)
    end = dt.date(year + (1 if (em, ed) < (sm, sd) else 0), em, ed)
    return start, end


def cross_year_stat(stack: np.ndarray, stat: str, p: float | None = None, min_frac: float = 0.5) -> np.ndarray:
    """(Y,H,W) per-year offsets (NaN = no crossing) -> (H,W). Cells with crossings in fewer
    than `min_frac` of years are masked (e.g. a place that only rarely sees the threshold)."""
    enough = np.isfinite(stack).mean(axis=0) >= min_frac
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if stat == "mean":
            out = np.nanmean(stack, axis=0)
        elif stat == "median":
            out = np.nanmedian(stack, axis=0)
        elif stat == "percentile":
            out = np.nanpercentile(stack, p, axis=0)
        else:
            raise ValueError(stat)
    return np.where(enough, out, np.nan).astype("float32")


def climatology(metric: Metric, client, bbox, normal_period: tuple[int, int], log=print) -> tuple[Grid, dict]:
    """Returns (grid of days-since-season-start, info). info['ref_date'] = month/day that offset 0 means."""
    if metric.source != "acis_grid1":
        raise NotImplementedError(f"source '{metric.source}' is not implemented yet (snow climatology needs the station path)")
    thr = metric.threshold
    per_year, template = [], None
    years = range(normal_period[0], normal_period[1] + 1)
    for y in years:
        start, end = season_window(metric.season, y)
        _, tmpl, daily = client.daily(metric.element, bbox, start, end)
        template = template or tmpl
        per_year.append(crossing_offset(daily, thr["op"], thr["value"], metric.direction))
        log(f"  {metric.name} {y}: {np.isfinite(per_year[-1]).mean():.0%} of cells crossed")
    cy = metric.cross_year
    out = cross_year_stat(np.stack(per_year), cy["stat"], cy.get("p"), metric.min_years_frac)
    sm, sd = metric.season["start"]
    return template.with_data(out), {"ref_month": sm, "ref_day": sd, "years": (years[0], years[-1])}
