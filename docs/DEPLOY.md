# Deploying to Streamlit Community Cloud

The app reads precomputed data from `data/` (grid first/last crossings, daily normals, per-station crossings; ~30 MB,
committed to git), so it needs no long pulls. Only *specific-date* ranges and NOHRSC snowfall call out to ACIS / NOHRSC / IEM
at run time. No secrets or API keys are required.

## Steps
1. **Branch**: merge the working branch into the default branch (or deploy straight from the feature branch).
2. Go to <https://share.streamlit.io>, sign in with GitHub, and authorize access to this repository.
3. **Create app** -> repository `justingehrts/gridded-climo`, branch, **main file path `streamlit_app.py`**.
4. **Advanced settings** -> Python 3.11 (tested; newer 3.x should also work). No secrets.
5. **Deploy**. The first build installs `packages.txt` (`gdal-bin`, the `gdalwarp`/`gdaldem`/`gdalinfo` CLI the renderer shells
   out to) and then `requirements.txt` (which ends in `-e .` to install the `gridded_climo` package). Allow several minutes.
6. **Smoke test** on the live URL:
   - Average first date -> Stations -> Generate (shipped data; instant)
   - Custom range -> specific dates -> Generate (live ACIS; ~10-30 s)
   - Custom range -> Snowfall, a recent storm window (live NOHRSC + IEM dots)
   - Map tab renders; Download KMZ opens in Google Earth / your graphics system
7. Pushes to the deployed branch redeploy automatically. Free apps sleep when idle; the first visit wakes them (~30 s), so
   open it before air.

## Refreshing the data (each autumn/year-end, locally or in any session with network access)
```
pip install -e .            # plus the GDAL CLI
gridded-climo precompute --elements mint,maxt --normals mint,maxt,pcpn --y0 1991 --workers 1
gridded-climo precompute --stations mint,maxt,snow --elements "" --normals "" --y0 1950   # server-side; ~20 min total
git add data && git commit -m "Refresh precomputed data" && git push
```
The grid command is resumable and only adds missing seasons (ACIS rate-limits with HTTP 429: keep `--workers 1`). The station command
rewrites each file from one server-side request, so it's safe to re-run any time. Thresholds and years not pre-saved are fetched live
in the app for the Stations method (~15-30 s); the Grid method needs pre-saved data. Pass a smaller `--y0` (e.g. 1951) to backfill earlier years.

## Troubleshooting
- *`gdalwarp: not found`*: `packages.txt` must be at the repo root containing `gdal-bin`.
- *Build fails on `-e .`*: replace it with `.` in `requirements.txt`.
- *Map tab blank, Image tab fine*: the browser is blocking the Leaflet CDN or Esri tiles (corporate network); the KMZ is unaffected.
- *"isn't in the precomputed menu"*: thresholds are limited to the menu in `gridded_climo/query.py`; add one and re-run precompute.
  Locally you can set `GRIDDED_CLIMO_ALLOW_LIVE=1` to compute off-menu thresholds live (slow).
