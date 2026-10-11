"""UI-facing orchestration: Query -> Computed (data, slow) -> Output (styled bytes, fast).

Splitting the two means restyling a map (ramp, date bins, colors) never re-fetches or re-computes the data."""
from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..grid import Grid
from ..precomputed import DATA_DIR
from ..query import Query, describe
from ..registry import Style
from ..render import overlay_to_kmz, render_overlay
from ..runner import run_query


@dataclass
class Computed:
    grid: Grid
    name: str
    style: Style                    # the metric's default style
    ref: tuple[int, int] | None     # (month, day) of offset 0 -> first/last-date map
    label_kind: str | None          # "date" | "inches" | None (how legend numbers are written)
    note: str
    points: dict | None
    filename: str


@dataclass
class Output:
    png: bytes
    legend_png: bytes | None
    bounds: tuple[float, float, float, float]  # south, west, north, east
    kmz: bytes
    name: str
    note: str
    filename: str
    points: dict | None = None
    bins: list | None = None        # [(label, (r, g, b, a)), ...] for discrete legends (feeds the color-table editor)
    data_min: float | None = None
    data_max: float | None = None
    seed_rows: list | None = None   # numeric maps: starting rows for the custom-legend editor


def label_formatter(kind: str | None, ref: tuple[int, int] | None):
    if kind == "date" and ref:
        base = dt.date(2001, *ref)
        return lambda v: (base + dt.timedelta(days=int(round(v)))).strftime("%b %-d")
    if kind == "inches":
        return lambda v: f'{v:g}"'
    return None


def compute(q: Query, bbox, cache_dir: str | Path, data_dir=DATA_DIR, allow_live: bool = True, log=print) -> Computed:
    st = Settings(bbox=tuple(bbox), normal_period=q.normal_period, cache_dir=Path(cache_dir))
    res = run_query(q, st, data_dir, allow_live, log)
    points = None
    if res.points is not None:
        fmt = label_formatter("date" if res.ref else "inches", res.ref) or (lambda v: f"{v:g}")
        points = {"lon": res.points["lon"].tolist(), "lat": res.points["lat"].tolist(),
                  "label": [fmt(v) for v in res.points["value"]], "name": [str(n) for n in res.points["name"]]}
    kind = "date" if res.ref else ("inches" if res.style.units_label == "in" else None)
    safe = "".join(c if c.isalnum() else "_" for c in describe(q)).strip("_").lower()
    return Computed(res.grid, res.name, res.style, res.ref, kind, res.note, points, f"{safe}.kmz")


def render_computed(c: Computed, style: Style | None = None) -> Output:
    style = style or c.style
    if not style.units_label:
        style = Style(**{**style.__dict__, "units_label": c.style.units_label})
    with tempfile.TemporaryDirectory(prefix="gridded_climo_ui_") as td:
        tif = c.grid.to_geotiff(Path(td) / "data.tif")
        ov = render_overlay(tif, style, c.name, legend_title=c.name if style.units_label else None,
                            label_fmt=label_formatter(c.label_kind, c.ref), ref=c.ref)
        kmz = overlay_to_kmz(ov, Path(td) / "out.kmz").read_bytes()
    r = ov.res
    bins = list(zip(r.labels, r.colors)) if r is not None and r.labels else None
    return Output(ov.png, ov.legend_png, (ov.south, ov.west, ov.north, ov.east), kmz, c.name, c.note, c.filename, c.points,
                  bins, None, None, getattr(r, "seed_rows", None))


def generate(q: Query, bbox, cache_dir, data_dir=DATA_DIR, allow_live: bool = True, log=print, style: Style | None = None) -> Output:
    return render_computed(compute(q, bbox, cache_dir, data_dir, allow_live, log), style)
