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
