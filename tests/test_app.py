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
    assert [b.label for b in at.get("download_button")] == ["⬇️ Download KMZ"]
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
