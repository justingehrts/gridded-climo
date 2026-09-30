"""gridded-climo CLI: registry entry + region + period -> KMZ."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .acis import ACISClient
from .cache import Cache
from .config import Settings
from .grid import Grid
from .nohrsc import NOHRSC
from .products.climatology import climatology
from .products.period import period_summary
from .registry import load_registry
from .render import render_kmz


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _datetime(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", ""))


def _bbox(s: str):
    return tuple(float(x) for x in s.split(","))


def _period(s: str):
    a, b = s.split("-")
    return int(a), int(b)


def build_parser():
    p = argparse.ArgumentParser(prog="gridded-climo")
    p.add_argument("--registry", help="metrics.yaml path (default: built-in)")
    p.add_argument("--cache-dir")
    p.add_argument("--bbox", type=_bbox, help="west,south,east,north (default: Columbus, OH region)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list registered metrics")
    r = sub.add_parser("run", help="generate a KMZ")
    r.add_argument("metric")
    r.add_argument("--normal-period", type=_period, metavar="YYYY-YYYY", help="default 1991-2020")
    r.add_argument("--start", help="period: YYYY-MM-DD | storm: YYYY-MM-DDTHH (UTC)")
    r.add_argument("--end")
    r.add_argument("--method", default="auto", choices=["auto", "difference", "sum6h"], help="storm accumulation method")
    r.add_argument("--out", type=Path, help="output .kmz (default out/<metric>.kmz)")
    r.add_argument("--keep-tif", action="store_true", help="also keep the intermediate GeoTIFF next to the KMZ")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    reg = load_registry(a.registry)
    if a.cmd == "list":
        for m in reg.values():
            print(f"{m.name:24s} {m.kind:12s} {m.source:11s} {m.title}")
        return 0

    if a.metric not in reg:
        sys.exit(f"unknown metric '{a.metric}'. Try: gridded-climo list")
    m = reg[a.metric]
    kw = {k: v for k, v in {"bbox": a.bbox, "cache_dir": a.cache_dir, "normal_period": a.normal_period}.items() if v}
    st = Settings(**kw)
    cache = Cache(st.cache_dir)
    label_fmt, name, info = None, m.title or m.name, {}

    if m.kind == "climatology":
        grid, info = climatology(m, ACISClient(st.acis_base_url, cache), st.bbox, st.normal_period)
        ref = dt.date(2001, info["ref_month"], info["ref_day"])  # non-leap reference year
        label_fmt = lambda v: (ref + dt.timedelta(days=int(round(v)))).strftime("%b %-d")
        name += f" ({info['years'][0]}-{info['years'][1]})"
    elif m.kind == "period":
        if not (a.start and a.end):
            sys.exit("period metrics need --start YYYY-MM-DD --end YYYY-MM-DD")
        s, e = _date(a.start), _date(a.end)
        grid = period_summary(m, ACISClient(st.acis_base_url, cache), st.bbox, s, e, st.normal_period)
        name += f" ({s} to {e})"
    else:  # storm
        if not (a.start and a.end):
            sys.exit("storm metrics need --start YYYY-MM-DDTHH --end YYYY-MM-DDTHH (UTC)")
        s, e = _datetime(a.start), _datetime(a.end)
        grid, used = NOHRSC(st.nohrsc_base_url, cache).storm_total(s, e, st.bbox, a.method)
        name += f" ({s:%b %-d %HZ} - {e:%b %-d %HZ}, NOHRSC, {used})"

    out = a.out or Path("out") / f"{m.name}.kmz"
    tif = grid.to_geotiff(out.with_suffix(".tif") if a.keep_tif else cache.file("products", f"{m.name}.tif"))
    render_kmz(tif, out, m.style, name, legend_title=name if m.style.units_label else None, label_fmt=label_fmt)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
