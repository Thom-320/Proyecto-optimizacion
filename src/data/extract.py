"""
Descarga datasets geoespaciales y GTFS.
"""
from __future__ import annotations

import os
import ssl
import zipfile
import time
from typing import Optional
import urllib.request
import warnings

import geopandas as gpd
import requests
import urllib3

# Suprimir warnings de SSL para datos públicos
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.config import Config, crear_directorios


def _download_geojson(url: str, filename: str) -> Optional[str]:
    last_exc: Optional[Exception] = None
    for i in range(3):
        try:
            # Intentar descargar con geopandas directamente
            try:
                gdf = gpd.read_file(url)
            except Exception:
                # Si falla, intentar con urllib.request (SSL relajado) y luego leer local
                try:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                    temp_path = os.path.join(Config.DATA_RAW, f"{filename}_temp.json")
                    urllib.request.urlretrieve(url, temp_path)
                    gdf = gpd.read_file(temp_path)
                    os.remove(temp_path)
                except Exception:
                    # Último intento de este ciclo: requests con verify=False
                    response = requests.get(url, verify=False, timeout=60)
                    response.raise_for_status()
                    temp_path = os.path.join(Config.DATA_RAW, f"{filename}_temp.json")
                    with open(temp_path, "wb") as f:
                        f.write(response.content)
                    gdf = gpd.read_file(temp_path)
                    os.remove(temp_path)

            path = os.path.join(Config.DATA_RAW, f"{filename}.geojson")
            gdf.to_file(path, driver="GeoJSON")
            print(f"✓ {filename} ({len(gdf)})")
            return path
        except Exception as exc:
            last_exc = exc
            wait = 2 ** i
            print(f"⚠️  Intento {i+1}/3 falló para {filename}: {exc}. Reintentando en {wait}s...")
            time.sleep(wait)
    print(f"❌ Error descargando {filename}: {last_exc}")
    print(f"   URL: {url[:80]}...")
    return None


def _download_gtfs(url: str, filename: str = "gtfs.zip") -> Optional[str]:
    zip_path = os.path.join(Config.DATA_RAW, filename)
    last_exc: Optional[Exception] = None
    for i in range(3):
        try:
            # Intentar con verify=True primero
            try:
                response = requests.get(url, timeout=180, verify=True)
            except requests.exceptions.SSLError:
                # Si falla SSL, intentar sin verificación (solo para datos públicos)
                print("⚠️  Advertencia SSL, intentando sin verificación de certificado...")
                response = requests.get(url, timeout=180, verify=False)

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
            last_exc = exc
            wait = 2 ** i
            print(f"⚠️  Intento {i+1}/3 falló para GTFS: {exc}. Reintentando en {wait}s...")
            time.sleep(wait)
    print(f"❌ Error descargando GTFS: {last_exc}")
    print(f"   URL: {url[:80]}...")
    return None


def main() -> None:
    print("=== DESCARGA DE DATOS ===")
    crear_directorios()
    _download_geojson(Config.URL_ZONAS, "zonas_sitp")
    _download_geojson(Config.URL_PATIOS, "patios_sitp")
    _download_geojson(Config.URL_RUTAS, "rutas_sitp")
    _download_geojson(Config.URL_PARADEROS, "paraderos_zonales")
    _download_gtfs(Config.URL_GTFS)
