"""Period of record: when stations in an area began reporting a variable (ACIS valid_daterange), and the 'POR' start-year shortcut."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

POR_WORDS = {"por", "p.o.r.", "p.o.r", "period of record", "periodofrecord"}
MIN_YEAR, MAX_YEAR = 1800, 2100


class PorError(ValueError):
    pass


@dataclass
class Por:
    first_year: int
    start_years: list[int]      # sorted record-start year of every station in the area that reports the variable

    def stations_by(self, year: int) -> int:
        """How many stations' records began on or before `year`."""
        return int(np.searchsorted(self.start_years, year, side="right"))

    def describe(self, element_label: str) -> str:
        n_first = self.stations_by(self.first_year)
        pts = [f"{self.stations_by(y)} by {y}" for y in (1900, 1950) if y > self.first_year]
        return (f"Period of record for {element_label} here starts in {self.first_year} ({n_first} station{'s' if n_first != 1 else ''}"
                + (f"; {', '.join(pts)}" if pts else "") + ").")


def parse_start(text: str) -> int | str:
    """'1890' -> 1890; 'por' (any case) -> 'por'. Raises PorError with a message fit to show the user."""
    t = (text or "").strip().lower()
    if t in POR_WORDS:
        return "por"
    try:
        y = int(t)
    except ValueError:
        raise PorError("Enter a four-digit year (like 1890) or POR for the start of the period of record.") from None
    if not MIN_YEAR <= y <= MAX_YEAR:
        raise PorError(f"Enter a year between {MIN_YEAR} and {MAX_YEAR}, or POR.")
    return y


def station_por(client, bbox, element: str) -> Por:
    """Record-start years of the stations in `bbox` for `element` (one small MultiStnData request; cached when the client has a cache)."""
    params = {"bbox": ",".join(f"{v:g}" for v in bbox), "sdate": "2024-01-01", "edate": "2024-01-01",
              "elems": [{"name": element}], "meta": ["valid_daterange"]}

    def fetch():
        out = client.post("MultiStnData", params)
        years = []
        for s in out.get("data", []):
            vr = (s.get("meta") or {}).get("valid_daterange") or []
            first = next((r[0] for r in vr if r and r[0]), None)       # first range with a start date
            if first:
                years.append(int(first[:4]))
        return {"starts": np.array(sorted(years), dtype="int16")}

    arr = client.cache.get_or_compute("acis_por_v1", params, fetch) if getattr(client, "cache", None) else fetch()
    starts = [int(y) for y in arr["starts"]]
    if not starts:
        raise PorError("No stations in this area report that variable, so there is no period of record.")
    return Por(starts[0], starts)


def resolve_start(text: str, *, method: str, client, bbox, element: str, grid_first_year: int) -> tuple[int, Por | None]:
    """Typed start-year text -> (year, Por or None). 'por' means the grid's first shipped year for the Grid method, else the
    earliest year a station in the area reports `element`."""
    parsed = parse_start(text)
    if parsed != "por":
        return parsed, None
    if method == "grid":
        return grid_first_year, None
    p = station_por(client, bbox, element)
    return p.first_year, p
