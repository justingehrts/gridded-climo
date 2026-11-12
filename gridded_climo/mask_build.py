"""Build data/mask/water.npz: oceans and large lakes at 0.01 degree over the lower 48 plus a buffer.

Build-time only (needs `pip install basemap` for its GSHHG shoreline data and rasterio); the app just reads the shipped file.
Run: python -m gridded_climo.mask_build"""
from __future__ import annotations

import numpy as np

from .landmask import MASK_EAST, MASK_NORTH, MASK_PATH, MASK_SOUTH, MASK_STEP, MASK_WEST

MIN_LAKE_KM2 = 3000.0     # lakes smaller than this stay "land" (colored)


def _area_km2(ring) -> float:
    a = np.asarray(ring, "float64")
    x, y = a[:, 0], a[:, 1]
    lat0 = np.deg2rad(y.mean())
    xk, yk = x * 111.32 * np.cos(lat0), y * 110.57
    return abs(0.5 * np.sum(xk[:-1] * yk[1:] - xk[1:] * yk[:-1]))


def build(path=MASK_PATH, log=print):
    from mpl_toolkits.basemap import Basemap
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    m = Basemap(llcrnrlon=MASK_WEST, llcrnrlat=MASK_SOUTH, urcrnrlon=MASK_EAST, urcrnrlat=MASK_NORTH, resolution="i", projection="cyl")
    h, w = int(round((MASK_NORTH - MASK_SOUTH) / MASK_STEP)), int(round((MASK_EAST - MASK_WEST) / MASK_STEP))
    tf = from_origin(MASK_WEST, MASK_NORTH, MASK_STEP, MASK_STEP)

    def burn(polys, base):
        shapes = [({"type": "Polygon", "coordinates": [[(float(x), float(y)) for x, y in p]]}, 1) for p in polys]
        return rasterize(shapes, out_shape=(h, w), transform=tf, fill=0, dtype="uint8", all_touched=False) if shapes else base

    polys = [np.asarray(p) if not isinstance(p, tuple) else np.column_stack(p) for p in m.coastpolygons]
    types = list(m.coastpolygontypes)
    land = burn([p for p, t in zip(polys, types) if t == 1], None).astype(bool)
    big, small = [], []
    for p, t in zip(polys, types):
        if t == 2:
            (big if _area_km2(p) >= MIN_LAKE_KM2 else small).append(p)
    lakes_big = burn(big, None).astype(bool) if big else np.zeros_like(land)
    islands = burn([p for p, t in zip(polys, types) if t == 3], None).astype(bool)
    # land = continental land, minus the big lakes, plus islands inside them; small lakes stay land
    land = (land & ~lakes_big) | (islands & lakes_big) | (islands & ~land & False)
    water = ~land
    bits = np.packbits(water, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, bits=bits, width=w, west=MASK_WEST, north=MASK_NORTH, step=MASK_STEP)
    log(f"{len(big)} large lakes kept, {len(small)} small lakes left as land; water {water.mean():.1%} of cells; {path.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    build()
