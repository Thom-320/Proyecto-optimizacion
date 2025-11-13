"""
Modelo MIP por bus individual.
"""
from __future__ import annotations

import json
import os

import pandas as pd
import pulp

from src.config import Config


class ModeloAsignacionMIP:
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
        self.patios = list(self.distancias.keys())
        self.rutas = [ruta for ruta in self.pvr if all(ruta in self.distancias[p] for p in self.patios)]
        missing = [ruta for ruta in self.pvr if ruta not in self.rutas]
        if missing:
            raise ValueError("Rutas sin costos en todos los patios: " + ", ".join(missing[:10]))

    def construir_modelo(self) -> None:
        costos = self.distancias if self.objetivo == "distancia" else self.tiempos
        self.modelo = pulp.LpProblem("AsignacionMIP", pulp.LpMinimize)
        self.buses = [(r, i) for r in self.rutas for i in range(int(self.pvr[r]))]
        self.x = {
            (r, b, p): pulp.LpVariable(f"x_{r}_{b}_{p}", cat="Binary")
            for r, b in self.buses for p in self.patios
        }
        self.modelo += pulp.lpSum(costos[p][r] * self.x[(r, b, p)] for (r, b, p) in self.x)
        for r, b in self.buses:
            self.modelo += pulp.lpSum(self.x[(r, b, p)] for p in self.patios) == 1
        for p in self.patios:
            capacidad = int(self.capacidades.get(p, Config.CAPACIDAD_PATIO_DEFAULT))
            self.modelo += pulp.lpSum(self.x[(r, b, p)] for r, b in self.buses) <= capacidad

    def resolver(self) -> bool:
        solver = pulp.PULP_CBC_CMD(timeLimit=Config.SOLVER_TIME_LIMIT, msg=False)
        result = self.modelo.solve(solver)
        return result == pulp.LpStatusOptimal

    def exportar(self) -> None:
        asignaciones = []
        for (r, b, p), var in self.x.items():
            if var.value() == 1:
                asignaciones.append({"geo_code": r, "bus": b, "patio_id": p})
        df = pd.DataFrame(asignaciones)
        os.makedirs(Config.DATA_RESULTS, exist_ok=True)
        df.to_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_mip.csv"), index=False)


def main(objetivo: str = "distancia") -> None:
    modelo = ModeloAsignacionMIP(objetivo=objetivo)
    modelo.cargar_datos()
    modelo.construir_modelo()
    if not modelo.resolver():
        raise RuntimeError("El solver MIP no encontró solución óptima.")
    modelo.exportar()
