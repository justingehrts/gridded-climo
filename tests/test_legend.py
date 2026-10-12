"""Numeric custom legends as [from, to) color bands (render/legend.py) and how they resolve and render."""
import io
import math

import numpy as np
import pytest
from PIL import Image

from gridded_climo.grid import Grid
from gridded_climo.registry import Style
from gridded_climo.render import render_overlay
from gridded_climo.render.legend import legend_records, normalize_legend, rows_from_records, segments
from gridded_climo.render.style import resolve

RED, GREEN, BLUE = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
T = (0, 0, 0, 0)


def test_legacy_rows_become_bands():
    rows = [[5, 255, 0, 0, 255], [0, 255, 255, 255, 0], [1, 0, 0, 255]]     # the last row has only 4 values
    with pytest.raises(ValueError):
        normalize_legend(rows)
    got = normalize_legend([[5, 255, 0, 0, 255], [0, 255, 255, 255, 0], [1, 0, 0, 255, 255]])
    assert got == [[0.0, 1.0, 255, 255, 255, 0], [1.0, 5.0, 0, 0, 255, 255], [5.0, None, 255, 0, 0, 255]]


def test_blank_from_is_kept_only_on_the_lowest_row_with_a_to():
    ok = normalize_legend([[3, None, 0, 0, 255, 255], [None, 3, 255, 0, 0, 255]])
    assert ok[0][0] is None and ok[0][1] == 3.0
    assert len(normalize_legend([[None, None, 1, 2, 3, 255], [0, 1, 4, 5, 6, 255]])) == 1      # stray empty row dropped
    assert len(normalize_legend([[None, None, 1, 2, 3, 255]])) == 1                              # ...unless it is the only row
    assert normalize_legend([[0, 1, 300, -4, 3.6, None]])[0][2:] == [255, 0, 4, 255]             # clamped, rounded, alpha default


def test_segments_gaps_overlaps_and_open_ends():
    s = segments([[None, 1, *RED], [3, 4, *GREEN], [4, None, *BLUE]])
    assert [(x.lo, x.hi, x.color) for x in s] == [(-math.inf, 1, RED), (1, 3, None), (3, 4, GREEN), (4, math.inf, BLUE)]
    # overlap: the row with the larger From wins where they overlap
    o = segments([[0, 10, *RED], [4, 6, *GREEN]])
    assert [(x.lo, x.hi, x.color) for x in o] == [(0, 4, RED), (4, 6, GREEN), (6, 10, RED)]
    assert segments([]) == []


def test_records_roundtrip():
    rows = [[None, 0.3, *RED], [0.3, None, *GREEN]]
    assert rows_from_records(legend_records(rows)) == normalize_legend(rows)
    assert legend_records(rows)[0]["From"] is None
    assert rows_from_records([{"from": 0, "to": 1, "r": 1, "g": 2, "b": 3, "a": 4}]) == [[0.0, 1.0, 1, 2, 3, 4]]


def _tif(tmp_path, values):
    data = np.array([values], dtype="float32")
    return Grid(np.repeat(data, 4, axis=0), -84.0, 41.0, 0.1, 0.1).to_geotiff(tmp_path / "t.tif")


def _row(tmp_path, values, rows, **style):
    tif = _tif(tmp_path, values)
    ov = render_overlay(tif, Style(legend_rows=rows, mode="stepped", **style), "t", legend_title="x")
    png = np.array(Image.open(io.BytesIO(ov.png)).convert("RGBA"))
    assert png.shape[1] == len(values)
    return [tuple(int(v) for v in px) for px in png[1]], ov


VALS = [0.0, 0.5, 0.99, 1.0, 2.0, 2.99, 3.0, 4.0, 4.5, 7.0]


def test_render_open_bottom_gap_and_closed_top(tmp_path):
    # [-inf, 1) red | [1, 2) green | gap [2, 3) | [3, 4) blue | nothing from 4 up
    rows = [[None, 1, *RED], [1, 2, *GREEN], [3, 4, *BLUE]]
    got, ov = _row(tmp_path, VALS, rows)
    assert got == [RED, RED, RED, GREEN, T, T, BLUE, T, T, T]
    assert ov.res.labels == ["below 1", "1–2", "2–3", "3–4"] and ov.res.colors[2] == T
    assert ov.legend_png


def test_render_below_first_from_is_transparent_unless_open(tmp_path):
    closed, _ = _row(tmp_path, VALS, [[1, 3, *GREEN], [3, None, *BLUE]])
    assert closed == [T, T, T, GREEN, GREEN, GREEN, BLUE, BLUE, BLUE, BLUE]      # open top, closed bottom
    opened, _ = _row(tmp_path, VALS, [[None, 3, *GREEN], [3, None, *BLUE]])
    assert opened == [GREEN] * 6 + [BLUE] * 4                                    # open bottom colors everything below


def test_legacy_rows_render_as_before(tmp_path):
    got, ov = _row(tmp_path, VALS, [[0, 255, 255, 255, 0], [1, 0, 0, 255, 255], [3, 255, 0, 0, 255]])
    W0 = (255, 255, 255, 0)                              # the first row is a see-through white
    assert got == [W0, W0, W0, BLUE, BLUE, BLUE, RED, RED, RED, RED]
    assert ov.res.labels == ["0–1", "1–3", "3+"]


def test_resolve_smooth_uses_each_rows_lower_bound(tmp_path):
    tif = _tif(tmp_path, [0.0, 10.0])
    r = resolve(Style(legend_rows=[[None, 2, *RED], [2, None, *BLUE]], mode="smooth"), tif)
    assert r.smooth and [row[0] for row in r.table] == [0.0, 2.0]                # open bottom starts at the data minimum


def test_ramp_catalog_keeps_every_name_the_metrics_and_presets_use():
    import yaml
    from pathlib import Path
    import gridded_climo
    from gridded_climo.render import RAMP_CATEGORIES, RAMPS, ramp_label
    cfg = yaml.safe_load((Path(gridded_climo.__file__).parent / "metrics.yaml").read_text())
    used = {m["style"]["ramp"] for m in (cfg["metrics"] if isinstance(cfg, dict) and "metrics" in cfg else cfg.values()) if isinstance(m, dict) and "style" in m}
    assert used and used <= set(RAMPS)
    assert ramp_label("coolwarm") == "Cool-Warm" and ramp_label("viridis") == "Viridis" and ramp_label("Spectral") == "Spectral"
    labels = [lab for group in RAMP_CATEGORIES.values() for lab in group]
    assert len(labels) == len(set(labels)) == 17 and all(lab in RAMPS for lab in labels)


# --- .wctrp export -------------------------------------------------------------------------------------------------
from gridded_climo.render.palettes import parse_wctrp                     # noqa: E402
from gridded_climo.render.wctrp import UNIT_IDS, fmt, wctrp_bytes         # noqa: E402

MAX_SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<VQXML CN="classWxdContourPalette" VN="7.7.0720.0008"><contourSize>2</contourSize>\n'
    "<unitContextId>2</unitContextId>\n<unitSetId>Display</unitSetId>\n"
    '<contourElem0 CN="classWxdContourPaletteChild"><contourFrom>0.01</contourFrom>\n<contourTo>0.0958763</contourTo>\n'
    "<paletteEntryAlpha>0</paletteEntryAlpha>\n<paletteEntryBlue>20</paletteEntryBlue>\n<paletteEntryGreen>255</paletteEntryGreen>\n"
    "<paletteEntryRed>8</paletteEntryRed>\n"
    '<textureFile CN="classWxFileMediaRef"><m_name>Default</m_name>\n<m_relativePath>Default</m_relativePath>\n<mediaRoot>0</mediaRoot>\n'
    "<mediaType>0</mediaType>\n</textureFile>\n</contourElem0>\n"
    '<contourElem1 CN="classWxdContourPaletteChild"><contourFrom>0.0958763</contourFrom>\n<contourTo>999</contourTo>\n'
    "<paletteEntryAlpha>255</paletteEntryAlpha>\n<paletteEntryBlue>238</paletteEntryBlue>\n<paletteEntryGreen>104</paletteEntryGreen>\n"
    "<paletteEntryRed>2</paletteEntryRed>\n"
    '<textureFile CN="classWxFileMediaRef"><m_name>Default</m_name>\n<m_relativePath>Default</m_relativePath>\n<mediaRoot>0</mediaRoot>\n'
    "<mediaType>0</mediaType>\n</textureFile>\n</contourElem1>\n</VQXML>\n"
)


def test_wctrp_export_matches_the_layout_of_a_real_max_file():
    rows, _ = parse_wctrp(MAX_SAMPLE)
    assert rows[-1][1] is None                                   # 999 means no upper limit
    assert wctrp_bytes(rows, UNIT_IDS["Precipitation (inches)"]).decode() == MAX_SAMPLE


def test_wctrp_number_format_and_element_order():
    assert [fmt(v) for v in (20.0, -80.0, 0.0958763, 24.91414, 0.1 + 0.2, 1e-7, -0.0)] == ["20", "-80", "0.0958763", "24.91414", "0.3", "0.0000001", "0"]
    rows = [[float(i), float(i + 1), i, 0, 0, 255] for i in range(12)]
    tags = [t for t in __import__("re").findall(r"<contourElem(\d+) ", wctrp_bytes(rows).decode())]
    assert tags == sorted(tags) and tags[:4] == ["0", "1", "10", "11"]               # lexicographic, like MAX
    assert "<contourSize>12</contourSize>" in wctrp_bytes(rows).decode()


def test_wctrp_gaps_become_transparent_bands_and_open_ends_use_sentinels():
    out = wctrp_bytes([[None, 1, *RED], [3, 4, *GREEN], [4, None, *BLUE]], 11).decode()
    back, _ = parse_wctrp(out)
    assert back == [[None, 1.0, *RED], [1.0, 3.0, 0, 0, 0, 0], [3.0, 4.0, *GREEN], [4.0, None, *BLUE]]
    assert "<contourFrom>-999</contourFrom>" in out and "<contourTo>999</contourTo>" in out and "<unitContextId>11</unitContextId>" in out
    with pytest.raises(ValueError):
        wctrp_bytes([])


def test_wctrp_roundtrip_through_the_editor_rows():
    rows = [[0, 0.5, 1, 2, 3, 255], [0.5, 2, 4, 5, 6, 128], [2, None, 7, 8, 9, 0]]
    assert parse_wctrp(wctrp_bytes(rows))[0] == normalize_legend(rows)
