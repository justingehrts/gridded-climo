"""Named style presets: plain JSON files (same format as 'Export style settings') in the repo's presets/ folder.

Streamlit Community Cloud's disk is ephemeral, so the app never writes presets itself: 'Save' downloads a file, and
committing it to presets/ makes it appear in everyone's dropdown after the next deploy."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .registry import Style
from .render.palettes import PaletteError, style_from_json

PRESET_DIR = Path(__file__).resolve().parents[1] / "presets"


def preset_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    if not slug:
        raise ValueError("give the preset a name (letters or numbers)")
    return slug


def list_presets(preset_dir: Path = PRESET_DIR) -> dict[str, Path]:
    """{display name: path}. The display name is the file's top-level "name" if present, else its file name."""
    out: dict[str, Path] = {}
    for p in sorted(Path(preset_dir).glob("*.json")):
        try:
            label = json.loads(p.read_text()).get("name") or p.stem.replace("-", " ")
        except (json.JSONDecodeError, AttributeError, OSError):
            continue   # a broken file shouldn't take the dropdown down
        out[str(label)] = p
    return out


def load_preset(name: str, preset_dir: Path = PRESET_DIR) -> Style:
    presets = list_presets(preset_dir)
    if name not in presets:
        raise PaletteError(f"no preset named '{name}'")
    return style_from_json(presets[name].read_bytes())
