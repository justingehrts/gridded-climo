"""Drives streamlit_app.py through every selector combination (needs shipped data/; live ones need network)."""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "streamlit_app.py")
DATA = Path(__file__).parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "occurrence").exists(), reason="run `gridded-climo precompute` first")
live = pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1 (hits ACIS/NOHRSC)")


def fresh():
    return AppTest.from_file(APP, default_timeout=180).run()


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
    at.selectbox[0].select(var).run()
    at.radio[2].set_value(method).run()
    assert "Average Date of" in gen(at)[0]


@pytest.mark.parametrize("when", ["Average first date", "Average last date"])
def test_first_last_snowfall_station_only(when):
    at = fresh()
    at.radio[0].set_value(when).run()
    at.selectbox[0].select("Snowfall").run()
    assert "Snowfall of 1" in gen(at)[0]


def test_normal_average_window_wraps_year():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.radio[1].set_value("Averaged over normal period").run()
    at.selectbox[0].select("Precipitation").run()           # default window Dec 1 -> Feb 28
    assert "average" in gen(at)[0].lower()


def test_snow_normal_average_is_disabled_with_reason():
    at = fresh()
    at.radio[0].set_value("Custom range").run()
    at.radio[1].set_value("Averaged over normal period").run()
    at.selectbox[0].select("Snowfall").run()
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
    at.selectbox[0].select("Snowfall").run()
    at.date_input[0].set_value(dt.date(2024, 1, 5)).run()
    at.date_input[1].set_value(dt.date(2024, 1, 8)).run()
    assert "Snowfall Total" in gen(at)[0]


def _set_years(at, lo, hi):
    next(n for n in at.number_input if n.label.startswith(("Years included", "Normal period"))).set_value(lo)
    next(n for n in at.number_input if n.label == "to").set_value(hi)


def test_earliest_snow_on_record_1950_2025():
    at = fresh()
    at.radio[0].set_value("Average first date").run()
    at.selectbox[0].select("Snowfall").run()
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
    at.selectbox[0].select("Temperature at or below").run()
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
    at.selectbox[0].select("Precipitation").run()
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
