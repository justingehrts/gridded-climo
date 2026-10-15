"""Sunrise, sunset and day length (NOAA / Meeus solar position, vectorized), in local clock time per map cell.

Sunrise/sunset are the upper limb on the horizon with standard refraction (-0.833 deg); accurate to about a minute at US latitudes."""
from __future__ import annotations

import datetime as dt

import numpy as np

from .grid import Grid
from .tz import offset_grid

STEP = 0.05      # degrees; sun times vary smoothly so this is plenty
ZENITH = 90.833


def _julian_day(day: dt.date) -> float:
    return day.toordinal() + 1721424.5          # 0h UTC


def _sun(jd: np.ndarray):
    """(equation of time [min], declination [rad]) at Julian day(s) `jd`."""
    t = (jd - 2451545.0) / 36525.0
    l0 = np.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = np.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (np.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + np.sin(2 * m) * (0.019993 - 0.000101 * t) + np.sin(3 * m) * 0.000289)
    true_lon = l0 + np.radians(c)
    omega = np.radians(125.04 - 1934.136 * t)
    app_lon = true_lon - np.radians(0.00569 + 0.00478 * np.sin(omega))
    eps = np.radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60 + 0.00256 * np.cos(omega))
    decl = np.arcsin(np.sin(eps) * np.sin(app_lon))
    y = np.tan(eps / 2) ** 2
    eqt = 4 * np.degrees(y * np.sin(2 * l0) - 2 * e * np.sin(m) + 4 * e * y * np.sin(m) * np.cos(2 * l0)
                         - 0.5 * y * y * np.sin(4 * l0) - 1.25 * e * e * np.sin(2 * m))
    return eqt, decl


def rise_set_utc(day: dt.date, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sunrise and sunset as minutes after 0h UTC of `day` (may be <0 or >1440 far from Greenwich); NaN if the sun doesn't rise/set."""
    lat, lon = np.radians(lat), np.asarray(lon, "float64")
    jd0 = _julian_day(day)
    rise = set_ = 720.0 - 4 * lon                    # first guess: solar noon
    sunrise = sunset = None
    for _ in range(3):                               # refine the solar position at the event time itself
        out = []
        for guess, sign in ((rise, +1), (set_, -1)):
            eqt, decl = _sun(jd0 + guess / 1440.0)
            cosh = (np.cos(np.radians(ZENITH)) - np.sin(lat) * np.sin(decl)) / (np.cos(lat) * np.cos(decl))
            ha = np.degrees(np.arccos(np.where(np.abs(cosh) <= 1, cosh, np.nan)))
            out.append(720.0 - 4 * (lon + sign * ha) - eqt)
        rise, set_ = out
        sunrise, sunset = rise, set_
    return sunrise, sunset


def sun_times(day: dt.date, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    """Local-clock minutes after midnight for sunrise and sunset, and day length in minutes, per cell on `day` (DST included)."""
    off = offset_grid(lat, lon, day)
    rise, set_ = rise_set_utc(day, lat, lon)
    return {"sunrise": rise + off, "sunset": set_ + off, "daylen": set_ - rise}


def cell_centers(bbox, step: float = STEP) -> tuple[np.ndarray, np.ndarray]:
    w, s, e, n = bbox
    lon = w + step / 2 + step * np.arange(int(np.ceil((e - w) / step)))
    lat = n - step / 2 - step * np.arange(int(np.ceil((n - s) / step)))
    return np.meshgrid(lat, lon, indexing="ij")


def _value(element: str, day: dt.date, lat, lon) -> np.ndarray:
    return sun_times(day, lat, lon)[element]


def sun_grid(element: str, bbox, day: dt.date, end: dt.date | None = None) -> tuple[Grid, dict]:
    """Map of sunrise / sunset / daylen on `day`, or (with `end`) its change from `day` to `end`.
    Returns (Grid in minutes, info) where info['dst_shift'] is the largest clock change (minutes) between the two dates in any cell."""
    lat, lon = cell_centers(bbox)
    first = _value(element, day, lat, lon)
    info = {"dst_shift": 0.0}
    if end is None:
        data = first
    else:
        data = _value(element, end, lat, lon) - first
        if element != "daylen":
            info["dst_shift"] = float(np.nanmax(np.abs(offset_grid(lat, lon, end) - offset_grid(lat, lon, day))))
    w, s, e, n = bbox
    return Grid(np.asarray(data, "float32"), w, n, STEP, STEP), info


# --- legend / label text ------------------------------------------------------------------------------------------------
def fmt_clock(m: float) -> str:
    m = int(round(m)) % 1440
    return f"{(m // 60) % 12 or 12}:{m % 60:02d} {'AM' if m < 720 else 'PM'}"


def fmt_duration(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}h {m % 60:02d}m"


def fmt_delta(m: float) -> str:
    m = int(round(m))
    sign, a = ("+" if m > 0 else "-" if m < 0 else ""), abs(m)
    return f"{sign}{a // 60}h {a % 60:02d}m" if a >= 60 else f"{sign}{a}m"


LABEL_KINDS = {"clock": fmt_clock, "duration": fmt_duration, "delta": fmt_delta}
_NICE = (1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 360)


def tidy_style(style, data: np.ndarray, symmetric: bool):
    """Copy of `style` with min/max/steps set so band edges fall on round minute values (5, 10, 15, 30, 60 ...)."""
    from dataclasses import replace
    v = data[np.isfinite(data)]
    if v.size == 0:
        return style
    lo, hi = (float(np.percentile(v, 2)), float(np.percentile(v, 98))) if v.size > 20 else (float(v.min()), float(v.max()))
    if symmetric:
        hi = max(abs(lo), abs(hi), 1.0)
        lo = -hi
    n = max(int(style.steps), 2)
    span = max(hi - lo, 1.0)
    step = next((x for x in _NICE if np.floor(hi / x) - np.floor(lo / x) + 1 <= n), _NICE[-1])    # smallest round step that fits in n bands
    if symmetric:
        vmax = np.ceil(max(abs(lo), abs(hi)) / step) * step
        vmin = -vmax
    else:
        vmin = np.floor(lo / step) * step                           # exactly n bands, so the style's own step count still applies
        vmax = vmin + n * step
    return replace(style, vmin=float(vmin), vmax=float(vmax), steps=n)
