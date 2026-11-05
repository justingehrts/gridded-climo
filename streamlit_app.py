"""Gridded Climo — broadcast climate maps. Run: streamlit run streamlit_app.py"""
from __future__ import annotations

import calendar
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
from gridded_climo.binning import MODE_LABELS, MODES, parse_custom_starts
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
from gridded_climo.ui import forms
from gridded_climo.ui.maptypes import BY_ID, DEFAULT_TYPE, VARIABLES, first_type, source_note, swatch_css, types_for
from gridded_climo.query import describe

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
MONTHS_FULL = [calendar.month_name[m] for m in range(1, 13)]
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


# ---------------------------------------------------------------- layout helpers
st.html("""<style>
/* Summary + Generate stick to the bottom of the sidebar on long forms. Streamlit wraps the keyed container in a box of the
   same size, so the wrapper is what sticks (sticky can't leave its parent). */
div:has(> .st-key-gen_dock) { position: sticky; bottom: 0; z-index: 5; }
.st-key-gen_dock { background: var(--secondary-background-color, #f0f2f6); padding: .5rem 0 .75rem;
  border-top: 1px solid rgba(128,128,128,.25); box-shadow: 0 -6px 12px -10px rgba(0,0,0,.35); }
.gc-swatch { height: 10px; border-radius: 3px; margin-bottom: 2px; }
section[data-testid="stSidebar"] { min-width: 340px; }
</style>""")

st.session_state.setdefault("f_var", "temperature")
st.session_state.setdefault("f_type", DEFAULT_TYPE)
st.session_state.setdefault("main_view", "Map")
if BY_ID.get(st.session_state["f_type"]) is None:
    st.session_state["f_type"] = DEFAULT_TYPE


def _on_var():
    if BY_ID[st.session_state["f_type"]].variable != st.session_state["f_var"]:
        st.session_state["f_type"] = first_type(st.session_state["f_var"])


def _pick_type(type_id: str):
    st.session_state["f_type"] = type_id
    st.session_state["f_var"] = BY_ID[type_id].variable


def _on_type_pill(pkey: str):
    picked = st.session_state.get(pkey)
    if picked:
        st.session_state["f_type"] = picked
    else:                       # clicking the chosen pill again would clear it; keep the current type selected
        st.session_state[pkey] = st.session_state["f_type"]


def _restore(snap: dict):
    st.session_state["_pending"] = dict(snap)


def _show_band_colors():
    st.session_state["main_view"] = "Band colors"


# ---------------------------------------------------------------- sidebar: Map tab
with st.sidebar:
    st.title("🗺️ Gridded Climo")
    st.caption("Broadcast climate maps · ACIS · NOHRSC")
    tab_map, tab_look, tab_export = st.tabs(["Map", "Look", "Export"])

with tab_map:
    area_name = st.selectbox("Area", AREAS, key="area",
                             help="Pick a state (shown with a buffer so neighbors and surroundings are included) or draw your own box. "
                                  "Ohio and the Columbus default use pre-saved data; other areas are fetched live from ACIS.")
    if area_name == DEFAULT_AREA:
        bbox = DEFAULT_BBOX
    elif area_name == "Custom…":
        c1, c2 = st.columns(2)
        w0, s0, e0, n0_ = CONUS_BOUNDS
        d0 = DEFAULT_BBOX
        west = c1.number_input("West", w0, e0, d0[0], 0.1, key="area_w"); east = c2.number_input("East", w0, e0, d0[2], 0.1, key="area_e")
        north = c1.number_input("North", s0, n0_, d0[3], 0.1, key="area_n"); south = c2.number_input("South", s0, n0_, d0[1], 0.1, key="area_s")
        bbox = (west, south, east, north)
    else:
        code = STATE_CODES[area_name]
        bbox = buffered_bbox(code)
        b = buffer_deg(tuple(states()[code]["bbox"]))
        st.caption(f"{area_name} plus a {b:.2f}° (~{b * 111:.0f} km) buffer.")
    if area_name != DEFAULT_AREA and presaved_bbox(tuple(bbox)) is None:
        st.caption("📡 Outside the pre-saved region: station maps and date ranges are fetched live from ACIS (can take longer), "
                   "and grid first/last dates and departure maps aren't available here.")

    st.segmented_control("Variable", list(VARIABLES), format_func=VARIABLES.get, required=True, key="f_var", on_change=_on_var,
                         width="stretch")
    type_id = st.session_state["f_type"]
    choices = types_for(st.session_state["f_var"])
    if len(choices) > 1:
        groups = list(dict.fromkeys(t.group for t in choices))
        for group in groups:
            ids = [t.id for t in choices if t.group == group]
            pkey = f"mt_{st.session_state['f_var']}_{group or 'all'}"
            st.session_state[pkey] = type_id if type_id in ids else None      # one map type is chosen across all groups
            st.pills(group or "Map type", ids, format_func=lambda i: BY_ID[i].name, key=pkey, on_change=_on_type_pill, args=(pkey,),
                     label_visibility="visible")
    st.markdown(f"#### {BY_ID[type_id].name}")
    st.caption(BY_ID[type_id].blurb)

    res = forms.render_form(type_id, forms.Ctx(tuple(bbox), cached_por, TODAY))
    q = Query(**{k: v for k, v in res.q.items() if k in Query.__dataclass_fields__})
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        reason = "Area: west must be less than east, and south less than north."
    elif res.error:
        reason = res.error
    elif q.when not in ("first", "last", "sun") and (q.start is None or q.end is None):
        reason = "Choose valid dates."
    else:
        reason = unsupported_reason(q, bbox)
    try:
        will_make = describe(q)
    except Exception:
        will_make = BY_ID[type_id].name

    with st.container(key="gen_dock"):
        with st.container(border=True, gap="small"):
            st.markdown(f"<small>Will make</small><br>**{will_make}**", unsafe_allow_html=True)
            st.caption(f"{area_name.replace(' (pre-saved)', '')} · {source_note(type_id, res.q.get('method'), presaved_bbox(tuple(bbox)) is not None)}")
            if reason:
                st.info(reason, icon="ℹ️")
        go = st.button("Generate map", type="primary", disabled=bool(reason), width="stretch")
    recent_box = st.container()

# ---------------------------------------------------------------- generate
if go:
    key = (q, tuple(bbox))
    if st.session_state.get("active") != key:   # a new map starts from clean styling
        for k in ("bin_colors", "palette", "bin_dropped"):
            st.session_state.pop(k, None)
        set_legend_rows(None)
    with st.status("Building map…", expanded=True) as status:
        try:
            st.write("Fetching / reading data…")
            cached_compute(q, tuple(bbox), allow_live())
            st.session_state["active"] = key
            st.session_state["main_view"] = "Map"
            title = describe(q)
            recent = [r for r in st.session_state.get("recent", []) if r["title"] != title or r["area"] != area_name]
            st.session_state["recent"] = [{"title": title, "area": area_name, "snap": forms.snapshot(st.session_state)}] + recent[:4]
            status.update(label="Done", state="complete", expanded=False)
        except Exception as e:  # show a readable message instead of a stack trace on air
            st.session_state.pop("active", None)
            status.update(label="Failed", state="error")
            st.error(f"{type(e).__name__}: {e}")

with recent_box:
    if st.session_state.get("recent"):
        st.markdown("**Recent maps**")
        for i, r in enumerate(st.session_state["recent"]):
            st.button(f"↺ {r['title']}" + ("" if r["area"] == DEFAULT_AREA else f" · {r['area']}"), key=f"recent_{i}",
                      on_click=_restore, args=(r["snap"],), width="stretch")
    else:
        st.caption("Maps you generate appear here, so you can re-make one in a click.")

active = st.session_state.get("active")
computed = cached_compute(active[0], active[1], allow_live()) if active else None
default_style = computed.style if computed else Style()
is_date_map = bool(computed and computed.ref)

# ---------------------------------------------------------------- sidebar: Look tab
DEFAULT_CUSTOM_STARTS = "Oct 1, Oct 8, Oct 15, Oct 22, Nov 1"
st.session_state.setdefault("style_custom_starts", DEFAULT_CUSTOM_STARTS)     # the text box and the style read the same key, even on the run that picks Custom


def date_grouping_controls():
    """'Group dates into' + custom bin starts. Rendered in one place per run (the Band colors view when it is open, otherwise
    the Look tab); both read and write the same widget keys, so build_style below just reads session state."""
    st.radio("Group dates into", MODES, format_func=MODE_LABELS.get, key="style_date_mode",
             help="Automatic: equal color steps across the data. Weekly: 1st–6th, 7th–13th, 14th–20th, 21st–end of "
                  "month. Thirds: early / mid / late month. Halves: 1st–15th and 16th–end. Custom: your own bin start dates.")
    if st.session_state.get("style_date_mode") == "custom":
        st.text_input("Bin start dates (in season order)", key="style_custom_starts",
                      help="Each bin runs from its start date to the day before the next one. Data before the first date "
                           "gets a 'Before…' bin; data after the last start extends the last bin.")


band_view_open = bool(computed) and st.session_state.get("main_view") == "Band colors"
with tab_look:
    st.caption("Changes apply to the current map right away.")
    presets = list_presets()
    chosen = st.selectbox("Preset", ["(none)"] + list(presets), key="style_preset")
    if st.button("Apply preset", disabled=chosen == "(none)", width="stretch",
                 help="Load this saved look. Only the settings the preset contains are changed."):
        st.session_state["_pending"] = pending_from_json(presets[chosen].read_bytes(), RAMPS)
        st.rerun()
    if not presets:
        st.caption("No presets yet. Save one from the Export tab and add the file to the repo's `presets/` folder.")
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
        if band_view_open:
            st.caption("Date grouping is set in the Band colors view.")
        else:
            date_grouping_controls()
    st.button("Edit individual band colors →", on_click=_show_band_colors, disabled=computed is None, width="stretch",
              help="Opens the band color table (with Ramp RGB to blend between two rows) next to the map.")
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
    if st.button("Reset all style choices", width="stretch"):
        for k in ("style_ramp", "style_flip", "style_mode", "style_steps", "style_vmin", "style_vmax", "style_date_mode",
                  "style_custom_starts", "palette", "bin_colors", "bin_dropped", "_imported"):
            st.session_state.pop(k, None)
        set_legend_rows(None)
        forget_ramp_pick()
        st.rerun()

date_mode = st.session_state.get("style_date_mode", "auto") if is_date_map else "auto"
custom_starts = st.session_state.get("style_custom_starts", DEFAULT_CUSTOM_STARTS) if date_mode == "custom" else ""
if date_mode == "custom":       # unreadable bin dates must not blank the page: say so, and draw this run with Automatic grouping
    try:
        parse_custom_starts(custom_starts)
    except ValueError as e:
        st.error(str(e))
        date_mode, custom_starts = "auto", ""
# Deleted date bins only apply to the grouping (and custom dates) they were deleted from
_drop = st.session_state.get("bin_dropped") or {}
dropped_bins = _drop.get("starts") if (is_date_map and date_mode != "auto" and _drop.get("sig") == (date_mode, custom_starts)) else None
style = build_style(
    default_style, ramp=explicit_ramp or None, flip=flip,
    mode=None if mode_choice == "Map default" else mode_choice.lower(), steps=steps if steps != default_style.steps else None,
    vmin=vmin, vmax=vmax, date_mode=date_mode, custom_starts=custom_starts,
    palette=st.session_state.get("palette"), bin_colors=st.session_state.get("bin_colors"),
    legend_rows=st.session_state.get("legend_rows"), dropped_bins=dropped_bins,
)

out = None
if computed:
    try:
        try:
            out = cached_render(active[0], active[1], allow_live(), json.dumps(dataclasses.asdict(style)))
        except ValueError as e:   # e.g. custom bin dates out of order: say so, and keep the page by drawing with Automatic grouping
            if style.date_mode == "auto":
                raise
            st.error(str(e))
            auto = dataclasses.replace(style, date_mode="auto", custom_starts="", dropped_bins=None)
            out = cached_render(active[0], active[1], allow_live(), json.dumps(dataclasses.asdict(auto)))
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------- sidebar: Export tab
with tab_export:
    if out:
        st.download_button("⬇️ Download KMZ", out.kmz, file_name=out.filename, mime="application/vnd.google-earth.kmz", type="primary",
                           width="stretch")
    else:
        st.caption("Generate a map to download its KMZ.")
    with st.expander("Save look as preset"):
        pname = st.text_input("Preset name", placeholder="e.g. On-air look", key="preset_name")
        try:
            slug = preset_slug(pname) if pname else None
        except ValueError:
            slug = None
        st.download_button("Download preset file", style_to_json(style, pname or None), file_name=f"{slug or 'preset'}.json",
                           mime="application/json", disabled=not slug, key="preset_dl")
        st.caption(f"To make it appear in everyone's Preset list, save the file as `presets/{slug or 'name'}.json` in the repo and commit it. "
                   "Presets store the look only (ramp, grouping, colors), never the data or the threshold.")
    with st.expander("Save or load a whole map"):
        saved = {"kind": "gridded-climo-map", "version": 1, "title": will_make,
                 "widgets": forms.to_jsonable(forms.snapshot(st.session_state)), "look": json.loads(style_to_json(style, None))}
        fname = "".join(ch if ch.isalnum() else "_" for ch in will_make).strip("_").lower()[:60] or "map"
        st.download_button("Save whole map (settings + look)", json.dumps(saved, indent=1), file_name=f"{fname}.map.json",
                           mime="application/json", key="map_dl", width="stretch")
        mup = st.file_uploader("Load a saved map", type=["json"], key="map_upload")
        if mup is not None and st.session_state.get("_map_loaded") != (mup.name, mup.size):
            st.session_state["_map_loaded"] = (mup.name, mup.size)
            try:
                d = json.loads(mup.getvalue())
                if not isinstance(d, dict) or d.get("kind") != "gridded-climo-map":
                    raise ValueError("That file isn't a saved map (use Look → Import for palettes and presets).")
                pending = forms.from_jsonable(d.get("widgets") or {})
                if d.get("look"):
                    pending.update(pending_from_json(json.dumps(d["look"]), RAMPS))
                st.session_state["_pending"] = pending
                st.rerun()
            except (ValueError, TypeError) as e:
                st.error(str(e))
        st.caption("A saved map keeps the area, map type, every setting and the look, so a routine map comes back in one step.")

# ---------------------------------------------------------------- main panel
if out:
    st.subheader(out.name)
    if out.note:
        st.caption(out.note)
    view = st.segmented_control("View", ["Map", "Image", "Band colors"], required=True, key="main_view", label_visibility="collapsed")
    if view == "Map":
        st_folium(build_map(out.png, out.bounds, counties(), out.points), use_container_width=True, height=560, returned_objects=[])
    elif view == "Image":  # dependency-free preview: works even if the map CDN / tile servers are unreachable
        overlay = Image.open(io.BytesIO(out.png)).convert("RGBA")
        canvas = Image.new("RGBA", overlay.size, (225, 225, 225, 255))
        canvas.alpha_composite(overlay)
        st.image(canvas.resize((overlay.width * 3, overlay.height * 3), Image.NEAREST),
                 caption="Rendered overlay on neutral gray (transparent areas = no data)", width="stretch")
    if out.legend_png:
        st.image(out.legend_png, caption="Legend (also included in the KMZ)")
    if view == "Band colors":
        if is_date_map:
            date_grouping_controls()
        if out.bins and style.date_mode != "auto":      # one editable color per date bin
            starts = list(out.bin_starts or [None] * len(out.bins))
            df = pd.DataFrame([{"Bin": lab, "R": c[0], "G": c[1], "B": c[2], "A": c[3]} for lab, c in out.bins])
            with st.form("bin_color_form"):
                edited = st.data_editor(df, disabled=["Bin"], hide_index=True, width="stretch", key=f"bin_color_editor_{zlib.crc32(repr([lab for lab, _ in out.bins]).encode())}", num_rows="delete",
                                        column_config={c: st.column_config.NumberColumn(c, min_value=0, max_value=255, step=1) for c in "RGBA"})
                apply_bins = st.form_submit_button("Apply colors")
            st.caption("A = opacity (0 = transparent). Each row is one date bin and one legend entry. **Delete rows to merge bins**: "
                       "removing the first rows makes a \"Before …\" bin, removing the last rows extends the final bin.")
            if apply_bins:
                new = dict(st.session_state.get("bin_colors") or {})
                for (lab, old), (_, row) in zip(out.bins, edited.iterrows()):
                    cur = [int(row[c]) for c in "RGBA"]
                    if cur != list(old):
                        new[lab] = cur
                st.session_state["bin_colors"] = new
                gone = [starts[i] for i in df.index.difference(edited.index) if i < len(starts) and starts[i]]
                if gone:
                    sig = (date_mode, custom_starts)
                    prev = _drop.get("starts", []) if _drop.get("sig") == sig else []
                    st.session_state["bin_dropped"] = {"sig": sig, "starts": prev + [g for g in gone if g not in prev]}
                st.rerun()
            if dropped_bins:
                if st.button("Restore all bins", help="Bring back every date bin you deleted."):
                    st.session_state.pop("bin_dropped", None)
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
            st.caption("Automatic grouping uses equal color steps, so there are no separate bins to recolor. Choose Weekly, Thirds, "
                       "Halves or Custom above to edit each bin's color.")
        if st.button("Reset colors"):
            for k in ("bin_colors", "palette", "bin_dropped"):
                st.session_state.pop(k, None)
            set_legend_rows(None)
            st.rerun()
elif not computed:
    st.markdown("### What would you like to map?")
    st.caption("Pick a map type here or in the sidebar, fill in its settings, then press **Generate map**.")
    for var, label in VARIABLES.items():
        st.markdown(f"#### {label}")
        cols = st.columns(3)
        for i, t in enumerate(types_for(var)):
            with cols[i % 3].container(border=True):
                st.html(f'<div class="gc-swatch" style="background:{swatch_css(t.ramp)}"></div>')
                st.markdown(f"**{t.name}**" + (f" · {t.group}" if t.group else ""))
                st.caption(t.blurb)
                st.button("Selected" if t.id == st.session_state["f_type"] else "Use this", key=f"g_{t.id}", on_click=_pick_type,
                          args=(t.id,), type="primary" if t.id == st.session_state["f_type"] else "secondary")
