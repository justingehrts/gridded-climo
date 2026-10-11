"""One-time builder for gridded_climo/threaded.json: every ACIS 'threaded' station record (e.g. CMHthr = 'Columbus Area') in the lower 48,
with the main airport it is placed at and the station records it replaces.

Why: threaded records stitch a city's successive stations into one long continuous record, which is what NWS offices use for official
climate normals and records. ACIS lists them nowhere in area queries and gives them no coordinates, so we discover them by testing
`<airport code>thr` for every station that carries a 3-letter FAA/IATA id, and place each at that airport."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .regions import states

ACIS = "https://data.rcc-acis.org"
OUT = Path(__file__).with_name("threaded.json")


def _post(endpoint: str, body: dict, timeout: int = 300) -> dict:
    r = requests.post(f"{ACIS}/{endpoint}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _span(vr) -> tuple[str, str]:
    """(end, start) of the first valid range, for ranking: prefer the most recently reporting, then the longest record."""
    return (vr[0][1], vr[0][0]) if vr and vr[0] and vr[0][0] else ("", "")


def build(log=print) -> dict:
    by_code: dict[str, list[dict]] = {}
    for st in states():
        meta = _post("StnMeta", {"state": st.lower(), "meta": "name,sids,ll,valid_daterange", "elems": "mint"})["meta"]
        for m in meta:
            if not m.get("ll"):
                continue
            for s in m["sids"]:
                if s.endswith(" 3"):                       # type 3 = FAA/IATA location id, e.g. 'CMH 3'
                    by_code.setdefault(s[:-2], []).append(m)
        log(f"{st}: {len(meta)} stations ({len(by_code)} codes so far)")
    codes = sorted(by_code)
    found: dict[str, dict] = {}
    for i in range(0, len(codes), 150):
        ids = ",".join(f"{c}thr" for c in codes[i:i + 150])
        for m in _post("StnMeta", {"sids": ids, "meta": "name,sids,valid_daterange", "elems": "mint"})["meta"]:
            found[m["sids"][0]] = m
    out = {}
    for thr_sid, m in sorted(found.items()):
        code = thr_sid.split("thr")[0]
        cands = by_code[code]
        main = max(cands, key=lambda x: _span(x["valid_daterange"]))           # the airport: reporting now, longest record
        out[thr_sid] = {
            "name": m["name"], "code": code, "airport": main["name"], "lon": round(main["ll"][0], 4), "lat": round(main["ll"][1], 4),
            "first_record": (m["valid_daterange"][0][0] if m.get("valid_daterange") and m["valid_daterange"][0] else None),
            # every station record carrying this airport's FAA id is folded into the threaded record: drop them from maps
            "replaces": sorted({(x["sids"][0], round(x["ll"][0], 3), round(x["ll"][1], 3)) for x in cands}),
        }
    log(f"{len(out)} threaded records found from {len(codes)} candidate codes")
    return out


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True))
    print("wrote", OUT, len(data))
