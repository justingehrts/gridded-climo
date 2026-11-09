import datetime as dt

import numpy as np
import pytest

from gridded_climo.query import Query, describe, metric_from_query, unsupported_reason
from gridded_climo.snow_normals import load_shipped, parse, window_label, window_months, window_sum


def test_window_months_wrap():
    assert window_months(11, 11) == [11]
    assert window_months(12, 2) == [12, 1, 2]
    assert window_months(7, 6) == list(range(7, 13)) + list(range(1, 7))
    assert window_label(11, 11) == "November" and window_label(12, 2) == "Dec–Feb" and window_label(7, 6) == "Seasonal (Jul–Jun)"


def test_parse_trace_and_missing():
    out = {"data": [
        {"meta": {"name": "A", "sids": ["1 2"], "ll": [-83, 40]}, "data": [["9.5"], ["T"]] + [["0.0"]] * 10},
        {"meta": {"name": "B", "sids": ["2 2"], "ll": [-84, 41]}, "data": [["M"]] + [["1.0"]] * 11},
        {"meta": {"name": "no ll", "sids": ["3 2"]}, "data": [["1.0"]] * 12}]}
    z = parse(out)
    assert list(z["name"]) == ["A", "B"] and z["monthly"][0, 1] == 0.0
    v, keep = window_sum(z, [1, 2])
    assert keep.tolist() == [True, False] and v.tolist() == [9.5]          # B lacks January -> dropped
    v, keep = window_sum(z, [2, 3])
    assert keep.tolist() == [True, True] and v.tolist() == [0.0, 2.0]


def test_shipped_columbus_matches_published():
    z = load_shipped()
    i = [j for j, n in enumerate(z["name"]) if "JOHN GLENN" in n][0]
    assert z["monthly"][i, 10] == pytest.approx(1.2)                        # NCEI 1991-2020 November normal at CMH


def test_query_rules():
    q = Query(when="range_normal", element="snow", start=dt.date(2001, 11, 1), end=dt.date(2001, 11, 30))
    assert unsupported_reason(q) is None and describe(q) == "Average November Snowfall"
    m = metric_from_query(q)
    assert m.normal == "average" and m.style.vmin is None and m.style.vmax is None
    assert unsupported_reason(Query(when="range_normal", element="snow", start=dt.date(2001, 11, 5), end=dt.date(2001, 11, 30)))
    assert unsupported_reason(Query(when="range_normal", element="snow", start=dt.date(2001, 11, 1), end=dt.date(2001, 11, 30),
                                    normal_period=(1981, 2010)))


def test_map_values_hug_station_normals():
    from gridded_climo.products.snow_normals import snow_normal_window
    grid, info = snow_normal_window((-87.5, 37.0, -78.5, 42.5), [11], smooth_km=0)
    assert info["data_source"] == "shipped"
    pts = info["points"]
    i = [j for j, n in enumerate(pts["name"]) if "JOHN GLENN" in n][0]
    r = int((grid.north - pts["lat"][i]) / grid.dy); c = int((pts["lon"][i] - grid.west) / grid.dx)
    assert abs(grid.data[r, c] - 1.2) < 0.3
    assert np.nanmax(grid.data) > 5            # lake-effect belt in NE Ohio / NW PA gets much more November snow


# --- departure from normal ---------------------------------------------------------------------------------------------
from gridded_climo.snow_normals import fetch_snow_departure, parse_departure


def _dep_response():
    row = lambda name, ll, obs, miss, norm, dep: {"meta": {"name": name, "sids": [name], "ll": ll}, "smry": [[obs, miss], [norm, 0], [dep, miss]]}
    return {"data": [row("CMH", [-82.88, 39.99], "14.1", 0, "17.1", "-3.0"), row("TRACE", [-83.5, 40.5], "T", 0, "0.4", "-0.4"),
                     row("GAPPY", [-84.0, 40.0], "2.0", 20, "10.0", "-8.0"), row("NOOBS", [-82.0, 39.5], "M", 59, "9.0", "M")]}


def test_parse_departure_filters_missing_and_reads_trace():
    z = parse_departure(_dep_response(), n_days=59, max_missing_frac=0.10)
    assert list(z["name"]) == ["CMH", "TRACE"]                      # GAPPY misses 20 of 59 days, NOOBS has no data
    assert z["departure"].tolist() == pytest.approx([-3.0, -0.4]) and z["obs"][1] == 0.0


class FakeACIS:
    cache = None

    def __init__(self):
        self.params = None

    def post(self, endpoint, params):
        self.params = params
        return _dep_response()


def test_fetch_departure_request_shape():
    c = FakeACIS()
    fetch_snow_departure(c, (-84, 39, -82, 41), dt.date(2025, 1, 1), dt.date(2025, 2, 28))
    e = c.params["elems"]
    assert [x.get("normal") for x in e] == [None, "1"] and all(x["smry_only"] == 1 for x in e)
    assert c.params["sdate"] == "2025-01-01" and c.params["edate"] == "2025-02-28"


def test_departure_query_rules():
    base = dict(when="range_specific", element="snow", departure=True)
    q = Query(**base, start=dt.date(2025, 1, 1), end=dt.date(2025, 2, 28))
    assert unsupported_reason(q) is None and describe(q) == "Snowfall Departure from Normal"
    assert metric_from_query(q).normal == "departure"
    assert unsupported_reason(Query(**base))                                                       # dates required
    assert unsupported_reason(Query(**base, start=dt.date(2024, 1, 1), end=dt.date(2025, 2, 28)))   # > 1 year
    assert unsupported_reason(Query(**base, start=dt.date(2025, 2, 1), end=dt.date(2025, 1, 1)))    # reversed
    assert unsupported_reason(Query(**base, start=dt.date(1960, 1, 1), end=dt.date(1960, 2, 1))) is None   # any year with station data


def test_departure_map_from_fake_client():
    from gridded_climo.products.snow_normals import snow_departure_map
    grid, info = snow_departure_map((-84, 39.5, -82, 41), dt.date(2025, 1, 1), dt.date(2025, 2, 28), FakeACIS(), smooth_km=0)
    assert len(info["points"]["value"]) == 2 and np.nanmin(grid.data) == pytest.approx(-3.0, abs=0.01)
    assert '14.1" vs 17.1" normal' in info["points"]["name"][0]


def test_parse_total_filters_missing_days():
    from gridded_climo.snow_normals import parse_total
    out = {"data": [{"meta": {"name": "A", "ll": [-83, 40]}, "smry": [[6.5, 0]]},
                    {"meta": {"name": "B", "ll": [-84, 41]}, "smry": [["M", 0]]},
                    {"meta": {"name": "C", "ll": [-82, 40]}, "smry": [[3.0, 9]]},
                    {"meta": {"name": "no ll"}, "smry": [[1.0, 0]]}]}
    z = parse_total(out, 3, 0.10)
    assert list(z["name"]) == ["A"] and z["obs"].tolist() == [6.5]


def test_blend_drops_reports_near_a_station():
    from gridded_climo.products.snow_storm import blend
    st = {"lon": np.array([-83.0]), "lat": np.array([40.0]), "name": np.array(["A"]), "obs": np.array([5.0])}
    rep = {"lon": [-83.01, -82.0], "lat": [40.0, 40.0], "value": [6.0, 7.0], "name": ["near", "far"]}
    p = blend(st, rep)
    assert p["n_stations"] == 1 and p["n_reports"] == 1 and p["value"].tolist() == [5.0, 7.0]
    assert "report" in p["name"][1] and "station" in p["name"][0]
    assert blend(st, None)["n_reports"] == 0


def test_stations_storm_total_is_allowed_before_nohrsc():
    base = dict(when="range_specific", element="snow", reduce="sum", normal_period=(1991, 2020))
    old = dt.date(2007, 2, 12), dt.date(2007, 2, 14)
    assert unsupported_reason(Query(**base, start=old[0], end=old[1], extra={"source": "stations"})) is None
    assert "Stations + reports" in unsupported_reason(Query(**base, start=dt.datetime(2007, 2, 12), end=dt.datetime(2007, 2, 14)))
    q = Query(**base, start=old[0], end=old[1], extra={"source": "stations"})
    assert describe(q) == "Storm Total Snowfall (Stations + Reports)" and metric_from_query(q).name == "storm_total_snow_stations"
    assert unsupported_reason(Query(**base, start=old[1], end=old[0], extra={"source": "stations"}))
