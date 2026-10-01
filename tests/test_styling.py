import datetime as dt
import json

import numpy as np
import pytest

from gridded_climo.binning import calendar_bins, custom_bins, month_bin_starts, parse_custom_starts, parse_month_day
from gridded_climo.grid import Grid
from gridded_climo.registry import Style
from gridded_climo.render import PaletteError, parse_legend_csv, parse_wctrp, style_from_json, style_to_json
from gridded_climo.render.palettes import sample_colors
from gridded_climo.render.style import resolve
from gridded_climo.ui.style_build import build_style


def off(m, d, ref=(7, 1)):  # day offset of a month/day from the reference season start (non-leap 2001/2002)
    y = 2001 if (m, d) >= ref else 2002
    return (dt.date(y, m, d) - dt.date(2001, *ref)).days


def bin_of(bins, m, d):
    v = off(m, d)
    return next(i for i in range(len(bins)) if bins.edges[i] <= v < bins.edges[i + 1])


def test_month_bin_starts_match_the_spec():
    assert month_bin_starts("weekly", 31) == [1, 7, 14, 21]                        # 1-6, 7-13, 14-20, 21-end
    assert month_bin_starts("thirds", 30) == [1, 11, 21] and month_bin_starts("thirds", 31) == [1, 11, 21]
    assert month_bin_starts("thirds", 28) == [1, 10, 19]                            # Feb: 1-9, 10-18, 19-28
    assert month_bin_starts("half", 30) == [1, 16] and month_bin_starts("half", 28) == [1, 15]
    with pytest.raises(ValueError):
        month_bin_starts("auto", 30)


@pytest.mark.parametrize("mode,expected", [
    ("weekly", ["Oct 1–6", "Oct 7–13", "Oct 14–20", "Oct 21–31"]),
    ("thirds", ["Early Oct (1–10)", "Mid Oct (11–20)", "Late Oct (21–31)"]),
    ("half", ["1st half Oct (1–15)", "2nd half Oct (16–31)"]),
])
def test_calendar_bins_labels_for_one_month(mode, expected):
    b = calendar_bins(mode, off(10, 3), off(10, 28), 7, 1)
    assert b.labels == expected and len(b.edges) == len(b.labels) + 1


def test_every_day_lands_in_exactly_one_bin_and_the_right_one():
    b = calendar_bins("weekly", off(9, 20), off(11, 9), 7, 1)                     # spans three months
    assert b.labels[0] == "Sep 14–20" and b.labels[-1] == "Nov 7–13"
    assert all(b.edges[i] < b.edges[i + 1] for i in range(len(b)))
    assert b.labels[bin_of(b, 10, 6)] == "Oct 1–6" and b.labels[bin_of(b, 10, 7)] == "Oct 7–13"
    assert b.labels[bin_of(b, 10, 31)] == "Oct 21–31" and b.labels[bin_of(b, 11, 1)] == "Nov 1–6"
    for d in range(off(9, 20), off(11, 9) + 1):                                   # no gaps, no overlaps
        assert sum(b.edges[i] <= d < b.edges[i + 1] for i in range(len(b))) == 1


def test_bins_cross_the_new_year_and_february():
    b = calendar_bins("thirds", off(12, 15), off(2, 20), 7, 1)
    assert b.labels == ["Mid Dec (11–20)", "Late Dec (21–31)", "Early Jan (1–10)", "Mid Jan (11–20)", "Late Jan (21–31)",
                        "Early Feb (1–9)", "Mid Feb (10–18)", "Late Feb (19–28)"]       # Feb 20 falls in Late Feb; Feb has 28 days
    assert b.labels[bin_of(b, 2, 20)] == "Late Feb (19–28)" and b.labels[bin_of(b, 12, 31)] == "Late Dec (21–31)"


def test_parse_month_day_formats_and_errors():
    assert parse_month_day("Sept 5") == parse_month_day("September 5") == (9, 5)
    assert parse_month_day("Oct 8") == parse_month_day("october 8") == parse_month_day("10/8") == parse_month_day("10-08") == (10, 8)
    for bad in ("Octo", "Octember 3", "13/1", "Feb 30", "soon", ""):
        with pytest.raises(ValueError):
            parse_month_day(bad)
    assert parse_custom_starts("Oct 1, Oct 8;\nNov 1") == [(10, 1), (10, 8), (11, 1)]


def test_custom_bins_edges_labels_and_validation():
    b = custom_bins(parse_custom_starts("Oct 8, Oct 15, Nov 1"), off(9, 20), off(11, 20), 7, 1)
    assert b.labels == ["Before Oct 8", "Oct 8–14", "Oct 15–31", "Nov 1 and later"]
    assert [bin_of(b, *md) for md in [(9, 25), (10, 8), (10, 14), (10, 15), (10, 31), (11, 1), (11, 20)]] == [0, 1, 1, 2, 2, 3, 3]
    inside = custom_bins([(10, 1), (11, 1)], off(10, 5), off(10, 20), 7, 1)       # data entirely inside the first bin
    assert len(inside) == 2 and inside.labels[0] == "Oct 1–31"
    with pytest.raises(ValueError, match="season order"):
        custom_bins([(10, 8), (10, 1)], 0, 100, 7, 1)
    with pytest.raises(ValueError, match="at least one"):
        custom_bins([], 0, 100, 7, 1)
    wrap = custom_bins([(12, 1), (1, 1), (2, 1)], off(12, 5), off(2, 10), 7, 1)    # a Jul-Jun season wraps the new year
    assert wrap.labels[:2] == ["Dec 1–31", "Jan 1–31"]


WCTRP = """<?xml version="1.0"?><palette>
 <contourElem10><contourFrom>10</contourFrom><paletteEntryRed>255</paletteEntryRed><paletteEntryGreen>0</paletteEntryGreen><paletteEntryBlue>0</paletteEntryBlue><paletteEntryAlpha>255</paletteEntryAlpha></contourElem10>
 <contourElem2><contourFrom>2</contourFrom><paletteEntryRed>0</paletteEntryRed><paletteEntryGreen>0</paletteEntryGreen><paletteEntryBlue>255</paletteEntryBlue><paletteEntryAlpha>200</paletteEntryAlpha><textureFile><m_name>Hatch</m_name></textureFile></contourElem2>
 <other/></palette>"""


def test_wctrp_sorted_numerically_not_lexicographically():
    rows, textured = parse_wctrp(WCTRP)
    assert rows == [[2.0, 0, 0, 255, 200], [10.0, 255, 0, 0, 255]] and textured == 1
    with pytest.raises(PaletteError, match="no contour"):
        parse_wctrp("<palette/>")
    with pytest.raises(PaletteError, match="XML"):
        parse_wctrp("not xml")


def test_csv_import_and_validation():
    assert parse_legend_csv("value,R,g,B\n5,1,2,3\n1,4,5,6") == [[1.0, 4, 5, 6, 255], [5.0, 1, 2, 3, 255]]
    assert parse_legend_csv(b"\xef\xbb\xbfValue,R,G,B,Alpha\n0,0,0,0,0\n")[0][4] == 0          # BOM + alpha
    for bad in ("a,b\n1,2", "Value,R,G,B\n1,300,0,0", "Value,R,G,B\nx,1,2,3", "Value,R,G,B\n"):
        with pytest.raises(PaletteError):
            parse_legend_csv(bad)


def test_palette_sampling_is_by_position_without_blending():
    rows = [[0, 255, 0, 0, 255], [0, 0, 255, 0, 255], [0, 0, 0, 255, 255]]
    assert sample_colors(rows, 3) == [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]]
    assert sample_colors(rows, 6) == [[255, 0, 0, 255]] * 2 + [[0, 255, 0, 255]] * 2 + [[0, 0, 255, 255]] * 2
    assert sample_colors(rows[:1], 4) == [[255, 0, 0, 255]] * 4


def test_style_json_roundtrip_and_unknown_keys():
    s = Style(ramp="Blues", date_mode="custom", custom_starts="Oct 1, Nov 1", bin_colors={"Oct 1–6": [1, 2, 3, 255]}, palette=[[1, 2, 3, 255]])
    assert style_from_json(style_to_json(s)) == s
    assert style_from_json(json.dumps({"ramp": "Viridis", "bogus": 1})).ramp == "Viridis"
    with pytest.raises(PaletteError):
        style_from_json("[1]")


def test_build_style_semantics():
    base = Style(ramp="RdYlBu", reverse=True, mode="stepped", steps=12)
    assert build_style(base) == base
    assert build_style(base, flip=True).reverse is False                      # flips the default's direction
    c = build_style(base, ramp="Blues", flip=True)
    assert (c.ramp, c.reverse) == ("Blues", True)                             # explicit ramp: flip = reversed
    assert build_style(base, ramp="Blues").reverse is False
    assert build_style(base, steps=7, vmin=1.0, vmax=9.0, date_mode="weekly").steps == 7
    with pytest.raises(ValueError):
        build_style(base, date_mode="monthly")


def _tif(tmp_path, lo=100.0, hi=130.0, ref=None):
    data = np.tile(np.linspace(lo, hi, 40, dtype="float32"), (8, 1)); data[0, 0] = np.nan
    return Grid(data, -84.0, 41.0, 0.1, 0.1).to_geotiff(tmp_path / "t.tif")


def test_resolve_date_bins_vs_automatic(tmp_path):
    tif = _tif(tmp_path, off(10, 3), off(10, 28))
    auto = resolve(Style(), tif, (7, 1))
    assert auto.edges is None and len(auto.table) > 2
    wk = resolve(Style(date_mode="weekly"), tif, (7, 1))
    assert wk.labels == ["Oct 1–6", "Oct 7–13", "Oct 14–20", "Oct 21–31"] and len(wk.colors) == 4
    assert resolve(Style(date_mode="weekly"), tif, None).edges is None        # not a date map -> grouping ignored
    # per-bin override by label, and palette by position
    ov = resolve(Style(date_mode="weekly", bin_colors={"Oct 7–13": [9, 9, 9, 255]}), tif, (7, 1))
    assert ov.colors[1] == (9, 9, 9, 255) and ov.colors[0] != (9, 9, 9, 255)
    pal = resolve(Style(date_mode="thirds", palette=[[255, 0, 0, 255], [0, 0, 255, 255]]), tif, (7, 1))
    assert pal.colors[0] == (255, 0, 0, 255) and pal.colors[-1] == (0, 0, 255, 255)
    # overrides survive a regrouping only where the label still exists
    assert resolve(Style(date_mode="half", bin_colors={"Oct 7–13": [9, 9, 9, 255]}), tif, (7, 1)).colors[0] != (9, 9, 9, 255)


def test_resolve_numeric_custom_legend(tmp_path):
    tif = _tif(tmp_path, 0.0, 12.0)
    rows = [[0, 255, 255, 255, 0], [1, 0, 0, 255, 255], [5, 255, 0, 0, 255]]
    r = resolve(Style(legend_rows=rows), tif)
    assert r.labels == ["0–1", "1–5", "5+"] and r.colors[0][3] == 0 and r.edges[-1] > 12
    assert r.table[0][3] == 0 and not r.smooth                                  # below the first row: transparent
    assert resolve(Style(legend_rows=rows, mode="smooth"), tif).smooth
    with pytest.raises(ValueError, match="at least two"):
        resolve(Style(legend_rows=[[0, 1, 2, 3, 255]]), tif)
    seed = resolve(Style(steps=4), tif).seed_rows
    assert len(seed) == 4 and all(len(row) == 5 for row in seed) and seed[0][0] < seed[-1][0]
