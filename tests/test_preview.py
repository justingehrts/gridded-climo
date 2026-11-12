from gridded_climo.ui.preview import build_map

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def test_dots_are_clickable_and_above_the_reference_layers():
    pts = {"lon": [-83.0], "lat": [40.0], "label": ['6.2"'], "name": ["Columbus <A&B>"]}
    html = build_map(PNG, (39.0, -84.0, 41.0, -82.0), counties={"type": "FeatureCollection", "features": []}, points=pts).get_root().render()
    assert "obs_pane" in html and '6.2&quot;' in html or "6.2" in html
    assert "Columbus &lt;A&amp;B&gt;" in html            # popup text is escaped
    assert "bindPopup" in html and "bindTooltip" in html
    assert '"interactive": false' in html                   # county outlines do not capture clicks


def test_no_points_still_builds():
    assert "obs_pane" in build_map(PNG, (39.0, -84.0, 41.0, -82.0)).get_root().render()
