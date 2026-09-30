"""Gridded Climo — broadcast climate maps. Run: streamlit run streamlit_app.py"""
from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from PIL import Image
from streamlit_folium import st_folium

from gridded_climo.config import DEFAULT_BBOX, DEFAULT_NORMAL_PERIOD
from gridded_climo.query import MENU, NOHRSC_START, STATION_MENU, TEMP_ELEMENTS, Query, allow_live, unsupported_reason
from gridded_climo.ui.preview import build_map, load_counties_geojson
from gridded_climo.ui.service import generate

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
def cached_generate(q: Query, bbox, allow_live_flag: bool):
    return generate(q, bbox, CACHE_DIR, allow_live=True)


@st.cache_data(show_spinner=False)
def counties():
    return load_counties_geojson()


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
            menu = STATION_MENU[("snow", "ge")]
            amount = st.number_input("Daily snowfall at least (in)", 0.1, 30.0, 1.0, 0.1) if allow_live() else \
                st.select_slider("Daily snowfall at least (in)", options=list(menu), value=1.0)
            q_kwargs.update(element="snow", op="ge", value=float(amount), method="station")
            st.caption("Snowfall has no ACIS grid, so this uses station observations interpolated to a map.")
        else:
            op = "le" if var.endswith("below") else "ge"
            el_label = st.radio("Which temperature?", list(TEMP_ELEMENTS.values()), index=0 if op == "le" else 1, horizontal=True)
            el = next(k for k, v in TEMP_ELEMENTS.items() if v == el_label)
            menu = MENU[(el, op)]
            if allow_live():
                value = st.number_input("Threshold (°F)", -40.0, 130.0, float(menu[0]), 1.0)
            else:
                value = st.select_slider("Threshold (°F)", options=list(menu), value=menu[0])
            method_label = st.radio(
                "Method", ["Grid (ACIS Grid 1)", "Stations (interpolated)"],
                help="Grid: NRCC's 5 km daily temperature grid, scanned cell by cell — smooth, every cell has a value. "
                     "Stations: each station's own average date (what the ACIS website shows), then interpolated — "
                     "official station values at the dots. The two can differ by days to a couple of weeks locally.")
            q_kwargs.update(element=el, op=op, value=float(value), method="station" if method_label.startswith("Stations") else "grid")
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
    if when_label != "Custom range":
        st.caption("Uses every year in the normal period (see Options).")
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
        normal = (n0.number_input("Normal from", 1950, 2024, DEFAULT_NORMAL_PERIOD[0]), n1.number_input("to", 1951, 2025, DEFAULT_NORMAL_PERIOD[1]))
        q_kwargs["normal_period"] = (int(normal[0]), int(normal[1]))
        if when_label != "Custom range":
            stat = st.selectbox("Statistic across years", ["mean", "median", "percentile"])
            q_kwargs["stat"] = stat
            if stat == "percentile":
                q_kwargs["percentile"] = st.slider("Percentile", 1, 99, 10)
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
go = st.sidebar.button("Generate map", type="primary", disabled=bool(reason), use_container_width=True)
if go:
    with st.status("Building map…", expanded=True) as status:
        try:
            st.write("Fetching / reading data and rendering…")
            st.session_state["out"] = cached_generate(q, tuple(bbox), allow_live())
            status.update(label="Done", state="complete", expanded=False)
        except Exception as e:  # show a readable message instead of a stack trace on air
            st.session_state.pop("out", None)
            status.update(label="Failed", state="error")
            st.error(f"{type(e).__name__}: {e}")

out = st.session_state.get("out")
if out:
    st.subheader(out.name)
    if out.note:
        st.caption(out.note)
    st.download_button("⬇️ Download KMZ", out.kmz, file_name=out.filename, mime="application/vnd.google-earth.kmz", type="primary")
    tab_map, tab_img = st.tabs(["Map", "Image"])
    with tab_map:
        st_folium(build_map(out.png, out.bounds, counties(), out.points), use_container_width=True, height=560, returned_objects=[])
    with tab_img:  # dependency-free preview: works even if the map CDN / tile servers are unreachable
        overlay = Image.open(io.BytesIO(out.png)).convert("RGBA")
        canvas = Image.new("RGBA", overlay.size, (225, 225, 225, 255))
        canvas.alpha_composite(overlay)
        st.image(canvas.resize((overlay.width * 3, overlay.height * 3), Image.NEAREST),
                 caption="Rendered overlay on neutral gray (transparent areas = no data)", use_container_width=True)
    if out.legend_png:
        st.image(out.legend_png, caption="Legend (also included in the KMZ)")
elif not reason:
    st.markdown("### Pick a map in the sidebar, then **Generate map**.")
