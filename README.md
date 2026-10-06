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

### Streamlit app
```
streamlit run streamlit_app.py      # needs data/ (see below) and the GDAL CLI
```
Pick **When** (average first / last date, or custom range), **What** (temperature at/below or at/above X, snowfall, precip…),
then **Generate map** for a preview and KMZ download. First/last dates for temperature can use either the **grid** (ACIS Grid 1,
scanned cell by cell) or **stations** (each station's own average date, interpolated; snowfall is stations-only).

The app reads precomputed data shipped in `data/` (Streamlit Community Cloud can't afford multi-decade pulls):
```
gridded-climo precompute --elements mint,maxt --normals mint,maxt,pcpn     # grid per-year crossings + daily normals
gridded-climo precompute --stations mint,maxt,snow --elements "" --normals "" --y0 1950   # per-station crossings (server-side, ~20 min)
```
The grid build pre-saves every whole degree (about 440 files, ~35 MB): lows ≤ X and highs ≤ X from -10 to 50°F, highs ≥ X from 50 to 105°F, lows ≥ X from 40 to 80°F.
The grid command is resumable (raw ACIS pulls are cached). Stations accept any threshold and any years back to 1900 (off-menu values are fetched live from ACIS, ~15-30 s); the grid method is limited to the pre-saved thresholds and 1991+.
Deploying to Streamlit Community Cloud: `requirements.txt` + `packages.txt` (installs `gdal-bin`) are included.

### Start year and POR
On first/last-date maps, **Years included: from** takes a year (like `1890`) or **`POR`**, the start of the period of record: the earliest year any station
in the chosen area reports that variable (looked up from ACIS, kept for a day). The app also shows how many stations that start has, since the
earliest years rest on very few. For the Grid method, POR means 1991, where the saved grid data begins. Years before the area's record are
rejected with the real start year. The command line takes `--normal-period por-2020`.

For the Ohio-centered region the saved station files reach back to the period of record (1866 for temperatures, 1857 for snow), so POR and any
start year are instant at the pre-saved thresholds. Anything not saved (another threshold, or another area) is fetched live from ACIS, which is
slow for long spans: roughly 30 s for 30 years, a minute or so back to 1900, and several minutes back to the 1860s.
To extend saved files yourself: `gridded-climo precompute --stations mint,maxt,snow --elements "" --normals "" --extend-to por` (fetches only the missing early seasons).

### Areas
The **Area** dropdown lists the Columbus-centered default, every state in the lower 48 (plus DC) and a custom box. A state is drawn with a
buffer so neighbors and surroundings show: 10% of its longer side, between 0.75° and 2° (Ohio gets 0.75°, about 80 km). State outlines come
from ACIS and live in `gridded_climo/states.json`. The CLI takes `--state TX` for the same thing.

Pre-saved data (grid first/last dates, daily normals, per-station files) only covers the Ohio-centered region, so for areas outside it:
- **Stations** work anywhere in the lower 48 (any threshold, any years): fetched live from ACIS, roughly 10-60 seconds depending on the area.
- **Date ranges** are fetched live too, capped by area x days so a big state can't exhaust a hosted app (about 100 days for Texas, 400+ for Ohio).
- **Storm-total snowfall** works anywhere (NOHRSC covers the lower 48).
- **Grid first/last dates and departure/normal-period maps** need the pre-saved files, so they are Ohio-region only. Ohio itself is cropped to the
  pre-saved area (its northern buffer over Lake Erie is trimmed).

### Styling
- **Group dates into** (first/last-date maps): *Automatic* (default, equal color steps), *Weekly* (1st-6th, 7th-13th, 14th-20th, 21st-end),
  *Thirds* (early / mid / late month), *Halves* (1st-15th, 16th-end), or *Custom* (your own bin start dates, e.g. `Oct 1, Oct 8, Oct 15, Nov 1`).
  Each bin is one color and one legend entry; bins are calendar-aligned, so "first week of October" means the same thing every month.
- **🎨 Style** (sidebar): color ramp + preview, reverse, stepped/smooth, number of steps, min/max, and import of a MAX `.wctrp` palette,
  a CSV legend (`Value,R,G,B,Alpha`), or a JSON settings export. For date maps an imported palette supplies colors only (assigned by
  position across the bins); for numeric maps its values become the color-band thresholds.
- **🎨 Edit colors** (below the map): edit R/G/B/A for each date bin, or the Value/R/G/B/A rows of a custom numeric legend.
- Styling re-renders the cached result instantly; it never re-fetches data.
- **Map smoothing** (Options, station maps): stations are interpolated (nearest 8, distance^-3) and then blurred a little. Default 3 km keeps
  the map within about a day of each airport's own average; 0 matches every station exactly (spottier), and higher values give smoother,
  blurrier contours that can drift several days from a single station.
- **Presets** are plain JSON files (the same format as a settings export) in `presets/`. Pick one under 🎨 Style → *Preset* → *Apply preset*;
  only the settings a preset contains are changed. To create one, restyle a map, open *Save this look as a preset*, name it, download the file,
  put it in `presets/`, and commit (Community Cloud's disk is temporary, so the app can't store presets itself). Presets hold the look only,
  never the data or the threshold, and a preset's numeric legend is ignored on date maps.
