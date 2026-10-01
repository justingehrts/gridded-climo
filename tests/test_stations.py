import datetime as dt

import numpy as np
import pytest

from gridded_climo.interpolate import grid_for_bbox, idw
from gridded_climo.products.climatology import climatology
from gridded_climo.products.station_climo import station_climatology
from gridded_climo.query import Query, metric_from_query, unsupported_reason
from gridded_climo.stations import (INVALID, NO_CROSS, build_station_occurrence, fetch_season, parse_value, station_offsets,
                                    station_stat)

BBOX = (-84.0, 39.0, -82.0, 41.0)
STATIONS = [("A 1", -83.0, 40.0), ("B 2", -82.5, 40.5), ("C 3", -83.5, 39.5)]


def test_parse_value():
    assert parse_value(["70"], "mint") == 70 and parse_value(["-5"], "mint") == -5
    assert np.isnan(parse_value(["M"], "mint")) and parse_value(["T"], "snow") == 0.0
    assert parse_value(["1.5"], "snow") == 1.5 and np.isnan(parse_value(["2.0A"], "snow")) and parse_value(["12"], "snow") == 12


class FakeStationClient:
    """Mimics ACISClient.post for MultiStnData: station C has gappy data; temps fall a bit each year."""
    cache = None

    def post(self, endpoint, params):
        assert endpoint == "MultiStnData" and params["elems"][0]["interval"] == "dly"
        s, e = dt.date.fromisoformat(params["sdate"]), dt.date.fromisoformat(params["edate"])
        n = (e - s).days + 1
        rows = []
        for k, (sid, lon, lat) in enumerate(STATIONS):
            base = np.linspace(60, 10, n) - 3 * k                      # cooling through the season
            vals = [[str(int(v))] for v in base]
            if sid.startswith("C"):
                vals = [["M"] if i % 2 else v for i, v in enumerate(vals)]  # 50% missing -> INVALID
            rows.append({"meta": {"ll": [lon, lat], "sids": [sid], "name": f"STN {sid[0]}"}, "data": vals})
        return {"data": rows}


def test_fetch_season_shape_and_values():
    d = fetch_season(FakeStationClient(), BBOX, "mint", dt.date(2019, 7, 1), dt.date(2020, 6, 30))
    assert d["data"].shape == (366, 3) and d["sids"].tolist() == ["A 1", "B 2", "C 3"]
    assert d["data"][0, 0] == 60 and np.isnan(d["data"][1, 2])


def test_station_offsets_valid_invalid_nocross():
    d = np.array([[50, 50, np.nan], [45, 39, np.nan], [38, 35, np.nan], [30, 50, np.nan]], "float32")
    off = station_offsets(d, "le", 40, "first")
    assert off.tolist() == [2, 1, INVALID]
    assert station_offsets(d, "le", 10, "first")[0] == NO_CROSS
    assert station_offsets(d, "le", 40, "last")[1] == 2   # 35 on day 2 is the last reading <= 40 (day 3 is 50)


def test_build_and_stat_and_interpolate(tmp_path):
    season = {"start": [7, 1], "end": [6, 30]}
    build_station_occurrence(FakeStationClient(), BBOX, "mint", "le", "first", (40, 32), season, y0=2017, data_dir=tmp_path,
                             log=lambda *_: None)
    m = metric_from_query(Query(when="first", element="mint", op="le", value=40, method="station", normal_period=(2018, 2020)))
    grid, info = station_climatology(m, BBOX, (2018, 2020), tmp_path, cell_deg=0.25)
    pts = info["points"]
    assert sorted(pts["name"].tolist()) == ["STN A", "STN B"]   # C dropped: too much missing data
    # values are int()-truncated, so A crosses 40 once the true value < 41 (~day 139) and B, 3 degrees cooler, ~week earlier
    assert 110 < pts["value"].min() < pts["value"].max() < 150 and pts["value"].min() < pts["value"].max()
    assert np.isfinite(grid.data).any() and np.nanmin(grid.data) >= pts["value"].min() - 1e-3
    # dispatched through the same climatology() entry point the UI uses, with no network client
    g2, info2 = climatology(m, None, BBOX, (2018, 2020), tmp_path)
    assert info2["source"] == "station" and g2.data.shape == (100, 100)   # default 0.02 deg cells over a 2x2 deg bbox


def test_station_stat_requires_years_and_mostly_crossing(tmp_path):
    z = {"years": np.array([2018, 2019, 2020], "int16"), "lon": np.array([-83.0, -82.0], "float32"),
         "lat": np.array([40.0, 40.0], "float32"), "sids": np.array(["a", "b"]), "name": np.array(["A", "B"]),
         "offsets": np.array([[100, NO_CROSS], [110, NO_CROSS], [120, 150]], "int16")}
    lon, lat, val, nv, sids, names = station_stat(z, (2018, 2020), "mean")
    assert sids.tolist() == ["a"] and val.tolist() == [110.0]      # b crossed in 1 of 3 valid seasons -> dropped
    assert station_stat(z, (2018, 2020), "median")[2].tolist() == [110.0]
    with pytest.raises(ValueError, match="needs"):
        station_stat(z, (2015, 2020), "mean")
    z["offsets"][:, 0] = INVALID                                     # station a has no valid seasons
    assert len(station_stat(z, (2018, 2020), "mean")[2]) == 0


def test_idw_limits_extrapolation_and_exact_at_station():
    tpl = grid_for_bbox((-84.0, 39.0, -82.0, 41.0), 0.1)
    g = idw([-83.0, -82.9], [40.0, 40.0], [10.0, 30.0], tpl, max_km=30)
    assert np.isnan(g.data[0, 0]) and np.isfinite(g.data).sum() > 0     # far corner has no station within 30 km
    assert 10 <= np.nanmin(g.data) and np.nanmax(g.data) <= 30           # IDW never overshoots the data range
    with pytest.raises(ValueError):
        idw([], [], [], tpl)


def test_min_max_stats_and_record_years():
    from gridded_climo.stations import extreme_years
    z = {"years": np.array([1950, 1951, 1952, 1953], "int16"), "lon": np.array([-83.0, -82.0, -81.0], "float32"),
         "lat": np.array([40.0, 40.0, 40.0], "float32"), "sids": np.array(["a", "b", "c"]), "name": np.array(["A", "B", "C"]),
         "offsets": np.array([[50, 90, NO_CROSS], [40, 80, NO_CROSS], [60, 70, NO_CROSS], [45, 100, 10]], "int16")}
    lon, lat, lo, nv, sids, names = station_stat(z, (1950, 1953), "min")
    keep = station_stat.last_mask
    assert sids.tolist() == ["a", "b"] and lo.tolist() == [40.0, 70.0]          # c crossed in 1 of 4 seasons -> dropped
    assert station_stat(z, (1950, 1953), "max")[2].tolist() == [60.0, 100.0]
    assert extreme_years(z, (1950, 1953), "min", keep).tolist() == [1951, 1952]
    assert extreme_years(z, (1950, 1953), "max", station_stat(z, (1950, 1953), "max") and station_stat.last_mask).tolist() == [1952, 1953]
    assert station_stat(z, (1951, 1952), "min")[2].tolist() == [40.0, 70.0]      # sub-range respected


def test_grid_cross_year_min_max():
    from gridded_climo.products.climatology import cross_year_stat
    stack = np.array([[[10.0, np.nan]], [[20.0, 7.0]], [[60.0, 9.0]]], "float32")
    assert cross_year_stat(stack, "min", min_frac=0.3)[0].tolist() == [10.0, 7.0]
    assert cross_year_stat(stack, "max", min_frac=0.3)[0].tolist() == [60.0, 9.0]


def test_titles_name_the_statistic():
    from gridded_climo.query import describe
    assert describe(Query(when="first", element="snow", op="ge", value=1.0, stat="min")) == 'Earliest First Snowfall of 1" or More on Record'
    assert describe(Query(when="last", element="mint", op="le", value=32, stat="max")).startswith("Latest Last Low Temperature")
    assert describe(Query(when="first", element="mint", op="le", value=32, stat="percentile", percentile=10)).startswith("10th Percentile Date of First")
    assert describe(Query(when="first", element="mint", op="le", value=32)).startswith("Average Date of First")


def test_year_coverage_messages(monkeypatch):
    import gridded_climo.query as qm
    monkeypatch.setattr(qm, "shipped_years", lambda d=None: {"grid": (1991, 2025), "station": (1950, 2025)})
    base = dict(when="first", element="mint", op="le", value=32)
    assert "Stations" in unsupported_reason(Query(**base, method="grid", normal_period=(1960, 2020)))
    assert unsupported_reason(Query(**base, method="station", normal_period=(1950, 2025))) is None
    assert "covers" in unsupported_reason(Query(**base, method="station", normal_period=(1940, 2020)))
    assert unsupported_reason(Query(**base, method="grid", normal_period=(1991, 2020))) is None
