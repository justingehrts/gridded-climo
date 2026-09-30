"""A lat/lon raster in memory, plus GeoTIFF writing."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

NODATA = -9999.0


@dataclass
class Grid:
    """Regular lat/lon grid. `data` is (H, W) float32 with NaN for missing; row 0 is the north edge."""
    data: np.ndarray
    west: float   # outer edge of the westernmost cell
    north: float  # outer edge of the northernmost cell
    dx: float
    dy: float     # positive

    @classmethod
    def from_centers(cls, data: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> "Grid":
        """Build from ACIS-style 2-D lat/lon center arrays (orients north-up)."""
        lat, lon = np.asarray(lat), np.asarray(lon)
        dx = float(lon[0, 1] - lon[0, 0]) if lon.shape[1] > 1 else 1 / 24
        dy = abs(float(lat[1, 0] - lat[0, 0])) if lat.shape[0] > 1 else 1 / 24
        if lat.shape[0] > 1 and lat[0, 0] < lat[-1, 0]:  # south-up -> flip to north-up
            data = data[::-1]
            lat = lat[::-1]
        return cls(np.asarray(data, dtype="float32"), float(lon.min() - dx / 2), float(lat.max() + dy / 2), dx, dy)

    @property
    def shape(self):
        return self.data.shape

    def with_data(self, data: np.ndarray) -> "Grid":
        return Grid(np.asarray(data, dtype="float32"), self.west, self.north, self.dx, self.dy)

    def to_geotiff(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        h, w = self.data.shape
        arr = np.where(np.isfinite(self.data), self.data, NODATA).astype("float32")
        with rasterio.open(
            path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32",
            crs="EPSG:4326", transform=from_origin(self.west, self.north, self.dx, self.dy),
            nodata=NODATA, compress="lzw",
        ) as dst:
            dst.write(arr, 1)
        return path

    @classmethod
    def from_geotiff(cls, path: str | Path, nodata_extra: tuple[float, ...] = ()) -> "Grid":
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float32")
            nd = src.nodata
            t = src.transform
        for v in ((nd,) if nd is not None else ()) + tuple(nodata_extra):
            arr[arr == v] = np.nan
        return cls(arr, t.c, t.f, t.a, -t.e)

    def clip(self, bbox: tuple[float, float, float, float]) -> "Grid":
        """Crop to the cells covering bbox (west, south, east, north)."""
        w, s, e, n = bbox
        c0 = max(int(np.floor((w - self.west) / self.dx)), 0)
        c1 = min(int(np.ceil((e - self.west) / self.dx)), self.data.shape[1])
        r0 = max(int(np.floor((self.north - n) / self.dy)), 0)
        r1 = min(int(np.ceil((self.north - s) / self.dy)), self.data.shape[0])
        if c1 <= c0 or r1 <= r0:
            raise ValueError(f"bbox {bbox} does not overlap the grid")
        return Grid(self.data[r0:r1, c0:c1], self.west + c0 * self.dx, self.north - r0 * self.dy, self.dx, self.dy)
