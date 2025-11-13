"""
Genera comparativo baseline vs overflow.
"""
import os
import pandas as pd
from src.config import Config

OUTPUT_DIR = os.path.join(Config.DATA_RESULTS, "report")

# Leer resultados baseline (capacities-scale 1.2)
baseline_asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
baseline_obj = (baseline_asign["buses"] * baseline_asign["costo"]).sum()
baseline_patios = len(baseline_asign["patio_id"].unique())
baseline_overflow_buses = 0  # Baseline no tiene overflow

# Leer resultados overflow (si existen)
overflow_path = os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv")
# Asumimos que overflow generó resultados con patio "overflow"
if os.path.exists(overflow_path):
    overflow_asign = pd.read_csv(overflow_path)
    overflow_obj = (overflow_asign["buses"] * overflow_asign["costo"]).sum()
    overflow_patios = len(overflow_asign["patio_id"].unique())
    overflow_buses = overflow_asign[overflow_asign["patio_id"] == "overflow"]["buses"].sum() if "overflow" in overflow_asign["patio_id"].values else 0
else:
    # Si no existe, leer de los resultados recién generados (que incluyen overflow)
    try:
        overflow_asign = pd.read_csv(overflow_path)
        overflow_obj = (overflow_asign["buses"] * overflow_asign["costo"]).sum()
        overflow_patios = len(overflow_asign["patio_id"].unique())
        overflow_buses = overflow_asign[overflow_asign["patio_id"] == "overflow"]["buses"].sum() if "overflow" in overflow_asign["patio_id"].values else 0
    except:
        overflow_obj = None
        overflow_patios = None
        overflow_buses = None

# Leer resultados con overflow desde el último solve
overflow_asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
if "overflow" in overflow_asign["patio_id"].values:
    overflow_obj = (overflow_asign["buses"] * overflow_asign["costo"]).sum()
    overflow_patios = len(overflow_asign["patio_id"].unique())
    overflow_buses = overflow_asign[overflow_asign["patio_id"] == "overflow"]["buses"].sum()
else:
    overflow_obj = (overflow_asign["buses"] * overflow_asign["costo"]).sum()
    overflow_patios = len(overflow_asign["patio_id"].unique())
    overflow_buses = 0

# Generar comparativo
with open(os.path.join(OUTPUT_DIR, "comparativo_baseline_vs_overflow.txt"), "w") as f:
    f.write("=" * 70 + "\n")
    f.write("COMPARATIVO: BASELINE vs OVERFLOW\n")
    f.write("=" * 70 + "\n\n")
    f.write("BASELINE (--capacities-scale 1.2):\n")
    f.write(f"  Objetivo total: {baseline_obj:.2f} km\n")
    f.write(f"  Número de patios utilizados: {baseline_patios}\n")
    f.write(f"  Buses en overflow: {baseline_overflow_buses:.0f}\n")
    f.write("\n")
    f.write("OVERFLOW (--overflow-penalty-km 3.0):\n")
    if overflow_obj is not None:
        f.write(f"  Objetivo total: {overflow_obj:.2f} km\n")
        f.write(f"  Número de patios utilizados: {overflow_patios}\n")
        f.write(f"  Buses en overflow: {overflow_buses:.0f}\n")
        f.write("\n")
        f.write("DIFERENCIAS:\n")
        f.write(f"  Delta objetivo: {overflow_obj - baseline_obj:.2f} km ({((overflow_obj - baseline_obj) / baseline_obj * 100):+.1f}%)\n")
        f.write(f"  Delta patios: {overflow_patios - baseline_patios:+d}\n")
        f.write(f"  Buses adicionales en overflow: {overflow_buses:.0f}\n")
    else:
        f.write("  (No disponible)\n")
    f.write("\n" + "=" * 70 + "\n")

print("✓ Generado: comparativo_baseline_vs_overflow.txt")

