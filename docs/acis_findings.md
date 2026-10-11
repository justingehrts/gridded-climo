# Data source findings (tested live, 2026-09-30)

## ACIS `GridData` (https://data.rcc-acis.org/GridData, grid 1)
| Question | Result |
|---|---|
| `first_le_32` / `last_ge_1` reduce | **Not supported** -> `{"error":"elem_0: firstlast"}` (any area type, `std`/`yly`, with/without `add`) |
| `cnt_le_32` with `duration` `std`/`yly` | Works (counts/sums can run server-side) |
| Flat `reduce:"first_le_32"` on `StnData` with `interval/duration: yly` | Returns calendar-year dates and ignores `season_start` (do not use for Jul-Jun seasons) |
| Nested `reduce:{reduce:..., add:"date"}` | `bad args` on both endpoints |
| Elements on grid 1 | `mint`, `maxt`, `pcpn`. `snow`, `snwd` -> `vX` error on grids 1, 2, 3, 21; grids 4, 22 invalid |
| `"normal":"departure"` / `"1"` | Accepted but returned raw values in every form tried (daily interval) -> not relied on |
| Bulk pull | bbox [-87.5,37,-78.5,42.5] is ~132x216 cells (1/24 deg); 10 days of `mint` = 1.5 MB JSON, 1.3 s |
| Point-vs-cell | Grid cell at CMH: first <=32F 2019-10-13 / 2020-10-17; CMH station 2019-11-01 / 2020-10-31 (grid is interpolated from colder rural stations; ACIS's own point query agrees with our cell indexing) |

**Architecture consequence (grids):** first/last threshold dates are computed client-side (numpy) from daily grids, cached as int16 (x100) npz per calendar quarter.

## ACIS station first/last dates: the request xmACIS uses (found by reading xmacis.rcc-acis.org's JavaScript)
`StnData` / `MultiStnData` DO compute seasonal first/last threshold dates server-side, but only in this exact shape:
```json
{"bbox": "...", "sdate": "<season END of first year>", "edate": "<season END of last year>",
 "elems": [{"name": "mint", "interval": [1,0,0], "duration": "std", "season_start": "07-01",
            "reduce": {"reduce": "first_le_40", "add": "value,mcnt"}}], "meta": ["name","ll","sids"]}
```
- `std` = season-to-date, so each yearly step ends on `sdate`'s month/day; hence `sdate` must be the season *end* (e.g. `2016-06-30` for the Jul 1 2015 - Jun 30 2016 season).
- `reduce` is an object; `add: "date"` inside it is rejected (`bad args`), `"value,mcnt"` works. Each cell = `[date | "M", value | "M", missing_day_count]`.
- `"M"` with a small count = threshold never reached; `"M"` with a count near the season length = no data.
- One request returned 827 stations x 30 seasons in ~12 s (630 KB); 1,170 stations x 76 seasons in ~1 min.
- Validated against a local daily scan: 14,779 identical station-years, 0 differences.
- Snow works too (`last_ge_1.0`). `GridData` still rejects first/last (`firstlast`) in every form, so grids use the daily scan.

## NOHRSC National Gridded Snowfall Analysis (sfav2)
- Plain HTTP, no auth: `https://www.nohrsc.noaa.gov/snowfall/data/YYYYMM/` (YYYYMM = month of END time).
- GeoTIFF/NetCDF/PNG per product: `sfav2_CONUS_6h_YYYYMMDDHH` (also `24h_`, `48h_`, `72h_`), and season-to-date `sfav2_CONUS_<YYYYMMDDHH of Sep 30 12Z>_to_<YYYYMMDDHH>` (00Z/12Z).
- GeoTIFF: EPSG:4326, 1500x850, **0.04 deg (~4 km, not 1 km)**, origin (-126, 55), Float32, **inches** (Columbus 0.12", Buffalo 7.4", Mt Baker 183" on 2024-01-01 season total), `-99999` = missing, no nodata tag.
- Arbitrary storm window = season-total(end) - season-total(start) (00Z/12Z snap), or sum of 6-hourly grids (6 h snap, also works across water years).
