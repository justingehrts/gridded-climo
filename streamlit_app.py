"""Gridded Climo — broadcast climate maps. Run: streamlit run streamlit_app.py"""
from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
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
from gridded_climo.query import MENU, NOHRSC_START, SPARSE_BEFORE, STATION_FIRST_YEAR, STATION_MENU, TEMP_ELEMENTS, default_season, last_complete_year, Query, allow_live, unsupported_reason
from gridded_climo.ui.preview import build_map, load_counties_geojson
from gridded_climo.binning import MODE_LABELS, MODES
from gridded_climo.registry import Style
from gridded_climo.render import PaletteError, RAMPS, parse_legend_csv, parse_wctrp, style_from_json, style_to_json
from gridded_climo.render.palettes import sample_colors
from gridded_climo.ui.service import compute, render_computed
from gridded_climo.ui.style_build import build_style

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
REGIONS = {
    "Columbus region (default)": DEFAULT_BBOX,
    "Central Ohio": (-84.5, 39.3, -81.5, 41.0),
    "Ohio": (-85.0, 38.3, -80.4, 42.1),
    "Custom…": None,
}
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


@st.cache_data(show_spinner=False)
def ramp_strip(name: str, reverse: bool) -> Image.Image:
    cmap = mpl.colormaps[RAMPS.get(name, name) + ("_r" if reverse else "")]
    arr = (cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype("uint8")[None, :, :].repeat(14, axis=0)
    return Image.fromarray(arr)


@st.cache_data(show_spinner=False)
def counties():
    return load_counties_geojson()


# Imported settings are applied before any widget exists in this run (Streamlit forbids changing a widget after creation).
if "_pending" in st.session_state:
    st.session_state.update(st.session_state.pop("_pending"))

# ---------------------------------------------------------------- selectors
with st.sidebar:
    st.title("🗺️ Gridded Climo")
    st.caption("Broadcast climate maps · ACIS Grid 1 · NOHRSC snowfall")

    st.subheader("1 · When")
    when_label = st.radio("When", ["Average first date", "Average last date", "Custom range"], label_visibility="collapsed")
    range_mode = None
    if when_label == "Custom range":
        range_mode = st.radio("Range type", ["Specific dates", "Averaged over normal period"],
                              help="Specific dates = one real period. Averaged = the same calendar dates averaged over every year in the normal period.")

    st.subheader("2 · What")
    q_kwargs: dict = {}
    if when_label != "Custom range":
        var = st.selectbox("Variable", ["Temperature at or below", "Temperature at or above", "Snowfall"])
        if var == "Snowfall":
            amount = st.number_input("Daily snowfall at least (in)", 0.1, 30.0, 1.0, 0.1,
                                     help="Pre-saved: " + ", ".join(f"{v:g}" for v in STATION_MENU[("snow", "ge")]) + ". Other amounts are fetched live from ACIS (~15-30 s).")
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
            menu = MENU[(el, op)]
            if by_station or allow_live():
                value = st.number_input("Threshold (°F)", -60.0, 140.0, float(menu[0]), 1.0,
                                        help=("Pre-saved: " + ", ".join(f"{v:g}" for v in STATION_MENU[(el, op)])
                                              + ". Other values are fetched live from ACIS (~15-30 s).") if by_station else None)
            else:
                value = st.select_slider("Threshold (°F)", options=list(menu), value=menu[0])
            q_kwargs.update(element=el, op=op, value=float(value), method="station" if by_station else "grid")
        q_kwargs["when"] = "first" if when_label == "Average first date" else "last"
    else:
        var = st.selectbox("Variable", ["High temperature", "Low temperature", "Precipitation", "Snowfall"])
        el = {"High temperature": "maxt", "Low temperature": "mint", "Precipitation": "pcpn", "Snowfall": "snow"}[var]
        q_kwargs["element"] = el
        if el != "snow":
            default = "sum" if el == "pcpn" else "mean"
            opts = ["mean", "sum", "max", "min"]
            q_kwargs["reduce"] = st.selectbox("Summarize as", opts, index=opts.index(default),
                                              format_func={"mean": "Average", "sum": "Total", "max": "Maximum", "min": "Minimum"}.get)
        q_kwargs["when"] = "range_specific" if range_mode == "Specific dates" else "range_normal"
        if range_mode == "Specific dates" and el != "snow":
            q_kwargs["departure"] = st.checkbox("Show departure from normal", help="Value minus the daily normals for the same days.")

    st.subheader("3 · Dates")
    date_mode, custom_starts = "auto", ""
    if when_label != "Custom range":
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

    with st.expander("Options"):
        n0, n1 = st.columns(2)
        label_y = "Years included: from" if when_label != "Custom range" else "Normal period: from"
        if when_label != "Custom range":
            ymax = last_complete_year(default_season(q_kwargs.get("op", "ge"), q_kwargs["when"], q_kwargs["element"]))
        else:
            ymax = last_complete_year({"start": [1, 1], "end": [12, 31]})
        normal = (n0.number_input(label_y, STATION_FIRST_YEAR, ymax - 1, DEFAULT_NORMAL_PERIOD[0]),
                  n1.number_input("to", STATION_FIRST_YEAR + 1, ymax, DEFAULT_NORMAL_PERIOD[1]))
        if when_label != "Custom range":
            st.caption("For a record (earliest/latest), set the range to all the years you want, e.g. 1950–2025. The Stations method works back to 1870 (most reliable from ~1895); the Grid method only has 1991 onward.")
            if int(normal[0]) < SPARSE_BEFORE:
                st.warning(f"Before ~{SPARSE_BEFORE} only a handful of stations report in this region, so these maps can be mostly blank or rest on very few stations.")
        q_kwargs["normal_period"] = (int(normal[0]), int(normal[1]))
        if when_label != "Custom range":
            stat_label = st.selectbox("Statistic across years", ["Average date", "Median date", "Earliest on record", "Latest on record", "Percentile"])
            stat = {"Average date": "mean", "Median date": "median", "Earliest on record": "min", "Latest on record": "max", "Percentile": "percentile"}[stat_label]
            q_kwargs["stat"] = stat
            if stat == "percentile":
                q_kwargs["percentile"] = st.slider("Percentile", 1, 99, 10)
            if stat in ("min", "max"):
                st.caption("Each station's single earliest/latest date in the chosen years; its record year shows in the map tooltip.")
        region_name = st.selectbox("Region", list(REGIONS))
        bbox = REGIONS[region_name]
        if bbox is None:
            w0, s0, e0, n0_ = DEFAULT_BBOX
            c1, c2 = st.columns(2)
            west = c1.number_input("West", w0, e0, w0, 0.1); east = c2.number_input("East", w0, e0, e0, 0.1)
            south = c1.number_input("South", s0, n0_, s0, 0.1); north = c2.number_input("North", s0, n0_, n0_, 0.1)
            bbox = (west, south, east, north)

q = Query(**{k: v for k, v in q_kwargs.items() if k in Query.__dataclass_fields__})
if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
    reason = "Region: west must be less than east and south less than north."
else:
    reason = unsupported_reason(q) if q.start is not None or q.when in ("first", "last") or q.element == "snow" else "Choose valid dates."
    if q.when != "first" and q.when != "last" and (q.start is None or q.end is None):
        reason = "Choose valid dates."

# ---------------------------------------------------------------- main panel
if reason:
    st.info(reason, icon="ℹ️")
go = st.sidebar.button("Generate map", type="primary", disabled=bool(reason), width="stretch")
if go:
    key = (q, tuple(bbox))
    if st.session_state.get("active") != key:   # a new map starts from clean styling
        for k in ("bin_colors", "palette", "legend_rows"):
            st.session_state.pop(k, None)
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
    up = st.file_uploader("Import palette / settings", type=["wctrp", "csv", "json"], key="style_upload",
                          help=".wctrp (MAX palette) or CSV (Value,R,G,B,Alpha) set the colors; JSON restores a full settings export.")
    if up is not None and st.session_state.get("_imported") != (up.name, up.size):
        st.session_state["_imported"] = (up.name, up.size)
        try:
            data = up.getvalue()
            if up.name.lower().endswith(".json"):
                imp = style_from_json(data)
                # widgets already exist this run, so hand the values to the top of the next run (see _pending below)
                st.session_state["_pending"] = dict(
                    style_ramp=imp.ramp if imp.ramp in RAMPS else "Map default", style_flip=imp.reverse,
                    style_mode=imp.mode.title(), style_steps=imp.steps, style_date_mode=imp.date_mode,
                    style_custom_starts=imp.custom_starts or "Oct 1, Oct 8, Oct 15, Oct 22, Nov 1",
                    palette=imp.palette, bin_colors=imp.bin_colors, legend_rows=imp.legend_rows)
            else:
                rows = parse_wctrp(data)[0] if up.name.lower().endswith(".wctrp") else parse_legend_csv(data)
                if is_date_map:   # dates aren't palette values, so only the colors carry over (by position across the bins)
                    st.session_state["palette"] = [r[1:5] for r in rows]
                else:
                    st.session_state["legend_rows"] = rows
            st.rerun()
        except PaletteError as e:
            st.error(str(e))
    ramp_choice = st.selectbox("Color ramp", ["Map default"] + sorted(RAMPS), key="style_ramp")
    flip = st.checkbox("Reverse colors", key="style_flip")
    shown = default_style.ramp if ramp_choice == "Map default" else ramp_choice
    st.image(ramp_strip(shown, (flip if ramp_choice != "Map default" else (default_style.reverse != flip))), width="stretch")
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
                  "palette", "bin_colors", "legend_rows", "_imported"):
            st.session_state.pop(k, None)
        st.rerun()

style = build_style(
    default_style, ramp=None if ramp_choice == "Map default" else ramp_choice, flip=flip,
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
    dl2.download_button("Export style settings (JSON)", style_to_json(style), file_name="gridded_climo_style.json", mime="application/json")
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

    with st.expander("🎨 Edit colors"):
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
        elif not is_date_map and (style.legend_rows or out.seed_rows):    # numeric maps: value = lower bound of its band
            rows = style.legend_rows or out.seed_rows
            df = pd.DataFrame([{"Value": r[0], "R": r[1], "G": r[2], "B": r[3], "A": r[4] if len(r) > 4 else 255} for r in rows])
            with st.form("legend_form"):
                edited = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="legend_editor")
                apply_leg = st.form_submit_button("Apply as custom legend")
            st.caption("Value = the lower bound of that color band, in the map's units. A = opacity (0 = transparent).")
            if apply_leg:
                clean = edited.dropna(subset=["Value"]).sort_values("Value")
                st.session_state["legend_rows"] = [[float(r.Value), int(r.R), int(r.G), int(r.B), int(r.A if r.A == r.A else 255)]
                                                   for r in clean.itertuples()]
                st.rerun()
        else:
            st.caption("Choose a date grouping (weekly, thirds, halves or custom) to edit the color of each date bin.")
        if st.button("Reset colors"):
            for k in ("bin_colors", "palette", "legend_rows"):
                st.session_state.pop(k, None)
            st.rerun()
elif not reason and not computed:
    st.markdown("### Pick a map in the sidebar, then **Generate map**.")
