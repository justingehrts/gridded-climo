import numpy as np
import pytest

from gridded_climo import stations
from gridded_climo.threaded import SUFFIX, apply_threaded, is_threaded_sid, load_threaded, strip_threaded, threaded_in_bbox

pytestmark = pytest.mark.threaded
INV = -32768


def table(sids, offs, lon=None, lat=None):
    n = len(sids)
    return {"sids": np.array(sids), "lon": np.array(lon or [-83.0] * n, "float32"), "lat": np.array(lat or [40.0] * n, "float32"),
            "name": np.array([f"n{s}" for s in sids]), "years": np.array([2000, 2001], "int16"), "offsets": np.array(offs, "int16")}


ENT = {"CMHthr 9": {"name": "Columbus Area", "lon": -82.88, "lat": 39.99, "replaces": [["14821 1", -82.88, 39.99]]}}


def test_mapping_sane():
    m = load_threaded()
    assert len(m) > 300 and all(is_threaded_sid(k) for k in m)
    ohio = threaded_in_bbox((-87.5, 37.0, -78.5, 42.5))
    assert "CMHthr 9" in ohio and len(ohio) >= 30
    assert all(len(v["replaces"]) >= 1 for v in ohio.values())


def test_apply_replaces_airport_and_relocates():
    main = table(["14821 1", "other 1"], [[10, 20], [11, 21]], lon=[-82.88, -83.5], lat=[39.99, 40.2])
    thr = table(["CMHthr 9"], [[5], [6]], lon=[0], lat=[0])
    out = apply_threaded(main, thr, ENT)
    assert list(out["sids"]) == ["other 1", "CMHthr 9"]
    assert out["offsets"][:, 1].tolist() == [5, 6]
    assert out["name"][1] == "Columbus Area" + SUFFIX
    assert (round(float(out["lon"][1]), 2), round(float(out["lat"][1]), 2)) == (-82.88, 39.99)


def test_apply_keeps_airport_when_threaded_empty():
    main = table(["14821 1"], [[10], [11]], lon=[-82.88], lat=[39.99])
    thr = table(["CMHthr 9"], [[INV], [INV]])
    out = apply_threaded(main, thr, ENT)
    assert list(out["sids"]) == ["14821 1"]


def test_same_sid_other_location_not_replaced():
    main = table(["14821 1", "14821 1"], [[1, 2], [3, 4]], lon=[-82.88, -85.0], lat=[39.99, 41.0])
    out = apply_threaded(main, table(["CMHthr 9"], [[5], [6]]), ENT)
    assert len(out["sids"]) == 2 and (np.round(out["lon"], 2) == -85.0).any()


def test_strip_roundtrip():
    main = table(["a 1"], [[1], [2]])
    out = apply_threaded(main, table(["CMHthr 9"], [[5], [6]]), {"CMHthr 9": {**ENT["CMHthr 9"], "replaces": []}})
    assert list(strip_threaded(out)["sids"]) == ["a 1"]


class TwoCalls:
    def __init__(self): self.reqs = []
    def post(self, endpoint, req):
        self.reqs.append(req)
        if "sids" in req:
            return {"data": [{"meta": {"sids": ["CMHthr 9"], "name": "Columbus Area"}, "data": [[["2000-10-25", 1, 0]], [["2001-10-20", 1, 0]]][:2]}]}
        return {"data": [{"meta": {"sids": ["14821 1"], "ll": [-82.877, 39.991], "name": "COLUMBUS AP"}, "data": [[["2000-10-26", 1, 0]], [["2001-10-21", 1, 0]]]}]}


def test_fetch_makes_threaded_request_and_swaps():
    season = {"start": [7, 1], "end": [6, 30]}
    c = TwoCalls()
    z = stations.fetch_station_thresholds(c, (-83.5, 39.5, -82.0, 40.5), "mint", "le", 32, "first", season, 2000, 2001, use_threaded=True)
    assert len(c.reqs) == 2 and "bbox" not in c.reqs[1] and "CMHthr 9" in c.reqs[1]["sids"]
    assert list(z["sids"]) == ["CMHthr 9"]


def test_shipped_files_are_threaded():
    z = np.load("data/stations/mint_le32_first.npz", allow_pickle=False)
    sids = [str(s) for s in z["sids"]]
    assert "CMHthr 9" in sids and "14821 1" not in sids
