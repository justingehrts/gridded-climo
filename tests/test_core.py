import datetime as dt
import zipfile

import numpy as np
import pytest

from gridded_climo import nohrsc
from gridded_climo.acis import ACISError, build_grid_request
from gridded_climo.cache import Cache
from gridded_climo.config import DEFAULT_BBOX, Settings
from gridded_climo.grid import Grid
from gridded_climo.products.climatology import cross_year_stat, crossing_offset, season_window
from gridded_climo.products.period import reduce_daily
from gridded_climo.registry import Metric, RegistryError, Style, load_registry
from gridded_climo.render import color_table, render_kmz


def test_crossing_first_last_and_never():
    d = np.full((6, 1, 3), 40.0, "float32")
    d[2, 0, 0] = 30; d[4, 0, 0] = 31          # cell 0: hits on day 2 and 4
    d[5, 0, 1] = 32                            # cell 1: hit only on last day (le is inclusive)
    d[1, 0, 2] = np.nan                        # cell 2: NaN never counts, never crosses
    assert crossing_offset(d, "le", 32, "first")[0].tolist()[:2] == [2, 5]
    assert crossing_offset(d, "le", 32, "last")[0].tolist()[:2] == [4, 5]
    assert np.isnan(crossing_offset(d, "le", 32, "first")[0, 2])
    assert crossing_offset(d, "lt", 32, "first")[0, 1] != 5 and np.isnan(crossing_offset(d, "lt", 32, "first")[0, 1])


def test_season_window_crosses_year():
    assert season_window({"start": [7, 1], "end": [6, 30]}, 1991) == (dt.date(1991, 7, 1), dt.date(1992, 6, 30))
    assert season_window({"start": [1, 1], "end": [6, 30]}, 1991) == (dt.date(1991, 1, 1), dt.date(1991, 6, 30))


def test_cross_year_stats_and_min_years():
    stack = np.array([[[10.0, np.nan]], [[20.0, np.nan]], [[60.0, 5.0]]], "float32")
    assert cross_year_stat(stack, "mean")[0, 0] == 30
    assert cross_year_stat(stack, "median")[0, 0] == 20
    assert cross_year_stat(stack, "percentile", 100)[0, 0] == 60
    assert np.isnan(cross_year_stat(stack, "mean", min_frac=0.5)[0, 1])  # 1 of 3 years < 50%
    assert cross_year_stat(stack, "mean", min_frac=0.3)[0, 1] == 5


def test_reduce_daily_all_nan_stays_nan():
    d = np.array([[[1.0, np.nan]], [[3.0, np.nan]]], "float32")
    assert reduce_daily(d, "sum")[0].tolist()[0] == 4 and np.isnan(reduce_daily(d, "sum")[0, 1])
    assert reduce_daily(d, "mean")[0, 0] == 2


def test_request_builder():
    r = build_grid_request("mint", DEFAULT_BBOX, "2020-07-01", "2020-09-30")
    assert r == {"bbox": "-87.5,37,-78.5,42.5", "sdate": "2020-07-01", "edate": "2020-09-30", "grid": "1",
                 "elems": [{"name": "mint"}], "meta": ["ll"]}
    with pytest.raises(ACISError):
        build_grid_request("snow", DEFAULT_BBOX, "2020-01-01", "2020-01-02")  # not on Grid 1


def test_registry_loads_and_validates():
    reg = load_registry()
    assert {"first_freeze", "storm_total_snow", "avg_high_period"} <= set(reg)
    with pytest.raises(RegistryError):
        Metric(name="x", kind="climatology", source="acis_grid1", element="mint").validate()
    with pytest.raises(RegistryError):
        Metric(name="x", kind="period", source="acis_grid1", element="maxt", reduce="mode").validate()


def test_settings_validation():
    with pytest.raises(ValueError):
        Settings(bbox=(-80, 40, -85, 42))
    with pytest.raises(ValueError):
        Settings(normal_period=(2020, 1991))


def test_cache_roundtrip_and_hit(tmp_path):
    c, calls = Cache(tmp_path), []
    def compute():
        calls.append(1); return {"a": np.arange(4)}
    req = {"k": 1}
    assert c.get_or_compute("ns", req, compute)["a"].tolist() == [0, 1, 2, 3]
    assert c.get_or_compute("ns", req, compute)["a"].tolist() == [0, 1, 2, 3]
    assert len(calls) == 1
    c.get_or_compute("ns", {"k": 2}, compute); assert len(calls) == 2


def test_grid_from_centers_orients_north_up_and_clips(tmp_path):
    lat = np.array([[40.0, 40.0], [40.5, 40.5]]); lon = np.array([[-83.0, -82.0], [-83.0, -82.0]])  # south-up input
    g = Grid.from_centers(np.array([[1, 2], [3, 4]]), lat, lon)
    assert g.data.tolist() == [[3, 4], [1, 2]] and g.north == pytest.approx(40.75) and g.west == pytest.approx(-83.5)
    assert g.clip((-83.4, 40.3, -83.0, 40.7)).data.tolist() == [[3]]
    g2 = Grid.from_geotiff(g.to_geotiff(tmp_path / "a.tif"))
    assert g2.data.tolist() == g.data.tolist() and (g2.west, g2.north, g2.dx) == (g.west, g.north, g.dx)


def test_nohrsc_urls_and_snap():
    base = "https://x"
    end = dt.datetime(2024, 1, 1, 12)
    assert nohrsc.season_total_url(base, end) == "https://x/202401/sfav2_CONUS_2023093012_to_2024010112.tif"
    assert nohrsc.six_hour_url(base, dt.datetime(2024, 1, 5, 6)) == "https://x/202401/sfav2_CONUS_6h_2024010506.tif"
    assert nohrsc.season_start(dt.datetime(2024, 10, 2)) == dt.datetime(2024, 9, 30, 12)
    assert nohrsc.snap(dt.datetime(2024, 1, 5, 14, 40), 12) == dt.datetime(2024, 1, 5, 12)
    assert nohrsc.snap(dt.datetime(2024, 1, 5, 19, 0), 12) == dt.datetime(2024, 1, 6, 0)
    assert nohrsc.snap(dt.datetime(2024, 1, 5, 14, 40), 6, "down") == dt.datetime(2024, 1, 5, 12)


def test_color_table_stepped_bins_and_hide_below():
    t = color_table(Style(ramp="Blues", mode="stepped", steps=4), 0, 4)
    assert [r[0] for r in t][::2] == [0, 1, 2, 3] and t[-1][0] == 4 and t[0][1:4] == t[1][1:4]  # flat within a bin
    h = color_table(Style(ramp="Blues", mode="stepped", steps=4, hide_below=0.5), 1, 5)
    assert h[0][4] == 0 and h[0][0] < 0.5 <= h[1][0] and h[1][4] == 255
    assert len(color_table(Style(mode="smooth"), 0, 1)) == 100


def test_render_kmz_end_to_end(tmp_path):
    data = np.tile(np.linspace(0, 10, 20, dtype="float32"), (10, 1)); data[0, 0] = np.nan
    tif = Grid(data, -84.0, 41.0, 0.1, 0.1).to_geotiff(tmp_path / "t.tif")
    out = render_kmz(tif, tmp_path / "t.kmz", Style(ramp="Viridis", steps=5, units_label="in"), "Test & <name>")
    z = zipfile.ZipFile(out)
    assert set(z.namelist()) == {"doc.kml", "output.png", "legend.png"}
    kml = z.read("doc.kml").decode()
    assert "Test &amp; &lt;name&gt;" in kml and "<west>-84" in kml and "<north>41" in kml
