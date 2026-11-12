import numpy as np

from gridded_climo.grid import Grid
from gridded_climo.landmask import mask_grid, water_at
from gridded_climo.registry import Style
from gridded_climo.render import style_from_json, style_to_json


def test_known_points_water_and_land():
    pts = {"erie": (41.7, -81.7, True), "michigan": (43.5, -87.0, True), "superior": (47.5, -87.5, True),
           "atlantic": (35.2, -74.5, True), "gulf": (28.5, -94.5, True), "pacific": (40, -126, True),
           "columbus": (39.96, -83.0, False), "cleveland": (41.4, -81.7, False), "okeechobee": (26.95, -80.8, False)}
    for k, (la, lo, exp) in pts.items():
        assert bool(water_at(np.array(la), np.array(lo))) is exp, k
    assert not water_at(np.array(60.0), np.array(-100.0))          # outside the shipped extent: not masked


def test_mask_grid_blanks_lake_erie_only():
    g = Grid(np.ones((100, 100), "float32"), -83.5, 42.5, 0.03, 0.03)       # spans Toledo..Cleveland and Lake Erie
    m = mask_grid(g)
    assert np.isnan(m.data).any() and np.isfinite(m.data).any()
    assert np.isfinite(m.data[-1, 0])                                         # SW corner (inland Ohio) kept


def test_refined_is_finer_keeps_extent_and_voids():
    d = np.array([[0, 10, np.nan], [0, 10, np.nan]], "float32")
    r = Grid(d, -83.0, 40.0, 0.1, 0.1).refined()
    assert r.data.shape == (8, 12) and r.dx == 0.025 and r.west == -83.0 and r.north == 40.0
    assert np.isnan(r.data[:, -4:]).all() and np.nanmin(r.data) >= 0 and np.nanmax(r.data) <= 10
    assert (np.diff(r.data[0, :8]) >= -1e-6).all()                            # ramps smoothly 0 -> 10
    big = Grid(np.zeros((2000, 2000), "float32"), 0, 0, 0.01, 0.01)
    assert big.refined(max_pixels=3_000_000) is big                           # too big to refine


def test_style_fields_round_trip():
    st = Style(smooth_edges=False, mask_water=False)
    back = style_from_json(style_to_json(st))
    assert back.smooth_edges is False and back.mask_water is False
    assert Style().smooth_edges is True and Style().mask_water is True
