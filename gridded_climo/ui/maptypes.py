"""The map types the app offers, grouped by variable (no Streamlit here, so it is easy to test).

Each map type is one entry in the sidebar's Map type picker and one card in the start-page gallery; ui/forms.py holds the
form that turns its fields into a Query."""
from __future__ import annotations

from dataclasses import dataclass

VARIABLES = {"temperature": "Temperature", "precipitation": "Precipitation", "sun": "Sun"}


@dataclass(frozen=True)
class MapType:
    id: str
    variable: str      # key of VARIABLES
    group: str         # sub-heading inside the variable ("Rain", "Snow"), or ""
    name: str
    blurb: str
    ramp: str          # matplotlib colormap used for the card's color strip


MAP_TYPES = [
    MapType("tdates", "temperature", "", "Cold & warm dates", "First or last date the low or high is at or past a threshold.", "RdYlBu_r"),
    MapType("tsum", "temperature", "", "Totals & averages", "Average high, day counts and degree days for chosen dates.", "Spectral_r"),
    MapType("tnormal", "temperature", "", "Normal for dates", "1991–2020 normal high or low for a span of the year.", "Spectral_r"),
    MapType("tdep", "temperature", "", "Vs normal", "How far the high or low ran from normal for chosen dates.", "coolwarm"),
    MapType("rsum", "precipitation", "Rain", "Totals", "Total precipitation, wettest day and rainy-day counts.", "YlGnBu"),
    MapType("rnormal", "precipitation", "Rain", "Normal for dates", "1991–2020 normal precipitation for a span of the year.", "YlGnBu"),
    MapType("rdep", "precipitation", "Rain", "Vs normal", "Precipitation minus normal for chosen dates.", "BrBG"),
    MapType("snowdate", "precipitation", "Snow", "Snowfall dates", "First or last day with at least X inches of snow.", "RdYlBu_r"),
    MapType("snownormal", "precipitation", "Snow", "Normal snowfall", "1991–2020 normal for a month or season.", "Blues"),
    MapType("snowstorm", "precipitation", "Snow", "Storm total", "Snowfall between two times: NOHRSC analysis, or stations + reports (any date).", "Blues"),
    MapType("snowdep", "precipitation", "Snow", "Snowfall vs normal", "Observed snowfall minus normal for chosen dates.", "RdBu"),
    MapType("sun", "sun", "", "Sunrise, sunset & day length", "On one date, or the change between two dates.", "YlOrBr"),
]
BY_ID = {t.id: t for t in MAP_TYPES}
DEFAULT_TYPE = "tdates"


def types_for(variable: str) -> list[MapType]:
    return [t for t in MAP_TYPES if t.variable == variable]


def first_type(variable: str) -> str:
    return types_for(variable)[0].id


def swatch_css(ramp: str, n: int = 8) -> str:
    """CSS linear-gradient for a card's color strip."""
    import matplotlib as mpl
    cmap = mpl.colormaps[ramp]
    stops = ", ".join("#%02x%02x%02x" % tuple(int(c * 255) for c in cmap(i / (n - 1))[:3]) for i in range(n))
    return f"linear-gradient(90deg, {stops})"


def source_note(type_id: str, method: str | None, presaved: bool, source: str | None = None) -> str:
    """One line for the summary card: where the data comes from and roughly how long it takes."""
    if type_id in ("tdates", "snowdate"):
        if method == "grid" and type_id == "tdates":
            return "ACIS Grid 1 · pre-saved · instant"
        return "Stations, interpolated · " + ("pre-saved · instant for menu values" if presaved else "fetched live from ACIS")
    if type_id in ("tnormal", "rnormal"):
        return "1991–2020 daily normals · pre-saved · instant"
    if type_id == "snownormal":
        return "NCEI 1991–2020 station normals · " + ("pre-saved · instant" if presaved else "fetched live (~5–10 s)")
    if type_id == "snowstorm":
        if source == "stations":
            return "ACIS stations + NWS storm reports · fetched live (~10–30 s)"
        return "NOHRSC analysis · fetched live (~10 s)"
    if type_id == "snowdep":
        return "Stations vs 1991–2020 normals · fetched live (~20–60 s)"
    if type_id == "sun":
        return "Astronomical · local clock time · instant"
    return "ACIS Grid 1 · fetched live (~10–30 s)"
