"""Drives streamlit_app.py through every selector combination (needs shipped data/; live ones need network)."""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "streamlit_app.py")
DATA = Path(__file__).parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "occurrence").exists(), reason="run `gridded-climo precompute` first")
live = pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1 (hits ACIS/NOHRSC)")


def _var(at):
    """The 'Variable' selectbox (found by label, so adding other selectboxes can't shift it)."""
    return next(b for b in at.selectbox if b.label == "Variable")


def fresh(timeout=180):
    return AppTest.from_file(APP, default_timeout=timeout).run()


def gen(at):
    at.button[0].click().run()
    assert not at.exception and not at.error, [str(e.value) for e in list(at.exception) + list(at.error)]
    assert "⬇️ Download KMZ" in [b.label for b in at.get("download_button")]
    return [s.value for s in at.subheader]


@pytest.mark.parametrize("when,var,method", [
    ("Average first date", "Temperature at or below", "Grid (ACIS Grid 1)"),
    ("Average last date", "Temperature at or below", "Stations (interpolated)"),
    ("Average first date", "Temperature at or above", "Grid (ACIS Grid 1)"),
    ("Average last date", "Temperature at or above", "Stations (interpolated)"),
])
def test_first_last_temperature(when, var, method):
    at = fresh()
    at.radio[0].set_value(when).run()
    _var(at).select(var).run()
    at.radio[2].set_value(method).run()
    assert "Average Date of" in gen(at)[0]


@pytest.mark.parametrize("when", ["Average first date", "Average last date"])
def test_first_last_snowfall_station_only(when):
    at = fresh()
    at.radio[0].set_value(when).run()
    _var(at).select("Snowfall").run()
    assert "Snowfall of 1" in gen(at)[0]


def test_normal_average_window_wraps_year():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.radio[1].set_value("Averaged over normal period").run()
    _var(at).select("Precipitation").run()           # default window Dec 1 -> Feb 28
    assert "average" in gen(at)[0].lower()


def test_snow_normal_average_is_disabled_with_reason():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.radio[1].set_value("Averaged over normal period").run()
    _var(at).select("Snowfall").run()
    assert any("coming soon" in i.value for i in at.info)
    assert at.button[0].disabled


@live
@pytest.mark.parametrize("departure", [False, True])
def test_specific_dates_temperature_live(departure):
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.checkbox[0].set_value(departure).run()
    assert ("Departure" in gen(at)[0]) == departure


@live
def test_specific_dates_snowfall_live():
    import datetime as dt
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    _var(at).select("Snowfall").run()
    at.date_input[0].set_value(dt.date(2024, 1, 5)).run()
    at.date_input[1].set_value(dt.date(2024, 1, 8)).run()
    assert "Snowfall Total" in gen(at)[0]


def _set_years(at, lo, hi):
    start = next((t for t in at.text_input if t.key == "years_from"), None)          # first/last maps: text (year or POR)
    if start is not None:
        start.set_value(str(lo))
    else:                                                                              # custom range: plain number
        next(n for n in at.number_input if n.label.startswith("Normal period")).set_value(lo)
    next(n for n in at.number_input if n.label == "to").set_value(hi)


def test_earliest_snow_on_record_1950_2025():
    at = fresh()
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Snowfall").run()
    next(s for s in at.selectbox if s.label == "Statistic across years").select("Earliest on record").run()
    _set_years(at, 1950, 2025)
    at.run()
    assert gen(at)[0] == 'Earliest First Snowfall of 1" or More on Record (1950-2025)'


@live
def test_off_menu_threshold_and_pre_shipped_years_fetch_live():
    at = fresh()
    at.radio[0].set_value("Average last date").run()
    next(n for n in at.number_input if n.label == "Threshold (°F)").set_value(37.0).run()   # not pre-saved
    _set_years(at, 1930, 1960)                                                              # before pre-saved data? (1950+ saved; 1930 is live)
    at.run()
    title = gen(at)[0]
    assert "37°F" in title and "(1930-1960)" in title
    assert any("fetched live" in c.value for c in at.caption)


def test_departure_requires_shipped_normals():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.checkbox[0].set_value(True).run()
    _set_years(at, 1981, 2010)
    at.run()
    assert any("1991-2020" in i.value for i in at.info) and at.button[0].disabled


def _stations_first_freeze(at):
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Temperature at or below").run()
    at.radio[2].set_value("Stations (interpolated)").run()
    at.button[0].click().run()
    assert not at.exception and not at.error


@pytest.mark.parametrize("mode", ["auto", "weekly", "thirds", "half"])
def test_date_grouping_modes_restyle_without_recomputing(mode):
    at = fresh()
    _stations_first_freeze(at)
    at.radio(key="style_date_mode").set_value(mode).run()
    assert not at.exception and not at.error
    assert [b.label for b in at.get("download_button")][:1] == ["⬇️ Download KMZ"]


def test_custom_date_bins_and_bad_input_message():
    at = fresh()
    _stations_first_freeze(at)
    at.radio(key="style_date_mode").set_value("custom").run()
    at.text_input(key="style_custom_starts").set_value("Oct 1, Oct 12, Nov 1").run()
    assert not at.exception and not at.error
    at.text_input(key="style_custom_starts").set_value("Oct 12, Oct 1").run()          # out of order
    assert any("season order" in e.value for e in at.error) and not at.exception
    at.text_input(key="style_custom_starts").set_value("Octember 3").run()
    assert any("isn't a month name" in e.value for e in at.error) and not at.exception


def test_color_overrides_and_reset():
    at = fresh()
    _stations_first_freeze(at)
    at.radio(key="style_date_mode").set_value("weekly").run()
    at.session_state["bin_colors"] = {"Oct 7–13": [1, 2, 3, 255]}
    at.run()
    assert not at.exception and not at.error
    next(b for b in at.button if b.label == "Reset colors").click().run()
    assert not at.session_state["bin_colors"] if "bin_colors" in at.session_state else True


def test_ramp_mode_range_controls_apply_to_a_numeric_map():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.radio[1].set_value("Averaged over normal period").run()
    _var(at).select("Precipitation").run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    at.selectbox(key="style_ramp").select("Magma").run()
    at.checkbox(key="style_flip").set_value(True).run()
    at.radio(key="style_mode").set_value("Smooth").run()
    at.number_input(key="style_vmin").set_value(0.0).run()
    at.number_input(key="style_vmax").set_value(8.0).run()
    assert not at.exception and not at.error
    at.session_state["legend_rows"] = [[0, 255, 255, 255, 0], [1, 0, 0, 255, 255], [3, 255, 0, 0, 255]]
    at.radio(key="style_mode").set_value("Stepped").run()
    assert not at.exception and not at.error


def test_apply_example_preset_sets_only_what_it_contains():
    at = fresh()
    _stations_first_freeze(at)
    steps_before = at.slider(key="style_steps").value
    at.selectbox(key="style_preset").select("Example: weekly bins, Spectral").run()
    next(b for b in at.button if b.label == "Apply preset").click().run()
    assert not at.exception and not at.error
    assert at.radio(key="style_date_mode").value == "weekly" and at.selectbox(key="style_ramp").value == "Spectral"
    assert at.checkbox(key="style_flip").value is True
    assert at.slider(key="style_steps").value == steps_before           # the preset didn't mention steps
    labels = [b.label for b in at.get("download_button")]
    assert "⬇️ Download KMZ" in labels and "Download preset file" in labels


def _threshold_field(at):
    return next(n for n in at.number_input if n.label == "Threshold (°F)")


def _first_low(at, method):
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Temperature at or below").run()
    at.radio[2].set_value(method).run()


def test_grid_threshold_field_accepts_only_presaved_values():
    at = fresh()
    _first_low(at, "Grid (ACIS Grid 1)")
    f = _threshold_field(at)
    assert f.step == 1 and f.value == 32
    f.set_value(36).run()
    assert "36°F" in gen(at)[0]
    _threshold_field(at).set_value(37).run()                                    # whole degree, but not pre-saved for the grid
    assert any("only has pre-saved" in i.value for i in at.info)
    assert next(b for b in at.button if b.label == "Generate map").disabled


@live
def test_station_threshold_field_fetches_off_menu_whole_degrees_live():
    at = fresh()
    _first_low(at, "Stations (interpolated)")
    _threshold_field(at).set_value(34).run()
    assert "34°F" in gen(at)[0] and any("fetched live" in c.value for c in at.caption)


def test_grid_field_bounds_and_snow_field_takes_tenths():
    at = fresh()
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Temperature at or below").run()
    at.radio[2].set_value("Grid (ACIS Grid 1)").run()
    field = next(n for n in at.number_input if n.label == "Threshold (°F)")
    assert (field.min, field.max) == (-10, 50)
    at.radio[2].set_value("Stations (interpolated)").run()
    assert (next(n for n in at.number_input if n.label == "Threshold (°F)").min) == -60   # stations: any value
    _var(at).select("Snowfall").run()
    snow = next(n for n in at.number_input if n.label.startswith("Daily snowfall"))
    assert snow.step == 0.1 and snow.value == 1.0
    snow.set_value(2.5).run()                                                    # accepted (tenths)...
    assert not at.exception and not at.error and not any("tenths" in i.value for i in at.info)
    snow.set_value(1.25).run()                                                   # ...but hundredths are rejected with a message
    assert any("tenths" in i.value for i in at.info)


@live
def test_off_menu_snow_amount_fetches_live():
    at = fresh(timeout=600)                                                      # one big ACIS request (thousands of snow stations)
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Snowfall").run()
    next(n for n in at.number_input if n.label.startswith("Daily snowfall")).set_value(2.5).run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert 'Snowfall of 2.5" or More' in [s.value for s in at.subheader][0]


def _area(at, name):
    at.selectbox(key="area").select(name).run()


def test_area_dropdown_lists_the_default_every_state_and_custom():
    at = fresh()
    opts = list(at.selectbox(key="area").options)
    assert opts[0].startswith("Columbus-centered default") and opts[-1] == "Custom…"
    assert len(opts) == 49 + 2 and {"Ohio", "Texas", "District of Columbia"} <= set(opts)
    assert opts[1:-1] == sorted(opts[1:-1])                                          # states A-Z
    _area(at, "Ohio")
    assert any("Ohio plus a 0.75°" in c.value for c in at.caption)


def test_ohio_area_runs_from_presaved_data_on_both_methods():
    for method in ("Grid (ACIS Grid 1)", "Stations (interpolated)"):
        at = fresh()
        _area(at, "Ohio")
        _first_low(at, method)
        title = gen(at)[0]
        assert "32°F" in title and any(("pre-saved" in c.value) or ("Grid 1" in c.value) for c in at.caption)


def test_other_states_explain_what_isnt_available_without_fetching():
    at = fresh()
    _area(at, "Texas")
    assert any("Outside the pre-saved region" in c.value for c in at.caption)
    _first_low(at, "Grid (ACIS Grid 1)")
    assert any("Ohio-centered region only" in i.value for i in at.info)
    assert next(b for b in at.button if b.label == "Generate map").disabled
    at.radio[2].set_value("Stations (interpolated)").run()                            # stations are allowed anywhere
    assert not any("Ohio-centered" in i.value for i in at.info)
    assert not next(b for b in at.button if b.label == "Generate map").disabled


def test_custom_area_accepts_a_box_anywhere_in_the_lower_48():
    at = fresh()
    _area(at, "Custom…")
    west = next(n for n in at.number_input if n.label == "West")
    assert west.min == -125.5
    west.set_value(-100.0).run()
    next(n for n in at.number_input if n.label == "East").set_value(-95.0).run()
    assert not at.exception


@live
def test_another_state_runs_live_on_stations():
    at = fresh(timeout=600)
    _area(at, "Indiana")                                                              # only 72% inside the pre-saved region
    _first_low(at, "Stations (interpolated)")
    assert "32°F" in gen(at)[0] and any("fetched live" in c.value for c in at.caption)


def _stub_por(monkeypatch, first=1872, starts=(1872, 1890, 1890, 1895, 1900)):
    import streamlit as st
    import gridded_climo.por as por
    st.cache_data.clear()
    calls = []
    monkeypatch.setattr(por, "station_por", lambda client, bbox, element: calls.append((tuple(bbox), element)) or por.Por(first, list(starts)))
    return calls


def _years_page(at, method="Stations (interpolated)"):
    at.radio[0].set_value("Average first date").run()
    _var(at).select("Temperature at or below").run()
    at.radio[2].set_value(method).run()


def test_por_in_the_start_year_field(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    _years_page(at)
    start = next(t for t in at.text_input if t.key == "years_from")
    assert start.value == "1991" and calls == []                                    # the default doesn't need a lookup
    start.set_value("por").run()
    assert not at.exception
    text = " ".join(c.value for c in at.caption)
    assert "Using 1872" in text and "Period of record for low temperature here starts in 1872 (1 station" in text
    assert calls == [((-87.5, 37.0, -78.5, 42.5), "mint")]                         # the area and variable asked about
    assert not next(b for b in at.button if b.label == "Generate map").disabled
    assert any("Before ~1895" in w.value for w in at.warning)                       # a very early start is flagged as sparse
    start.set_value("POR").run()                                                    # any case; cached, so no second lookup
    assert len(calls) == 1


def test_early_year_before_the_record_is_rejected_and_late_years_never_look_it_up(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    _years_page(at)
    start = next(t for t in at.text_input if t.key == "years_from")
    start.set_value("1860").run()
    assert any("begin in 1872" in i.value for i in at.info) and next(b for b in at.button if b.label == "Generate map").disabled
    start.set_value("1890").run()                                                   # inside the record: fine
    assert not any("begin in" in i.value for i in at.info)
    start.set_value("1960").run()
    assert len(calls) == 1                                                          # only years before 1950 trigger the check


def test_bad_start_text_and_inverted_years_are_explained(monkeypatch):
    _stub_por(monkeypatch)
    at = fresh()
    _years_page(at)
    start = next(t for t in at.text_input if t.key == "years_from")
    for text, msg in (("soon", "four-digit year"), ("1750", "between"), ("2025", "must be before")):
        start.set_value(text).run()
        assert not at.exception and any(msg in i.value for i in at.info), text
        assert next(b for b in at.button if b.label == "Generate map").disabled


def test_por_with_the_grid_method_means_where_the_saved_grid_begins(monkeypatch):
    calls = _stub_por(monkeypatch)
    at = fresh()
    _years_page(at, "Grid (ACIS Grid 1)")
    next(t for t in at.text_input if t.key == "years_from").set_value("por").run()
    assert "Using 1991, where the saved grid data begins" in " ".join(c.value for c in at.caption) and calls == []
    assert not next(b for b in at.button if b.label == "Generate map").disabled


@live
def test_por_start_generates_a_record_map_live():
    at = fresh(timeout=900)
    at.selectbox(key="area").select("Ohio").run()
    _years_page(at)
    next(t for t in at.text_input if t.key == "years_from").set_value("por").run()
    assert not at.exception
    title = gen(at)[0]
    assert "(18" in title and "-2020)" in title                                      # starts in the 1800s
