"""Folium preview of a rendered overlay, with broadcast-style reference layers on top of the data."""
from __future__ import annotations

import base64
import json
import urllib.request

import folium

ESRI_ATTR = "Esri, HERE, Garmin, FAO, NOAA, USGS, © OpenStreetMap contributors, and the GIS User Community"
COUNTIES_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"


def load_counties_geojson():
    try:
        with urllib.request.urlopen(COUNTIES_URL, timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None  # preview still works without county lines


def build_map(png: bytes, bounds: tuple[float, float, float, float], counties=None) -> folium.Map:
    south, west, north, east = bounds
    m = folium.Map(location=[(north + south) / 2, (east + west) / 2], tiles=None)
    folium.TileLayer(tiles="Esri.WorldGrayCanvas", name="Light Basemap", show=True).add_to(m)
    folium.TileLayer(tiles="Esri.WorldImagery", name="Satellite", show=False).add_to(m)
    folium.raster_layers.ImageOverlay(
        image="data:image/png;base64," + base64.b64encode(png).decode(), bounds=[[south, west], [north, east]],
        opacity=0.85, name="Data",
    ).add_to(m)
    folium.map.CustomPane("reference_pane", z_index=650).add_to(m)  # above the overlay pane
    base = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    for label, svc in (("Highways", "World_Transportation"), ("States & Cities", "World_Boundaries_and_Places")):
        folium.TileLayer(tiles=base.format(svc), attr=ESRI_ATTR, name=label, overlay=True, show=True, pane="reference_pane").add_to(m)
    if counties:
        folium.GeoJson(counties, name="Counties", style_function=lambda f: {"color": "#555555", "weight": 0.75, "fillOpacity": 0},
                       pane="reference_pane").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    return m
