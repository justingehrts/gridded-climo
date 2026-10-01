"""A UI-level request (When x What x options) -> registry Metric. Shared by the CLI and Streamlit."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from .precomputed import DATA_DIR, has_occurrence, shipped_years
from .registry import Metric, Style

WHENS = ("first", "last", "range_specific", "range_normal")
TEMP_ELEMENTS = {"mint": "Low (min) temperature", "maxt": "High (max) temperature"}
# Pre-saved temperature thresholds (grid AND stations): every 10 degrees, plus 28, 32 and 36 for the cold-side (<=) maps.
# The grid method can ONLY use these (its first/last dates can't be computed on demand in the hosted app); the station method
# serves these instantly and fetches any other whole degree from ACIS on demand (~15-30 s).
def _menu(lo: int, hi: int, extras: tuple[int, ...] = ()) -> tuple[int, ...]:
    return tuple(sorted(set(range(lo, hi + 1, 10)) | set(extras)))


_COLD_EXTRAS = (28, 32, 36)
MENU: dict[tuple[str, str], tuple[int, ...]] = {
    ("mint", "le"): _menu(-10, 50, _COLD_EXTRAS), ("maxt", "le"): _menu(-10, 50, _COLD_EXTRAS),
    ("maxt", "ge"): _menu(50, 100), ("mint", "ge"): _menu(40, 80),
}
GRID_RANGES: dict[tuple[str, str], tuple[int, int]] = {k: (v[0], v[-1]) for k, v in MENU.items()}   # field bounds only
STATION_MENU: dict[tuple[str, str], tuple[float, ...]] = {**MENU, ("snow", "ge"): (0.1, 1.0, 3.0, 6.0)}
DEFAULT_THRESHOLD: dict[tuple[str, str], int] = {("mint", "le"): 32, ("maxt", "le"): 32, ("maxt", "ge"): 90, ("mint", "ge"): 70}
NOHRSC_START = dt.datetime(2008, 10, 1)


def last_complete_year(season: dict, today: dt.date | None = None) -> int:
    """Latest season-start year whose season has finished (>5 days ago), so shipped/live data never reaches a season in progress."""
    today = today or dt.date.today()
    (sm, sd), (em, ed) = season["start"], season["end"]
    y = today.year
    while dt.date(y + (1 if (em, ed) < (sm, sd) else 0), em, ed) >= today - dt.timedelta(days=5):
        y -= 1
    return y


STATION_FIRST_YEAR = 1870   # ACIS has a handful of stations from the 1870s; the region is dense only from ~1895
SPARSE_BEFORE = 1895
NORMALS_PERIOD = (1991, 2020)  # daily-normal files are shipped for this period only


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
    smooth_km: float = 3.0         # station maps: blur radius after interpolation (0 = hugs each station exactly)
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
        if q.element == "snow":
            if abs(q.value * 10 - round(q.value * 10)) > 1e-6:
                return "Snowfall amounts go in tenths of an inch (for example 0.5 or 2.5)."
        elif q.value != round(q.value):
            return "Temperature thresholds must be whole degrees."
        if method == "station":
            lo, hi = (-60, 140) if q.element != "snow" else (0.1, 60)
            if not lo <= q.value <= hi:
                return f"Threshold should be between {lo} and {hi}."
            last = last_complete_year(q.season or default_season(q.op, q.when, q.element))
            if not 0 <= q.smooth_km <= 30:
                return "Smoothing should be between 0 and 30 km."
            if q.normal_period[0] < STATION_FIRST_YEAR:
                return f"Station data is used from {STATION_FIRST_YEAR} onward."
            if q.normal_period[1] > last:
                return f"The latest completed season is {last}; choose an end year of {last} or earlier."
            return None
        cover = shipped_years(DATA_DIR).get("grid")  # grid first/last dates come only from shipped data (GridData has no server-side first/last)
        if cover and q.season is None and not allow_live():
            if q.normal_period[0] < cover[0] or q.normal_period[1] > cover[1]:
                return f"Grid data ships for {cover[0]}-{cover[1]}; choose Stations to use other years."
        menu = MENU[(q.element, q.op)]
        if q.season is None and not allow_live() and q.value not in menu:
            return (f"The grid method only has pre-saved thresholds at {', '.join(str(v) for v in menu)}°F for this variable; "
                    "use Stations for any other value.")
        if q.season is None and not allow_live() and not has_occurrence(DATA_DIR, q.element, q.op, q.value, q.when):
            return f"{q.value:g}°F isn't pre-saved for the grid method yet; use Stations (any value works)."
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
    if (q.when == "range_normal" or q.departure) and tuple(q.normal_period) != NORMALS_PERIOD and not allow_live():
        return f"Daily normals are shipped for {NORMALS_PERIOD[0]}-{NORMALS_PERIOD[1]} only; use that normal period."
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
        return Style(ramp="RdYlBu", reverse=(q.when == "first") == (q.op == "le"), mode="stepped", steps=6, units_label="date")
    if q.element == "snow":
        return Style(ramp="Blues", mode="stepped", steps=10, vmin=0.5, vmax=24, hide_below=0.1, units_label="in")
    if q.departure:
        return Style(ramp="coolwarm", mode="stepped", steps=6, symmetric=True,
                     units_label="in" if q.element == "pcpn" else "°F")
    if q.element == "pcpn":
        return Style(ramp="YlGnBu", mode="stepped", steps=10, units_label="in")
    return Style(ramp="Spectral", reverse=True, mode="stepped", steps=6, units_label="°F")


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
