import datetime as dt

import numpy as np
import pytest

from gridded_climo.acis import derive
from gridded_climo.grid import Grid
from gridded_climo.products.period import period_summary, reduce_conditional
from gridded_climo.query import Query, describe, metric_from_query, unsupported_reason


def test_derive():
    hi, lo = np.array([90.0, 50.0]), np.array([70.0, 30.0])
    assert derive("avgt", hi, lo).tolist() == [80, 40]
    assert derive("cdd", hi, lo).tolist() == [15, 0]
    assert derive("hdd", hi, lo).tolist() == [0, 25]
    assert derive("gdd", hi, lo).tolist() == [(86 + 70) / 2 - 50, (50 + 50) / 2 - 50]


def test_conditional_reduce():
    d = np.array([[[85.0, np.nan]], [[75.0, np.nan]], [[90.0, np.nan]]], "float32")      # (T=3, 1, 2)
    assert reduce_conditional(d, "count", "ge", 80)[0].tolist()[0] == 2
    assert reduce_conditional(d, "pct", "ge", 80)[0, 0] == pytest.approx(200 / 3)
    assert reduce_conditional(d, "sum", "ge", 80)[0, 0] == 175
    assert reduce_conditional(d, "mean", "ge", 80)[0, 0] == 87.5
    assert reduce_conditional(d, "sum", "ge", 95)[0, 0] == 0                  # data but nothing qualifies
    assert np.isnan(reduce_conditional(d, "mean", "ge", 95)[0, 0])
    assert np.isnan(reduce_conditional(d, "count", "ge", 80)[0, 1])           # no data at all stays blank


def test_query_rules_and_titles():
    base = dict(when="range_specific", start=dt.date(2026, 5, 1), end=dt.date(2026, 9, 30))
    q = Query(element="maxt", reduce="count", op="ge", value=90.0, **base)
    assert unsupported_reason(q) is None and describe(q) == "Number of Days with High ≥ 90°F"
    m = metric_from_query(q)
    assert m.reduce == "count" and m.threshold == {"op": "ge", "value": 90.0}
    assert describe(Query(element="maxt", reduce="sum", op="ge", value=80.0, **base)) == "Total High on Days ≥ 80°F"
    assert "Percent of Days" in describe(Query(element="mint", reduce="pct", op="le", value=32.0, **base))
    assert unsupported_reason(Query(element="maxt", reduce="count", **base))                        # threshold required
    assert unsupported_reason(Query(element="maxt", reduce="count", op="ge", value=90.0, when="range_normal"))
    assert unsupported_reason(Query(element="hdd", reduce="sum", departure=True, **base))
    assert unsupported_reason(Query(element="hdd", reduce="sum", **base)) is None


class FakeClient:
    def __init__(self):
        self.asked = []

    def daily(self, element, bbox, start, end, grid=1):
        self.asked.append(element)
        T = (end - start).days + 1
        base = {"maxt": 80.0, "mint": 60.0}[element]
        data = np.full((T, 2, 2), base, "float32") + np.arange(T)[:, None, None]
        tpl = Grid.from_centers(np.zeros((2, 2), "float32"), np.array([[40.5, 40.5], [40.0, 40.0]]), np.array([[-83.0, -82.5], [-83.0, -82.5]]))
        return np.array([start + dt.timedelta(days=i) for i in range(T)], "datetime64[D]"), tpl, data


def test_period_summary_derived_and_filtered():
    c = FakeClient()
    q = Query(element="cdd", reduce="sum", when="range_specific", start=dt.date(2026, 6, 1), end=dt.date(2026, 6, 3))
    g = period_summary(metric_from_query(q), c, (-83, 40, -82.5, 40.5), q.start, q.end, (1991, 2020))
    assert set(c.asked) == {"maxt", "mint"}
    assert float(np.nanmax(g.data)) == 5 + 6 + 7                                  # avg 70,71,72 -> cdd 5,6,7
    q = Query(element="maxt", reduce="count", op="ge", value=81.0, when="range_specific", start=dt.date(2026, 6, 1), end=dt.date(2026, 6, 3))
    g = period_summary(metric_from_query(q), FakeClient(), (-83, 40, -82.5, 40.5), q.start, q.end, (1991, 2020))
    assert float(np.nanmax(g.data)) == 2
