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


def test_year_coverage_and_threshold_rules(monkeypatch):
    import gridded_climo.query as qm
    monkeypatch.setattr(qm, "shipped_years", lambda d=None: {"grid": (1991, 2025), "station": (1950, 2025)})
    base = dict(when="first", element="mint", op="le", value=32)
    assert "Stations" in unsupported_reason(Query(**base, method="grid", normal_period=(1960, 2020)))
    assert unsupported_reason(Query(**base, method="station", normal_period=(1950, 2025))) is None
    assert unsupported_reason(Query(**{**base, "value": 37}, method="station", normal_period=(1930, 2025))) is None  # off-menu, live
    assert "1870" in unsupported_reason(Query(**base, method="station", normal_period=(1850, 2020)))
    assert unsupported_reason(Query(**{**base, "value": 37}, method="grid", normal_period=(1991, 2020))) is None     # every whole degree is saved
    assert "pre-saved" in unsupported_reason(Query(**{**base, "value": 70}, method="grid", normal_period=(1991, 2020)))   # out of grid range
    assert unsupported_reason(Query(**base, method="grid", normal_period=(1991, 2020))) is None


# --- server-side threshold search (response shapes captured from the live API, 2026-10) ---------------------------
SEASON = {"start": [7, 1], "end": [6, 30]}


def _server_response():
    cell = lambda d, v, m: [[d, v, m]]
    return {"data": [
        {"meta": {"ll": [-82.88, 39.99], "sids": ["14821 1", "CMH 3"], "name": "JOHN GLENN"},
         "data": [cell("2015-10-15", "38", 0), cell("M", "M", 0), cell("2017-10-17", "39", 12)]},          # 2016: never reached
        {"meta": {"ll": [-83.1, 40.1], "sids": ["X 1"], "name": "SPOTTY"},
         "data": [cell("2015-10-20", "40", 150), cell("M", "M", 182), cell("2017-10-21", "40", 0)]},      # too much missing data
        {"meta": {"name": "NO COORDS"}, "data": [cell("M", "M", 365)] * 3},                               # dropped
    ]}


def test_threshold_request_matches_xmacis_shape():
    from gridded_climo.stations import threshold_request
    r = threshold_request(BBOX, "mint", "le", 40, "first", SEASON, 2015, 2017)
    e = r["elems"][0]
    assert (r["sdate"], r["edate"]) == ("2016-06-30", "2018-06-30")                    # season END dates (std = season-to-date)
    assert e["interval"] == [1, 0, 0] and e["duration"] == "std" and e["season_start"] == "07-01"
    assert e["reduce"] == {"reduce": "first_le_40", "add": "value,mcnt"}
    assert threshold_request(BBOX, "snow", "ge", 1, "last", SEASON, 2015, 2017)["elems"][0]["reduce"]["reduce"] == "last_ge_1.0"
    cal = threshold_request(BBOX, "maxt", "ge", 90, "first", {"start": [1, 1], "end": [12, 31]}, 2015, 2016)
    assert (cal["sdate"], cal["edate"], cal["elems"][0]["season_start"]) == ("2015-12-31", "2016-12-31", "01-01")


def test_parse_threshold_response_semantics():
    from gridded_climo.stations import parse_threshold_response
    z = parse_threshold_response(_server_response(), SEASON, 2015, 2017)
    assert z["sids"].tolist() == ["14821 1", "X 1"] and z["years"].tolist() == [2015, 2016, 2017]
    assert z["offsets"][:, 0].tolist() == [106, NO_CROSS, 108]       # Oct 15 = 106 days after Jul 1; 'M' + few missing = never reached
    assert z["offsets"][:, 1].tolist() == [INVALID, INVALID, 112]    # >10% of the season missing -> not trusted, with or without a date
    with pytest.raises(ValueError, match="seasons"):
        parse_threshold_response(_server_response(), SEASON, 2015, 2018)


class FakeServerClient:
    cache = None

    def __init__(self):
        self.requests = []

    def post(self, endpoint, params):
        self.requests.append((endpoint, params))
        return _server_response()


def test_live_fallback_when_not_shipped_then_shipped_is_preferred(tmp_path):
    from gridded_climo.products.station_climo import station_climatology
    from gridded_climo.stations import fetch_station_thresholds, station_path
    m = metric_from_query(Query(when="first", element="mint", op="le", value=40, method="station", normal_period=(2015, 2017)))
    c = FakeServerClient()
    grid, info = station_climatology(m, (-84.0, 39.0, -82.0, 41.0), (2015, 2017), tmp_path, cell_deg=0.25, client=c)
    assert info["data_source"] == "live" and len(c.requests) == 1 and c.requests[0][0] == "MultiStnData"
    assert c.requests[0][1]["bbox"] == "-85,38,-81,42"                    # map bbox + 1 degree margin for edge stations
    assert info["points"]["name"].tolist() == ["JOHN GLENN"]              # SPOTTY has <20 valid... only 1 valid year -> excluded
    # ship the file -> served without touching ACIS
    z = fetch_station_thresholds(FakeServerClient(), BBOX, "mint", "le", 40, "first", SEASON, 2015, 2017)
    np.savez_compressed(station_path(tmp_path, "mint", "le", 40, "first").parent.mkdir(parents=True, exist_ok=True) or station_path(tmp_path, "mint", "le", 40, "first"), **z)
    c2 = FakeServerClient()
    _, info2 = station_climatology(m, (-84.0, 39.0, -82.0, 41.0), (2015, 2017), tmp_path, cell_deg=0.25, client=c2)
    assert info2["data_source"] == "shipped" and c2.requests == []
    with pytest.raises(FileNotFoundError, match="live ACIS access is disabled"):
        station_climatology(m, (-84.0, 39.0, -82.0, 41.0), (2000, 2017), tmp_path, cell_deg=0.25, client=None)  # years not covered


def test_build_station_occurrence_server_writes_files(tmp_path, monkeypatch):
    import gridded_climo.stations as sm
    from gridded_climo.stations import build_station_occurrence_server, load_station_occurrence
    monkeypatch.setattr(sm, "last_complete_season", lambda season, today=None: 2017)  # fake client returns 2015-2017
    build_station_occurrence_server(FakeServerClient(), BBOX, "mint", "le", "first", (40, 32), SEASON, y0=2015, data_dir=tmp_path,
                                    log=lambda *_: None)
    z = load_station_occurrence(tmp_path, "mint", "le", 32, "first")
    assert z["offsets"].shape[1] == 2 and z["years"][0] == 2015


def test_extreme_years_ignores_dropped_all_nan_stations():
    """Regression: a station that never crossed (all NaN, dropped by station_stat) must not crash the record-year lookup."""
    from gridded_climo.stations import extreme_years
    z = {"years": np.array([2000, 2001, 2002], "int16"), "lon": np.array([-83.0, -82.0], "float32"),
         "lat": np.array([40.0, 40.0], "float32"), "sids": np.array(["a", "never"]), "name": np.array(["A", "N"]),
         "offsets": np.array([[50, NO_CROSS], [40, NO_CROSS], [60, NO_CROSS]], "int16")}
    station_stat(z, (2000, 2002), "min")
    assert extreme_years(z, (2000, 2002), "min", station_stat.last_mask).tolist() == [2001]


def _at(grid, lon, lat):
    r = np.clip(((grid.north - lat) // grid.dy).astype(int), 0, grid.data.shape[0] - 1)
    c = np.clip(((lon - grid.west) // grid.dx).astype(int), 0, grid.data.shape[1] - 1)
    return grid.data[r, c]


def test_interpolated_map_honors_station_values():
    """The map at a station should show that station's own value (this is what viewers compare to NWS station tables)."""
    from gridded_climo.interpolate import idw, smooth
    rng = np.random.default_rng(3)
    lon, lat = rng.uniform(-83.8, -82.2, 70), rng.uniform(39.2, 40.8, 70)
    val = 110 + 6 * np.sin(lon * 5) + 5 * np.cos(lat * 6) + rng.normal(0, 2.5, 70)        # smooth trend + local differences
    tpl = grid_for_bbox((-84.0, 39.0, -82.0, 41.0), 0.02)

    def err(sm, k=8, p=3.0):
        g = idw(lon, lat, val, tpl, k=k, power=p, max_km=80)
        return np.abs(_at(smooth(g, sm) if sm else g, lon, lat) - val)

    assert err(0).mean() < 0.1 and np.percentile(err(0), 90) < 0.1   # no blur: exact (two stations sharing a 2 km cell can differ)
    assert err(3).mean() < 1.0 and np.percentile(err(3), 90) < 2.0   # the shipped default
    assert err(12).mean() > 2 * err(3).mean()                  # heavy blur drifts from stations: why it's a slider, not the default
    assert err(3, k=12, p=2.0).mean() > err(3).mean()          # the old weighting is looser even at equal blur


def test_shipped_station_map_stays_close_to_station_values():
    from gridded_climo.config import DEFAULT_BBOX
    from gridded_climo.products.climatology import climatology
    from pathlib import Path
    if not Path("data/stations/mint_le32_first.npz").exists():
        pytest.skip("no shipped station data")
    m = metric_from_query(Query(when="first", element="mint", op="le", value=32, method="station"))
    grid, info = climatology(m, None, DEFAULT_BBOX, (1991, 2020))
    p = info["points"]
    err = np.abs(_at(grid, p["lon"], p["lat"]) - p["value"])
    ok = np.isfinite(err)
    assert ok.mean() > 0.9
    assert err[ok].mean() < 0.8 and np.percentile(err[ok], 90) < 2.0     # was 2.2 / 5.3 days with the old 12 km blur


def test_smooth_km_validation_and_passthrough():
    from gridded_climo.query import unsupported_reason
    base = dict(when="first", element="mint", op="le", value=32, method="station")
    assert unsupported_reason(Query(**base, smooth_km=0)) is None and "0 and 30" in unsupported_reason(Query(**base, smooth_km=99))
