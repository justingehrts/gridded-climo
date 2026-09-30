# gridded-climo

Gridded climate maps for broadcast graphics (default region: Columbus, OH), output as colorized KMZ.

```
pip install -e .[dev]        # also needs the GDAL CLI (gdalwarp, gdaldem, gdalinfo): apt install gdal-bin
gridded-climo list
gridded-climo run first_freeze                         # 1991-2020 average, default bbox
gridded-climo run first_freeze --normal-period 2001-2020 --bbox -84,39,-82,41
gridded-climo run avg_high_period --start 2025-07-01 --end 2025-07-31
gridded-climo run high_departure_period --start 2025-07-01 --end 2025-07-31
gridded-climo run storm_total_snow --start 2024-01-05T12 --end 2024-01-07T12   # UTC
```
Output goes to `out/<metric>.kmz` (`--out`, `--keep-tif` for the intermediate GeoTIFF). Downloads are cached in
`.cache/gridded_climo` (`--cache-dir` or `$GRIDDED_CLIMO_CACHE`); the first multi-decade climatology is a large
pull (~50 MB JSON per season), later runs and other thresholds reuse it.

Metrics live in `gridded_climo/metrics.yaml` (see `registry.py` for the schema). Data-source findings: `docs/acis_findings.md`.

**Not yet implemented:** snow climatology (`last_1in_snow`, needs the station path), full style controls / Streamlit UI.
