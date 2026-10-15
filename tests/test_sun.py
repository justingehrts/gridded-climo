import datetime as dt

import numpy as np
import pytest

from gridded_climo import tz
from gridded_climo.query import SUN_ELEMENTS, Query, describe, metric_from_query, unsupported_reason
from gridded_climo.sun import fmt_clock, fmt_delta, fmt_duration, sun_grid, sun_times, tidy_style
from gridded_climo.registry import Style

OHIO = (-87.5, 37.0, -78.5, 42.5)
# (city lat, lon, date, sunrise, sunset) in local clock minutes after midnight, from an independent implementation (astral)
REF = [(39.96, -82.99, dt.date(2026, 6, 21), 363.7, 1263.9), (39.96, -82.99, dt.date(2026, 12, 21), 470.4, 1029.8),
       (41.88, -87.63, dt.date(2026, 3, 20), 413.9, 1142.6), (33.45, -112.07, dt.date(2026, 6, 21), 319.2, 1181.1)]


@pytest.mark.parametrize("lat,lon,day,rise,set_", REF)
def test_times_match_independent_reference(lat, lon, day, rise, set_):
    t = sun_times(day, np.array([[lat]]), np.array([[lon]]))
    assert abs(float(t["sunrise"][0, 0]) - rise) < 1.5 and abs(float(t["sunset"][0, 0]) - set_) < 1.5
    assert float(t["daylen"][0, 0]) == pytest.approx(float(t["sunset"][0, 0] - t["sunrise"][0, 0]), abs=1e-3)


def test_time_zones():
    lat, lon = np.array([[39.96, 41.88, 33.45, 37.97]]), np.array([[-82.99, -87.63, -112.07, -87.57]])
    zi, names = tz.zone_index(lat, lon)
    assert [names[i] for i in zi[0]][:3] == ["America/New_York", "America/Chicago", "America/Phoenix"]
    assert "Chicago" in names[zi[0][3]]                                              # Evansville is Central
    assert tz.utc_offset_minutes("America/New_York", dt.date(2026, 7, 1)) == -240
    assert tz.utc_offset_minutes("America/New_York", dt.date(2026, 12, 1)) == -300
    assert tz.utc_offset_minutes("America/Phoenix", dt.date(2026, 7, 1)) == -420


def test_dst_jump_is_reported_and_zone_border_steps():
    _, info = sun_grid("sunrise", OHIO, dt.date(2026, 10, 15), dt.date(2026, 11, 15))
    assert info["dst_shift"] == 60
    _, info = sun_grid("sunrise", OHIO, dt.date(2026, 10, 15), dt.date(2026, 10, 25))
    assert info["dst_shift"] == 0
    g, _ = sun_grid("sunset", OHIO, dt.date(2026, 10, 15))
    row = g.data[90]                                                                 # lat ~38: Central time in the west (Evansville), Eastern to the east
    assert np.nanmax(np.abs(np.diff(row))) > 30


def test_change_antisymmetric_and_daylength_has_no_clock_jump():
    a, b = dt.date(2026, 10, 15), dt.date(2026, 12, 21)
    up, _ = sun_grid("daylen", OHIO, a, b)
    down, _ = sun_grid("daylen", OHIO, b, a)
    assert np.allclose(up.data, -down.data, atol=1e-3) and np.nanmax(up.data) < 0
    _, info = sun_grid("daylen", OHIO, a, b)
    assert info["dst_shift"] == 0


def test_labels():
    assert fmt_clock(463) == "7:43 AM" and fmt_clock(1110) == "6:30 PM" and fmt_clock(0) == "12:00 AM" and fmt_clock(720) == "12:00 PM"
    assert fmt_duration(605) == "10h 05m"
    assert fmt_delta(3) == "+3m" and fmt_delta(-72) == "-1h 12m" and fmt_delta(0) == "0m"


def test_tidy_style_edges_are_round():
    data = np.linspace(413.0, 478.0, 200).astype("float32")
    s = tidy_style(Style(steps=6), data, symmetric=False)
    step = (s.vmax - s.vmin) / s.steps
    assert s.steps == 6 and s.vmin % step == 0 and step in (5, 10, 15) and s.vmin <= 413 and s.vmax >= 478


def test_query_and_metric():
    base = dict(when="sun", element="sunrise", start=dt.date(2026, 10, 15))
    q = Query(**base)
    assert unsupported_reason(q) is None and describe(q) == "Sunrise on Oct 15, 2026"
    assert describe(Query(**{**base, "element": "daylen", "end": dt.date(2026, 12, 21)})) == "Change in Day Length, Oct 15, 2026 to Dec 21, 2026"
    m = metric_from_query(Query(**base, end=dt.date(2026, 11, 1)))
    assert m.kind == "sun" and m.change and m.element == "sunrise"
    assert unsupported_reason(Query(**base, end=dt.date(2026, 10, 15)))              # end must be after start
    assert unsupported_reason(Query(when="sun", element="sunrise")) == "Choose a date."
    assert unsupported_reason(Query(**base), bbox=(-10, 40, 0, 45))                  # outside time-zone coverage
    assert set(SUN_ELEMENTS) == {"sunrise", "sunset", "daylen"}
