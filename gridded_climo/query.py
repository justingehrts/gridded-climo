"""A UI-level request (When x What x options) -> registry Metric. Shared by the CLI and Streamlit."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from .precomputed import DATA_DIR, shipped_years
from .registry import Metric, Style

WHENS = ("first", "last", "range_specific", "range_normal")
TEMP_ELEMENTS = {"mint": "Low (min) temperature", "maxt": "High (max) temperature"}
# Thresholds with precomputed per-year grids in data/occurrence (see precompute.py)
MENU: dict[tuple[str, str], tuple[int, ...]] = {
    ("mint", "le"): (40, 36, 32, 28, 25, 20, 10, 0),
    ("maxt", "le"): (40, 32, 20, 10, 0),
    ("maxt", "ge"): (70, 80, 85, 90, 95, 100),
    ("mint", "ge"): (60, 65, 70, 75),
}
STATION_MENU: dict[tuple[str, str], tuple[float, ...]] = {**MENU, ("snow", "ge"): (0.1, 1.0, 3.0, 6.0)}
NOHRSC_START = dt.datetime(2008, 10, 1)


def allow_live() -> bool:
    return os.environ.get("GRIDDED_CLIMO_ALLOW_LIVE") == "1"


def default_season(op: str, direction: str, element: str | None = None) -> dict[str, list[int]]:
    """Cold-side thresholds (<=) run on a Jul-Jun cool season (first = fall, last = spring); snow always does;
    warm-side thresholds (>=) use the calendar year."""
    if element == "snow":
        return {"start": [7, 1], "end": [6, 30]}
    if op in ("le", "lt"):
        return {"start": [7, 1], "end": [6, 30]} if direction == "first" else {"start": [1, 1], "end": [6, 30]}
    return {"start": [1, 1], "end": [12, 31]}


@dataclass
class Query:
    when: str                      # first | last | range_specific | range_normal
    element: str                   # mint | maxt | pcpn | snow
    op: str | None = None          # le | ge   (first/last only)
    value: float | None = None     # threshold X (first/last only)
    reduce: str = "mean"           # sum|mean|max|min (range modes)
    start: dt.datetime | dt.date | None = None
    end: dt.datetime | dt.date | None = None
    departure: bool = False        # range_specific only
    stat: str = "mean"             # cross-year: mean|median|percentile
    percentile: float = 50.0
    normal_period: tuple[int, int] = (1991, 2020)
    season: dict[str, list[int]] | None = None   # override default_season
    method: str = "grid"           # first/last only: grid (ACIS Grid 1) | station (MultiStnData, interpolated)
    extra: dict = field(default_factory=dict)


def unsupported_reason(q: Query) -> str | None:
    """None if runnable, else a short user-facing explanation (UI disables / CLI errors)."""
    if q.when not in WHENS:
        return f"unknown 'when': {q.when}"
    if q.when in ("first", "last"):
        method = "station" if q.element == "snow" else q.method
        if method not in ("grid", "station"):
            return f"unknown method '{q.method}'"
        if q.element == "snow" and q.op != "ge":
            return "Snowfall first/last dates use 'at or above' an amount."
        if q.element not in TEMP_ELEMENTS and q.element != "snow":
            return "First/last dates are available for temperature and snowfall thresholds."
        if q.op not in ("le", "ge") or q.value is None:
            return "Choose 'at or below' / 'at or above' and a threshold."
        if method == "station":
            lo, hi = (-60, 140) if q.element != "snow" else (0.1, 60)
            if not lo <= q.value <= hi:
                return f"Threshold should be between {lo} and {hi}."
            if q.normal_period[0] < 1900:
                return "Station data is used from 1900 onward."
            return None
        cover = shipped_years(DATA_DIR).get("grid")  # grid first/last dates come only from shipped data (GridData has no server-side first/last)
        if cover and q.season is None and not allow_live():
            if q.normal_period[0] < cover[0] or q.normal_period[1] > cover[1]:
                return f"Grid data ships for {cover[0]}-{cover[1]}; choose Stations to use other years."
        if q.season is None and not allow_live() and q.value not in MENU.get((q.element, q.op), ()):
            return f"{q.value:g} isn't in the precomputed grid menu for this variable (available: {list(MENU.get((q.element, q.op), ()))}); Stations accepts any value."
        return None
    if q.element == "snow":
        if q.when == "range_normal":
            return "Snowfall averaged over a normal period is coming soon (needs the station path)."
        if q.departure:
            return "Snowfall departure from normal is coming soon."
        if not (q.start and q.end):
            return "Choose a start and end time."
        if isinstance(q.start, dt.datetime) and q.start < NOHRSC_START:
            return "NOHRSC snowfall analyses begin Oct 2008."
        return None
    if q.element not in ("mint", "maxt", "pcpn"):
        return f"unsupported element '{q.element}'"
    if q.when == "range_normal" and q.reduce not in ("mean", "sum"):
        return "Averaging over the normal period supports mean and total only (not max/min)."
    if q.departure and q.reduce not in ("mean", "sum"):
        return "Departure from normal supports mean and total only (not max/min)."
    if q.when == "range_specific" and not (q.start and q.end):
        return "Choose a start and end date."
    if q.when == "range_specific" and (q.end - q.start).days > 366:
        return "Choose a range of one year or less."
    if q.when == "range_specific" and q.end < q.start:
        return "The end date is before the start date."
    if q.when == "range_normal" and not (q.start and q.end):
        return "Choose a month/day start and end."
    return None


def _style(q: Query) -> Style:
    if q.when in ("first", "last"):
        # Warmer = red. Later first-<=X and earlier last-<=X are warmer; the reverse holds for >=X.
        return Style(ramp="RdYlBu", reverse=(q.when == "first") == (q.op == "le"), mode="stepped", steps=12, units_label="date")
    if q.element == "snow":
        return Style(ramp="Blues", mode="stepped", steps=10, vmin=0.5, vmax=24, hide_below=0.1, units_label="in")
    if q.departure:
        return Style(ramp="coolwarm", mode="stepped", steps=12, symmetric=True,
                     units_label="in" if q.element == "pcpn" else "°F")
    if q.element == "pcpn":
        return Style(ramp="YlGnBu", mode="stepped", steps=10, units_label="in")
    return Style(ramp="Spectral", reverse=True, mode="stepped", steps=12, units_label="°F")


def _stat_prefix(q: Query) -> str:
    return {"mean": "Average Date of", "median": "Median Date of", "min": "Earliest", "max": "Latest",
            "percentile": f"{q.percentile:g}th Percentile Date of"}[q.stat]


def describe(q: Query) -> str:
    el = {"mint": "Low", "maxt": "High", "pcpn": "Precipitation", "snow": "Snowfall"}[q.element]
    if q.when in ("first", "last"):
        rel = "at or below" if q.op == "le" else "at or above"
        what = (f"Snowfall of {q.value:g}\" or More" if q.element == "snow"
                else f"{el} Temperature {rel} {q.value:g}°F")
        title = f"{_stat_prefix(q)} {q.when.title()} {what}"
        return title + (" on Record" if q.stat in ("min", "max") else "")
    kind = {"mean": "Average", "sum": "Total", "max": "Maximum", "min": "Minimum"}[q.reduce]
    if q.element == "snow":
        return "Snowfall Total"
    label = f"{kind} {el}" if q.element != "pcpn" else f"{kind if q.reduce != 'mean' else 'Average'} Precipitation"
    return label + (" Departure from Normal" if q.departure else "")


def metric_from_query(q: Query) -> Metric:
    why = unsupported_reason(q)
    if why:
        raise ValueError(why)
    style, title = _style(q), describe(q)
    if q.when in ("first", "last"):
        return Metric(
            name=f"{q.when}_{q.element}_{q.op}{q.value:g}", kind="climatology", element=q.element,
            source="acis_stn" if (q.element == "snow" or q.method == "station") else "acis_grid1",
            title=title, threshold={"op": q.op, "value": q.value}, direction=q.when,
            season=q.season or default_season(q.op, q.when, q.element),
            cross_year={"stat": q.stat, **({"p": q.percentile} if q.stat == "percentile" else {})}, style=style,
        ).validate()
    if q.element == "snow":
        return Metric(name="storm_total_snow", kind="storm", source="nohrsc", element="snow", title=title, style=style).validate()
    normal = "average" if q.when == "range_normal" else ("departure" if q.departure else None)
    return Metric(name=f"{q.element}_{q.reduce}_{q.when}", kind="period", source="acis_grid1", element=q.element,
                  title=title, reduce=q.reduce, normal=normal, style=style).validate()
