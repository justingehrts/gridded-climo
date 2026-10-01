"""Metric registry: each product is a config entry, not a script."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KINDS = {"climatology", "period", "storm"}
ELEMENTS = {"mint", "maxt", "pcpn", "snow", "snwd"}
OPS = {"le", "lt", "ge", "gt"}
DIRECTIONS = {"first", "last"}
STATS = {"mean", "median", "percentile", "min", "max"}  # min/max = earliest/latest date on record
PERIOD_REDUCES = {"sum", "mean", "max", "min"}
SOURCES = {"acis_grid1", "acis_stn", "nohrsc"}


class RegistryError(ValueError):
    pass


@dataclass
class Style:
    ramp: str = "Viridis"
    reverse: bool = False
    mode: str = "stepped"  # stepped | smooth
    steps: int = 10
    vmin: float | None = None
    vmax: float | None = None
    hide_below: float | None = None  # values below this render fully transparent
    symmetric: bool = False  # diverging data: range is +/- max(|p2|, |p98|) around 0
    units_label: str = ""


@dataclass
class Metric:
    name: str
    kind: str
    source: str
    element: str | None = None
    title: str = ""
    # climatology
    threshold: dict[str, Any] | None = None  # {op, value}
    direction: str | None = None
    season: dict[str, list[int]] | None = None  # {start:[m,d], end:[m,d]}
    cross_year: dict[str, Any] = field(default_factory=lambda: {"stat": "mean"})
    min_years_frac: float = 0.5
    # period
    reduce: str | None = None
    normal: str | None = None  # None | "departure"
    style: Style = field(default_factory=Style)

    def validate(self) -> "Metric":
        def bad(msg):
            raise RegistryError(f"metric '{self.name}': {msg}")

        if self.kind not in KINDS:
            bad(f"kind must be one of {sorted(KINDS)}")
        if self.source not in SOURCES:
            bad(f"source must be one of {sorted(SOURCES)}")
        if self.kind in ("climatology", "period") and self.element not in ELEMENTS:
            bad(f"element must be one of {sorted(ELEMENTS)}")
        if self.kind == "climatology":
            if not self.threshold or self.threshold.get("op") not in OPS or "value" not in self.threshold:
                bad("threshold needs {op: le|lt|ge|gt, value: <number>}")
            if self.direction not in DIRECTIONS:
                bad("direction must be first|last")
            if not self.season or set(self.season) != {"start", "end"}:
                bad("season needs {start: [m, d], end: [m, d]}")
            if self.cross_year.get("stat") not in STATS:
                bad(f"cross_year.stat must be one of {sorted(STATS)}")
            if self.cross_year["stat"] == "percentile" and not 0 <= self.cross_year.get("p", -1) <= 100:
                bad("cross_year.p (0-100) required for percentile")
        if self.kind == "period":
            if self.reduce not in PERIOD_REDUCES:
                bad(f"reduce must be one of {sorted(PERIOD_REDUCES)}")
            if self.normal not in (None, "departure", "average"):
                bad("normal must be null, 'departure' (specific dates minus normal) or 'average' (same month/days averaged over the normal period)")
        if self.style.mode not in ("stepped", "smooth"):
            bad("style.mode must be stepped|smooth")
        return self


def _build(name: str, raw: dict[str, Any]) -> Metric:
    raw = dict(raw)
    style = Style(**raw.pop("style", {}))
    try:
        return Metric(name=name, style=style, **raw).validate()
    except TypeError as e:
        raise RegistryError(f"metric '{name}': {e}") from None


def load_registry(path: str | Path | None = None) -> dict[str, Metric]:
    path = Path(path) if path else Path(__file__).with_name("metrics.yaml")
    data = yaml.safe_load(path.read_text()) or {}
    return {name: _build(name, raw) for name, raw in data.items()}
