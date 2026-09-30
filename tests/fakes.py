import datetime as dt

import numpy as np

from gridded_climo.grid import Grid

H, W = 5, 7
TEMPLATE = Grid(np.zeros((H, W), "float32"), -85.0, 41.0, 0.5, 0.5)
BBOX = (-85.0, 38.5, -81.5, 41.0)  # exactly the fake grid's extent


class FakeClient:
    """Deterministic per-day random fields: any window of days returns consistent values."""
    def daily(self, element, bbox, start, end, grid=1):
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        data = np.stack([np.random.default_rng(d.toordinal()).normal(35, 15, (H, W)) for d in days]).astype("float32")
        data = np.rint(data)
        return np.array(days, dtype="datetime64[D]"), TEMPLATE, data
