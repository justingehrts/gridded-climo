"""UI-facing orchestration: Query -> bytes (overlay PNG, legend, KMZ). Plain, picklable output so Streamlit can cache it."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..precomputed import DATA_DIR
from ..query import Query, describe
from ..render import overlay_to_kmz, render_overlay
from ..runner import run_query


@dataclass
class Output:
    png: bytes
    legend_png: bytes | None
    bounds: tuple[float, float, float, float]  # south, west, north, east
    kmz: bytes
    name: str
    note: str
    filename: str


def generate(q: Query, bbox: tuple[float, float, float, float], cache_dir: str | Path, data_dir=DATA_DIR,
             allow_live: bool = True, log=print) -> Output:
    st = Settings(bbox=bbox, normal_period=q.normal_period, cache_dir=Path(cache_dir))
    res = run_query(q, st, data_dir, allow_live, log)
    with tempfile.TemporaryDirectory(prefix="gridded_climo_ui_") as td:
        tif = res.grid.to_geotiff(Path(td) / "data.tif")
        ov = render_overlay(tif, res.style, res.name, legend_title=res.name if res.style.units_label else None,
                            label_fmt=res.label_fmt)
        kmz_path = overlay_to_kmz(ov, Path(td) / "out.kmz")
        kmz = kmz_path.read_bytes()
    safe = "".join(c if c.isalnum() else "_" for c in describe(q)).strip("_").lower()
    return Output(ov.png, ov.legend_png, (ov.south, ov.west, ov.north, ov.east), kmz, res.name, res.note, f"{safe}.kmz")
