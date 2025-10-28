"""
CLI principal del pipeline SITP.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config, crear_directorios
from src.data import extract, process
from src.features import crosswalk, pvr_gtfs, cost_matrix
from src.model import assign_lp, assign_mip


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
    success = pvr_gtfs.main(layover_factor=args.layover_factor, date=args.date)
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
            assign_lp.main(objetivo=args.objective)
        else:
            assign_mip.main(objetivo=args.objective)
    except (ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        return 1
    return 0


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
    parser_solve.add_argument("--mode", choices=["lp", "mip"], default="lp")
    parser_solve.add_argument("--objective", choices=["distancia", "tiempo"], default="distancia")
    parser_solve.set_defaults(func=cmd_solve)

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
