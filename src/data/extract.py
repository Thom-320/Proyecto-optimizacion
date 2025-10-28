"""
Descarga datasets geoespaciales y GTFS.
"""
from __future__ import annotations

import os
import zipfile
from typing import Optional

import geopandas as gpd
import requests

from src.config import Config, crear_directorios


def _download_geojson(url: str, filename: str) -> Optional[str]:
    try:
        gdf = gpd.read_file(url)
        path = os.path.join(Config.DATA_RAW, f"{filename}.geojson")
        gdf.to_file(path, driver="GeoJSON")
        print(f"✓ {filename} ({len(gdf)})")
        return path
    except Exception as exc:
        print(f"❌ Error descargando {filename}: {exc}")
        return None


def _download_gtfs(url: str, filename: str = "gtfs.zip") -> Optional[str]:
    zip_path = os.path.join(Config.DATA_RAW, filename)
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        with open(zip_path, "wb") as fh:
            fh.write(response.content)
        print(f"✓ GTFS descargado ({len(response.content)/1024/1024:.1f} MB)")
        gtfs_dir = os.path.join(Config.DATA_RAW, "gtfs")
        os.makedirs(gtfs_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(gtfs_dir)
        print(f"✓ GTFS extraído en {gtfs_dir}")
        return gtfs_dir
    except Exception as exc:
        print(f"❌ Error descargando GTFS: {exc}")
        return None


def main() -> None:
    print("=== DESCARGA DE DATOS ===")
    crear_directorios()
    _download_geojson(Config.URL_ZONAS, "zonas_sitp")
    _download_geojson(Config.URL_PATIOS, "patios_sitp")
    _download_geojson(Config.URL_RUTAS, "rutas_sitp")
    _download_geojson(Config.URL_PARADEROS, "paraderos_zonales")
    _download_gtfs(Config.URL_GTFS)
