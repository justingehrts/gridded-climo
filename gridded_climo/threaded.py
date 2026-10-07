"""Threaded station records (e.g. CMHthr 'Columbus Area'): use them wherever they exist, placed at the site's main airport.

A threaded record stitches a city's successive stations into one continuous record (what NWS uses for official normals and records).
ACIS never lists them in area queries and gives them no coordinates, so threaded.json (built by threaded_build.py) says where each
sits and which station records it replaces. Replacement is by (id, lon, lat): ACIS ids alone are not unique."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

NO_CROSS, INVALID = -32767, -32768
SUFFIX = " (threaded)"


@lru_cache(maxsize=1)
def load_threaded() -> dict[str, dict]:
    """{'CMHthr 9': {'name': 'Columbus Area', 'airport': ..., 'lon': ..., 'lat': ..., 'replaces': [[sid, lon, lat], ...]}, ...}"""
    return json.loads(Path(__file__).with_name("threaded.json").read_text())


def threaded_in_bbox(bbox, mapping: dict | None = None) -> dict[str, dict]:
    """Threaded records whose airport lies inside `bbox` (west, south, east, north)."""
    w, s, e, n = bbox
    return {k: v for k, v in (mapping if mapping is not None else load_threaded()).items() if w <= v["lon"] <= e and s <= v["lat"] <= n}


def _key(sid, lon, lat) -> tuple:
    return (str(sid), round(float(lon), 3), round(float(lat), 3))


def is_threaded_sid(sid) -> bool:
    return str(sid).split(" ")[0].endswith("thr")


def apply_threaded(main: dict, thr: dict, entries: dict[str, dict]) -> dict:
    """Swap threaded columns in for the station records they replace.

    main / thr: season tables {sids, lon, lat, name, years, offsets} over the same years. A threaded record is used only if it has
    an answer for at least one season; otherwise its airport station stays. Threaded columns are named '<Area> (threaded)' and
    located at the main airport."""
    usable = {}
    for j, sid in enumerate(thr["sids"]):
        if sid in entries and (thr["offsets"][:, j] != INVALID).any():
            usable[sid] = j
    drop = {_key(*r) for sid in usable for r in entries[sid]["replaces"]}
    keep = [j for j in range(len(main["sids"])) if _key(main["sids"][j], main["lon"][j], main["lat"][j]) not in drop]
    add = list(usable.values())
    return {
        "sids": np.concatenate([main["sids"][keep], thr["sids"][add]]),
        "lon": np.concatenate([main["lon"][keep], [entries[thr["sids"][j]]["lon"] for j in add]]).astype("float32"),
        "lat": np.concatenate([main["lat"][keep], [entries[thr["sids"][j]]["lat"] for j in add]]).astype("float32"),
        "name": np.concatenate([main["name"][keep], [entries[thr["sids"][j]]["name"] + SUFFIX for j in add]]),
        "years": main["years"],
        "offsets": np.concatenate([main["offsets"][:, keep], thr["offsets"][:, add]], axis=1).astype("int16"),
    }


def strip_threaded(table: dict) -> dict:
    """Remove threaded columns (so a file can be re-threaded cleanly)."""
    keep = [j for j, s in enumerate(table["sids"]) if not is_threaded_sid(s)]
    out = dict(table)
    for k in ("sids", "lon", "lat", "name"):
        out[k] = table[k][keep]
    out["offsets"] = table["offsets"][:, keep]
    return out
