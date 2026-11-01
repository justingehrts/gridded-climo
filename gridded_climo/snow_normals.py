"""NCEI 1991-2020 monthly snowfall normals for every station in an area (one ACIS MultiStnData request), and month-window sums.

ACIS serves the official normals (`normal: "1"`), so station values match what NWS/NCEI publish (e.g. Columbus Nov = 1.2")."""
from __future__ import annotations

import calendar
from pathlib import Path

import numpy as np

from .precomputed import DATA_DIR

PERIOD = (1991, 2020)
MONTH_ABBR = [calendar.month_abbr[m] for m in range(1, 13)]


def shipped_path(data_dir=DATA_DIR) -> Path:
    return Path(data_dir) / "normals" / f"snow_monthly_{PERIOD[0]}-{PERIOD[1]}.npz"


def _num(v) -> float:
    v = v[0] if isinstance(v, list) else v
    if v == "T":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def parse(out: dict) -> dict:
    rows = [r for r in out.get("data", []) if (r.get("meta") or {}).get("ll") and len(r.get("data", [])) == 12]
    return {"sids": np.array([(r["meta"].get("sids") or [""])[0] for r in rows]),
            "lon": np.array([r["meta"]["ll"][0] for r in rows], "float32"), "lat": np.array([r["meta"]["ll"][1] for r in rows], "float32"),
            "name": np.array([r["meta"].get("name", "") for r in rows]),
            "monthly": np.array([[_num(v) for v in r["data"]] for r in rows], "float32").reshape(len(rows), 12)}


def fetch_snow_normals(client, bbox) -> dict:
    params = {"bbox": ",".join(f"{v:g}" for v in bbox), "sdate": "2020-01", "edate": "2020-12",
              "elems": [{"name": "snow", "interval": "mly", "duration": "mly", "reduce": "sum", "normal": "1"}],
              "meta": ["name", "sids", "ll"]}
    fetch = lambda: parse(client.post("MultiStnData", params))
    return client.cache.get_or_compute("acis_snow_normals_v1", params, fetch) if getattr(client, "cache", None) else fetch()


def load_shipped(data_dir=DATA_DIR) -> dict | None:
    p = shipped_path(data_dir)
    return {k: v for k, v in np.load(p, allow_pickle=False).items()} if p.exists() else None


def save_shipped(z: dict, data_dir=DATA_DIR) -> Path:
    p = shipped_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez_compressed(tmp, **z)
    tmp.replace(p)
    return p


def window_months(m1: int, m2: int) -> list[int]:
    """Months from m1 through m2, wrapping the year (11, 3 -> [11, 12, 1, 2, 3])."""
    return [((m1 - 1 + i) % 12) + 1 for i in range(((m2 - m1) % 12) + 1)]


def window_label(m1: int, m2: int) -> str:
    if m1 == m2:
        return calendar.month_name[m1]
    if window_months(m1, m2) == [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]:
        return "Seasonal (Jul–Jun)"
    return f"{MONTH_ABBR[m1 - 1]}–{MONTH_ABBR[m2 - 1]}"


def window_sum(z: dict, months: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """(values, keep) — per-station sum over `months`; stations missing any of them are dropped."""
    v = z["monthly"][:, [m - 1 for m in months]]
    keep = np.isfinite(v).all(axis=1)
    return v[keep].sum(axis=1), keep
