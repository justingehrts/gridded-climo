"""gridded-climo CLI: registry entry + region + period -> KMZ."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .cache import Cache
from .config import Settings
from .registry import load_registry
from .render import render_kmz
from .runner import run_metric
from .acis import ACISClient


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _datetime(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", ""))


def _bbox(s: str):
    return tuple(float(x) for x in s.split(","))


def _period(s: str):
    """'1991-2020' or 'por-2020' (POR = start of the period of record, resolved once the area and variable are known)."""
    a, b = s.split("-")
    return ("por" if a.strip().lower() == "por" else int(a)), int(b)


def build_parser():
    p = argparse.ArgumentParser(prog="gridded-climo")
    p.add_argument("--registry", help="metrics.yaml path (default: built-in)")
    p.add_argument("--cache-dir")
    p.add_argument("--bbox", type=_bbox, help="west,south,east,north (default: Columbus, OH region)")
    p.add_argument("--state", help="two-letter state code; uses the state plus a buffer (instead of --bbox)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list registered metrics")
    pc = sub.add_parser("precompute", help="build data/occurrence + data/normals for the Streamlit app (slow, resumable)")
    pc.add_argument("--elements", default="mint,maxt", help="elements for first/last occurrence grids")
    pc.add_argument("--normals", default="mint,maxt,pcpn", help="elements for daily-normal grids ('' to skip)")
    pc.add_argument("--normal-period", type=_period, metavar="YYYY-YYYY", help="period for daily normals (default 1991-2020)")
    pc.add_argument("--stations", default="", help="elements for station-based files, e.g. mint,maxt,snow")
    pc.add_argument("--missing-only", action="store_true", help="stations: skip thresholds that already have a file")
    pc.add_argument("--prune", action="store_true", help="delete pre-saved files whose threshold is no longer in the menus, then exit")
    pc.add_argument("--y0", type=int, default=1950)
    pc.add_argument("--workers", type=int, default=3)
    pc.add_argument("--data-dir", type=Path)
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

    if a.cmd == "precompute":
        if a.prune:
            from .precompute import prune_unlisted
            from .precomputed import DATA_DIR as _D
            prune_unlisted(a.data_dir or _D)
            return 0
        from .precompute import run_precompute
        from .precomputed import DATA_DIR
        st = Settings(**{k: v for k, v in {"bbox": a.bbox, "cache_dir": a.cache_dir, "normal_period": a.normal_period}.items() if v})
        client = ACISClient(st.acis_base_url, Cache(st.cache_dir))
        if a.stations:
            from .precompute import run_precompute_stations
            run_precompute_stations(client, st.bbox, tuple(a.stations.split(",")), a.y0, a.data_dir or DATA_DIR,
                                    log=lambda m: print(m, flush=True), only_missing=a.missing_only)
            if not a.elements and not a.normals:
                return 0
        run_precompute(client, st.bbox,
                       elements=tuple(x for x in a.elements.split(",") if x), normals=tuple(x for x in a.normals.split(",") if x),
                       period=st.normal_period, y0=a.y0, data_dir=a.data_dir or DATA_DIR, workers=a.workers,
                       log=lambda m: print(m, flush=True))
        return 0

    if a.metric not in reg:
        sys.exit(f"unknown metric '{a.metric}'. Try: gridded-climo list")
    m = reg[a.metric]
    if a.state:
        from .regions import buffered_bbox
        try:
            a.bbox = buffered_bbox(a.state.upper())
        except KeyError as e:
            sys.exit(str(e))
    if a.normal_period and a.normal_period[0] == "por":
        from .acis import ACISClient as _C
        from .config import ACIS_BASE_URL
        from .por import station_por
        from .precomputed import shipped_years
        if m.source == "acis_grid1":      # the grid's saved data begins here
            first = (shipped_years().get("grid") or (1991,))[0]
        else:
            first = station_por(_C(ACIS_BASE_URL, Cache(a.cache_dir) if a.cache_dir else Cache(Settings().cache_dir)),
                                a.bbox or Settings().bbox, m.element).first_year
        print(f"POR start year: {first}")
        a.normal_period = (first, a.normal_period[1])
    kw = {k: v for k, v in {"bbox": a.bbox, "cache_dir": a.cache_dir, "normal_period": a.normal_period}.items() if v}
    st = Settings(**kw)
    if m.kind == "period" and m.normal != "average" or m.kind == "storm":
        if not (a.start and a.end):
            sys.exit(f"{m.kind} metrics need --start and --end")
    start, end = (a.start, a.end)
    if m.kind == "storm":
        start, end = (_datetime(start), _datetime(end)) if start and end else (None, None)
    elif start and end:
        start, end = _date(start), _date(end)
    res = run_metric(m, st, start, end, a.method)
    cache = Cache(st.cache_dir)

    out = a.out or Path("out") / f"{m.name}.kmz"
    tif = res.grid.to_geotiff(out.with_suffix(".tif") if a.keep_tif else cache.file("products", f"{m.name}.tif"))
    render_kmz(tif, out, res.style, res.name, legend_title=res.name if res.style.units_label else None, label_fmt=res.label_fmt)
    print(f"wrote {out}" + (f"  [{res.note}]" if res.note else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
