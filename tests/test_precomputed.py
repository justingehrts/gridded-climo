import datetime as dt

import numpy as np
import pytest

from gridded_climo.precompute import build_normals, build_occurrence
from gridded_climo.precomputed import load_normals, monthday_window
from gridded_climo.products.climatology import climatology_live, climatology_precomputed
from gridded_climo.products.period import normal_window_average, period_summary, reduce_daily
from gridded_climo.query import Query, metric_from_query
from gridded_climo.registry import Metric
from .fakes import BBOX, FakeClient, H, W


def test_precomputed_equals_live(tmp_path):
    client = FakeClient()
    for direction in ("first", "last"):
        build_occurrence(client, BBOX, "mint", "le", direction, (32, 20), y0=2017, data_dir=tmp_path, log=lambda *_: None)
        m = metric_from_query(Query(when=direction, element="mint", op="le", value=32, normal_period=(2018, 2020)))
        pre, info = climatology_precomputed(m, BBOX, (2018, 2020), tmp_path)
        live, _ = climatology_live(m, client, BBOX, (2018, 2020), log=lambda *_: None)
        np.testing.assert_array_equal(pre.data, live.data)
        assert info["years"] == (2018, 2020)


def test_precomputed_year_range_error(tmp_path):
    build_occurrence(FakeClient(), BBOX, "mint", "le", "first", (32,), y0=2020, data_dir=tmp_path, log=lambda *_: None)
    m = metric_from_query(Query(when="first", element="mint", op="le", value=32))
    with pytest.raises(ValueError, match="precomputed data covers"):
        climatology_precomputed(m, BBOX, (1991, 2020), tmp_path)


def test_build_occurrence_resumes_without_duplicating(tmp_path, monkeypatch):
    c, quiet = FakeClient(), lambda *_: None
    build_occurrence(c, BBOX, "maxt", "ge", "first", (90,), y0=2021, data_dir=tmp_path, log=quiet)
    with np.load(tmp_path / "occurrence" / "maxt_ge90_first.npz") as z:
        first = z["years"].tolist()
    build_occurrence(c, BBOX, "maxt", "ge", "first", (90,), y0=2019, data_dir=tmp_path, log=quiet)  # extends backwards
    with np.load(tmp_path / "occurrence" / "maxt_ge90_first.npz") as z:
        years = z["years"].tolist()
    assert years == sorted(set(years)) and set(first) <= set(years) and years[0] == 2019


def _pcpn_metric(reduce, normal=None):
    return Metric(name="t", kind="period", source="acis_grid1", element="pcpn", reduce=reduce, normal=normal).validate()


def test_normals_window_identity_no_wrap(tmp_path):
    """mean over years of each year's window-mean == window-mean of the daily normals (window inside one year)."""
    c, years = FakeClient(), range(2017, 2021)
    build_normals(c, BBOX, "pcpn", (2017, 2020), tmp_path, log=lambda *_: None)
    for how in ("mean", "sum"):
        per_year = [reduce_daily(c.daily("pcpn", BBOX, dt.date(y, 3, 1), dt.date(y, 5, 31))[2], how) for y in years]
        expected = np.mean(per_year, axis=0)
        got, _ = normal_window_average(_pcpn_metric(how, "average"), BBOX, (3, 1), (5, 31), (2017, 2020), tmp_path)
        np.testing.assert_allclose(got.data, expected, atol=0.02 * (90 if how == "sum" else 1))  # normals stored to 0.01


def test_normals_feb29_weighting(tmp_path):
    """A window spanning Feb 29 must equal the average of real yearly totals (leap day counts 1/4 over 2017-2020)."""
    c = FakeClient()
    build_normals(c, BBOX, "pcpn", (2017, 2020), tmp_path, log=lambda *_: None)
    per_year = [reduce_daily(c.daily("pcpn", BBOX, dt.date(y, 2, 25), dt.date(y, 3, 2))[2], "sum") for y in range(2017, 2021)]
    got, _ = normal_window_average(_pcpn_metric("sum", "average"), BBOX, (2, 25), (3, 2), (2017, 2020), tmp_path)
    np.testing.assert_allclose(got.data, np.mean(per_year, axis=0), atol=0.1)
    idx, w = monthday_window((2, 25), (3, 2), np.arange(2017, 2021))
    assert w.tolist().count(0.25) == 1


def test_departure_uses_normals_and_aligns_subregion(tmp_path):
    c = FakeClient()
    build_normals(c, BBOX, "maxt", (2017, 2020), tmp_path, log=lambda *_: None)
    m = Metric(name="d", kind="period", source="acis_grid1", element="maxt", reduce="mean", normal="departure").validate()
    g = period_summary(m, c, BBOX, dt.date(2020, 6, 1), dt.date(2020, 6, 30), (2017, 2020), tmp_path)
    actual = reduce_daily(c.daily("maxt", BBOX, dt.date(2020, 6, 1), dt.date(2020, 6, 30))[2], "mean")
    normals, _, _ = load_normals(tmp_path, "maxt", (2017, 2020))
    idx = [(dt.date(2000, 6, d) - dt.date(2000, 1, 1)).days for d in range(1, 31)]
    np.testing.assert_allclose(g.data, actual - normals[idx].mean(axis=0), atol=1e-4)


def test_max_min_not_supported_from_normals(tmp_path):
    build_normals(FakeClient(), BBOX, "pcpn", (2017, 2020), tmp_path, log=lambda *_: None)
    with pytest.raises(ValueError, match="only sum/mean"):
        normal_window_average(_pcpn_metric("max", "average"), BBOX, (3, 1), (3, 5), (2017, 2020), tmp_path)


def test_every_grid_menu_threshold_is_shipped():
    """The UI lets users type any whole degree in GRID_RANGES, so each one needs its pre-saved file (both directions)."""
    from pathlib import Path
    from gridded_climo.precomputed import DATA_DIR, occurrence_path
    from gridded_climo.query import MENU
    if not (Path(DATA_DIR) / "occurrence").exists():
        pytest.skip("no shipped data")
    missing = [(el, op, v, d) for (el, op), vals in MENU.items() for v in vals for d in ("first", "last")
               if not occurrence_path(DATA_DIR, el, op, v, d).exists()]
    assert not missing, f"{len(missing)} missing, e.g. {missing[:3]}"
