"""Sidebar forms, one per map type (see maptypes.py). Each returns the Query fields it collected plus the first problem
found in its own fields (shown under the field and in the summary). Widget keys start with "f_" so a whole map's settings
can be saved, restored from Recent maps, or loaded from a file."""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable
from zoneinfo import ZoneInfo

import streamlit as st

from ..config import DEFAULT_NORMAL_PERIOD
from ..por import PorError, parse_start
from ..precomputed import shipped_years
from ..query import (DEFAULT_THRESHOLD, GRID_RANGES, MENU, NOHRSC_START, RANGE_REDUCES, SPARSE_BEFORE, STATION_FIRST_YEAR,
                     STATION_MENU, default_season, last_complete_year)

MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]
MONTHS_FULL = [calendar.month_name[m] for m in range(1, 13)]
STATS = {"mean": "Average", "median": "Median", "min": "Earliest on record", "max": "Latest on record", "percentile": "Percentile"}
COLD, WARM = "Cold (at or below)", "Warm (at or above)"
TEMP_VARS = {"maxt": "High", "mint": "Low", "avgt": "Average temperature", "hdd": "Heating degree days (base 65)",
             "cdd": "Cooling degree days (base 65)", "gdd": "Growing degree days (base 50)"}
RAIN_REDUCES = {"sum": "Total", "max": "Wettest day", "count": "Number of days", "pct": "Percent of days"}
SNOW_PICKS = {**{MONTHS_FULL[m - 1]: (m, m) for m in (10, 11, 12, 1, 2, 3, 4)},
              "Winter (Dec–Feb)": (12, 2), "Oct–Apr": (10, 4), "Season total (Jul–Jun)": (7, 6), "Choose months…": None}


@dataclass
class Ctx:
    bbox: tuple
    por: Callable          # (bbox, element) -> Por, cached by the app
    today: dt.date


@dataclass
class FormResult:
    q: dict = field(default_factory=dict)
    error: str | None = None       # the first problem in this form's own fields (years, dates); None if fine


def problem(msg: str) -> None:
    st.caption(f":red[{msg}]")


# ---------------------------------------------------------------------------------------------------------------- helpers
def stat_field(r: FormResult) -> None:
    r.q["stat"] = st.selectbox("Statistic", list(STATS), format_func=STATS.get, key="f_stat")
    if r.q["stat"] == "percentile":
        r.q["percentile"] = float(st.slider("Percentile", 1, 99, 10, key="f_pct"))
    if r.q["stat"] in ("min", "max"):
        st.caption("Each station's single earliest/latest date in the chosen years; its record year shows in the map tooltip.")


def years_fields(r: FormResult, ctx: Ctx, element: str, op: str, direction: str, by_grid: bool) -> None:
    """Years from (a year or POR) and to. Validates against the area's period of record when needed."""
    ymax = last_complete_year(default_season(op, direction, element))
    c0, c1 = st.columns(2)
    raw = c0.text_input("Years from", value=str(DEFAULT_NORMAL_PERIOD[0]), key="f_y0",
                        help="A year (like 1890), or POR for the start of the period of record in the chosen area.")
    end = int(c1.number_input("to", STATION_FIRST_YEAR + 1, ymax, min(DEFAULT_NORMAL_PERIOD[1], ymax), key="f_y1"))
    start, info, parsed, err = DEFAULT_NORMAL_PERIOD[0], None, None, None
    try:
        parsed = parse_start(raw)
        if parsed == "por":
            if by_grid:
                start = (shipped_years().get("grid") or (DEFAULT_NORMAL_PERIOD[0],))[0]    # the grid's saved data begins here
            else:
                info = ctx.por(tuple(ctx.bbox), element)
                start = info.first_year
        else:
            start = parsed
            if not by_grid and start < 1950:
                info = ctx.por(tuple(ctx.bbox), element)
                if start < info.first_year:
                    err = f"Records in this area begin in {info.first_year}. Use POR, or a year from {info.first_year} on."
                    info = None
    except PorError as e:
        err = str(e)
    except Exception as e:      # ACIS unreachable, etc.: a typed year doesn't need the lookup
        err = f"Couldn't look up the period of record ({type(e).__name__}). Type a year instead."
    if err is None and start >= end:
        err = f"The start year ({start}) must be before the end year ({end})."
    if err:
        problem(err)
        r.error = r.error or err
    elif info is not None:
        st.caption(f"📅 Using {start}. " + info.describe({"mint": "low temperature", "maxt": "high temperature", "snow": "snowfall"}
                                                         .get(element, "this variable")))
    elif parsed == "por" and by_grid:
        st.caption(f"📅 Using {start}, where the saved grid data begins.")
    if not err and start < SPARSE_BEFORE:
        st.warning(f"Before ~{SPARSE_BEFORE} only a handful of stations report in most areas, so these maps can be mostly blank "
                   "or rest on very few stations.")
    r.q["normal_period"] = (int(start), int(end))


def smoothing(r: FormResult, key: str = "f_smooth") -> None:
    r.q["smooth_km"] = float(st.slider(
        "Map smoothing (km)", 0, 15, 3, key=key,
        help="Stations are interpolated, then lightly blurred. 0 = the map matches each station's own value exactly (but looks "
             "spottier); higher = smoother contours that drift from individual stations."))


def date_range(r: FormResult, ctx: Ctx, earliest: dt.date = dt.date(1950, 1, 1), k1: str = "f_d1", k2: str = "f_d2") -> None:
    last_month_end = ctx.today.replace(day=1) - dt.timedelta(days=1)
    c1, c2 = st.columns(2)
    r.q["start"] = c1.date_input("Start", last_month_end.replace(day=1), min_value=earliest, max_value=ctx.today, key=k1)
    r.q["end"] = c2.date_input("End", last_month_end, min_value=earliest, max_value=ctx.today, key=k2)
    if r.q["start"] and r.q["end"] and r.q["end"] < r.q["start"]:
        problem("The end date is before the start date.")
        r.error = r.error or "The end date is before the start date."


def month_window(r: FormResult) -> None:
    c1, c2 = st.columns(2)
    sm = c1.selectbox("From", range(1, 13), index=11, format_func=lambda m: MONTHS[m - 1], key="f_nm1")
    sd = c1.number_input("Day", 1, 31, 1, key="f_nd1")
    em = c2.selectbox("To", range(1, 13), index=1, format_func=lambda m: MONTHS[m - 1], key="f_nm2")
    ed = c2.number_input("Day ", 1, 31, 28, key="f_nd2")
    try:
        r.q["start"], r.q["end"] = dt.date(2001, sm, int(sd)), dt.date(2001, em, int(ed))
    except ValueError:
        r.q["start"] = r.q["end"] = None
        problem("That day doesn't exist in that month.")
        r.error = r.error or "Choose valid dates."
    r.q["normal_period"] = DEFAULT_NORMAL_PERIOD
    st.caption(f"Averaged over {DEFAULT_NORMAL_PERIOD[0]}–{DEFAULT_NORMAL_PERIOD[1]}.")


# ---------------------------------------------------------------------------------------------------------------- forms
def form_tdates(ctx: Ctx) -> FormResult:
    r = FormResult()
    direction = st.segmented_control("Which date", ["First", "Last"], default="First", required=True, key="f_dir", width="stretch")
    kind = st.segmented_control("Threshold", [COLD, WARM], default=COLD, required=True, key="f_kind", width="stretch")
    op = "le" if kind == COLD else "ge"
    with st.expander("Advanced"):
        method_label = st.radio("Data", ["Stations (interpolated)", "Grid (ACIS Grid 1)"], key="f_method", horizontal=True,
                                help="Stations: each station's own date, interpolated — any threshold, any years back to the period of "
                                     "record. Grid: NRCC's 5 km daily grid scanned cell by cell — smooth, but only the pre-saved "
                                     "thresholds and 1991+.")
        smoothing(r)
    by_station = method_label.startswith("Stations")
    c1, c2 = st.columns(2)
    temp = c1.selectbox("Temperature", ["Low", "High"], index=0 if op == "le" else 1, key=f"f_temp_{op}")
    el = "mint" if temp == "Low" else "maxt"
    glo, ghi = GRID_RANGES[(el, op)]
    lo, hi = (-60, 140) if by_station else (glo, ghi)
    value = c2.number_input(
        "At or below (°F)" if op == "le" else "At or above (°F)", min_value=lo, max_value=hi,
        value=min(max(DEFAULT_THRESHOLD[(el, op)], lo), hi), step=1, key=f"f_thr_{el}_{op}_{'stn' if by_station else 'grid'}",
        help=(("Whole degrees. Pre-saved (instant): " + ", ".join(f"{v:g}" for v in STATION_MENU[(el, op)])
               + ". Any other value is fetched live from ACIS (~15-30 s).") if by_station else
              "Whole degrees. The grid method only has these pre-saved: " + ", ".join(str(v) for v in MENU[(el, op)])
              + ". Use Stations (under Advanced) for any other value."))
    when = "first" if direction == "First" else "last"
    stat_field(r)
    years_fields(r, ctx, el, op, when, by_grid=not by_station)
    if not by_station:
        r.q.pop("smooth_km", None)
    r.q.update(when=when, element=el, op=op, value=float(value), method="station" if by_station else "grid")
    return r


def form_snowdate(ctx: Ctx) -> FormResult:
    r = FormResult()
    direction = st.segmented_control("Which date", ["First", "Last"], default="First", required=True, key="f_dir", width="stretch")
    amount = st.number_input("Daily snowfall at least (in)", 0.1, 30.0, 1.0, 0.1, format="%.1f", key="f_snow_amt",
                             help="Pre-saved: " + ", ".join(f"{v:g}" for v in STATION_MENU[("snow", "ge")]) + ". Other amounts are "
                                  "fetched live from ACIS (about 1-2 minutes: snow comes from thousands of stations).")
    when = "first" if direction == "First" else "last"
    stat_field(r)
    years_fields(r, ctx, "snow", "ge", when, by_grid=False)
    with st.expander("Advanced"):
        smoothing(r)
    st.caption("Snowfall has no ACIS grid, so this uses station observations interpolated to a map.")
    r.q.update(when=when, element="snow", op="ge", value=float(amount), method="station")
    return r


def form_tsum(ctx: Ctx) -> FormResult:
    r = FormResult()
    el = st.selectbox("Variable", list(TEMP_VARS), format_func=TEMP_VARS.get, key="f_tsum_var")
    default = "sum" if el in ("hdd", "cdd", "gdd") else "mean"
    opts = list(RANGE_REDUCES)
    reduce = st.selectbox("Show", opts, index=opts.index(default), format_func=RANGE_REDUCES.get, key=f"f_tsum_reduce_{el in ('hdd', 'cdd', 'gdd')}")
    r.q.update(when="range_specific", element=el, reduce=reduce)
    if reduce in ("count", "pct") or st.checkbox("Only include days meeting a threshold", key="f_tsum_filter",
                                                 help="For example, a total of daily highs only on days at or above 80°F."):
        c1, c2 = st.columns(2)
        rel = c1.selectbox("Days", ["at or above", "at or below"], key="f_tsum_op")
        unit = "°F" if el in ("maxt", "mint", "avgt") else "°F-days"
        thr = c2.number_input(f"Threshold ({unit})", value=80.0 if el == "maxt" else 32.0 if el == "mint" else 65.0 if el == "avgt" else 10.0,
                              step=1.0, format="%.0f", key=f"f_tsum_thr_{el}")
        r.q.update(op="ge" if rel == "at or above" else "le", value=float(thr))
    date_range(r, ctx)
    return r


def form_rsum(ctx: Ctx) -> FormResult:
    r = FormResult()
    reduce = st.selectbox("Show", list(RAIN_REDUCES), format_func=RAIN_REDUCES.get, key="f_rsum_reduce")
    r.q.update(when="range_specific", element="pcpn", reduce=reduce)
    if reduce in ("count", "pct"):
        thr = st.number_input("Days with at least (in)", min_value=0.01, value=0.01, step=0.01, format="%.2f", key="f_rsum_thr")
        r.q.update(op="ge", value=float(thr))
    date_range(r, ctx)
    return r


def form_tnormal(ctx: Ctx) -> FormResult:
    r = FormResult()
    temp = st.segmented_control("Temperature", ["High", "Low"], default="High", required=True, key="f_tn_var", width="stretch")
    r.q.update(when="range_normal", element="maxt" if temp == "High" else "mint", reduce="mean")
    month_window(r)
    return r


def form_rnormal(ctx: Ctx) -> FormResult:
    r = FormResult()
    r.q.update(when="range_normal", element="pcpn", reduce="sum")
    month_window(r)
    return r


def form_tdep(ctx: Ctx) -> FormResult:
    r = FormResult()
    temp = st.segmented_control("Temperature", ["High", "Low"], default="High", required=True, key="f_tdep_var", width="stretch")
    r.q.update(when="range_specific", element="maxt" if temp == "High" else "mint", reduce="mean", departure=True,
               normal_period=DEFAULT_NORMAL_PERIOD)
    date_range(r, ctx)
    st.caption("Average minus the 1991–2020 daily normals for the same days.")
    return r


def form_rdep(ctx: Ctx) -> FormResult:
    r = FormResult()
    r.q.update(when="range_specific", element="pcpn", reduce="sum", departure=True, normal_period=DEFAULT_NORMAL_PERIOD)
    date_range(r, ctx)
    st.caption("Total minus the 1991–2020 daily normals for the same days.")
    return r


def form_snownormal(ctx: Ctx) -> FormResult:
    r = FormResult()
    pick = st.selectbox("Months", list(SNOW_PICKS), index=1, key="f_snow_pick")
    if SNOW_PICKS[pick] is None:
        c1, c2 = st.columns(2)
        sm = c1.selectbox("From month", range(1, 13), index=10, format_func=lambda m: MONTHS[m - 1], key="f_snow_m1")
        em = c2.selectbox("To month", range(1, 13), index=1, format_func=lambda m: MONTHS[m - 1], key="f_snow_m2")
    else:
        sm, em = SNOW_PICKS[pick]
    r.q.update(when="range_normal", element="snow", start=dt.date(2001, sm, 1),
               end=dt.date(2001, em, calendar.monthrange(2001, em)[1]), normal_period=DEFAULT_NORMAL_PERIOD)
    st.caption("NCEI's official 1991–2020 monthly snowfall normals at each station (the numbers NWS publishes), summed over the "
               "chosen months and interpolated to a map.")
    with st.expander("Advanced"):
        smoothing(r)
    return r


def form_snowstorm(ctx: Ctx) -> FormResult:
    r = FormResult()
    tz = st.radio("Enter times as", ["Eastern (auto EST/EDT)", "UTC"], horizontal=True, key="f_storm_tz")
    zone = ZoneInfo("America/New_York") if tz.startswith("Eastern") else ZoneInfo("UTC")
    c1, c2 = st.columns(2)
    sd = c1.date_input("Start date", ctx.today - dt.timedelta(days=3), min_value=NOHRSC_START.date(), max_value=ctx.today, key="f_storm_d1")
    sh = c1.selectbox("Start hour", range(24), index=7, format_func=lambda h: f"{h:02d}:00", key="f_storm_h1")
    ed = c2.date_input("End date", ctx.today - dt.timedelta(days=1), min_value=NOHRSC_START.date(), max_value=ctx.today, key="f_storm_d2")
    eh = c2.selectbox("End hour", range(24), index=7, format_func=lambda h: f"{h:02d}:00", key="f_storm_h2")
    to_utc = lambda d, h: dt.datetime.combine(d, dt.time(h), tzinfo=zone).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    r.q.update(when="range_specific", element="snow", start=to_utc(sd, sh), end=to_utc(ed, eh),
               extra={"reports": st.checkbox("Overlay NWS snow reports (IEM)", value=True, key="f_storm_reports",
                                             help="Observed snowfall from NWS local storm reports, shown as dots on the map.")})
    st.caption(f"UTC window: **{r.q['start']:%b %-d %HZ} → {r.q['end']:%b %-d %HZ}**. NOHRSC analyses are 00Z/12Z (season totals) or "
               "6-hourly; times snap to the nearest available.")
    return r


def form_snowdep(ctx: Ctx) -> FormResult:
    r = FormResult()
    r.q.update(when="range_specific", element="snow", departure=True, normal_period=DEFAULT_NORMAL_PERIOD)
    date_range(r, ctx, earliest=dt.date(1900, 1, 1), k1="f_sdep_d1", k2="f_sdep_d2")
    st.caption("Station snowfall (each day ends around 7 AM) minus NCEI's 1991–2020 normal for the same days, fetched live from "
               "ACIS (~20–60 s) and interpolated. Stations missing more than 10% of the days are left out.")
    with st.expander("Advanced"):
        smoothing(r)
    return r


def form_sun(ctx: Ctx) -> FormResult:
    r = FormResult()
    labels = {"sunrise": "Sunrise", "sunset": "Sunset", "daylen": "Day length"}
    shown = st.segmented_control("Show", list(labels.values()), default="Sunrise", required=True, key="f_sun_var", width="stretch")
    change = st.checkbox("Change between two dates", key="f_sun_change",
                         help="Times are local clock time on each date (daylight saving included), by the time zone at each point; "
                              "the map steps where a zone border is crossed.")
    lo, hi = dt.date(1900, 1, 1), dt.date(2100, 12, 31)
    if change:
        c1, c2 = st.columns(2)
        start = c1.date_input("Start date", ctx.today, min_value=lo, max_value=hi, key="f_sun_d1")
        end = c2.date_input("End date", ctx.today + dt.timedelta(days=30), min_value=lo, max_value=hi, key="f_sun_d2")
    else:
        start, end = st.date_input("Date", ctx.today, min_value=lo, max_value=hi, key="f_sun_d1"), None
    r.q.update(when="sun", element=next(k for k, v in labels.items() if v == shown), start=start, end=end)
    return r


FORMS = {"tdates": form_tdates, "snowdate": form_snowdate, "tsum": form_tsum, "rsum": form_rsum, "tnormal": form_tnormal,
         "rnormal": form_rnormal, "tdep": form_tdep, "rdep": form_rdep, "snownormal": form_snownormal,
         "snowstorm": form_snowstorm, "snowdep": form_snowdep, "sun": form_sun}


def render_form(type_id: str, ctx: Ctx) -> FormResult:
    return FORMS[type_id](ctx)


# ---------------------------------------------------------------------------------------------------------------- snapshots
def snapshot(state) -> dict:
    """The current map's settings (form widgets + area), for Recent maps and Save whole map."""
    keep = {k: state[k] for k in state if isinstance(k, str) and (k.startswith("f_") or k.startswith("area"))}
    return keep


def to_jsonable(snap: dict) -> dict:
    out = {}
    for k, v in snap.items():
        if isinstance(v, dt.datetime):
            out[k] = {"__datetime__": v.isoformat()}
        elif isinstance(v, dt.date):
            out[k] = {"__date__": v.isoformat()}
        elif isinstance(v, tuple):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def from_jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and "__date__" in v:
            out[k] = dt.date.fromisoformat(v["__date__"])
        elif isinstance(v, dict) and "__datetime__" in v:
            out[k] = dt.datetime.fromisoformat(v["__datetime__"])
        else:
            out[k] = v
    return out
