import json

import numpy as np
import pytest

from gridded_climo.grid import Grid
from gridded_climo.presets import list_presets, load_preset, preset_slug
from gridded_climo.registry import Style
from gridded_climo.render import PaletteError, RAMPS, style_from_json, style_to_json
from gridded_climo.render.style import resolve
from gridded_climo.ui.style_build import pending_from_json


def test_preset_slug_and_listing(tmp_path):
    assert preset_slug("On-air look #2") == "on-air-look-2" and preset_slug("  Weekly  Blues ") == "weekly-blues"
    with pytest.raises(ValueError):
        preset_slug("###")
    (tmp_path / "a.json").write_text(json.dumps({"name": "Alpha look", "ramp": "Blues"}))
    (tmp_path / "b-no-name.json").write_text(json.dumps({"ramp": "Magma"}))
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "list.json").write_text("[1, 2]")
    (tmp_path / "notes.txt").write_text("ignored")
    assert sorted(list_presets(tmp_path)) == ["Alpha look", "b no name"]               # broken / non-object files are skipped
    assert load_preset("Alpha look", tmp_path).ramp == "Blues"
    with pytest.raises(PaletteError, match="no preset"):
        load_preset("Missing", tmp_path)


def test_shipped_example_preset_loads():
    s = load_preset("Example: weekly bins, Spectral")
    assert (s.ramp, s.reverse, s.date_mode) == ("Spectral", True, "weekly")


def test_saved_file_roundtrips_and_name_is_a_label_only():
    s = Style(ramp="Blues", date_mode="thirds", bin_colors={"Early Oct (1–10)": [1, 2, 3, 255]})
    text = style_to_json(s, "My look")
    assert json.loads(text)["name"] == "My look" and style_from_json(text) == s


def test_pending_only_contains_fields_present_in_the_file():
    assert pending_from_json(json.dumps({"date_mode": "half"}), RAMPS) == {"style_date_mode": "half"}   # nothing else touched
    p = pending_from_json(json.dumps({"ramp": "Blues", "reverse": True, "mode": "smooth", "steps": 99, "vmin": 0, "vmax": 8,
                                      "date_mode": "custom", "custom_starts": "Oct 1, Nov 1", "palette": [[1, 2, 3, 255]]}), RAMPS)
    assert p == {"style_ramp": "Blues", "style_flip": True, "style_mode": "Smooth", "style_steps": 20, "style_vmin": 0.0,
                 "style_vmax": 8.0, "style_date_mode": "custom", "style_custom_starts": "Oct 1, Nov 1", "palette": [[1, 2, 3, 255]]}
    assert pending_from_json(json.dumps({"ramp": "NotARamp", "date_mode": "monthly", "mode": "weird"}), RAMPS) == {}   # junk ignored
    with pytest.raises(ValueError):
        pending_from_json("[1]", RAMPS)


def test_numeric_legend_rows_are_ignored_on_date_maps(tmp_path):
    data = np.tile(np.linspace(100, 130, 40, dtype="float32"), (8, 1))
    tif = Grid(data, -84.0, 41.0, 0.1, 0.1).to_geotiff(tmp_path / "t.tif")
    rows = [[0, 255, 0, 0, 255], [50, 0, 0, 255, 255]]                  # e.g. a degrees-F legend carried over by a preset
    assert resolve(Style(legend_rows=rows), tif, None).labels == ["0–50", "50+"]      # numeric map: honored
    on_date_map = resolve(Style(legend_rows=rows), tif, (7, 1))
    assert on_date_map.labels is None                                   # date map: falls back to the automatic look
