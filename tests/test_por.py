import pytest

from gridded_climo.cache import Cache
from gridded_climo.por import Por, PorError, parse_start, resolve_start, station_por


def _resp(*ranges):
    return {"data": [{"meta": {"valid_daterange": r}} for r in ranges]}


class FakeClient:
    def __init__(self, response, cache=None):
        self.response, self.cache, self.calls = response, cache, 0

    def post(self, endpoint, params):
        self.calls += 1
        assert endpoint == "MultiStnData" and params["meta"] == ["valid_daterange"]
        return self.response


def test_parse_start_year_or_por():
    assert [parse_start(t) for t in ("por", " POR ", "Period of Record", "P.O.R.")] == ["por"] * 4
    assert parse_start("1890") == 1890 and parse_start(" 1991 ") == 1991
    for bad, msg in (("", "four-digit"), ("abc", "four-digit"), ("18.5", "four-digit"), ("90", "between"), ("2500", "between")):
        with pytest.raises(PorError, match=msg):
            parse_start(bad)


def test_station_por_reads_each_stations_first_record_and_skips_gaps_in_the_metadata():
    c = FakeClient({"data": [
        {"meta": {"valid_daterange": [["1896-05-01", "2020-01-01"]]}},
        {"meta": {"valid_daterange": [["1866-06-01", "1999-01-01"]]}},
        {"meta": {"valid_daterange": [[None, None], ["1910-01-01", "2000-01-01"]]}},    # first range empty: use the next one
        {"meta": {}}, {"meta": {"valid_daterange": []}},                                  # no range at all: ignored
        {"meta": {"valid_daterange": [["1950-01-01", "2024-01-01"]]}}]})
    p = station_por(c, (-85, 38, -80, 42), "mint")
    assert p.first_year == 1866 and p.start_years == [1866, 1896, 1910, 1950]       # stations with no usable range are ignored
    assert [p.stations_by(y) for y in (1865, 1866, 1900, 1949, 2000)] == [0, 1, 2, 3, 4]
    assert "starts in 1866 (1 station; 2 by 1900, 4 by 1950)" in p.describe("low temperature")   # a record starting in 1950 counts as "by 1950"


def test_no_stations_means_no_period_of_record():
    with pytest.raises(PorError, match="No stations"):
        station_por(FakeClient({"data": []}), (-85, 38, -80, 42), "snow")


def test_lookup_is_cached(tmp_path):
    resp = _resp([["1880-01-01", "2020-01-01"]])
    cache = Cache(tmp_path)
    a = FakeClient(resp, cache); station_por(a, (-85, 38, -80, 42), "maxt")
    b = FakeClient(resp, cache); p = station_por(b, (-85, 38, -80, 42), "maxt")
    assert a.calls == 1 and b.calls == 0 and p.first_year == 1880
    c = FakeClient(resp, cache); station_por(c, (-85, 38, -80, 42), "mint")          # a different variable is a different lookup
    assert c.calls == 1


def test_resolve_start_by_method():
    c = FakeClient(_resp([["1872-10-11", "2020-01-01"]]))
    assert resolve_start("por", method="station", client=c, bbox=(-85, 38, -80, 42), element="mint", grid_first_year=1991)[0] == 1872
    assert resolve_start("por", method="grid", client=c, bbox=(-85, 38, -80, 42), element="mint", grid_first_year=1991) == (1991, None)
    assert c.calls == 1                                                              # the grid path never asks ACIS
    assert resolve_start("1890", method="station", client=c, bbox=(0, 0, 1, 1), element="mint", grid_first_year=1991) == (1890, None)
    assert c.calls == 1


def test_cli_period_accepts_por():
    from gridded_climo.cli import _period
    assert _period("1991-2020") == (1991, 2020) and _period("por-2020") == ("por", 2020) and _period("POR-2010") == ("por", 2010)
