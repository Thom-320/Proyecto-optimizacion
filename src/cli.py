"""
CLI principal del pipeline SITP.
"""
import argparse
import json
import os
import sys
from typing import Optional

import pandas as pd
import pulp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config, crear_directorios
from src.data import extract, process
from src.features import crosswalk, pvr_gtfs, cost_matrix
from src.model import assign_lp, assign_mip


def _compute_sensitivity(
    scale: float,
    overflow_penalty_km: Optional[float],
    lp_solver: str,
) -> dict:
    result = {
        "scale": scale,
        "objective_km": None,
        "patios_saturados": "",
        "rutas_sin_asignacion": "",
        "notas": "",
    }
    try:
        modelo = assign_lp.ModeloAsignacionLP(
            objetivo="distancia",
            relax=False,
            cap_multiplier=scale,
            export_results=False,
            overflow_penalty_km=overflow_penalty_km,
            lp_solver=lp_solver,
        )
        modelo.cargar_datos()
        modelo.construir_modelo()
    except ValueError as exc:
        result["notas"] = str(exc)
        return result, None
    if not modelo.resolver():
        result["notas"] = "Solver no encontró solución óptima"
        return result, None
    modelo.exportar()
    objetivo = float(pulp.value(modelo.modelo.objective))
    result["objective_km"] = objetivo
    saturados = []
    for p in modelo.patios:
        name = f"Capacidad_Patio_{p}"
        constr = modelo.modelo.constraints.get(name)
        if constr is not None:
            slack = getattr(constr, "slack", None)
            if slack is not None and abs(slack) < 1e-5:
                saturados.append(p)
    result["patios_saturados"] = ",".join(saturados)
    if modelo.resultados_df is not None:
        asignados = modelo.resultados_df.groupby("geo_code")["buses"].sum()
        faltantes = [r for r in modelo.rutas if abs(asignados.get(r, 0) - modelo.pvr[r]) > 1e-3]
        if faltantes:
            result["rutas_sin_asignacion"] = ",".join(faltantes)
    return result, modelo


def cmd_extract(_args: argparse.Namespace) -> int:
    crear_directorios()
    extract.main()
    return 0


def cmd_process(_args: argparse.Namespace) -> int:
    if not os.path.exists(os.path.join(Config.DATA_RAW, "gtfs")):
        print("❌ GTFS no descargado. Ejecuta primero: python -m src.cli extract")
        return 1
    process.main()
    return 0


def cmd_crosswalk(_args: argparse.Namespace) -> int:
    required = [
        os.path.join(Config.DATA_PROCESSED, "rutas_bk.geojson"),
        os.path.join(Config.DATA_RAW, "gtfs", "routes.txt"),
    ]
    missing = [path for path in required if not os.path.exists(path)]
    if missing:
        for path in missing:
            print(f"❌ Falta archivo requerido: {path}")
        print("Ejecuta previamente: python -m src.cli extract && python -m src.cli process")
        return 1
    crosswalk.main()
    return 0


def cmd_pvr(args: argparse.Namespace) -> int:
    if not os.path.exists(os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv")):
        print("❌ Crosswalk no encontrado. Ejecuta primero: python -m src.cli crosswalk")
        return 1
    success = pvr_gtfs.main(
        layover_factor=args.layover_factor,
        date=args.date,
        auto_weekday=args.auto_weekday,
    )
    return 0 if success else 1


def cmd_costs(args: argparse.Namespace) -> int:
    if not os.path.exists(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv")):
        print("❌ PVR no calculado. Ejecuta antes: python -m src.cli pvr --date YYYY-MM-DD")
        return 1
    terminal_mode = args.terminal_mode or None
    success = cost_matrix.main(terminal_mode=terminal_mode, use_osrm=args.osrm)
    return 0 if success else 1


def cmd_solve(args: argparse.Namespace) -> int:
    if not os.path.exists(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json")):
        print("❌ Matriz de costos no encontrada. Ejecuta: python -m src.cli costs")
        return 1
    try:
        if args.mode == "lp":
            assign_lp.main(
                objetivo=args.objective,
                relax=False,
                cap_multiplier=args.capacities_scale if hasattr(args, "capacities_scale") else 1.0,
                kmax=args.kmax if hasattr(args, "kmax") else None,
                max_distance_km=args.max_distance_km if hasattr(args, "max_distance_km") else None,
                overflow_penalty_km=args.overflow_penalty_km if hasattr(args, "overflow_penalty_km") else None,
            )
        elif args.mode == "lp_relax":
            assign_lp.main(
                objetivo=args.objective,
                relax=True,
                cap_multiplier=args.capacities_scale if hasattr(args, "capacities_scale") else 1.0,
                max_distance_km=args.max_distance_km if hasattr(args, "max_distance_km") else None,
            )
        else:
            assign_mip.main(objetivo=args.objective)
    except (ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        return 1
    return 0


def cmd_sensitivity(args: argparse.Namespace) -> int:
    scales = args.capacities_scale or [1.0]
    overflow_penalty = getattr(args, "overflow_penalty_km", None)
    lp_solver = getattr(args, "lp_solver", "cbc")
    rows = []
    feasible_models = {}
    for scale in scales:
        res, model = _compute_sensitivity(scale, overflow_penalty, lp_solver)
        rows.append(res)
        if model is not None:
            feasible_models[scale] = model
    os.makedirs(Config.DATA_RESULTS, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(Config.DATA_RESULTS, "sensitivity_capacities.csv"), index=False)

    if feasible_models:
        # Usar el escenario factible con mayor escala
        base_scale = max(feasible_models.keys())
        base_model = feasible_models[base_scale]
        base_objective = float(pulp.value(base_model.modelo.objective))
        base_capacidades = base_model.capacidades.copy()
        shadow_rows = []
        for patio, cap in base_capacidades.items():
            override = {patio: cap + 1}
            try:
                modelo = assign_lp.ModeloAsignacionLP(
                    objetivo="distancia",
                    relax=False,
                    cap_multiplier=base_scale,
                    capacity_override=override,
                    export_results=False,
                )
                modelo.cargar_datos()
                modelo.construir_modelo()
                if not modelo.resolver():
                    raise RuntimeError("Solver no converge")
                obj = float(pulp.value(modelo.modelo.objective))
                delta = base_objective - obj
                note = ""
            except Exception as exc:  # noqa: BLE001
                obj = None
                delta = None
                note = str(exc)
            shadow_rows.append(
                {
                    "patio_id": patio,
                    "scale_base": base_scale,
                    "base_capacity": cap,
                    "base_objective_km": base_objective,
                    "objective_with_plus1": obj,
                    "delta_objective_km": delta,
                    "notas": note,
                }
            )
        pd.DataFrame(shadow_rows).to_csv(
            os.path.join(Config.DATA_RESULTS, "shadow_like_by_depot.csv"), index=False
        )
    else:
        print("⚠️  Ningún escenario fue factible; no se generó shadow_like_by_depot.csv")
    return 0


def cmd_diagnose(_args: argparse.Namespace) -> int:
    os.makedirs(Config.DATA_RESULTS, exist_ok=True)
    report_lines = []
    exit_code = 0

    # Crosswalk coverage
    crosswalk_report_path = os.path.join(Config.DATA_PROCESSED, "crosswalk_report.txt")
    if not os.path.exists(crosswalk_report_path):
        report_lines.append("CROSSWALK: ❌ No se encontró crosswalk_report.txt. Ejecuta 'python -m src.cli crosswalk'.")
        exit_code = 1
    else:
        with open(crosswalk_report_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        missing = data.get("missing", 0)
        manual = data.get("manual", 0)
        report_lines.append(
            f"CROSSWALK: {'✅' if missing == 0 else '⚠️'} total={data.get('total', 0)} exact={data.get('exact', 0)} "
            f"geo={data.get('geospatial', 0)} manual={manual} missing={missing}"
        )
        if missing > 0:
            exit_code = 1

    # PVR y matrices
    rutas_sin_costos = []
    rutas_sin_cobertura = []
    try:
        pvr_df = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))
        pvr_df = pvr_df[pvr_df["PVR"].notna()]
        rutas_pvr = pvr_df[pvr_df["PVR"] > 0]["geo_code"].tolist()
    except FileNotFoundError:
        report_lines.append("PVR: ❌ data/processed/pvr_por_ruta.csv no encontrado. Ejecuta 'pvr'.")
        rutas_pvr = []
        exit_code = 1

    try:
        with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), "r", encoding="utf-8") as fh:
            distancias = json.load(fh)
    except FileNotFoundError:
        report_lines.append("COSTOS: ❌ matriz_distancias.json no encontrado. Ejecuta 'costs'.")
        distancias = {}
        exit_code = 1

    if rutas_pvr and distancias:
        patios = list(distancias.keys())
        # Construir matriz de compatibilidad A[r,p] (igual que en assign_lp.py)
        import math
        A = {}
        viable_pairs = 0
        for ruta in rutas_pvr:
            tiene_alguno = False
            for patio in patios:
                costo_val = distancias.get(patio, {}).get(ruta)
                if costo_val is not None and math.isfinite(costo_val):
                    A[(ruta, patio)] = 1
                    tiene_alguno = True
                    viable_pairs += 1
                else:
                    A[(ruta, patio)] = 0
            if not tiene_alguno:
                rutas_sin_cobertura.append(ruta)
        
        if rutas_sin_cobertura:
            report_lines.append(
                f"COBERTURA A[r,p]: ❌ {len(rutas_sin_cobertura)} rutas sin compatibilidad con ningún patio → "
                + ",".join(sorted(set(rutas_sin_cobertura))[:10])
            )
            exit_code = 1
        else:
            report_lines.append(
                f"COBERTURA A[r,p]: ✅ {viable_pairs} pares (ruta,patio) viables de {len(rutas_pvr) * len(patios)} posibles"
            )
        
        # Verificar costos faltantes (más estricto)
        for ruta in rutas_pvr:
            missing_cost = False
            for patio in patios:
                valor = distancias.get(patio, {}).get(ruta)
                if valor is None:
                    missing_cost = True
                    break
            if missing_cost:
                rutas_sin_costos.append(ruta)
        if rutas_sin_costos:
            report_lines.append(
                "COSTOS: ⚠️ rutas sin costo en algún patio → " + ",".join(sorted(set(rutas_sin_costos))[:10])
            )
            exit_code = max(exit_code, 1)
        else:
            report_lines.append("COSTOS: ✅ matriz completa para rutas con PVR>0")

    # Capacidad vs PVR
    try:
        with open(os.path.join(Config.DATA_PROCESSED, "capacidades_patios.json"), "r", encoding="utf-8") as fh:
            cap_data = json.load(fh)
        cap_total = cap_data.get("cap_total", 0)
    except FileNotFoundError:
        report_lines.append("CAPACIDADES: ❌ capacidades_patios.json no encontrado. Ejecuta 'process'.")
        cap_total = 0
        exit_code = 1

    total_pvr = None
    if rutas_pvr:
        total_pvr = float(pvr_df["PVR"].sum())
    if total_pvr is not None and cap_total:
        if cap_total >= total_pvr:
            report_lines.append(f"CAPACIDADES: ✅ ΣPVR={total_pvr:.0f} ≤ ΣCap={cap_total:.0f}")
        else:
            report_lines.append(
                f"CAPACIDADES: ❌ ΣPVR={total_pvr:.0f} > ΣCap={cap_total:.0f} (déficit: {total_pvr - cap_total:.0f})"
            )
            exit_code = 1

    report_path = os.path.join(Config.DATA_RESULTS, "diagnose_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report_lines))

    for line in report_lines:
        print(line)

    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline de optimización SITP", formatter_class=argparse.RawTextHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")

    parser_extract = subparsers.add_parser("extract", help="Descarga datos crudos (GTFS y geo)")
    parser_extract.set_defaults(func=cmd_extract)

    parser_process = subparsers.add_parser("process", help="Procesa datos para Bosa y Kennedy")
    parser_process.set_defaults(func=cmd_process)

    parser_crosswalk = subparsers.add_parser("crosswalk", help="Genera correspondencia GTFS↔Geo")
    parser_crosswalk.set_defaults(func=cmd_crosswalk)

    parser_pvr = subparsers.add_parser("pvr", help="Calcula Peak Vehicle Requirement")
    parser_pvr.add_argument("--layover-factor", type=float, default=None)
    parser_pvr.add_argument("--date", type=str, default=None, help="Fecha YYYY-MM-DD para PVR")
    parser_pvr.add_argument(
        "--auto-weekday",
        action="store_true",
        help="Elegir automáticamente el último lunes con servicio (ignora --date si es necesario)",
    )
    parser_pvr.set_defaults(func=cmd_pvr)

    parser_costs = subparsers.add_parser("costs", help="Construye matrices de costos")
    parser_costs.add_argument("--osrm", action="store_true", help="Usar OSRM")
    parser_costs.add_argument(
        "--terminal-mode",
        choices=["weighted", "max_arrivals", "conservative", "conservative=max"],
        default=None,
    )
    parser_costs.set_defaults(func=cmd_costs)

    parser_solve = subparsers.add_parser("solve", help="Resuelve el modelo LP o MIP")
    parser_solve.add_argument("--mode", choices=["lp", "lp_relax", "mip"], default="lp")
    parser_solve.add_argument("--objective", choices=["distancia", "tiempo"], default="distancia")
    parser_solve.add_argument(
        "--capacities-scale",
        type=float,
        default=1.0,
        help="Factor multiplicador para escalar todas las capacidades (default: 1.0)",
    )
    parser_solve.add_argument(
        "--kmax",
        type=int,
        default=None,
        help="Límite máximo de patios por ruta (opcional, activa variables z[r,p] y restricciones MIP)",
    )
    parser_solve.add_argument(
        "--max-distance-km",
        type=float,
        default=None,
        help="Umbral máximo de distancia para considerar compatible un par (ruta,patio)",
    )
    parser_solve.add_argument(
        "--overflow-penalty-km",
        type=float,
        default=None,
        help="Penalización en km para buses asignados a patio overflow (activa patio virtual)",
    )
    parser_solve.set_defaults(func=cmd_solve)

    parser_sensitivity = subparsers.add_parser("sensitivity", help="Análisis de sensibilidad de capacidades")
    parser_sensitivity.add_argument(
        "--capacities-scale",
        nargs="*",
        type=float,
        default=[0.8, 1.0, 1.2],
        help="Factores de capacidad global a evaluar (default: 0.8 1.0 1.2)",
    )
    parser_sensitivity.set_defaults(func=cmd_sensitivity)

    parser_diagnose = subparsers.add_parser("diagnose", help="Ejecuta validaciones de consistencia")
    parser_diagnose.set_defaults(func=cmd_diagnose)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    crear_directorios()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
