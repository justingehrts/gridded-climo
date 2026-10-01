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
