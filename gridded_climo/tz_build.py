"""Build data/tz/tzgrid.npz: IANA time zone of every 0.05-degree cell over the lower 48 plus a buffer (nearest land zone offshore).

Build-time only (needs `pip install timezonefinder`); the app reads the shipped grid and uses stdlib zoneinfo.
Run: python -m gridded_climo.tz_build"""
from __future__ import annotations

import numpy as np

from .tz import TZ_PATH, TZ_STEP, TZ_WEST, TZ_NORTH, TZ_EAST, TZ_SOUTH


def build(path=TZ_PATH, step: float = TZ_STEP, log=print):
    from scipy.ndimage import distance_transform_edt
    from timezonefinder import TimezoneFinder
    tf = TimezoneFinder()
    lons = np.arange(TZ_WEST + step / 2, TZ_EAST, step)
    lats = np.arange(TZ_NORTH - step / 2, TZ_SOUTH, -step)          # row 0 = north
    names: list[str] = []
    idx = np.full((len(lats), len(lons)), -1, "int16")
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            z = tf.timezone_at(lng=float(lo), lat=float(la))
            if z is None or z.startswith("Etc/"):
                continue
            if z not in names:
                names.append(z)
            idx[i, j] = names.index(z)
        if i % 50 == 0:
            log(f"row {i}/{len(lats)}")
    missing = idx < 0
    near = distance_transform_edt(missing, return_distances=False, return_indices=True)
    idx = idx[near[0], near[1]]                                      # offshore / unlabeled cells take the nearest zone
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, idx=idx.astype("int8"), names=np.array(names), west=TZ_WEST, north=TZ_NORTH, step=step)
    log(f"{len(names)} zones, grid {idx.shape}, {path.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    build()
