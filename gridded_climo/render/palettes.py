"""Palette / legend import & export: MAX .wctrp, CSV, and JSON settings. (.wctrp + CSV parsing ported from geotiff-to-kmz.)"""
from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, fields

from ..registry import Style

Row = list  # [value, r, g, b, a]


class PaletteError(ValueError):
    pass


def parse_wctrp(data: bytes | str) -> tuple[list[Row], int]:
    """MAX weather-graphics contour palette (XML). Each contourElemN has a contourFrom value and a solid RGBA. Elements
    appear in lexicographic tag order (contourElem10 before contourElem2), so rows are sorted by value afterwards.
    Returns (rows, number of entries that used a named texture, which isn't supported; their solid color is still used)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise PaletteError(f"could not parse .wctrp as XML: {e}") from None
    rows, textured = [], 0
    for elem in root:
        if not elem.tag.startswith("contourElem"):
            continue
        f = elem.find("contourFrom")
        rgba = [elem.find(t) for t in ("paletteEntryRed", "paletteEntryGreen", "paletteEntryBlue", "paletteEntryAlpha")]
        if f is None or any(x is None for x in rgba):
            continue
        rows.append([float(f.text), *(int(x.text) for x in rgba)])
        tex = elem.find("textureFile/m_name")
        textured += tex is not None and tex.text != "Default"
    if not rows:
        raise PaletteError("no contour entries found in this .wctrp file")
    rows.sort(key=lambda r: r[0])
    return rows, textured


def parse_legend_csv(data: bytes | str) -> list[Row]:
    """CSV with columns Value, R, G, B and optional Alpha (header names case-insensitive)."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
    need = ["value", "r", "g", "b"]
    if any(n not in cols for n in need):
        raise PaletteError("CSV needs columns Value, R, G, B (and optionally Alpha)")
    rows = []
    for rec in reader:
        try:
            rows.append([float(rec[cols["value"]]), *(int(float(rec[cols[c]])) for c in ("r", "g", "b")),
                         int(float(rec[cols["alpha"]])) if "alpha" in cols and rec[cols["alpha"]] not in (None, "") else 255])
        except (TypeError, ValueError):
            raise PaletteError(f"bad row in CSV: {rec}") from None
    if not rows:
        raise PaletteError("the CSV has no rows")
    for r in rows:
        if not all(0 <= c <= 255 for c in r[1:]):
            raise PaletteError("R, G, B and Alpha must be 0-255")
    return sorted(rows, key=lambda r: r[0])


def sample_colors(rows: list[Row], n: int) -> list[list[int]]:
    """n colors from palette rows by position (nearest entry; palettes are categorical, so no blending)."""
    if n <= 0:
        return []
    m = len(rows)
    return [list(rows[min(m - 1, int(i * m / n + (m / n) / 2))][1:]) for i in range(n)]


def style_to_json(style: Style, name: str | None = None) -> str:
    """Settings as JSON. `name` (optional) is stored as a top-level label; loading ignores it."""
    return json.dumps({**({"name": name} if name else {}), **asdict(style)}, indent=2)


def style_from_json(text: str | bytes) -> Style:
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise PaletteError(f"not valid JSON: {e}") from None
    if not isinstance(d, dict):
        raise PaletteError("settings JSON must be an object")
    allowed = {f.name for f in fields(Style)}
    return Style(**{k: v for k, v in d.items() if k in allowed})
