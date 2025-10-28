"""
Generación de tabla de correspondencia entre rutas geo y GTFS.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from src.config import Config, crear_directorios

TOKEN_PATTERN = re.compile(r"[A-Za-z]\d[\dA-Za-z\-]*|[A-Za-z]{1,3}\d{1,3}|[A-Za-z]{2,}")


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def _extract_tokens(text: str) -> List[str]:
    if not text:
        return []
    return [token.upper() for token in TOKEN_PATTERN.findall(text)]


@dataclass
class MatchResult:
    geo_code: str
    gtfs_route_id: Optional[str]
    gtfs_route_short: Optional[str]
    match_method: str
    confidence: float


def _get_geo_code(row: pd.Series) -> str:
    for col in ["cod_linea", "codigo", "codigo_ruta", "cod_linea_", "abrevia"]:
        if col in row and pd.notna(row[col]):
            return str(row[col]).strip()
    if "nom_ruta" in row and pd.notna(row["nom_ruta"]):
        return str(row["nom_ruta"]).strip()
    return str(row.get("objectid", "desconocido"))


def _geo_route_points(geometry) -> Optional[Tuple[Point, Point]]:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
    else:
        try:
            coords = list(list(geometry.geoms)[0].coords)
        except Exception:
            return None
    if len(coords) < 2:
        return None
    return Point(coords[0]), Point(coords[-1])


def _build_gtfs_stops(gtfs_dir: str) -> Dict[str, List[Tuple[float, float]]]:
    trips = pd.read_csv(os.path.join(gtfs_dir, "trips.txt"), dtype=str)
    stop_times = pd.read_csv(os.path.join(gtfs_dir, "stop_times.txt"), dtype=str)
    stops = pd.read_csv(os.path.join(gtfs_dir, "stops.txt"), dtype={"stop_lat": float, "stop_lon": float})

    stops_dict = {row["stop_id"]: (row["stop_lon"], row["stop_lat"]) for _, row in stops.iterrows()}

    route_to_stops: Dict[str, List[Tuple[float, float]]] = {}
    for route_id, trips_route in trips.groupby("route_id"):
        trip_id = trips_route.iloc[0]["trip_id"]
        times_trip = stop_times[stop_times["trip_id"] == trip_id].sort_values("stop_sequence")
        coords = [stops_dict[stop_id] for stop_id in times_trip["stop_id"] if stop_id in stops_dict]
        if coords:
            route_to_stops[route_id] = coords
    return route_to_stops


def _distance(point: Point, coord: Tuple[float, float]) -> float:
    return point.distance(Point(coord[0], coord[1])) * 111_000


def _geospatial_match(
    points: Tuple[Point, Point],
    route_to_stops: Dict[str, List[Tuple[float, float]]],
    threshold_m: float = 120.0,
) -> Optional[Tuple[str, float]]:
    start, end = points
    best = None
    for route_id, coords in route_to_stops.items():
        d_start = min(_distance(start, coord) for coord in coords)
        d_end = min(_distance(end, coord) for coord in coords)
        if max(d_start, d_end) <= threshold_m:
            confidence = max(0.0, 1 - (d_start + d_end) / (2 * threshold_m))
            if best is None or confidence > best[1]:
                best = (route_id, confidence)
    return best


def _load_manual() -> Dict[str, MatchResult]:
    manual_path = os.path.join(Config.DATA_PROCESSED, "route_crosswalk_manual.csv")
    if not os.path.exists(manual_path):
        return {}
    manual = pd.read_csv(manual_path, dtype=str)
    overrides: Dict[str, MatchResult] = {}
    for _, row in manual.iterrows():
        geo_code = str(row["geo_code"])
        overrides[geo_code] = MatchResult(
            geo_code=geo_code,
            gtfs_route_id=row.get("gtfs_route_id"),
            gtfs_route_short=row.get("gtfs_route_short"),
            match_method=row.get("match_method", "manual"),
            confidence=float(row.get("confidence", 1.0)),
        )
    return overrides


def main() -> None:
    crear_directorios()
    rutas_geo = gpd.read_file(os.path.join(Config.DATA_PROCESSED, "rutas_bk.geojson"))
    routes_gtfs = pd.read_csv(os.path.join(Config.DATA_RAW, "gtfs", "routes.txt"), dtype=str)
    route_to_stops = _build_gtfs_stops(os.path.join(Config.DATA_RAW, "gtfs"))

    gtfs_by_short = {row["route_short_name"]: row for _, row in routes_gtfs.iterrows()}
    gtfs_by_id = {row["route_id"]: row for _, row in routes_gtfs.iterrows()}

    manual_overrides = _load_manual()

    stats = {"total": len(rutas_geo), "exact": 0, "token": 0, "geospatial": 0, "manual": len(manual_overrides), "missing": 0}
    results: Dict[str, MatchResult] = {}

    for _, row in rutas_geo.iterrows():
        geo_code = _get_geo_code(row)
        if geo_code in manual_overrides:
            results[geo_code] = manual_overrides[geo_code]
            continue

        geo_norm = _normalize(geo_code)
        route_id = None
        route_short = None
        method = "none"
        confidence = 0.0

        # Exacto
        for _, rt_row in routes_gtfs.iterrows():
            if _normalize(rt_row.get("route_short_name", "")) == geo_norm:
                route_id = rt_row["route_id"]
                route_short = rt_row.get("route_short_name")
                method = "exact"
                confidence = 1.0
                stats["exact"] += 1
                break

        # Tokens
        if route_id is None:
            geo_tokens = set(_extract_tokens(geo_code))
            if geo_tokens:
                for _, rt_row in routes_gtfs.iterrows():
                    rt_tokens = set(_extract_tokens(rt_row.get("route_short_name", "")))
                    if geo_tokens & rt_tokens:
                        route_id = rt_row["route_id"]
                        route_short = rt_row.get("route_short_name")
                        method = "token"
                        confidence = 0.7
                        stats["token"] += 1
                        break

        # Geoespacial
        if route_id is None:
            points = _geo_route_points(row.geometry)
            if points:
                geo_match = _geospatial_match(points, route_to_stops)
                if geo_match:
                    route_id = geo_match[0]
                    route_short = gtfs_by_id.get(route_id, {}).get("route_short_name") if route_id in gtfs_by_id else None
                    method = "geospatial"
                    confidence = round(geo_match[1], 3)
                    stats["geospatial"] += 1

        if route_id is None:
            stats["missing"] += 1
            results[geo_code] = MatchResult(geo_code, None, None, "unmatched", 0.0)
        else:
            results[geo_code] = MatchResult(geo_code, route_id, route_short, method, confidence)

    df = pd.DataFrame([res.__dict__ for res in results.values()]).sort_values("geo_code")
    output_path = os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv")
    df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"✓ Crosswalk guardado en {output_path} ({len(df)} filas)")

    report_path = os.path.join(Config.DATA_PROCESSED, "crosswalk_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, ensure_ascii=False)
    print(f"✓ Reporte guardado en {report_path}")
