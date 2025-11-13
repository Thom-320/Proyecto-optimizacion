"""
Modelo LP de transporte ruta-patio.

Formulación matemática:
  Conjuntos: R = rutas, P = patios
  Parámetros: PVR[r], Cap[p], c[r,p] >= 0, A[r,p] in {0,1}, K_max (opcional)
  Variables: x[r,p] in Z_>=0 (buses)
  FO: min sum_r sum_p c[r,p] * x[r,p]
  Restricciones:
    (1) sum_p x[r,p] = PVR[r] forall r
    (2) sum_r x[r,p] <= Cap[p] forall p
    (3) x[r,p] <= A[r,p] * PVR[r] forall r,p
    (4a) sum_p z[r,p] <= K_max forall r (opcional, si kmax > 0)
    (4b) x[r,p] <= PVR[r] * z[r,p] forall r,p (opcional, si kmax > 0)
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
import pulp

from src.config import Config


class ModeloAsignacionLP:
    def __init__(
        self,
        objetivo: str = "distancia",
        relax: bool = False,
        cap_multiplier: float = 1.0,
        capacity_override: Optional[Dict[str, int]] = None,
        export_results: bool = True,
        overflow_penalty_km: Optional[float] = None,
        lp_solver: str = "cbc",
        kmax: Optional[int] = None,
        max_distance_km: Optional[float] = None,
    ) -> None:
        self.objetivo = objetivo
        self.relax = relax
        self.cap_multiplier = cap_multiplier
        self.capacity_override = capacity_override or {}
        self.export_results = export_results
        self.overflow_penalty_km = overflow_penalty_km
        self.lp_solver = lp_solver.lower()
        self.kmax = kmax if kmax is not None and kmax > 0 else None
        self.max_distance_km = max_distance_km
        self.resultados_df: Optional[pd.DataFrame] = None
        self.resumen_patios_df: Optional[pd.DataFrame] = None
        self.total_cost: float = 0.0
        self.cap_total_base: float = 0.0
        self.cap_deficit: float = 0.0
        self.overflow_id = "overflow"
        self.A: Dict[tuple[str, str], int] = {}  # Matriz de compatibilidad A[r,p]
        self.z: Optional[Dict[tuple[str, str], pulp.LpVariable]] = None  # Variables z[r,p] si kmax > 0

    def cargar_datos(self) -> None:
        with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), "r", encoding="utf-8") as fh:
            self.distancias = json.load(fh)
        with open(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"), "r", encoding="utf-8") as fh:
            self.tiempos = json.load(fh)
        pvr = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))
        self.pvr = dict(zip(pvr["geo_code"], pvr["PVR"]))
        with open(os.path.join(Config.DATA_PROCESSED, "capacidades_patios.json"), "r", encoding="utf-8") as fh:
            cap_data = json.load(fh)
        raw_caps = {str(k): int(v) for k, v in cap_data["capacidades"].items()}
        scaled_caps = {}
        for patio, cap in raw_caps.items():
            if patio in self.capacity_override:
                new_cap = int(self.capacity_override[patio])
            else:
                new_cap = int(round(cap * self.cap_multiplier))
            scaled_caps[patio] = max(0, new_cap)
        self.capacidades = dict(scaled_caps)
        self.cap_total_base = float(sum(scaled_caps.values()))
        self.patios = list(self.distancias.keys())
        self.rutas = list(self.pvr.keys())
        if self.overflow_penalty_km is not None:
            self._add_overflow_patio()
        
        # Construir matriz de compatibilidad A[r,p]
        self._build_compatibility_matrix()
        
        # Validar cobertura: toda ruta debe tener al menos un patio compatible
        rutas_sin_cobertura = [r for r in self.rutas if all(self.A.get((r, p), 0) == 0 for p in self.patios)]
        if rutas_sin_cobertura:
            raise ValueError(
                f"Rutas sin compatibilidad con ningún patio (A[r,p]=0 para todo p): "
                f"{', '.join(rutas_sin_cobertura[:10])}"
            )
        
        # Filtrar rutas: solo mantener aquellas con al menos un patio compatible
        self.rutas = [r for r in self.rutas if any(self.A.get((r, p), 0) == 1 for p in self.patios)]
        
        self.cap_total = float(sum(self.capacidades.values()))
        self.total_pvr = float(sum(self.pvr[r] for r in self.rutas))
        self.cap_deficit = max(0.0, self.total_pvr - self.cap_total_base)
        if self.overflow_penalty_km is None and self.total_pvr > self.cap_total_base:
            raise ValueError(
                f"Capacidad insuficiente: ΣPVR={self.total_pvr:.0f} > ΣCap={self.cap_total_base:.0f}. "
                f"Usa --capacities-scale <factor> o ajusta capacidades_patios.json."
            )

    def _build_compatibility_matrix(self) -> None:
        """Construye A[r,p]: 1 si existe costo finito y distancia <= umbral (si aplica), 0 en otro caso."""
        costos = self.distancias if self.objetivo == "distancia" else self.tiempos
        viable_pairs = 0
        
        for r in self.rutas:
            for p in self.patios:
                # A[r,p] = 1 si existe costo finito
                costo_val = costos.get(p, {}).get(r)
                if costo_val is None or not math.isfinite(costo_val):
                    self.A[(r, p)] = 0
                    continue
                
                # Opcional: filtrar por umbral de distancia
                if self.max_distance_km is not None and self.objetivo == "distancia":
                    dist_val = self.distancias.get(p, {}).get(r)
                    if dist_val is None or dist_val > self.max_distance_km:
                        self.A[(r, p)] = 0
                        continue
                
                self.A[(r, p)] = 1
                viable_pairs += 1
        
        print(f"✓ Matriz de compatibilidad: {viable_pairs} pares (ruta,patio) viables de {len(self.rutas) * len(self.patios)} posibles")
    
    def construir_modelo(self) -> None:
        costos = self.distancias if self.objetivo == "distancia" else self.tiempos
        self.modelo = pulp.LpProblem("AsignacionTransporte", pulp.LpMinimize)
        var_cat = "Continuous" if self.relax else "Integer"
        
        # Variables x[r,p] in Z_>=0 (buses)
        self.x = {
            (r, p): pulp.LpVariable(f"x_{r}_{p}", lowBound=0, cat=var_cat)
            for r in self.rutas for p in self.patios
        }
        
        # Variables z[r,p] in {0,1} (opcional, si kmax > 0)
        if self.kmax is not None:
            self.z = {
                (r, p): pulp.LpVariable(f"z_{r}_{p}", cat="Binary")
                for r in self.rutas for p in self.patios
            }
        
        # FO: min sum_r sum_p c[r,p] * x[r,p]
        self.modelo += pulp.lpSum(
            costos[p][r] * self.x[(r, p)]
            for r in self.rutas for p in self.patios
            if self.A.get((r, p), 0) == 1  # Solo considerar pares compatibles
        )
        
        # Restricción (1): sum_p x[r,p] = PVR[r] forall r
        for r in self.rutas:
            self.modelo += (
                pulp.lpSum(self.x[(r, p)] for p in self.patios if self.A.get((r, p), 0) == 1) == int(self.pvr[r]),
                f"Demanda_Ruta_{r}"
            )
        
        # Restricción (2): sum_r x[r,p] <= Cap[p] forall p
        for p in self.patios:
            capacidad = int(self.capacidades.get(p, Config.CAPACIDAD_PATIO_DEFAULT))
            self.modelo += (
                pulp.lpSum(self.x[(r, p)] for r in self.rutas if self.A.get((r, p), 0) == 1) <= capacidad,
                f"Capacidad_Patio_{p}"
            )
        
        # Restricción (3): x[r,p] <= A[r,p] * PVR[r] forall r,p
        for r in self.rutas:
            for p in self.patios:
                if self.A.get((r, p), 0) == 0:
                    # Si no es compatible, forzar x[r,p] = 0
                    self.modelo += self.x[(r, p)] == 0, f"Compatibilidad_{r}_{p}"
                else:
                    # x[r,p] <= A[r,p] * PVR[r] = PVR[r] (ya que A[r,p]=1)
                    self.modelo += self.x[(r, p)] <= int(self.pvr[r]) * self.A[(r, p)], f"Límite_Compat_{r}_{p}"
        
        # Restricciones opcionales (4a) y (4b) si kmax > 0
        if self.kmax is not None and self.z is not None:
            # (4a): sum_p z[r,p] <= K_max forall r
            for r in self.rutas:
                self.modelo += (
                    pulp.lpSum(self.z[(r, p)] for p in self.patios if self.A.get((r, p), 0) == 1) <= self.kmax,
                    f"KMax_Ruta_{r}"
                )
            # (4b): x[r,p] <= PVR[r] * z[r,p] forall r,p
            for r in self.rutas:
                for p in self.patios:
                    if self.A.get((r, p), 0) == 1:
                        self.modelo += (
                            self.x[(r, p)] <= int(self.pvr[r]) * self.z[(r, p)],
                            f"Z_Binding_{r}_{p}"
                        )

    def resolver(self) -> bool:
        solver = self._create_solver()
        result = self.modelo.solve(solver)
        return result == pulp.LpStatusOptimal

    def exportar(self) -> None:
        asignaciones = []
        for (r, p), var in self.x.items():
            value = var.value()
            if value and value > 0:
                # Solo exportar si es compatible y tiene costo definido
                if self.A.get((r, p), 0) == 1 and r in self.distancias.get(p, {}):
                    costo = self.distancias[p][r]
                    asignaciones.append({"geo_code": r, "patio_id": p, "buses": float(value), "costo": costo})
        df = pd.DataFrame(asignaciones)
        resumen = pd.DataFrame()
        if not df.empty:
            resumen = df.groupby("patio_id")["buses"].sum().reset_index(name="buses_asignados")
        overflow_buses = float(df[df["patio_id"] == self.overflow_id]["buses"].sum()) if not df.empty else 0.0
        overflow_cost = float(
            (df[df["patio_id"] == self.overflow_id]["buses"] * df[df["patio_id"] == self.overflow_id]["costo"]).sum()
        ) if not df.empty else 0.0
        self.total_cost = float((df["buses"] * df["costo"]).sum()) if not df.empty else 0.0
        self.resultados_df = df
        self.resumen_patios_df = resumen

        if not self.export_results:
            return

        os.makedirs(Config.DATA_RESULTS, exist_ok=True)
        df.to_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"), index=False)
        resumen.to_csv(os.path.join(Config.DATA_RESULTS, "resumen_por_patio_lp.csv"), index=False)
        with open(os.path.join(Config.DATA_RESULTS, "resumen_ejecutivo_lp.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"Fecha: {datetime.now().isoformat()}\n")
            fh.write(f"Patios: {len(self.patios)}\n")
            fh.write(f"Rutas: {len(self.rutas)}\n")
            fh.write(f"Buses totales: {self.total_pvr}\n")
            fh.write(f"Capacidad base (sin overflow): {self.cap_total_base}\n")
            fh.write(f"Costo total (km): {self.total_cost:.2f}\n")
            if overflow_buses > 0:
                fh.write(f"Overflow buses: {overflow_buses:.2f} (costo penalizado: {overflow_cost:.2f} km)\n")
            elif self.cap_deficit > 0:
                fh.write(f"Déficit de capacidad (sin overflow): {self.cap_deficit:.2f} buses\n")

        # Si es relajación, intentar exportar duales y costos reducidos
        if self.relax:
            try:
                # Precios sombra de capacidad
                dual_rows = []
                for name, constr in self.modelo.constraints.items():
                    if name.startswith("Capacidad_Patio_"):
                        patio = name.replace("Capacidad_Patio_", "")
                        price = getattr(constr, "pi", None)
                        if price is not None:
                            dual_rows.append({"patio_id": patio, "shadow_price": float(price)})
                if dual_rows and self.export_results:
                    pd.DataFrame(dual_rows).to_csv(
                        os.path.join(Config.DATA_RESULTS, "duales_capacidad_lp.csv"), index=False
                    )
                # Costos reducidos
                rc_rows = []
                for (r, p), var in self.x.items():
                    dj = getattr(var, "dj", None)
                    if dj is not None:
                        rc_rows.append({"geo_code": r, "patio_id": p, "reduced_cost": float(dj)})
                if rc_rows and self.export_results:
                    pd.DataFrame(rc_rows).to_csv(
                        os.path.join(Config.DATA_RESULTS, "reduced_costs_lp.csv"), index=False
                    )
            except Exception:
                pass

    def _add_overflow_patio(self) -> None:
        if self.overflow_penalty_km is None:
            return
        if self.overflow_id in self.distancias:
            return
        overflow_costs: Dict[str, float] = {}
        overflow_times: Dict[str, float] = {}
        for ruta in self.rutas:
            costos_ruta = [self.distancias[p][ruta] for p in self.patios if ruta in self.distancias[p]]
            if not costos_ruta:
                raise ValueError(f"Ruta {ruta} sin costos definidos; no se puede calcular overflow.")
            max_cost = max(costos_ruta)
            penalty_cost = float(self.overflow_penalty_km * max_cost)
            overflow_costs[ruta] = round(penalty_cost, 2)
            if Config.VELOCIDAD_PROMEDIO > 0:
                penalty_time = penalty_cost / Config.VELOCIDAD_PROMEDIO * 60
            else:
                penalty_time = penalty_cost
            overflow_times[ruta] = round(penalty_time, 2)
        self.distancias[self.overflow_id] = overflow_costs
        self.tiempos[self.overflow_id] = overflow_times
        self.capacidades[self.overflow_id] = int(1e9)
        self.patios.append(self.overflow_id)

    def _create_solver(self):
        name = self.lp_solver
        if name == "cbc":
            solver = pulp.PULP_CBC_CMD(timeLimit=Config.SOLVER_TIME_LIMIT, msg=False)
        elif name == "glpk":
            solver = pulp.GLPK_CMD(msg=False)
        elif name == "clp":
            solver = pulp.COIN_CMD(msg=False)
        else:
            raise ValueError(f"Solver no soportado: {self.lp_solver}")
        if hasattr(solver, "available") and not solver.available():
            raise RuntimeError(f"Solver '{self.lp_solver}' no disponible en el entorno actual")
        return solver


def main(
    objetivo: str = "distancia",
    relax: bool = False,
    cap_multiplier: float = 1.0,
    capacity_override: Optional[Dict[str, int]] = None,
    overflow_penalty_km: Optional[float] = None,
    lp_solver: str = "cbc",
    kmax: Optional[int] = None,
    max_distance_km: Optional[float] = None,
) -> None:
    modelo = ModeloAsignacionLP(
        objetivo=objetivo,
        relax=relax,
        cap_multiplier=cap_multiplier,
        capacity_override=capacity_override,
        export_results=True,
        overflow_penalty_km=overflow_penalty_km,
        lp_solver=lp_solver,
        kmax=kmax,
        max_distance_km=max_distance_km,
    )
    modelo.cargar_datos()
    modelo.construir_modelo()
    if not modelo.resolver():
        raise RuntimeError("El solver LP no encontró solución óptima.")
    modelo.exportar()
