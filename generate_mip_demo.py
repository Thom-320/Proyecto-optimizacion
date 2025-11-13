"""
Genera mini-MIP demo para las top 10 rutas por PVR.
"""
import os
import pandas as pd
import json
import tempfile
import shutil
from src.config import Config

# Leer top 10 rutas por PVR
pvr = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))
top_10 = pvr.nlargest(10, "PVR")["geo_code"].tolist()

print(f"Top 10 rutas por PVR: {top_10}")

# Filtrar datos solo para estas rutas
pvr_filtrado = pvr[pvr["geo_code"].isin(top_10)].copy()
pvr_filtrado.to_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta_top10.csv"), index=False)

# Filtrar matrices de costos
with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), "r") as f:
    dist_full = json.load(f)
    
with open(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"), "r") as f:
    time_full = json.load(f)

dist_top10 = {}
time_top10 = {}
for patio_id, rutas_dict in dist_full.items():
    dist_top10[patio_id] = {r: v for r, v in rutas_dict.items() if r in top_10}
    time_top10[patio_id] = {r: v for r, v in time_full[patio_id].items() if r in top_10}

# Guardar temporalmente
with open(os.path.join(Config.DATA_PROCESSED, "matriz_distancias_top10.json"), "w") as f:
    json.dump(dist_top10, f)
    
with open(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos_top10.json"), "w") as f:
    json.dump(time_top10, f)

# Backup de archivos originales
backup_dist = os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json.backup")
backup_time = os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json.backup")
backup_pvr = os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv.backup")

shutil.copy2(os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"), backup_dist)
shutil.copy2(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"), backup_time)
shutil.copy2(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"), backup_pvr)

# Reemplazar temporalmente
shutil.copy2(os.path.join(Config.DATA_PROCESSED, "matriz_distancias_top10.json"), os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"))
shutil.copy2(os.path.join(Config.DATA_PROCESSED, "matriz_tiempos_top10.json"), os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"))
shutil.copy2(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta_top10.csv"), os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))

print("✓ Datos filtrados temporalmente para top 10 rutas")
print("Ejecutando MIP...")

# Ejecutar MIP
import subprocess
result = subprocess.run(
    ["python", "-m", "src.cli", "solve", "--mode", "mip", "--objective", "distancia"],
    capture_output=True,
    text=True
)

print(result.stdout)
if result.returncode != 0:
    print("Error:", result.stderr)

# Restaurar archivos originales
shutil.copy2(backup_dist, os.path.join(Config.DATA_PROCESSED, "matriz_distancias.json"))
shutil.copy2(backup_time, os.path.join(Config.DATA_PROCESSED, "matriz_tiempos.json"))
shutil.copy2(backup_pvr, os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))

# Copiar resultado MIP al reporte
if os.path.exists(os.path.join(Config.DATA_RESULTS, "asignaciones_mip.csv")):
    shutil.copy2(
        os.path.join(Config.DATA_RESULTS, "asignaciones_mip.csv"),
        os.path.join(Config.DATA_RESULTS, "report", "asignaciones_mip_demo.csv")
    )
    print("✓ Copiado: asignaciones_mip_demo.csv")
else:
    print("⚠ asignaciones_mip.csv no encontrado")

# Limpiar backups
os.remove(backup_dist)
os.remove(backup_time)
os.remove(backup_pvr)

