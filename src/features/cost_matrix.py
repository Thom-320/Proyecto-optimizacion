"""
Construcción de matrices de costos terminal→patio utilizando crosswalk.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
from geopy.distance import geodesic

from src.config import Config


def _load_crosswalk() -> pd.DataFrame:
    path = os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv")
    if not os.path.exists(path):
        raise FileNotFoundError("route_crosswalk.csv no encontrado. Ejecuta: python -m src.cli crosswalk")
    df = pd.read_csv(path, dtype=str)
    matched = df[df["gtfs_route_id"].notna()].copy()
    if matched.empty:
        raise ValueError("Crosswalk sin coincidencias; completa route_crosswalk_manual.csv y reintenta.")
    return matched


def _geo_terminal(gtfs_dir: str, route_id: str) -> Optional[Tuple[float, float]]:
    trips = pd.read_csv(os.path.join(gtfs_dir, "trips.txt"), dtype=str)
    stop_times = pd.read_csv(os.path.join(gtfs_dir, "stop_times.txt"), dtype=str)
    stops = pd.read_csv(os.path.join(gtfs_dir, "stops.txt"), dtype={"stop_lat": float, "stop_lon": float})

    trips_route = trips[trips["route_id"] == route_id]
    if trips_route.empty:
        return None
    trip_id = trips_route.iloc[0]["trip_id"]
    times = stop_times[stop_times["trip_id"] == trip_id].sort_values("stop_sequence")
    if times.empty:
        return None
    stop_id = times.iloc[-1]["stop_id"]
    stop_row = stops[stops["stop_id"] == stop_id]
    if stop_row.empty:
        return None
    return stop_row.iloc[0]["stop_lat"], stop_row.iloc[0]["stop_lon"]


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return geodesic((lat1, lon1), (lat2, lon2)).km


def main(terminal_mode: Optional[str] = None, use_osrm: bool = False) -> bool:
    del terminal_mode, use_osrm  # Parámetros reservados para futuras mejoras

    gtfs_dir = os.path.join(Config.DATA_RAW, "gtfs")
    crosswalk = _load_crosswalk()

    rutas_geo = gpd.read_file(os.path.join(Config.DATA_PROCESSED, "rutas_bk.geojson"))
    patios = gpd.read_file(os.path.join(Config.DATA_PROCESSED, "patios_bk.geojson"))

    patios_coords: Dict[str, Tuple[float, float]] = {}
    for _, patio in patios.iterrows():
        patio_id = str(int(patio.get("objectid", patio.get("OBJECTID", len(patios_coords)))))
        centroid = patio.geometry.centroid
        patios_coords[patio_id] = (centroid.y, centroid.x)

    matriz_distancias: Dict[str, Dict[str, float]] = {patio_id: {} for patio_id in patios_coords}
    matriz_tiempos: Dict[str, Dict[str, float]] = {patio_id: {} for patio_id in patios_coords}

    missing_geo = []
    for _, cross_row in crosswalk.iterrows():
        geo_code = cross_row["geo_code"]
        route_id = cross_row["gtfs_route_id"]
        latlon = _geo_terminal(gtfs_dir, route_id)
        if not latlon:
            missing_geo.append(geo_code)
            continue
        lat_r, lon_r = latlon
        for patio_id, (lat_p, lon_p) in patios_coords.items():
            dist = _distance(lat_r, lon_r, lat_p, lon_p)
            matriz_distancias[patio_id][geo_code] = round(dist, 2)
            matriz_tiempos[patio_id][geo_code] = round(dist / Config.VELOCIDAD_PROMEDIO * 60, 2)

    with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), "w", encoding="utf-8") as fh:
        json.dump(matriz_distancias, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"), "w", encoding="utf-8") as fh:
        json.dump(matriz_tiempos, fh, indent=2, ensure_ascii=False)

    pd.DataFrame({"patio_id": list(patios_coords.keys())}).to_csv(
        os.path.join(Config.DATA_PROCESSED, "terminales_por_ruta.csv"), index=False
    )

    print("✓ Matrices de distancia y tiempo generadas")
    if missing_geo:
        print("⚠️  Rutas sin terminal GTFS identificable:", ", ".join(missing_geo[:10]))
    return True
