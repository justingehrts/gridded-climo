"""Gridded Climo — broadcast climate maps. Run: streamlit run streamlit_app.py"""
from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
import zlib
from pathlib import Path
from zoneinfo import ZoneInfo

import dataclasses
import json

import matplotlib as mpl
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_folium import st_folium

from gridded_climo.config import DEFAULT_BBOX, DEFAULT_NORMAL_PERIOD
from gridded_climo.query import DEFAULT_THRESHOLD, GRID_RANGES, MENU, NOHRSC_START, SPARSE_BEFORE, STATION_FIRST_YEAR, STATION_MENU, RANGE_ELEMENTS, RANGE_REDUCES, SUN_ELEMENTS, TEMP_ELEMENTS, default_season, last_complete_year, Query, allow_live, unsupported_reason
from gridded_climo.ui.preview import build_map, load_counties_geojson
from gridded_climo.binning import MODE_LABELS, MODES
from gridded_climo.registry import Style
from gridded_climo.render.wctrp import UNIT_IDS, wctrp_bytes
from gridded_climo.render import PaletteError, RAMPS, parse_legend_csv, parse_wctrp, ramp_label, style_from_json, style_to_json
from gridded_climo.render.palettes import sample_colors
from gridded_climo.ui.components import legend_editor, ramp_picker
from gridded_climo.ui.service import compute, render_computed
from gridded_climo.acis import ACISClient
from gridded_climo.cache import Cache
from gridded_climo.config import ACIS_BASE_URL
from gridded_climo.por import PorError, parse_start, station_por
from gridded_climo.precomputed import shipped_years
from gridded_climo.presets import list_presets, preset_slug
from gridded_climo.regions import CONUS_BOUNDS, buffer_deg, buffered_bbox, presaved_bbox, state_names, states
from gridded_climo.ui.style_build import build_style, pending_from_json

def _writable_cache_dir() -> Path:
    """Preferred cache dir if we can write there, else a temp dir (hosted filesystems may be read-only)."""
    want = Path(os.environ.get("GRIDDED_CLIMO_CACHE", Path(__file__).parent / ".cache" / "gridded_climo"))
    try:
        want.mkdir(parents=True, exist_ok=True)
        (want / ".w").write_text("ok")
        return want
    except OSError:
        return Path(tempfile.gettempdir()) / "gridded_climo_cache"


CACHE_DIR = _writable_cache_dir()
DEFAULT_AREA = "Columbus-centered default (pre-saved)"
STATE_CODES = state_names()                       # {"Ohio": "OH", ...}
AREAS = [DEFAULT_AREA] + list(STATE_CODES) + ["Custom…"]
TODAY = dt.date.today()
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

st.set_page_config(page_title="Gridded Climo", page_icon="🗺️", layout="wide")


@st.cache_data(show_spinner=False)
def cached_compute(q: Query, bbox, allow_live_flag: bool):
    """The slow part (ACIS / shipped data -> grid). Restyling never re-runs this."""
    return compute(q, bbox, CACHE_DIR, allow_live=True)


@st.cache_data(show_spinner=False, max_entries=48)
def cached_render(q: Query, bbox, allow_live_flag: bool, style_json: str):
    """The fast part (grid + style -> PNG / legend / KMZ)."""
    return render_computed(cached_compute(q, bbox, allow_live_flag), Style(**json.loads(style_json)))


@st.cache_data(show_spinner="Looking up the period of record…", ttl=24 * 3600)
def cached_por(bbox, element: str):
    """When stations in this area began reporting `element` (one small ACIS request, kept a day)."""
    return station_por(ACISClient(ACIS_BASE_URL, Cache(CACHE_DIR)), bbox, element)


@st.cache_data(show_spinner=False)
def counties():
    return load_counties_geojson()


# Imported settings are applied before any widget exists in this run (Streamlit forbids changing a widget after creation).


def set_legend_rows(rows):
    """Replace the custom legend from Python (an import, Reset, a new map). The version bump tells the band editor to drop
    its own copy of the table and show this one."""
    if rows:
        st.session_state["legend_rows"] = rows
    else:
        st.session_state.pop("legend_rows", None)
    st.session_state["legend_version"] = st.session_state.get("legend_version", 0) + 1


def forget_ramp_pick():
    """Make the ramp dropdown forget its own last pick, so a ramp set from Python (a preset, Reset) isn't overridden."""
    st.session_state["ramp_epoch"] = st.session_state.get("ramp_epoch", 0) + 1


if "_pending" in st.session_state:
    pending = st.session_state.pop("_pending")
    st.session_state.update(pending)
    if "legend_rows" in pending:
        set_legend_rows(pending["legend_rows"])
    forget_ramp_pick()

# ---------------------------------------------------------------- selectors
years_error = None      # set by the Options panel when the years can't be used; shown in the main panel and disables Generate
with st.sidebar:
    st.title("🗺️ Gridded Climo")
    st.caption("Broadcast climate maps · ACIS Grid 1 · NOHRSC snowfall")

    st.subheader("Area")
    area_name = st.selectbox("Area", AREAS, key="area", label_visibility="collapsed",
                             help="Pick a state (shown with a buffer so neighbors and surroundings are included) or draw your own box. "
                                  "Ohio and the Columbus default use pre-saved data; other areas are fetched live from ACIS.")
    if area_name == DEFAULT_AREA:
        bbox = DEFAULT_BBOX
    elif area_name == "Custom…":
        c1, c2 = st.columns(2)
        w0, s0, e0, n0_ = CONUS_BOUNDS
        d0 = DEFAULT_BBOX
        west = c1.number_input("West", w0, e0, d0[0], 0.1); east = c2.number_input("East", w0, e0, d0[2], 0.1)
        north = c1.number_input("North", s0, n0_, d0[3], 0.1); south = c2.number_input("South", s0, n0_, d0[1], 0.1)
        bbox = (west, south, east, north)
    else:
        code = STATE_CODES[area_name]
        bbox = buffered_bbox(code)
        b = buffer_deg(tuple(states()[code]["bbox"]))
        st.caption(f"{area_name} plus a {b:.2f}° (~{b * 111:.0f} km) buffer.")
    if area_name != DEFAULT_AREA and presaved_bbox(tuple(bbox)) is None:
        st.caption("📡 Outside the pre-saved region: station maps and date ranges are fetched live from ACIS (can take longer), "
                   "and grid first/last dates and departure maps aren't available here.")

    st.subheader("1 · When")
    when_label = st.radio("When", ["Average first date", "Average last date", "Custom range", "Sun (sunrise, sunset, day length)"],
                          label_visibility="collapsed")
    is_sun = when_label.startswith("Sun")
    range_mode = None
    if when_label == "Custom range":
        range_mode = st.radio("Range type", ["Specific dates", "Averaged over normal period"],
                              help="Specific dates = one real period. Averaged = the same calendar dates averaged over every year in the normal period.")

    st.subheader("2 · What")
    q_kwargs: dict = {}
    sun_change = False
    if is_sun:
        sun_labels = SUN_ELEMENTS
        chosen_sun = st.selectbox("Variable", list(sun_labels.values()), key="sun_var")
        q_kwargs.update(when="sun", element=next(k for k, v in sun_labels.items() if v == chosen_sun))
        sun_change = st.radio("Show", ["Value on one date", "Change between two dates"], key="sun_mode",
                              help="Times are local clock time on each date (daylight saving included), by the time zone at each point; "
                                   "the map steps where a zone border is crossed.") == "Change between two dates"
    elif when_label != "Custom range":
        var = st.selectbox("Variable", ["Temperature at or below", "Temperature at or above", "Snowfall"])
        if var == "Snowfall":
            amount = st.number_input("Daily snowfall at least (in)", 0.1, 30.0, 1.0, 0.1, format="%.1f",
                                     help="Pre-saved: " + ", ".join(f"{v:g}" for v in STATION_MENU[("snow", "ge")]) + ". Other amounts are fetched live from ACIS (about 1-2 minutes: snow comes from thousands of stations).")
            q_kwargs.update(element="snow", op="ge", value=float(amount), method="station")
            st.caption("Snowfall has no ACIS grid, so this uses station observations interpolated to a map.")
        else:
            op = "le" if var.endswith("below") else "ge"
            el_label = st.radio("Which temperature?", list(TEMP_ELEMENTS.values()), index=0 if op == "le" else 1, horizontal=True)
            el = next(k for k, v in TEMP_ELEMENTS.items() if v == el_label)
            method_label = st.radio(
                "Method", ["Stations (interpolated)", "Grid (ACIS Grid 1)"],
                help="Stations: each station's own date (what the ACIS website shows), interpolated — official values at the dots, any "
                     "threshold, any years back to 1900. Grid: NRCC's 5 km daily temperature grid scanned cell by cell — smooth, every "
                     "cell has a value, but only the pre-saved thresholds and 1991+ years. They agree within ~2 days for typical "
                     "freeze thresholds; warm thresholds (90°F+) can differ more.")
            by_station = method_label.startswith("Stations")
            glo, ghi = GRID_RANGES[(el, op)]
            lo, hi = (-60, 140) if by_station else (glo, ghi)
            value = st.number_input(
                "Threshold (°F)", min_value=lo, max_value=hi, value=min(max(DEFAULT_THRESHOLD[(el, op)], lo), hi), step=1,
                key=f"thr_{el}_{op}_{'stn' if by_station else 'grid'}",
                help=(("Whole degrees. Pre-saved (instant): " + ", ".join(f"{v:g}" for v in STATION_MENU[(el, op)])
                       + ". Any other value is fetched live from ACIS (~15-30 s).") if by_station else
                      "Whole degrees. The grid method only has these pre-saved: " + ", ".join(str(v) for v in MENU[(el, op)])
                      + ". Use Stations for any other value."))
            q_kwargs.update(element=el, op=op, value=float(value), method="station" if by_station else "grid")
        q_kwargs["when"] = "first" if when_label == "Average first date" else "last"
    else:
        specific = range_mode == "Specific dates"
        labels = {k: v for k, v in RANGE_ELEMENTS.items() if specific or k in ("maxt", "mint", "pcpn", "snow")}
        chosen = st.selectbox("Variable", list(labels.values()), key=f"range_var_{'s' if specific else 'n'}")
        el = next(k for k, v in labels.items() if v == chosen)
        q_kwargs["element"] = el
        if el != "snow":
            default = "sum" if el in ("pcpn", "hdd", "cdd", "gdd") else "mean"
            opts = list(RANGE_REDUCES) if specific else ["mean", "sum", "max", "min"]
            q_kwargs["reduce"] = st.selectbox("Summary", opts, index=opts.index(default), format_func=RANGE_REDUCES.get, key="range_reduce")
            counting = q_kwargs["reduce"] in ("count", "pct")
            if specific and (counting or st.checkbox("Only include days meeting a threshold", key="range_filter",
                                                     help="For example, a total of daily highs only on days at or above 80°F.")):
                is_in = el == "pcpn"
                c1, c2 = st.columns(2)
                rel = c1.selectbox("Days where value is", ["at or above", "at or below"], key="range_op")
                thr = c2.number_input("Threshold (in)" if is_in else "Threshold (°F)" if el in ("maxt", "mint", "avgt") else "Threshold",
                                      value=0.01 if is_in else 80.0 if el == "maxt" else 32.0 if el == "mint" else 65.0 if el == "avgt" else 10.0,
                                      step=0.01 if is_in else 1.0, format="%.2f" if is_in else "%.0f", key=f"range_thr_{el}")
                q_kwargs.update(op="ge" if rel == "at or above" else "le", value=float(thr))
        q_kwargs["when"] = "range_specific" if range_mode == "Specific dates" else "range_normal"
        if range_mode == "Specific dates" and el in ("maxt", "mint", "pcpn") and q_kwargs.get("value") is None \
                and q_kwargs.get("reduce") in ("mean", "sum"):
            q_kwargs["departure"] = st.checkbox("Show departure from normal", help="Value minus the daily normals for the same days.")

    st.subheader("3 · Dates")
    date_mode, custom_starts = "auto", ""
    if is_sun:
        c1, c2 = st.columns(2) if sun_change else (st.container(), None)
        q_kwargs["start"] = c1.date_input("Start date" if sun_change else "Date", TODAY, min_value=dt.date(1900, 1, 1), max_value=dt.date(2100, 12, 31), key="sun_d1")
        if sun_change:
            q_kwargs["end"] = c2.date_input("End date", TODAY + dt.timedelta(days=30), min_value=dt.date(1900, 1, 1), max_value=dt.date(2100, 12, 31), key="sun_d2")
    elif when_label != "Custom range":
        st.caption("Uses every year in the years range (see Options).")
        date_mode = st.radio("Group dates into", MODES, format_func=MODE_LABELS.get, key="style_date_mode",
                             help="Automatic: equal color steps across the data. Weekly: 1st–6th, 7th–13th, 14th–20th, 21st–end of "
                                  "month. Thirds: early / mid / late month. Halves: 1st–15th and 16th–end. Custom: your own bin start dates.")
        if date_mode == "custom":
            custom_starts = st.text_input("Bin start dates (in season order)", "Oct 1, Oct 8, Oct 15, Oct 22, Nov 1", key="style_custom_starts",
                                          help="Each bin runs from its start date to the day before the next one. Data before the first date "
                                               "gets a 'Before…' bin; data after the last start extends the last bin.")
    elif range_mode == "Specific dates" and el != "snow":
        d1, d2 = st.columns(2)
        first_of_month = TODAY.replace(day=1) - dt.timedelta(days=1)
        q_kwargs["start"] = d1.date_input("Start", first_of_month.replace(day=1), min_value=dt.date(1950, 1, 1), max_value=TODAY)
        q_kwargs["end"] = d2.date_input("End", first_of_month, min_value=dt.date(1950, 1, 1), max_value=TODAY)
    elif range_mode == "Specific dates":  # snowfall / NOHRSC: date + hour, Eastern or UTC
        tz = st.radio("Enter times as", ["Eastern (auto EST/EDT)", "UTC"], horizontal=True)
        zone = ZoneInfo("America/New_York") if tz.startswith("Eastern") else ZoneInfo("UTC")
        c1, c2 = st.columns(2)
        sd = c1.date_input("Start date", TODAY - dt.timedelta(days=3), min_value=NOHRSC_START.date(), max_value=TODAY)
        sh = c1.selectbox("Start hour", range(24), index=7, format_func=lambda h: f"{h:02d}:00")
        ed = c2.date_input("End date", TODAY - dt.timedelta(days=1), min_value=NOHRSC_START.date(), max_value=TODAY)
        eh = c2.selectbox("End hour", range(24), index=7, format_func=lambda h: f"{h:02d}:00")
        to_utc = lambda d, h: dt.datetime.combine(d, dt.time(h), tzinfo=zone).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        q_kwargs["start"], q_kwargs["end"] = to_utc(sd, sh), to_utc(ed, eh)
        q_kwargs["extra"] = {"reports": st.checkbox("Overlay NWS snow reports (IEM)", value=True,
                                                    help="Observed snowfall from NWS local storm reports, shown as dots on the map.")}
        st.caption(f"UTC window: **{q_kwargs['start']:%b %-d %HZ} → {q_kwargs['end']:%b %-d %HZ}**. NOHRSC analyses are 00Z/12Z "
                   "(season totals) or 6-hourly; times snap to the nearest available.")
    else:  # averaged over normal period: month/day window
        c1, c2 = st.columns(2)
        sm = c1.selectbox("From month", range(1, 13), index=11, format_func=lambda m: MONTHS[m - 1])
        sdy = c1.number_input("From day", 1, 31, 1)
        em = c2.selectbox("To month", range(1, 13), index=1, format_func=lambda m: MONTHS[m - 1])
        edy = c2.number_input("To day", 1, 31, 28)
        try:
            q_kwargs["start"], q_kwargs["end"] = dt.date(2001, sm, int(sdy)), dt.date(2001, em, int(edy))
        except ValueError:
            q_kwargs["start"] = q_kwargs["end"] = None

    years_error = None
    if not is_sun:
        with st.expander("Options"):
            n0, n1 = st.columns(2)
            label_y = "Years included: from" if when_label != "Custom range" else "Normal period: from"
            if when_label != "Custom range":
                ymax = last_complete_year(default_season(q_kwargs.get("op", "ge"), q_kwargs["when"], q_kwargs["element"]))
            else:
                ymax = last_complete_year({"start": [1, 1], "end": [12, 31]})
            years_error = None
            if when_label == "Custom range":      # daily normals are pre-saved for 1991-2020 only, so this stays a plain number
                start_year = int(n0.number_input(label_y, STATION_FIRST_YEAR, ymax - 1, DEFAULT_NORMAL_PERIOD[0]))
            else:
                raw_start = n0.text_input(label_y, value=str(DEFAULT_NORMAL_PERIOD[0]), key="years_from",
                                          help="A year (like 1890), or POR for the start of the period of record in the chosen area.")
                start_year, por_info, parsed = DEFAULT_NORMAL_PERIOD[0], None, None
                by_grid = q_kwargs.get("method") == "grid"
                try:
                    parsed = parse_start(raw_start)
                    if parsed == "por":
                        if by_grid:
                            start_year = (shipped_years().get("grid") or (DEFAULT_NORMAL_PERIOD[0],))[0]   # the grid's saved data begins here
                        else:
                            por_info = cached_por(tuple(bbox), q_kwargs["element"])
                            start_year = por_info.first_year
                    else:
                        start_year = parsed
                        if not by_grid and start_year < 1950:
                            por_info = cached_por(tuple(bbox), q_kwargs["element"])
                            if start_year < por_info.first_year:
                                years_error = f"Records in this area begin in {por_info.first_year}. Use POR, or a year from {por_info.first_year} on."
                                por_info = None
                except PorError as e:
                    years_error = str(e)
                except Exception as e:     # ACIS unreachable, etc.: the typed-year path doesn't need the lookup
                    years_error = f"Couldn't look up the period of record ({type(e).__name__}). Type a year instead."
            end_year = int(n1.number_input("to", STATION_FIRST_YEAR + 1, ymax, min(DEFAULT_NORMAL_PERIOD[1], ymax)))
            if years_error is None and start_year >= end_year:
                years_error = f"The start year ({start_year}) must be before the end year ({end_year})."
            normal = (start_year, end_year)
            if when_label != "Custom range":
                if por_info is not None:
                    st.caption(f"📅 Using {start_year}. " + por_info.describe({"mint": "low temperature", "maxt": "high temperature", "snow": "snowfall"}.get(q_kwargs["element"], "this variable")))
                elif parsed == "por" and by_grid:
                    st.caption(f"📅 Using {start_year}, where the saved grid data begins.")
                st.caption("For a record (earliest/latest), start at POR. Stations go back as far as the area's records (most reliable from ~1895); the Grid method has 1991 onward.")
                if start_year < SPARSE_BEFORE:
                    st.warning(f"Before ~{SPARSE_BEFORE} only a handful of stations report in most areas, so these maps can be mostly blank or rest on very few stations.")
            q_kwargs["normal_period"] = (int(normal[0]), int(normal[1]))
            if when_label != "Custom range":
                stat_label = st.selectbox("Statistic across years", ["Average date", "Median date", "Earliest on record", "Latest on record", "Percentile"])
                stat = {"Average date": "mean", "Median date": "median", "Earliest on record": "min", "Latest on record": "max", "Percentile": "percentile"}[stat_label]
                q_kwargs["stat"] = stat
                if stat == "percentile":
                    q_kwargs["percentile"] = st.slider("Percentile", 1, 99, 10)
                if stat in ("min", "max"):
                    st.caption("Each station's single earliest/latest date in the chosen years; its record year shows in the map tooltip.")
            if when_label != "Custom range" and (q_kwargs.get("method") == "station" or q_kwargs.get("element") == "snow"):
                q_kwargs["smooth_km"] = float(st.slider(
                    "Map smoothing (km)", 0, 15, 3,
                    help="Stations are interpolated, then lightly blurred. 0 = the map matches each station's own value exactly (but looks "
                         "spottier); higher = smoother contours that drift from individual stations (12 km can be ~5 days off at a single airport)."))

q = Query(**{k: v for k, v in q_kwargs.items() if k in Query.__dataclass_fields__})
if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
    reason = "Region: west must be less than east and south less than north."
else:
    reason = unsupported_reason(q, bbox) if q.start is not None or q.when in ("first", "last") or q.element == "snow" else "Choose valid dates."
    if q.when not in ("first", "last", "sun") and (q.start is None or q.end is None):
        reason = "Choose valid dates."

# ---------------------------------------------------------------- main panel
if years_error and not reason:
    reason = years_error
if reason:
    st.info(reason, icon="ℹ️")
go = st.sidebar.button("Generate map", type="primary", disabled=bool(reason), width="stretch")
if go:
    key = (q, tuple(bbox))
    if st.session_state.get("active") != key:   # a new map starts from clean styling
        for k in ("bin_colors", "palette"):
            st.session_state.pop(k, None)
        set_legend_rows(None)
    with st.status("Building map…", expanded=True) as status:
        try:
            st.write("Fetching / reading data…")
            cached_compute(q, tuple(bbox), allow_live())
            st.session_state["active"] = key
            status.update(label="Done", state="complete", expanded=False)
        except Exception as e:  # show a readable message instead of a stack trace on air
            st.session_state.pop("active", None)
            status.update(label="Failed", state="error")
            st.error(f"{type(e).__name__}: {e}")

active = st.session_state.get("active")
computed = cached_compute(active[0], active[1], allow_live()) if active else None
default_style = computed.style if computed else Style()
is_date_map = bool(computed and computed.ref)

# ---- style panel (sidebar)
with st.sidebar.expander("🎨 Style"):
    presets = list_presets()
    chosen = st.selectbox("Preset", ["(none)"] + list(presets), key="style_preset")
    if st.button("Apply preset", disabled=chosen == "(none)", width="stretch",
                 help="Load this saved look. Only the settings the preset contains are changed."):
        st.session_state["_pending"] = pending_from_json(presets[chosen].read_bytes(), RAMPS)
        st.rerun()
    if not presets:
        st.caption("No presets yet. Save one below and add the file to the repo's `presets/` folder.")
    up = st.file_uploader("Import palette / settings", type=["wctrp", "csv", "json"], key="style_upload",
                          help=".wctrp (MAX palette) or CSV (Value,R,G,B,Alpha) set the colors; JSON restores a full settings export.")
    if up is not None and st.session_state.get("_imported") != (up.name, up.size):
        st.session_state["_imported"] = (up.name, up.size)
        try:
            data = up.getvalue()
            if up.name.lower().endswith(".json"):
                # widgets already exist this run, so hand the values to the top of the next run (see _pending above)
                st.session_state["_pending"] = pending_from_json(data, RAMPS)
            else:
                rows = parse_wctrp(data)[0] if up.name.lower().endswith(".wctrp") else parse_legend_csv(data)
                if is_date_map:   # dates aren't palette values, so only the colors carry over (by position across the bins)
                    st.session_state["palette"] = [r[2:6] for r in rows]
                else:
                    set_legend_rows(rows)
            st.rerun()
        except (PaletteError, ValueError) as e:
            st.error(str(e))
    # The dropdown shows the ramp exactly as it will be applied, so it reads the other style widgets' current values
    # (Streamlit has already updated them for this run, even though they are created below).
    explicit_ramp = st.session_state.get("style_ramp")
    flip = st.session_state.get("style_flip", False)
    mode_now = st.session_state.get("style_mode", "Map default")
    shown_stepped = default_style.mode == "stepped" if mode_now == "Map default" else mode_now == "Stepped"
    picked = ramp_picker(
        "Color ramp", key=f"ramp_picker_{st.session_state.get('ramp_epoch', 0)}",
        selected=ramp_label(explicit_ramp or default_style.ramp),
        mode="Stepped" if shown_stepped else "Smooth Gradient", steps=st.session_state.get("style_steps", default_style.steps),
        reverse=flip if explicit_ramp else (default_style.reverse != flip),
    )
    if picked:        # rerun so the dropdown (already drawn this run) and the rest of the page see the new ramp
        st.session_state["style_ramp"] = picked
        st.rerun()
    flip = st.checkbox("Reverse colors", key="style_flip")
    mode_choice = st.radio("Shading", ["Map default", "Stepped", "Smooth"], horizontal=True, key="style_mode")
    steps = st.slider("Number of steps (automatic grouping)", 3, 20, int(default_style.steps), key="style_steps")
    if not is_date_map:
        c1, c2 = st.columns(2)
        vmin = c1.number_input("Min value", value=None, placeholder="auto", key="style_vmin")
        vmax = c2.number_input("Max value", value=None, placeholder="auto", key="style_vmax")
    else:
        vmin = vmax = None
    if st.button("Reset all style choices"):
        for k in ("style_ramp", "style_flip", "style_mode", "style_steps", "style_vmin", "style_vmax", "style_date_mode",
                  "palette", "bin_colors", "_imported"):
            st.session_state.pop(k, None)
        set_legend_rows(None)
        forget_ramp_pick()
        st.rerun()

style = build_style(
    default_style, ramp=explicit_ramp or None, flip=flip,
    mode=None if mode_choice == "Map default" else mode_choice.lower(), steps=steps if steps != default_style.steps else None,
    vmin=vmin, vmax=vmax, date_mode=date_mode if is_date_map else "auto", custom_starts=custom_starts,
    palette=st.session_state.get("palette"), bin_colors=st.session_state.get("bin_colors"),
    legend_rows=st.session_state.get("legend_rows"),
)

out = None
if computed:
    try:
        out = cached_render(active[0], active[1], allow_live(), json.dumps(dataclasses.asdict(style)))
    except ValueError as e:   # e.g. unreadable custom bin dates
        st.error(str(e))
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")

if out:
    st.subheader(out.name)
    if out.note:
        st.caption(out.note)
    dl1, dl2 = st.columns([1, 1])
    dl1.download_button("⬇️ Download KMZ", out.kmz, file_name=out.filename, mime="application/vnd.google-earth.kmz", type="primary")
    with dl2.popover("Save this look as a preset"):
        pname = st.text_input("Preset name", placeholder="e.g. On-air look", key="preset_name")
        try:
            slug = preset_slug(pname) if pname else None
        except ValueError:
            slug = None
        st.download_button("Download preset file", style_to_json(style, pname or None), file_name=f"{slug or 'preset'}.json",
                           mime="application/json", disabled=not slug, key="preset_dl")
        st.caption(f"To make it appear in everyone's Preset list, save the file as `presets/{slug or 'name'}.json` in the repo and commit it. "
                   "Presets store the look only (ramp, grouping, colors), never the data or the threshold.")
    tab_map, tab_img = st.tabs(["Map", "Image"])
    with tab_map:
        st_folium(build_map(out.png, out.bounds, counties(), out.points), use_container_width=True, height=560, returned_objects=[])
    with tab_img:  # dependency-free preview: works even if the map CDN / tile servers are unreachable
        overlay = Image.open(io.BytesIO(out.png)).convert("RGBA")
        canvas = Image.new("RGBA", overlay.size, (225, 225, 225, 255))
        canvas.alpha_composite(overlay)
        st.image(canvas.resize((overlay.width * 3, overlay.height * 3), Image.NEAREST),
                 caption="Rendered overlay on neutral gray (transparent areas = no data)", width="stretch")
    if out.legend_png:
        st.image(out.legend_png, caption="Legend (also included in the KMZ)")

    with st.expander("🎨 Edit colors", expanded=st.session_state.get("edit_colors_open", False)):
        if out.bins and style.date_mode != "auto":      # one editable color per date bin
            df = pd.DataFrame([{"Bin": lab, "R": c[0], "G": c[1], "B": c[2], "A": c[3]} for lab, c in out.bins])
            with st.form("bin_color_form"):
                edited = st.data_editor(df, disabled=["Bin"], hide_index=True, width="stretch", key="bin_color_editor",
                                        column_config={c: st.column_config.NumberColumn(c, min_value=0, max_value=255, step=1) for c in "RGBA"})
                apply_bins = st.form_submit_button("Apply colors")
            st.caption("A = opacity (0 = transparent). Each row is one date bin and one legend entry.")
            if apply_bins:
                new = dict(st.session_state.get("bin_colors") or {})
                for (lab, old), (_, row) in zip(out.bins, edited.iterrows()):
                    cur = [int(row[c]) for c in "RGBA"]
                    if cur != list(old):
                        new[lab] = cur
                st.session_state["bin_colors"] = new
                st.rerun()
        elif not is_date_map and (style.legend_rows or out.seed_rows):    # numeric maps: bands "from this value up to To"
            rows = style.legend_rows or out.seed_rows
            lo, hi = out.data_min, out.data_max
            with st.expander("🎨 Generate bands from a preset ramp"):
                gcols = st.columns([3, 1])
                with gcols[0]:
                    gen_pick = ramp_picker(
                        "Ramp", key="gen_ramp", selected=st.session_state.get("gen_ramp_label", "RdYlBu"),
                        mode="Smooth Gradient", steps=10, reverse=st.session_state.get("gen_reverse", False))
                    if gen_pick:
                        st.session_state["gen_ramp_label"] = gen_pick
                        st.rerun()
                gen_reverse = gcols[1].checkbox("Reverse", key="gen_reverse")
                gen_by = st.radio("Make bands", ["By number of bands", "By band width"], horizontal=True, key="gen_by")
                a, b, c = st.columns(3)
                gen_start = a.number_input("Start", value=float(f"{lo:.6g}") if lo is not None else 0.0, format="%g", key=f"gen_start_{zlib.crc32(repr(active).encode())}")
                gen_end = b.number_input("End", value=float(f"{hi:.6g}") if hi is not None else 10.0, format="%g", key=f"gen_end_{zlib.crc32(repr(active).encode())}")
                if gen_by == "By number of bands":
                    gen_count, gen_width = c.number_input("Number of bands", 2, 300, 10, 1, key="gen_count"), None
                else:
                    gen_width = c.number_input("Band width", min_value=1e-6, value=float(f"{(gen_end - gen_start) / 10:.2g}") or 1.0, format="%g", key=f"gen_width_{zlib.crc32(repr(active).encode())}")
                gen_open_bottom = st.checkbox("Bottom band has no lower limit", key="gen_open_bottom")
                gen_open_top = st.checkbox("Top band has no upper limit", value=True, key="gen_open_top")
                if st.button("Generate bands"):
                    if gen_end <= gen_start:
                        st.error("End must be greater than Start.")
                    else:
                        n = int(gen_count) if gen_width is None else int(np.ceil((gen_end - gen_start) / gen_width - 1e-9))
                        edges = np.linspace(gen_start, gen_end, n + 1) if gen_width is None else gen_start + gen_width * np.arange(n + 1)
                        if n > 300:
                            st.error(f"That would make {n} bands; the limit is 300. Use a wider band width.")
                        else:
                            cmap = mpl.colormaps[RAMPS[st.session_state.get("gen_ramp_label", "RdYlBu")] + ("_r" if gen_reverse else "")]
                            new_rows = []
                            for i in range(n):
                                r_, g_, b_ = (int(x * 255) for x in cmap(i / (n - 1) if n > 1 else 0.5)[:3])
                                new_rows.append([None if (i == 0 and gen_open_bottom) else float(f"{edges[i]:.8g}"),
                                                 None if (i == n - 1 and gen_open_top) else float(f"{edges[i + 1]:.8g}"), r_, g_, b_, 255])
                            set_legend_rows(new_rows)
                            st.rerun()
            st.caption("Each row colors values from its **From** up to (not including) its **To**; leave the last To blank for no upper "
                       "limit, or the first From blank for no lower limit. Values outside every row are transparent. Smooth shading "
                       "blends from each row's From color, ignoring To.")
            if not style.legend_rows:     # the editor reloads whenever the automatic steps (ramp, steps, range) change
                st.session_state["seed_sig"] = hash(json.dumps(out.seed_rows))
            edited = legend_editor(rows, version=f"{st.session_state.get('legend_version', 0)}:{st.session_state.get('seed_sig', 0)}")
            if edited is not None:
                st.session_state["legend_rows"] = edited
                st.session_state["edit_colors_open"] = True     # the rerun below would otherwise fold the expander
                st.rerun()
            units = default_style.units_label
            unit_names = list(UNIT_IDS) + ["Other…"]
            guess = {"°F": "Temperature (°F)", "in": "Precipitation (inches)"}.get(units, "Precipitation (inches)")
            wc1, wc2 = st.columns([3, 2], vertical_alignment="bottom")
            unit_pick = wc1.selectbox("MAX unit for the .wctrp", unit_names, index=unit_names.index(guess), key=f"wctrp_unit_{units}",
                                      help="Written into the file as MAX's unit id. Precipitation (inches) is 2 and Temperature (°F) is 11; "
                                           "use Other… for another unit's id.")
            unit_id = UNIT_IDS.get(unit_pick)
            if unit_id is None:
                unit_id = wc1.number_input("MAX unit id", 0, 999, 2, 1, key="wctrp_unit_other")
            try:
                wc2.download_button("⬇️ Download as .wctrp", wctrp_bytes(rows, unit_id), file_name=out.filename.rsplit(".", 1)[0] + ".wctrp",
                                    mime="application/octet-stream", width="stretch",
                                    help="A MAX color palette: one band per row, a gap becomes a transparent band, no upper limit is written as 999.")
            except ValueError as e:
                wc2.caption(str(e))
        else:
            st.caption("Choose a date grouping (weekly, thirds, halves or custom) to edit the color of each date bin.")
        if st.button("Reset colors"):
            for k in ("bin_colors", "palette"):
                st.session_state.pop(k, None)
            set_legend_rows(None)
            st.rerun()
elif not reason and not computed:
    st.markdown("### Pick a map in the sidebar, then **Generate map**.")
