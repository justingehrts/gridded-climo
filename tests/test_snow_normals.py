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
