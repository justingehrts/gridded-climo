"""Pure helper (no Streamlit): the user's style choices applied on top of a map's default Style."""
from __future__ import annotations

from dataclasses import replace

from ..binning import MODES
from ..registry import Style


def build_style(base: Style, *, ramp: str | None = None, flip: bool = False, mode: str | None = None, steps: int | None = None,
                vmin: float | None = None, vmax: float | None = None, date_mode: str = "auto", custom_starts: str = "",
                palette: list | None = None, bin_colors: dict | None = None, legend_rows: list | None = None) -> Style:
    """`ramp=None` / `mode=None` keep the map's default. `flip` reverses the default ramp's direction; with an explicitly
    chosen ramp it simply means 'reversed' (the default's direction belongs to the default ramp)."""
    if date_mode not in MODES:
        raise ValueError(f"unknown date grouping '{date_mode}'")
    return replace(
        base,
        ramp=ramp or base.ramp,
        reverse=flip if ramp else ((not base.reverse) if flip else base.reverse),
        mode=mode or base.mode,
        steps=int(steps) if steps else base.steps,
        vmin=vmin if vmin is not None else base.vmin,
        vmax=vmax if vmax is not None else base.vmax,
        date_mode=date_mode, custom_starts=custom_starts,
        palette=palette or None, bin_colors=bin_colors or None, legend_rows=legend_rows or None,
    )


def pending_from_json(raw: str | bytes, known_ramps) -> dict:
    """Settings/preset JSON -> {session_state key: value}, containing ONLY the fields present in the file (so a preset that
    omits e.g. `steps` leaves the map's own default alone)."""
    import json
    d = json.loads(raw)
    if not isinstance(d, dict):
        raise ValueError("settings JSON must be an object")
    out: dict = {}
    if d.get("ramp") in known_ramps:
        out["style_ramp"] = d["ramp"]
        out["style_flip"] = bool(d.get("reverse", False))       # with an explicit ramp, 'reverse' is absolute
    if d.get("mode") in ("stepped", "smooth"):
        out["style_mode"] = d["mode"].title()
    if isinstance(d.get("steps"), int):
        out["style_steps"] = max(3, min(20, d["steps"]))
    for k in ("vmin", "vmax"):
        if isinstance(d.get(k), (int, float)):
            out[f"style_{k}"] = float(d[k])
    if d.get("date_mode") in MODES:
        out["style_date_mode"] = d["date_mode"]
    if d.get("custom_starts"):
        out["style_custom_starts"] = d["custom_starts"]
    for k in ("palette", "bin_colors", "legend_rows"):
        if d.get(k):
            out[k] = d[k]
    return out
