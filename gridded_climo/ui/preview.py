"""Folium preview of a rendered overlay, with broadcast-style reference layers on top of the data."""
from __future__ import annotations

import base64
import html
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


def build_map(png: bytes, bounds: tuple[float, float, float, float], counties=None, points: dict | None = None) -> folium.Map:
    south, west, north, east = bounds
    m = folium.Map(location=[(north + south) / 2, (east + west) / 2], tiles=None)
    folium.TileLayer(tiles="Esri.WorldGrayCanvas", name="Light Basemap", show=True).add_to(m)
    folium.TileLayer(tiles="Esri.WorldImagery", name="Satellite", show=False).add_to(m)
    folium.raster_layers.ImageOverlay(
        image="data:image/png;base64," + base64.b64encode(png).decode(), bounds=[[south, west], [north, east]],
        opacity=0.85, name="Data",
    ).add_to(m)
    folium.map.CustomPane("reference_pane", z_index=450).add_to(m)  # above the data overlay (400), below markers (600) and tooltips (650)
    folium.map.CustomPane("obs_pane", z_index=600).add_to(m)        # observation dots above the reference layers, so they get the clicks
    base = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
    for label, svc in (("Highways", "World_Transportation"), ("States & Cities", "World_Boundaries_and_Places")):
        folium.TileLayer(tiles=base.format(svc), attr=ESRI_ATTR, name=label, overlay=True, show=True, pane="reference_pane").add_to(m)
    if counties:
        folium.GeoJson(counties, name="Counties", style_function=lambda f: {"color": "#555555", "weight": 0.75, "fillOpacity": 0},
                       pane="reference_pane", interactive=False).add_to(m)   # outlines must never swallow clicks meant for the dots
    if points:
        fg = folium.FeatureGroup(name="Stations", show=True)
        for lo, la, lab, nm in zip(points["lon"], points["lat"], points["label"], points["name"]):
            folium.CircleMarker([la, lo], radius=4, color="#111", weight=1, fill=True, fill_opacity=0.9, pane="obs_pane",
                                tooltip=f"{nm}: {lab}",
                                popup=folium.Popup(f"<b>{html.escape(str(nm))}</b><br>{html.escape(str(lab))}", max_width=260)).add_to(fg)
        fg.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    return m
