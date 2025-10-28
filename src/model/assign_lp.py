"""
Modelo LP de transporte ruta-patio.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pandas as pd
import pulp

from src.config import Config


class ModeloAsignacionLP:
    def __init__(self, objetivo: str = "distancia") -> None:
        self.objetivo = objetivo

    def cargar_datos(self) -> None:
        with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), "r", encoding="utf-8") as fh:
            self.distancias = json.load(fh)
        with open(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"), "r", encoding="utf-8") as fh:
            self.tiempos = json.load(fh)
        pvr = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))
        self.pvr = dict(zip(pvr["geo_code"], pvr["PVR"]))
        with open(os.path.join(Config.DATA_PROCESSED, "capacidades_patios.json"), "r", encoding="utf-8") as fh:
            cap_data = json.load(fh)
        self.capacidades = cap_data["capacidades"]
        self.cap_total = cap_data["cap_total"]
        self.patios = list(self.distancias.keys())
        self.rutas = [ruta for ruta in self.pvr if all(ruta in self.distancias[p] for p in self.patios)]
        missing = [ruta for ruta in self.pvr if ruta not in self.rutas]
        if missing:
            raise ValueError("Rutas sin costos en todos los patios: " + ", ".join(missing[:10]))
        total_pvr = sum(self.pvr.values())
        if total_pvr > self.cap_total:
            raise ValueError("Capacidad insuficiente. Ajusta las capacidades de los patios.")
        self.total_pvr = total_pvr

    def construir_modelo(self) -> None:
        costos = self.distancias if self.objetivo == "distancia" else self.tiempos
        self.modelo = pulp.LpProblem("AsignacionTransporte", pulp.LpMinimize)
        self.x = {
            (r, p): pulp.LpVariable(f"x_{r}_{p}", lowBound=0, cat="Integer")
            for r in self.rutas for p in self.patios
        }
        self.modelo += pulp.lpSum(costos[p][r] * self.x[(r, p)] for r in self.rutas for p in self.patios)
        for r in self.rutas:
            self.modelo += pulp.lpSum(self.x[(r, p)] for p in self.patios) == int(self.pvr[r])
        for p in self.patios:
            capacidad = int(self.capacidades.get(p, Config.CAPACIDAD_PATIO_DEFAULT))
            self.modelo += pulp.lpSum(self.x[(r, p)] for r in self.rutas) <= capacidad

    def resolver(self) -> bool:
        solver = pulp.PULP_CBC_CMD(timeLimit=Config.SOLVER_TIME_LIMIT, msg=False)
        result = self.modelo.solve(solver)
        return result == pulp.LpStatusOptimal

    def exportar(self) -> None:
        asignaciones = []
        for (r, p), var in self.x.items():
            value = var.value()
            if value and value > 0:
                costo = self.distancias[p][r]
                asignaciones.append({"geo_code": r, "patio_id": p, "buses": int(value), "costo": costo})
        df = pd.DataFrame(asignaciones)
        os.makedirs(Config.DATA_RESULTS, exist_ok=True)
        df.to_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"), index=False)
        resumen = df.groupby("patio_id")["buses"].sum().reset_index(name="buses_asignados")
        resumen.to_csv(os.path.join(Config.DATA_RESULTS, "resumen_por_patio_lp.csv"), index=False)
        with open(os.path.join(Config.DATA_RESULTS, "resumen_ejecutivo_lp.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"Fecha: {datetime.now().isoformat()}\n")
            fh.write(f"Patios: {len(self.patios)}\n")
            fh.write(f"Rutas: {len(self.rutas)}\n")
            fh.write(f"Buses totales: {self.total_pvr}\n")


def main(objetivo: str = "distancia") -> None:
    modelo = ModeloAsignacionLP(objetivo=objetivo)
    modelo.cargar_datos()
    modelo.construir_modelo()
    if not modelo.resolver():
        raise RuntimeError("El solver LP no encontró solución óptima.")
    modelo.exportar()
