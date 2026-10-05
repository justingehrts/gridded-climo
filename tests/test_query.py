import datetime as dt

import pytest

from gridded_climo.query import Query, default_season, describe, metric_from_query, unsupported_reason


def test_season_rules():
    assert default_season("le", "first") == {"start": [7, 1], "end": [6, 30]}
    assert default_season("le", "last") == {"start": [1, 1], "end": [6, 30]}
    assert default_season("ge", "first") == default_season("ge", "last") == {"start": [1, 1], "end": [12, 31]}


def test_first_last_metric_and_style_direction():
    m = metric_from_query(Query(when="first", element="mint", op="le", value=32))
    assert (m.kind, m.direction, m.threshold) == ("climatology", "first", {"op": "le", "value": 32})
    rev = lambda w, op, v: metric_from_query(Query(when=w, element="maxt", op=op, value=v)).style.reverse
    assert [rev("first", "le", 32), rev("last", "le", 32), rev("first", "ge", 90), rev("last", "ge", 90)] == [True, False, False, True]


def test_unsupported_states_have_reasons():
    assert unsupported_reason(Query(when="last", element="snow", op="ge", value=1.0)) is None  # station path
    assert unsupported_reason(Query(when="last", element="snow", op="ge", value=2.0)) is None   # stations: any amount (fetched live)
    assert "between" in unsupported_reason(Query(when="last", element="snow", op="ge", value=500))
    assert "at or above" in unsupported_reason(Query(when="last", element="snow", op="le", value=1.0))
    assert unsupported_reason(Query(when="first", element="maxt", op="ge", value=90)) is None
    for v in (91, 120):                                                    # the grid only has its pre-saved set
        assert "only has pre-saved" in unsupported_reason(Query(when="first", element="maxt", op="ge", value=v))
    assert unsupported_reason(Query(when="first", element="maxt", op="ge", value=91, method="station")) is None   # stations: any
    assert "coming soon" in unsupported_reason(Query(when="range_normal", element="snow", start=dt.date(2001, 12, 1), end=dt.date(2001, 12, 31)))
    assert "mean and total" in unsupported_reason(Query(when="range_normal", element="maxt", reduce="max", start=dt.date(2001, 1, 1), end=dt.date(2001, 1, 9)))
    assert "mean and total" in unsupported_reason(Query(when="range_specific", element="maxt", reduce="min", departure=True, start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 9)))
    assert "one year" in unsupported_reason(Query(when="range_specific", element="pcpn", reduce="sum", start=dt.date(2020, 1, 1), end=dt.date(2022, 1, 1)))
    assert "2008" in unsupported_reason(Query(when="range_specific", element="snow", start=dt.datetime(2005, 1, 1), end=dt.datetime(2005, 1, 3)))
    with pytest.raises(ValueError):
        metric_from_query(Query(when="last", element="pcpn", op="ge", value=1))


def test_range_metrics():
    m = metric_from_query(Query(when="range_specific", element="maxt", reduce="mean", departure=True, start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31)))
    assert (m.kind, m.normal, m.style.symmetric) == ("period", "departure", True)
    assert metric_from_query(Query(when="range_normal", element="pcpn", reduce="sum", start=dt.date(2001, 12, 1), end=dt.date(2001, 12, 31))).normal == "average"
    assert metric_from_query(Query(when="range_specific", element="snow", start=dt.datetime(2024, 1, 5), end=dt.datetime(2024, 1, 7))).kind == "storm"
    assert describe(Query(when="last", element="maxt", op="ge", value=90)) == "Average Date of Last High Temperature at or above 90°F"


def test_station_method_and_snow_routing():
    g = metric_from_query(Query(when="first", element="mint", op="le", value=40))
    st = metric_from_query(Query(when="first", element="mint", op="le", value=40, method="station"))
    sn = metric_from_query(Query(when="last", element="snow", op="ge", value=1.0))
    assert (g.source, st.source, sn.source) == ("acis_grid1", "acis_stn", "acis_stn")
    assert sn.season == {"start": [7, 1], "end": [6, 30]} and sn.style.units_label == "date"
    assert "Snowfall of 1" in describe(Query(when="last", element="snow", op="ge", value=1.0))


def test_last_complete_year_rolls_over_with_the_calendar():
    from gridded_climo.query import last_complete_year
    cool, cal = {"start": [7, 1], "end": [6, 30]}, {"start": [1, 1], "end": [12, 31]}
    d = dt.date
    assert (last_complete_year(cool, d(2026, 10, 1)), last_complete_year(cal, d(2026, 10, 1))) == (2025, 2025)
    assert last_complete_year(cool, d(2026, 6, 29)) == 2024        # 2025-26 season hasn't ended
    assert last_complete_year(cool, d(2026, 7, 10)) == 2025        # ...and has by mid-July
    assert last_complete_year(cool, d(2027, 10, 1)) == 2026        # a year from now: no code change needed
    assert last_complete_year(cal, d(2027, 1, 3)) == 2025          # within 5 days of year end: still settling


def test_station_year_limits_and_shipped_normals(monkeypatch):
    import gridded_climo.query as qm
    base = dict(when="first", element="mint", op="le", value=32, method="station")
    last = qm.last_complete_year(qm.default_season("le", "first", "mint"))
    assert unsupported_reason(Query(**base, normal_period=(1870, last))) is None
    assert "1870" in unsupported_reason(Query(**base, normal_period=(1850, 2000)))
    assert "latest completed season" in unsupported_reason(Query(**base, normal_period=(1991, last + 1)))
    monkeypatch.setattr(qm, "allow_live", lambda: False)
    r = dict(when="range_normal", element="maxt", reduce="mean", start=dt.date(2001, 12, 1), end=dt.date(2001, 12, 31))
    assert unsupported_reason(Query(**r)) is None
    assert "1991-2020" in unsupported_reason(Query(**r, normal_period=(1981, 2010)))
    assert "1991-2020" in unsupported_reason(Query(when="range_specific", element="maxt", reduce="mean", departure=True,
                                                   start=dt.date(2024, 7, 1), end=dt.date(2024, 7, 31), normal_period=(1981, 2010)))


def test_default_color_steps_are_six_on_date_and_temperature_maps():
    from gridded_climo.registry import Style
    from gridded_climo.registry import load_registry
    assert Style().steps == 6
    for q in [Query(when="first", element="mint", op="le", value=32), Query(when="last", element="maxt", op="ge", value=90, method="station"),
              Query(when="last", element="snow", op="ge", value=1.0),
              Query(when="range_specific", element="maxt", reduce="mean", start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31)),
              Query(when="range_specific", element="maxt", reduce="mean", departure=True, start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31))]:
        assert metric_from_query(q).style.steps == 6
    reg = load_registry()
    assert all(reg[n].style.steps == 6 for n in ("first_freeze", "last_freeze", "last_1in_snow", "avg_high_period", "high_departure_period"))


def test_thresholds_are_whole_degrees_for_temperature_and_tenths_for_snow():
    t = dict(when="first", element="mint", op="le")
    for method in ("grid", "station"):
        assert unsupported_reason(Query(**t, value=32, method=method)) is None
        assert "whole degrees" in unsupported_reason(Query(**t, value=32.5, method=method))
    s = dict(when="last", element="snow", op="ge")
    assert all(unsupported_reason(Query(**s, value=v)) is None for v in (0.1, 0.5, 1.0, 2.5, 12.3))
    assert all("tenths" in unsupported_reason(Query(**s, value=v)) for v in (1.25, 0.05, 2.75))


def test_presaved_temperature_set_is_tens_plus_28_32_36_and_defaults_are_inside_it():
    from gridded_climo.query import DEFAULT_THRESHOLD, MENU, STATION_MENU
    assert MENU[("mint", "le")] == (-10, 0, 10, 20, 28, 30, 32, 36, 40, 50) == MENU[("maxt", "le")]
    assert MENU[("maxt", "ge")] == (50, 60, 70, 80, 90, 100) and MENU[("mint", "ge")] == (40, 50, 60, 70, 80)
    for key, vals in MENU.items():
        assert all(v % 10 == 0 or v in (28, 32, 36) for v in vals)
        assert DEFAULT_THRESHOLD[key] in vals and STATION_MENU[key] == vals    # stations pre-save the same temperatures
    assert not any(v in (28, 32, 36) for key in (("maxt", "ge"), ("mint", "ge")) for v in MENU[key])   # cold extras only for <= maps


def test_snow_presaved_amounts_are_tenth_one_and_three_inches():
    from gridded_climo.query import STATION_MENU
    assert STATION_MENU[("snow", "ge")] == (0.1, 1.0, 3.0)


def test_region_rules_in_validation():
    from gridded_climo.regions import buffered_bbox
    tx, oh, ind = buffered_bbox("TX"), buffered_bbox("OH"), buffered_bbox("IN")
    grid = Query(when="first", element="mint", op="le", value=32, method="grid")
    stn = Query(when="first", element="mint", op="le", value=32, method="station")
    assert unsupported_reason(grid) is None and unsupported_reason(grid, oh) is None            # default region and Ohio: pre-saved
    for bb in (tx, ind):
        assert "pre-saved for the Ohio-centered region only" in unsupported_reason(grid, bb)
        assert unsupported_reason(stn, bb) is None                                                # stations work anywhere
    dep = Query(when="range_specific", element="maxt", reduce="mean", departure=True, start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31))
    avg = Query(when="range_normal", element="maxt", reduce="mean", start=dt.date(2001, 12, 1), end=dt.date(2001, 12, 31))
    for q in (dep, avg):
        assert unsupported_reason(q, oh) is None and "daily normals" in unsupported_reason(q, tx)
    year = Query(when="range_specific", element="maxt", reduce="mean", start=dt.date(2024, 7, 1), end=dt.date(2025, 6, 30))
    assert unsupported_reason(year, oh) is None and "can use at most" in unsupported_reason(year, tx)
    month = Query(when="range_specific", element="maxt", reduce="mean", start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31))
    assert unsupported_reason(month, tx) is None
    storm = Query(when="range_specific", element="snow", start=dt.datetime(2024, 1, 5), end=dt.datetime(2024, 1, 8))
    assert unsupported_reason(storm, tx) is None                                                 # NOHRSC covers the whole lower 48
