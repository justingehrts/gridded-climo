"""Defaults. Everything here is overridable per call / CLI flag / environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# (west, south, east, north) -- centered on Columbus, OH
DEFAULT_BBOX = (-87.5, 37.0, -78.5, 42.5)
DEFAULT_NORMAL_PERIOD = (1991, 2020)
ACIS_BASE_URL = "https://data.rcc-acis.org"
NOHRSC_BASE_URL = "https://www.nohrsc.noaa.gov/snowfall/data"


def default_cache_dir() -> Path:
    return Path(os.environ.get("GRIDDED_CLIMO_CACHE", Path.cwd() / ".cache" / "gridded_climo"))


@dataclass
class Settings:
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX
    normal_period: tuple[int, int] = DEFAULT_NORMAL_PERIOD
    cache_dir: Path = field(default_factory=default_cache_dir)
    acis_base_url: str = ACIS_BASE_URL
    nohrsc_base_url: str = NOHRSC_BASE_URL

    def __post_init__(self):
        w, s, e, n = self.bbox
        if not (w < e and s < n):
            raise ValueError(f"bbox must be (west, south, east, north) with west<east, south<north; got {self.bbox}")
        if self.normal_period[0] > self.normal_period[1]:
            raise ValueError(f"normal_period start must be <= end; got {self.normal_period}")
        self.cache_dir = Path(self.cache_dir)
