import numpy as np
import pytest

from gridded_climo.config import DEFAULT_BBOX
from gridded_climo.interpolate import adaptive_cell_deg, adaptive_max_km
from gridded_climo.regions import (BUFFER_MAX, BUFFER_MIN, CONUS_BOUNDS, buffer_deg, buffered_bbox, coverage_fraction, intersection,
                                   max_live_days, presaved_bbox, state_names, states)


def test_state_file_is_complete_and_sane():
    s = states()
    assert len(s) == 49 and {"OH", "TX", "DC", "CA", "ME"} <= set(s)
    assert "AK" not in s and "HI" not in s                                   # data extent is the lower 48
    cw, cs, ce, cn = CONUS_BOUNDS
    for code, v in s.items():
        w, so, e, n = v["bbox"]
        assert w < e and so < n and cw < w and e < ce and cs < so and n < cn, code
        assert len(code) == 2 and v["name"]
    assert s["OH"]["bbox"] == [-84.8207, 38.4036, -80.5207, 41.9774]          # as reported by ACIS
    assert list(state_names())[:3] == ["Alabama", "Arizona", "Arkansas"] and state_names()["Ohio"] == "OH"


def test_buffer_rule_and_clamping():
    assert buffer_deg((-84.8, 38.4, -80.5, 42.0)) == pytest.approx(0.75)          # Ohio: 10% of 4.3 deg < minimum
    assert buffer_deg((-106.6, 25.8, -93.5, 36.5)) == pytest.approx(1.31, abs=0.01)   # Texas: 10% of the long side
    assert buffer_deg((0, 0, 40, 10)) == BUFFER_MAX and buffer_deg((0, 0, 0.2, 0.2)) == BUFFER_MIN
    for code in states():
        b = buffered_bbox(code)
        w, s, e, n = states()[code]["bbox"]
        cw, cs, ce, cn = CONUS_BOUNDS
        assert cw <= b[0] <= w and b[2] >= e and cs <= b[1] <= s and b[3] >= n, code     # contains the state, stays in the data extent
        assert b[2] <= ce and b[3] <= cn
    assert buffered_bbox("OH") == (-85.571, 37.654, -79.771, 42.727)
    with pytest.raises(KeyError):
        buffered_bbox("ZZ")


def test_presaved_coverage_rules():
    assert presaved_bbox(DEFAULT_BBOX) == DEFAULT_BBOX
    oh = buffered_bbox("OH")
    assert coverage_fraction(oh) == pytest.approx(0.96, abs=0.01)
    cropped = presaved_bbox(oh)
    assert cropped is not None and cropped[3] == DEFAULT_BBOX[3] and cropped[0] == oh[0]     # only the northern sliver is cropped
    assert presaved_bbox(buffered_bbox("IN")) is None and presaved_bbox(buffered_bbox("TX")) is None   # 72% / 0%
    assert intersection((0, 0, 1, 1), (2, 2, 3, 3)) is None and coverage_fraction((0, 0, 1, 1), (2, 2, 3, 3)) == 0


def test_live_pull_budget_scales_with_area():
    assert max_live_days(DEFAULT_BBOX) >= 366                                 # a full year over the default region still works
    assert max_live_days(buffered_bbox("TX")) < 150 < max_live_days(buffered_bbox("OH"))
    assert max_live_days(buffered_bbox("RI")) > 3000


def test_interpolation_settings_adapt_to_area_and_station_density():
    assert adaptive_cell_deg(buffered_bbox("OH")) == 0.02                      # unchanged for Ohio
    assert 0.02 < adaptive_cell_deg(buffered_bbox("TX")) < 0.03                # big state: slightly coarser, bounded cell count
    lon, lat = np.meshgrid(np.arange(-84, -80, 0.1), np.arange(39, 42, 0.1))
    assert adaptive_max_km(lon.ravel(), lat.ravel()) == 80                     # dense network: default reach
    lon, lat = np.meshgrid(np.arange(-110, -100, 1.5), np.arange(36, 42, 1.5))
    assert 120 < adaptive_max_km(lon.ravel(), lat.ravel()) <= 200              # sparse network: reaches farther, capped
    assert adaptive_max_km([-83, -82], [40, 40]) == 80                         # too few stations to judge
