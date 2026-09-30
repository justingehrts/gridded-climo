"""GeoTIFF -> colorized PNG -> KMZ GroundOverlay, using the GDAL CLI (same flow as geotiff-to-kmz)."""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from ..grid import NODATA  # noqa: E402
from ..registry import Style  # noqa: E402
from .ramps import color_table, get_cmap  # noqa: E402


def _write_color_file(path: Path, table) -> None:
    """gdaldem color-relief text table. `nv` = NoData. Note: unlike geotiff-to-kmz we do NOT force
    true-zero pixels transparent -- zero is a real value for departures and day-offsets."""
    lines = ["nv 0 0 0 0"]
    for v, r, g, b, a in table:
        lines.append(f"{v:.6f} {r} {g} {b} {a}")
    path.write_text("\n".join(lines) + "\n")


def auto_range(tif: Path, style: Style) -> tuple[float, float]:
    if style.vmin is not None and style.vmax is not None:
        return style.vmin, style.vmax
    with rasterio.open(tif) as src:
        a = src.read(1, masked=True).compressed()
    if a.size == 0:
        raise ValueError("raster has no valid data to render (all NoData)")
    lo, hi = np.percentile(a, [2, 98])
    return (style.vmin if style.vmin is not None else float(lo)), (style.vmax if style.vmax is not None else float(hi))


def _legend_png(style: Style, vmin: float, vmax: float, title: str, fmt: Callable[[float], str]) -> bytes:
    fig, ax = plt.subplots(figsize=(4.2, 1.0), dpi=150)
    n = style.steps if style.mode == "stepped" else 256
    cmap = get_cmap(style).resampled(n) if style.mode == "stepped" else get_cmap(style)
    ax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=cmap, extent=[vmin, vmax, 0, 1])
    ax.set_yticks([])
    ticks = np.linspace(vmin, vmax, 5)
    ax.set_xticks(ticks, [fmt(t) for t in ticks], fontsize=7)
    ax.set_title(title, fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", transparent=False, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def render_kmz(
    tif: str | Path, out_kmz: str | Path, style: Style, name: str,
    clip: tuple[float, float, float, float] | None = None,
    legend_title: str | None = None, label_fmt: Callable[[float], str] | None = None,
) -> Path:
    tif, out_kmz = Path(tif), Path(out_kmz)
    out_kmz.parent.mkdir(parents=True, exist_ok=True)
    vmin, vmax = auto_range(tif, style)
    table = color_table(style, vmin, vmax)
    with tempfile.TemporaryDirectory(prefix="gridded_climo_") as td:
        td = Path(td)
        ctab, warped, png = td / "color_map.txt", td / "warped.tif", td / "output.png"
        _write_color_file(ctab, table)
        clip_args = ["-te", *(str(c) for c in clip)] if clip else []
        stepped = style.mode == "stepped"
        subprocess.run(
            ["gdalwarp", "-q", "-t_srs", "EPSG:4326", "-dstalpha", "-dstnodata", str(NODATA), "-r", "near" if stepped else "bilinear",
             *clip_args, str(tif), str(warped)], check=True)
        subprocess.run(
            ["gdaldem", "color-relief", "-q", str(warped), str(ctab), str(png), "-alpha"], check=True)
        ext = json.loads(subprocess.run(["gdalinfo", "-json", str(warped)], capture_output=True, text=True, check=True).stdout)
        ring = ext["wgs84Extent"]["coordinates"][0]
        lons, lats = [c[0] for c in ring], [c[1] for c in ring]
        legend = _legend_png(style, vmin, vmax, legend_title or style.units_label, label_fmt or (lambda v: f"{v:g}")) \
            if legend_title is not None or style.units_label else None
        kml = (
            '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape(name)}</name>"
            f"<GroundOverlay><name>{escape(name)}</name><Icon><href>output.png</href></Icon>"
            f"<LatLonBox><north>{max(lats)}</north><south>{min(lats)}</south><east>{max(lons)}</east><west>{min(lons)}</west></LatLonBox></GroundOverlay>"
            + ('<ScreenOverlay><name>Legend</name><Icon><href>legend.png</href></Icon>'
               '<overlayXY x="0" y="0" xunits="fraction" yunits="fraction"/><screenXY x="0.01" y="0.02" xunits="fraction" yunits="fraction"/>'
               '<size x="0" y="0" xunits="pixels" yunits="pixels"/></ScreenOverlay>' if legend else "")
            + "</Document></kml>"
        )
        with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.kml", kml)
            z.write(png, "output.png")
            if legend:
                z.writestr("legend.png", legend)
    return out_kmz
