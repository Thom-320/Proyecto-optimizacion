"""
Procesamiento y filtrado de datos para Bosa y Kennedy.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import geopandas as gpd
import pandas as pd

from src.config import Config, crear_directorios


class ProcesadorDatos:
    def __init__(self) -> None:
        self.path_capacidades = os.path.join(Config.DATA_PROCESSED, "capacidades_patios.json")

    def cargar(self) -> bool:
        try:
            self.zonas = gpd.read_file(os.path.join(Config.DATA_RAW, "zonas_sitp.geojson"))
            self.patios = gpd.read_file(os.path.join(Config.DATA_RAW, "patios_sitp.geojson"))
            self.rutas = gpd.read_file(os.path.join(Config.DATA_RAW, "rutas_sitp.geojson"))
            self.paraderos = gpd.read_file(os.path.join(Config.DATA_RAW, "paraderos_zonales.geojson"))
            print("✓ Datos geoespaciales cargados")
            return True
        except Exception as exc:
            print(f"❌ Error cargando datos: {exc}")
            return False

    def filtrar(self) -> bool:
        try:
            zonas_objetivo = self.zonas[self.zonas["zona"].isin(Config.LOCALIDADES)]
            self.patios_bk = gpd.sjoin(
                self.patios,
                zonas_objetivo[["zona", "geometry"]],
                how="inner",
                predicate="within",
            )
            self.paraderos_bk = self.paraderos[self.paraderos["localidad_"].isin(Config.NUM_LOCALIDAD)]
            self.rutas_bk = self.rutas[
                self.rutas["loc_dest"].isin(Config.NUM_LOCALIDAD)
                & self.rutas["tip_serv"].isin(Config.TIPO_RUTA)
            ]
            print(
                f"✓ Patios filtrados: {len(self.patios_bk)}, "
                f"Paraderos: {len(self.paraderos_bk)}, Rutas: {len(self.rutas_bk)}"
            )
            return True
        except Exception as exc:
            print(f"❌ Error filtrando localidades: {exc}")
            return False

    def _estimar_capacidad(self, geometry) -> int:
        try:
            gdf = gpd.GeoDataFrame([{"geometry": geometry}], crs="EPSG:4326").to_crs(Config.CRS_PROYECCION)
            area = gdf.geometry.area.iloc[0]
            return max(5, int(area * Config.CAPACIDAD_ESTIMACION_FACTOR))
        except Exception:
            return Config.CAPACIDAD_PATIO_DEFAULT

    def guardar(self) -> bool:
        try:
            crear_directorios()
            self.patios_bk.to_file(os.path.join(Config.DATA_PROCESSED, "patios_bk.geojson"), driver="GeoJSON")
            self.rutas_bk.to_file(os.path.join(Config.DATA_PROCESSED, "rutas_bk.geojson"), driver="GeoJSON")
            self.paraderos_bk.to_file(os.path.join(Config.DATA_PROCESSED, "paraderos_bk.geojson"), driver="GeoJSON")

            capacidades: Dict[str, Dict[str, Any]] = {}
            metadata: Dict[str, Dict[str, Any]] = {}

            posibles_cols = ["cap_total", "capacidad", "capacity"]
            col_cap = next((c for c in posibles_cols if c in self.patios_bk.columns), None)

            for _, row in self.patios_bk.iterrows():
                patio_id = row.get("objectid") or row.get("OBJECTID") or row.get("id") or row.get("Id")
                if patio_id is None:
                    continue
                patio_id = str(int(patio_id))
                capacidad = None
                estimado = False
                metodo = "cap_total"
                if col_cap and pd.notna(row[col_cap]):
                    try:
                        val = float(str(row[col_cap]).replace(",", "").strip())
                        if val > 0:
                            capacidad = int(val)
                    except Exception:
                        capacidad = None
                if capacidad is None or capacidad <= 0:
                    capacidad = self._estimar_capacidad(row.geometry)
                    estimado = True
                    metodo = "area"
                capacidades[patio_id] = {"capacidad": capacidad}
                metadata[patio_id] = {"metodo": metodo, "estimado": estimado}

            cap_total = sum(item["capacidad"] for item in capacidades.values())
            salida = {
                "capacidades": {pid: data["capacidad"] for pid, data in capacidades.items()},
                "metadata": metadata,
                "cap_total": cap_total,
            }
            with open(self.path_capacidades, "w", encoding="utf-8") as fh:
                json.dump(salida, fh, indent=2, ensure_ascii=False)
            print(f"✓ Capacidades guardadas (total={cap_total})")
            return True
        except Exception as exc:
            print(f"❌ Error guardando datos procesados: {exc}")
            return False


def main() -> None:
    print("=== PROCESAMIENTO DE DATOS ===")
    procesador = ProcesadorDatos()
    if not procesador.cargar():
        return
    if not procesador.filtrar():
        return
    procesador.guardar()
