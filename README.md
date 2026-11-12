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
The sidebar has three tabs:
- **Map**: the Area, a **Variable** (Temperature, Precipitation, Sun), a **Map type** and that type's short form. The summary
  ("Will make …") and **Generate map** come after the form and stick to the bottom of the sidebar on long forms; **Recent maps** below
  them re-make an earlier map in one click.
  - Temperature: *Cold & warm dates* (first/last date the low or high is at or below / at or above X), *Totals & averages*,
    *Normal for dates*, *Vs normal*.
  - Precipitation: Rain (*Totals*, *Normal for dates*, *Vs normal*) and Snow (*Snowfall dates*, *Normal snowfall*, *Storm total*,
    *Snowfall vs normal*).
  - Sun: sunrise, sunset and day length.
- **Look**: preset, color ramp, reverse, shading, steps, min/max, date grouping (date maps), import, reset. Changes apply right away.
- **Export**: Download KMZ, save the look as a preset, and **save or load a whole map** (area, map type, every setting and the look).

The main panel starts with a gallery of every map type. After Generate it shows the map with **Map / Image / Band colors** views.
Cold & warm dates can use **stations** (each station's own date, interpolated; the default) or the **grid** (ACIS Grid 1, scanned
cell by cell), under Advanced; snowfall is stations-only.

The app reads precomputed data shipped in `data/` (Streamlit Community Cloud can't afford multi-decade pulls):
```
gridded-climo precompute --elements mint,maxt --normals mint,maxt,pcpn     # grid per-year crossings + daily normals
gridded-climo precompute --stations mint,maxt,snow --elements "" --normals "" --y0 1950   # per-station crossings (server-side, ~20 min)
```
The grid build pre-saves every whole degree (about 440 files, ~35 MB): lows ≤ X and highs ≤ X from -10 to 50°F, highs ≥ X from 50 to 105°F, lows ≥ X from 40 to 80°F.
The grid command is resumable (raw ACIS pulls are cached). Stations accept any threshold and any years back to 1900 (off-menu values are fetched live from ACIS, ~15-30 s); the grid method is limited to the pre-saved thresholds and 1991+.
Deploying to Streamlit Community Cloud: `requirements.txt` + `packages.txt` (installs `gdal-bin`) are included.

### Start year and POR
On date maps, **Years from** takes a year (like `1890`) or **`POR`**, the start of the period of record: the earliest year any station
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
- **Group dates into** (first/last-date maps; set in the Look tab, or right above the color table in the Band colors view when that is open): *Automatic* (default, equal color steps), *Weekly* (1st-6th, 7th-13th, 14th-20th, 21st-end),
  *Thirds* (early / mid / late month), *Halves* (1st-15th, 16th-end), or *Custom* (your own bin start dates, e.g. `Oct 1, Oct 8, Oct 15, Nov 1`).
  Each bin is one color and one legend entry; bins are calendar-aligned, so "first week of October" means the same thing every month.
  **Delete rows** in the Band colors table to merge bins (select rows, press Delete, then *Apply colors*): the remaining bins keep their start
  dates, deleting the first rows makes one "Before <date>" bin, deleting the last rows extends the final bin ("<date> and later"), and *Restore all bins* undoes it.
- **Look** tab: color ramp (a dropdown that draws each ramp's gradient), reverse, stepped/smooth, number of steps, min/max, and import of a MAX `.wctrp` palette,
  a CSV legend (`From,To,R,G,B,Alpha`, or the older `Value,R,G,B,Alpha`), or a JSON settings export. For date maps an imported palette supplies colors only (assigned by
  position across the bins); for numeric maps its values become the color-band thresholds.
- **Band colors** view (next to Map / Image): edit R/G/B/A for each date bin, or, on numeric maps, a MAX-style color table: one row per band
  (From, To, color swatch with a color picker, Red/Green/Blue, Transparency), each color applying from its From up to its To. Leave the first
  From blank for no lower limit and the last To blank for no upper limit; values in no band are transparent. Select two rows and **Ramp RGB** (or
  **Ramp RGB + Transparency**) to blend the rows between them, or **Generate bands** from a preset ramp. **Download as .wctrp** writes the table as a MAX palette (gaps become transparent bands, no upper limit is written as 999).
  (Ported from geotiff-to-kmz.)
- Styling re-renders the cached result instantly; it never re-fetches data.
- **Map smoothing** (Advanced, station maps): stations are interpolated (nearest 8, distance^-3) and then blurred a little. Default 3 km keeps
  the map within about a day of each airport's own average; 0 matches every station exactly (spottier), and higher values give smoother,
  blurrier contours that can drift several days from a single station.
- **Presets** are plain JSON files (the same format as a settings export) in `presets/`. A bundled **NWS snowfall** preset applies the NWS snowfall bands (0.1″ to 72″+, in inches). Pick one under Look → *Preset* → *Apply preset*;
  only the settings a preset contains are changed. To create one, restyle a map, open Export → *Save look as preset*, name it, download the file,
  put it in `presets/`, and commit (Community Cloud's disk is temporary, so the app can't store presets itself). Presets hold the look only,
  never the data or the threshold, and a preset's numeric legend is ignored on date maps.

## Threaded station records

Station maps use NWS *threaded* records (e.g. `CMHthr` "Columbus Area") wherever one exists. A threaded record stitches a city's
successive stations into one continuous period of record, so it reaches much further back than the current airport station. Each is
placed at the city's main airport and replaces that airport's own record (labelled "… (threaded)"). `gridded_climo/threaded.json`
lists them (rebuild with `python -m gridded_climo.threaded_build`); `precompute --stations ... --add-threaded` re-threads the shipped
files. Other stations in the same city (old downtown, NAS, university sites) stay separate, since ACIS doesn't say which stations a
threaded record is made of.

## Custom-range summaries

For specific dates the Variable list covers high, low and average temperature, precipitation, snowfall (NOHRSC totals) and heating /
cooling (base 65) / growing (base 50) degree days. Summaries: average, total, maximum, minimum, **number of days** and **percent of days**
meeting a threshold; any other summary can also be limited to days at/above or at/below a threshold (e.g. total of highs ≥ 80°F).
Average temperature and degree days are derived from the daily max/min grids. Thresholded summaries, day counts and the derived variables
are specific-dates only (the shipped daily normals are averages, so there is no normal-period average or departure for them).

## Sun data

**Variable → Sun** maps sunrise, sunset or length of day on one date, or the change in each between two dates. Values are astronomical
(NOAA/Meeus solar position, upper limb with standard refraction; within about a minute of other calculators) on a 0.05° grid, in **local clock
time**: each point uses its own time zone (`data/tz/tzgrid.npz`, built once by `python -m gridded_climo.tz_build` with `timezonefinder`)
and that date's daylight-saving offset, so the map steps by an hour across a zone border, and a range that spans a daylight-saving change
includes the one-hour clock jump (the map says so). Day length has no clock component. No ACIS/NOHRSC call is needed, so any date and any
area in the US and nearby works instantly.

## Average monthly / seasonal snowfall

**Precipitation → Normal snowfall** maps NCEI's official 1991–2020 monthly snowfall normals (what NWS publishes;
Columbus November = 1.2") summed over the chosen months: any single month, Dec–Feb, Oct–Apr, the Jul–Jun season, or any month range.
Station normals come from ACIS in one request and are interpolated like the other station maps. The Ohio-centered region ships
them (`data/normals/snow_monthly_1991-2020.npz`, rebuilt with `gridded-climo precompute --snow-normals`); other areas fetch live (~5–10 s).
Whole months and the 1991–2020 period only, since those are what the official normals cover.

## Snowfall departure from normal

**Precipitation → Snowfall vs normal** maps observed station snowfall minus the NCEI 1991–2020
normal for the same days (ACIS daily normals, so any date range works; CMH Jan–Feb 2025 = 14.1" vs 17.1" normal, −3.0"). Station days
end around 7 AM, so the inputs are dates rather than NOHRSC hours, and any year with station data works. Stations missing more than
10% of the days are left out; the rest are interpolated like the other station maps. Fetched live (~20–60 s for the Ohio region, depending on ACIS load).

### Storm total without NOHRSC (stations + reports)
Precipitation → Snow → **Storm total** has a **Data** switch. *NOHRSC analysis* (hour-level, Oct 2008 onward) is the default; *Stations + reports* sums ACIS station snowfall over whole calendar days for **any date** (back to 1900) and blends in NWS local storm reports (IEM archive; reports within 10 km of a station are ignored in favor of the station, and windows over 31 days use stations only). Station snow days end in the morning, so this is not an exact hour window.

### Smooth edges and the water stencil
Maps are drawn from a finer, interpolated copy of the grid (Look → **Smooth band edges**) so band edges are smooth curves instead of blocky ~2 km steps, and oceans and the Great Lakes are left uncolored (Look → **Hide color over large water**; small lakes stay colored). Both are on by default, saved with presets, and apply to the KMZ too. The water stencil is a shipped 0.01° raster (`data/mask/water.npz`, built from GSHHG shorelines with `python -m gridded_climo.mask_build`).
