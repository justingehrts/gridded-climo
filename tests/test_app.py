"""Drives streamlit_app.py through every map type (needs shipped data/; live ones need network)."""
import datetime as dt
import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "streamlit_app.py")
DATA = Path(__file__).parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "occurrence").exists(), reason="run `gridded-climo precompute` first")
live = pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1 (hits ACIS/NOHRSC)")
VAR = {"Temperature": "temperature", "Precipitation": "precipitation", "Sun": "sun"}


def fresh(timeout=180):
    return AppTest.from_file(APP, default_timeout=timeout).run()


def seg(at, label):
    return next(b for b in at.button_group if b.label == label)


def pick(at, variable, type_id=None):
    """Variable segmented control, then the map-type button (by id)."""
    seg(at, "Variable").set_value(VAR[variable]).run()
    if type_id:
        from gridded_climo.ui.maptypes import BY_ID
        t = BY_ID[type_id]
        at.button_group(key=f"mt_{t.variable}_{t.group or 'all'}").set_value(type_id).run()
    assert not at.exception, [e.value for e in at.exception]


def gen_button(at):
    return next(b for b in at.button if b.label == "Generate map")


def gen(at):
    gen_button(at).click().run()
    assert not at.exception and not at.error, [str(e.value) for e in list(at.exception) + list(at.error)]
    assert "⬇️ Download KMZ" in [b.label for b in at.get("download_button")]
    return [s.value for s in at.subheader]


def num(at, label):
    return next(n for n in at.number_input if n.label == label)


def years(at, lo, hi):
    at.text_input(key="f_y0").set_value(str(lo))
    at.number_input(key="f_y1").set_value(hi)
    at.run()


def method(at, name):
    at.radio(key="f_method").set_value(name).run()


# ------------------------------------------------------------------------------------------------ layout
def test_start_page_shows_the_gallery_and_one_generate_button():
    at = fresh()
    assert not at.exception
    assert any("What would you like to map?" in m.value for m in at.markdown)
    assert sum(b.label == "Generate map" for b in at.button) == 1
    assert [t.label for t in at.tabs][:3] == ["Map", "Look", "Export"]
    at.button(key="g_snownormal").click().run()                                         # a gallery card selects the type
    assert seg(at, "Variable").value == "precipitation" and at.session_state["f_type"] == "snownormal"
    assert at.selectbox(key="f_snow_pick").value == "November"


def test_variables_list_their_map_types():
    at = fresh()
    names = lambda: [(b.label, o) for b in at.button_group if (b.key or "").startswith("mt_") for o in b.options]
    assert names() == [("Map type", n) for n in ("Cold & warm dates", "Totals & averages", "Normal for dates", "Vs normal")]
    pick(at, "Precipitation")
    assert names() == [("Rain", "Totals"), ("Rain", "Normal for dates"), ("Rain", "Vs normal"), ("Snow", "Snowfall dates"),
                       ("Snow", "Normal snowfall"), ("Snow", "Storm total"), ("Snow", "Snowfall vs normal")]
    assert at.session_state["f_type"] == "rsum"                                          # switching variable picks its first type
    pick(at, "Sun")
    assert names() == [] and at.session_state["f_type"] == "sun"


# ------------------------------------------------------------------------------------------------ cold & warm dates
@pytest.mark.parametrize("which,kind,data", [
    ("First", "Cold (at or below)", "Grid (ACIS Grid 1)"),
    ("Last", "Cold (at or below)", "Stations (interpolated)"),
    ("First", "Warm (at or above)", "Grid (ACIS Grid 1)"),
    ("Last", "Warm (at or above)", "Stations (interpolated)"),
])
def test_cold_and_warm_dates(which, kind, data):
    at = fresh()
    seg(at, "Which date").set_value(which).run()
    seg(at, "Threshold").set_value(kind).run()
    method(at, data)
    title = gen(at)[0]
    assert title.startswith(f"Average Date of {which}") and ("or Colder" in title) == kind.startswith("Cold")


def test_cold_defaults_to_low_32_and_warm_to_high_90():
    at = fresh()
    assert at.selectbox(key="f_temp_le").value == "Low" and num(at, "At or below (°F)").value == 32
    seg(at, "Threshold").set_value("Warm (at or above)").run()
    assert at.selectbox(key="f_temp_ge").value == "High" and num(at, "At or above (°F)").value == 90
    num(at, "At or above (°F)").set_value(70).run()
    assert "First High of 70°F or Warmer" in gen(at)[0]


def test_grid_threshold_field_accepts_only_presaved_values():
    at = fresh()
    method(at, "Grid (ACIS Grid 1)")
    f = num(at, "At or below (°F)")
    assert f.step == 1 and f.value == 32 and (f.min, f.max) == (-10, 50)
    f.set_value(36).run()
    assert "36°F" in gen(at)[0]
    num(at, "At or below (°F)").set_value(37).run()                          # whole degree, but not pre-saved for the grid
    assert any("only has pre-saved" in i.value for i in at.info) and gen_button(at).disabled
    method(at, "Stations (interpolated)")
    assert num(at, "At or below (°F)").min == -60                              # stations: any value


@live
def test_station_threshold_field_fetches_off_menu_whole_degrees_live():
    at = fresh()
    num(at, "At or below (°F)").set_value(34).run()
    assert "34°F" in gen(at)[0] and any("fetched live" in c.value for c in at.caption)


@live
def test_off_menu_threshold_and_pre_shipped_years_fetch_live():
    at = fresh()
    seg(at, "Which date").set_value("Last").run()
    num(at, "At or below (°F)").set_value(37).run()
    years(at, 1930, 1960)
    title = gen(at)[0]
    assert "37°F" in title and "(1930-1960)" in title


def test_statistic_and_years_are_in_the_form():
    at = fresh()
    at.selectbox(key="f_stat").select("max").run()
    years(at, 1950, 2020)
    assert gen(at)[0] == "Latest First Low of 32°F or Colder on Record (1950-2020)"


# ------------------------------------------------------------------------------------------------ snow
@pytest.mark.parametrize("which", ["First", "Last"])
def test_snowfall_dates_station_only(which):
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    seg(at, "Which date").set_value(which).run()
    assert 'Snowfall of 1" or More' in gen(at)[0]


def test_earliest_snow_on_record_1950_2025():
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    at.selectbox(key="f_stat").select("min").run()
    years(at, 1950, 2025)
    assert gen(at)[0] == 'Earliest First Snowfall of 1" or More on Record (1950-2025)'


def test_snow_field_takes_tenths():
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    snow = at.number_input(key="f_snow_amt")
    assert snow.step == 0.1 and snow.value == 1.0
    snow.set_value(2.5).run()
    assert not at.exception and not any("tenths" in i.value for i in at.info)
    at.number_input(key="f_snow_amt").set_value(1.25).run()
    assert any("tenths" in i.value for i in at.info)


@live
def test_off_menu_snow_amount_fetches_live():
    at = fresh(timeout=600)
    pick(at, "Precipitation", "snowdate")
    at.number_input(key="f_snow_amt").set_value(2.5).run()
    assert 'Snowfall of 2.5" or More' in gen(at)[0]


def test_snow_normals_quick_picks_and_custom_months():
    at = fresh()
    pick(at, "Precipitation", "snownormal")
    assert "Average November Snowfall" in gen(at)[0]
    at.selectbox(key="f_snow_pick").select("Winter (Dec–Feb)").run()
    assert "Average Dec–Feb Snowfall" in gen(at)[0]
    at.selectbox(key="f_snow_pick").select("Choose months…").run()
    at.selectbox(key="f_snow_m1").select(10).run()
    at.selectbox(key="f_snow_m2").select(4).run()
    assert "Average Oct–Apr Snowfall" in gen(at)[0]


def test_snow_departure_uses_station_dates(monkeypatch):
    import numpy as np
    from gridded_climo import snow_normals
    fake = {"lon": np.array([-83.0, -82.5, -82.0, -84.0], "float32"), "lat": np.array([40.0, 39.5, 41.0, 39.0], "float32"),
            "name": np.array(["A", "B", "C", "D"]), "obs": np.array([5, 9, 20, 1], "float32"),
            "normal": np.array([8, 8, 15, 4], "float32"), "departure": np.array([-3, 1, 5, -3], "float32"), "missing": np.zeros(4, "int32")}
    monkeypatch.setattr(snow_normals, "fetch_snow_departure", lambda *a, **k: fake)
    at = fresh()
    pick(at, "Precipitation", "snowdep")
    assert not any(s.label == "Start hour" for s in at.selectbox)
    assert "Snowfall Departure from Normal" in gen(at)[0]


def test_storm_total_from_stations_works_before_nohrsc(monkeypatch):
    import numpy as np
    from gridded_climo import snow_normals
    fake = {"lon": np.array([-83.0, -82.5, -82.0, -84.0], "float32"), "lat": np.array([40.0, 39.5, 41.0, 39.0], "float32"),
            "name": np.array(["A", "B", "C", "D"]), "obs": np.array([5, 9, 20, 1], "float32"), "missing": np.zeros(4, "int32")}
    monkeypatch.setattr(snow_normals, "fetch_snow_total", lambda *a, **k: fake)
    from gridded_climo import iem
    monkeypatch.setattr(iem, "fetch_snow_reports", lambda *a, **k: {"lon": [-82.9], "lat": [41.5], "value": [7.0], "name": ["X"]})
    at = fresh()
    pick(at, "Precipitation", "snowstorm")
    seg(at, "Data").set_value("Stations + reports").run()
    assert not at.exception
    assert min(int(o) for o in next(x for x in at.selectbox if x.label == "Start date year").options) == 1900
    for pre, (y, m, d) in (("Start date", (2007, 2, 12)), ("End date", (2007, 2, 14))):
        for part, v in (("year", y), ("month", m), ("day", d)):
            next(x for x in at.selectbox if x.label == f"{pre} {part}").set_value(v).run()
    assert not any(s.label == "Start hour" for s in at.selectbox)
    assert "Storm Total Snowfall (Stations + Reports)" in gen(at)[0]


@live
def test_storm_total_live():
    at = fresh()
    pick(at, "Precipitation", "snowstorm")
    at.date_input(key="f_storm_d1").set_value(dt.date(2024, 1, 5)).run()
    at.date_input(key="f_storm_d2").set_value(dt.date(2024, 1, 8)).run()
    assert "Snowfall Total" in gen(at)[0]


# ------------------------------------------------------------------------------------------------ totals, normals, departures
def test_rain_normal_window_wraps_year():
    at = fresh()
    pick(at, "Precipitation", "rnormal")                                     # default window Dec 1 -> Feb 28
    assert "average" in gen(at)[0].lower()


def test_temperature_normal_for_dates():
    at = fresh()
    pick(at, "Temperature", "tnormal")
    seg(at, "Temperature").set_value("Low").run()
    assert "Low" in gen(at)[0]


def test_count_days_summary_shows_threshold_field():
    at = fresh()
    pick(at, "Temperature", "tsum")
    at.selectbox(key="f_tsum_var").select("avgt").run()
    next(s for s in at.selectbox if s.label == "Show").select("count").run()
    assert not at.exception and any(n.label.startswith("Threshold") for n in at.number_input)


def test_rain_count_days_field():
    at = fresh()
    pick(at, "Precipitation", "rsum")
    at.selectbox(key="f_rsum_reduce").select("count").run()
    assert at.number_input(key="f_rsum_thr").value == 0.01


def test_reversed_dates_are_flagged_under_the_field():
    at = fresh()
    pick(at, "Temperature", "tdep")
    at.date_input(key="f_d1").set_value(dt.date(2025, 3, 1)).run()
    at.date_input(key="f_d2").set_value(dt.date(2025, 2, 1)).run()
    assert any("before the start date" in c.value for c in at.caption) and gen_button(at).disabled


@live
@pytest.mark.parametrize("type_id", ["tsum", "tdep", "rsum", "rdep"])
def test_specific_dates_live(type_id):
    at = fresh()
    pick(at, "Temperature" if type_id.startswith("t") else "Precipitation", type_id)
    title = gen(at)[0]
    assert ("Departure" in title) == type_id.endswith("dep")


# ------------------------------------------------------------------------------------------------ sun
def test_sun_one_date_and_change():
    at = fresh()
    pick(at, "Sun")
    assert not any(t.key == "f_y0" for t in at.text_input)                    # no years for sun maps
    assert "Sunrise on" in gen(at)[0]
    at.checkbox(key="f_sun_change").set_value(True).run()
    assert any(d.label == "End date" for d in at.date_input)
    seg(at, "Show").set_value("Day length").run()
    assert "Change in Day Length" in gen(at)[0]


# ------------------------------------------------------------------------------------------------ area
def test_area_dropdown_lists_the_default_every_state_and_custom():
    at = fresh()
    opts = list(at.selectbox(key="area").options)
    assert opts[0].startswith("Columbus-centered default") and opts[-1] == "Custom…"
    assert len(opts) == 49 + 2 and {"Ohio", "Texas", "District of Columbia"} <= set(opts)
    assert opts[1:-1] == sorted(opts[1:-1])
    at.selectbox(key="area").select("Ohio").run()
    assert any("Ohio plus a 0.75°" in c.value for c in at.caption)


def test_ohio_area_runs_from_presaved_data_on_both_methods():
    for m in ("Grid (ACIS Grid 1)", "Stations (interpolated)"):
        at = fresh()
        at.selectbox(key="area").select("Ohio").run()
        method(at, m)
        assert "32°F" in gen(at)[0]


def test_other_states_explain_what_isnt_available():
    at = fresh()
    at.selectbox(key="area").select("Texas").run()
    assert any("Outside the pre-saved region" in c.value for c in at.caption)
    method(at, "Grid (ACIS Grid 1)")
    assert any("Ohio-centered region only" in i.value for i in at.info) and gen_button(at).disabled
    method(at, "Stations (interpolated)")
    assert not any("Ohio-centered" in i.value for i in at.info) and not gen_button(at).disabled


def test_custom_area_north_comes_before_south():
    at = fresh()
    at.selectbox(key="area").select("Custom…").run()
    labels = [n.label for n in at.number_input if n.key in ("area_w", "area_e", "area_n", "area_s")]
    assert labels.index("North") < labels.index("South")
    at.number_input(key="area_w").set_value(-100.0).run()
    at.number_input(key="area_e").set_value(-95.0).run()
    assert not at.exception


@live
def test_another_state_runs_live_on_stations():
    at = fresh(timeout=600)
    at.selectbox(key="area").select("Indiana").run()
    assert "32°F" in gen(at)[0] and any("fetched live" in c.value for c in at.caption)


# ------------------------------------------------------------------------------------------------ years / POR
def _stub_por(monkeypatch, first=1872, starts=(1872, 1890, 1890, 1895, 1900)):
    import streamlit as st
    import gridded_climo.por as por
    st.cache_data.clear()
    calls = []
    monkeypatch.setattr(por, "station_por", lambda client, bbox, element: calls.append((tuple(bbox), element)) or por.Por(first, list(starts)))
    return calls


def test_por_in_the_start_year_field(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    start = at.text_input(key="f_y0")
    assert start.value == "1991" and calls == []
    start.set_value("por").run()
    text = " ".join(c.value for c in at.caption)
    assert "Using 1872" in text and "Period of record for low temperature here starts in 1872 (1 station" in text
    assert calls == [((-87.5, 37.0, -78.5, 42.5), "mint")]
    assert not gen_button(at).disabled and any("Before ~1895" in w.value for w in at.warning)
    at.text_input(key="f_y0").set_value("POR").run()
    assert len(calls) == 1


def test_early_year_before_the_record_is_rejected(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    at.text_input(key="f_y0").set_value("1860").run()
    assert any("begin in 1872" in c.value for c in at.caption) and gen_button(at).disabled
    at.text_input(key="f_y0").set_value("1890").run()
    assert not any("begin in" in c.value for c in at.caption)
    at.text_input(key="f_y0").set_value("1960").run()
    assert len(calls) == 1


def test_bad_start_text_and_inverted_years_are_explained(monkeypatch):
    _stub_por(monkeypatch)
    at = fresh()
    for text, msg in (("soon", "four-digit year"), ("1750", "between"), ("2025", "must be before")):
        at.text_input(key="f_y0").set_value(text).run()
        assert not at.exception and any(msg in c.value for c in at.caption), text
        assert gen_button(at).disabled


def test_por_with_the_grid_method_means_where_the_saved_grid_begins(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    method(at, "Grid (ACIS Grid 1)")
    at.text_input(key="f_y0").set_value("por").run()
    assert "Using 1991, where the saved grid data begins" in " ".join(c.value for c in at.caption) and calls == []
    assert not gen_button(at).disabled


@live
def test_por_start_generates_a_record_map_live():
    at = fresh(timeout=900)
    at.selectbox(key="area").select("Ohio").run()
    at.text_input(key="f_y0").set_value("por").run()
    title = gen(at)[0]
    assert "(18" in title and "-2020)" in title


# ------------------------------------------------------------------------------------------------ look / band colors
def _first_freeze(at):
    gen(at)


@pytest.mark.parametrize("mode", ["auto", "weekly", "thirds", "half"])
def test_date_grouping_lives_in_look_and_restyles(mode):
    at = fresh()
    _first_freeze(at)
    at.radio(key="style_date_mode").set_value(mode).run()
    assert not at.exception and not at.error


def test_custom_date_bins_and_bad_input_message():
    at = fresh()
    _first_freeze(at)
    at.radio(key="style_date_mode").set_value("custom").run()
    at.text_input(key="style_custom_starts").set_value("Oct 1, Oct 12, Nov 1").run()
    assert not at.exception and not at.error
    for bad, msg in (("Oct 12, Oct 1", "season order"), ("Octember 3", "isn't a month name"), ("", "at least one bin start")):
        at.text_input(key="style_custom_starts").set_value(bad).run()
        assert any(msg in e.value for e in at.error) and not at.exception
        assert "⬇️ Download KMZ" in [b.label for b in at.get("download_button")]          # the page stays; it falls back to Automatic


@pytest.mark.parametrize("from_band_view", [False, True])
def test_choosing_custom_grouping_keeps_the_page(from_band_view):
    """Regression: picking Custom used to raise 'enter at least one bin start date' and blank everything but the sidebar."""
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    gen(at)
    if from_band_view:
        seg(at, "View").set_value("Band colors").run()
    at.radio(key="style_date_mode").set_value("custom").run()
    assert not at.exception and not at.error
    assert at.text_input(key="style_custom_starts").value == "Oct 1, Oct 8, Oct 15, Oct 22, Nov 1"
    assert "⬇️ Download KMZ" in [b.label for b in at.get("download_button")]
    if from_band_view:
        assert len(at.dataframe) == 1


def test_band_colors_view_has_the_date_grouping_control():
    """Regression: on a date map in Automatic grouping, Band colors used to be a dead end (the grouping radio was only in Look)."""
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    gen(at)
    seg(at, "View").set_value("Band colors").run()
    assert not at.exception
    assert any("no separate bins" in c.value for c in at.caption)                          # explains why, and where to go
    at.radio(key="style_date_mode").set_value("weekly").run()                              # the control is right here
    assert not at.exception and not at.error
    assert len(at.dataframe) == 1                                                          # the per-bin color table appeared
    assert seg(at, "View").value == "Band colors"
    assert any("Date grouping is set in the Band colors view" in c.value for c in at.caption)   # Look tab points here, no duplicate radio
    seg(at, "View").set_value("Map").run()
    assert at.radio(key="style_date_mode").value == "weekly" and not at.exception          # back in Look, same setting


def test_deleting_date_bins_and_restoring_them():
    at = fresh()
    pick(at, "Precipitation", "snowdate")
    gen(at)
    seg(at, "View").set_value("Band colors").run()
    at.radio(key="style_date_mode").set_value("weekly").run()
    full = [r["Bin"] for r in at.dataframe[0].value.to_dict("records")]
    # what the table's Delete button + Apply colors store: the start dates of the deleted rows
    at.session_state["bin_dropped"] = {"sig": ("weekly", ""), "starts": _first_starts(at, 2)}
    at.run()
    assert not at.exception and not at.error
    now = [r["Bin"] for r in at.dataframe[0].value.to_dict("records")]
    assert now[0].startswith("Before ") and len(now) == len(full) - 1
    next(b for b in at.button if b.label == "Restore all bins").click().run()
    assert [r["Bin"] for r in at.dataframe[0].value.to_dict("records")] == full
    at.session_state["bin_dropped"] = {"sig": ("weekly", ""), "starts": _first_starts(at, 2)}
    at.radio(key="style_date_mode").set_value("thirds").run()                       # a different grouping ignores old deletions
    assert not at.exception and not any(r["Bin"].startswith("Before ") for r in at.dataframe[0].value.to_dict("records"))


def _first_starts(at, n):
    """Start dates ("11-7") of the first n bins in the table, from the rendered Output."""
    import re
    months = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
    out = []
    for r in at.dataframe[0].value.to_dict("records")[:n]:
        m = re.match(r"([A-Z][a-z]{2}) (\d+)", r["Bin"])
        out.append(f"{months[m[1]]}-{int(m[2])}")
    return out


def test_band_colors_button_opens_the_band_view_and_reset_works():
    at = fresh()
    _first_freeze(at)
    at.radio(key="style_date_mode").set_value("weekly").run()
    next(b for b in at.button if b.label.startswith("Edit individual band colors")).click().run()
    assert seg(at, "View").value == "Band colors" and not at.exception
    at.session_state["bin_colors"] = {"Oct 7–13": [1, 2, 3, 255]}
    at.run()
    next(b for b in at.button if b.label == "Reset colors").click().run()
    assert not at.session_state["bin_colors"] if "bin_colors" in at.session_state else True


def test_ramp_mode_range_controls_apply_to_a_numeric_map():
    at = fresh()
    pick(at, "Precipitation", "rnormal")
    gen(at)
    at.session_state["style_ramp"] = "Magma"; at.run()
    at.checkbox(key="style_flip").set_value(True).run()
    at.radio(key="style_mode").set_value("Smooth").run()
    at.number_input(key="style_vmin").set_value(0.0).run()
    at.number_input(key="style_vmax").set_value(8.0).run()
    assert not at.exception and not at.error
    at.session_state["legend_rows"] = [[0, 255, 255, 255, 0], [1, 0, 0, 255, 255], [3, 255, 0, 0, 255]]
    at.radio(key="style_mode").set_value("Stepped").run()
    seg(at, "View").set_value("Band colors").run()
    assert not at.exception and not at.error


def test_apply_example_preset_sets_only_what_it_contains():
    at = fresh()
    _first_freeze(at)
    steps_before = at.slider(key="style_steps").value
    at.selectbox(key="style_preset").select("Example: weekly bins, Spectral").run()
    next(b for b in at.button if b.label == "Apply preset").click().run()
    assert not at.exception and not at.error
    assert at.radio(key="style_date_mode").value == "weekly" and at.session_state["style_ramp"] == "Spectral"
    assert at.checkbox(key="style_flip").value is True and at.slider(key="style_steps").value == steps_before
    labels = [b.label for b in at.get("download_button")]
    assert "⬇️ Download KMZ" in labels and "Download preset file" in labels and not any("PNG" in l for l in labels)


# ------------------------------------------------------------------------------------------------ recent / saved maps
def test_recent_maps_restore_settings():
    at = fresh()
    seg(at, "Threshold").set_value("Warm (at or above)").run()
    num(at, "At or above (°F)").set_value(80).run()
    gen(at)
    pick(at, "Sun")
    gen(at)
    recents = [b for b in at.button if (b.key or "").startswith("recent_")]
    assert len(recents) == 2 and "Sunrise" in recents[0].label and "80°F" in recents[1].label
    recents[1].click().run()
    assert not at.exception and at.session_state["f_type"] == "tdates" and seg(at, "Threshold").value == "Warm (at or above)"
    assert num(at, "At or above (°F)").value == 80


def test_save_and_load_whole_map_round_trip():
    from gridded_climo.ui import forms
    at = fresh()
    pick(at, "Precipitation", "snownormal")
    at.selectbox(key="f_snow_pick").select("Winter (Dec–Feb)").run()
    gen(at)
    snap = forms.to_jsonable(forms.snapshot(at.session_state))
    saved = {"kind": "gridded-climo-map", "version": 1, "widgets": snap, "look": {"ramp": "Magma"}}
    assert json.loads(json.dumps(saved))["widgets"]["f_type"] == "snownormal"
    at2 = fresh()
    at2.session_state["_pending"] = forms.from_jsonable(saved["widgets"]) | {"style_ramp": "Magma"}
    at2.run()
    assert at2.session_state["f_type"] == "snownormal" and at2.selectbox(key="f_snow_pick").value == "Winter (Dec–Feb)"
    assert "Average Dec–Feb Snowfall" in gen(at2)[0]


def test_snapshot_json_handles_dates():
    from gridded_climo.ui import forms
    snap = {"f_d1": dt.date(2025, 1, 1), "f_t": dt.datetime(2025, 1, 1, 7), "f_y": (1991, 2020), "area": "Ohio"}
    back = forms.from_jsonable(json.loads(json.dumps(forms.to_jsonable(snap))))
    assert back["f_d1"] == dt.date(2025, 1, 1) and back["f_t"] == dt.datetime(2025, 1, 1, 7) and back["area"] == "Ohio"
