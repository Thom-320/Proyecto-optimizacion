"""
Script para generar artefactos de reporte (tablas y gráficos) para Entrega 2.
"""
import json
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

from src.config import Config

OUTPUT_DIR = os.path.join(Config.DATA_RESULTS, "report")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_top_rutas_table():
    """Genera tabla_top_rutas.csv: top-10 rutas por PVR con patio asignado y costo_km."""
    pvr = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "pvr_por_ruta.csv"))
    asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
    
    # Top 10 por PVR
    top_pvr = pvr.nlargest(10, "PVR")[["geo_code", "PVR"]].copy()
    
    # Agregar información de asignación
    resultados = []
    for _, row in top_pvr.iterrows():
        geo_code = row["geo_code"]
        pvr_val = row["PVR"]
        
        # Obtener asignaciones para esta ruta
        asign_ruta = asign[asign["geo_code"] == geo_code]
        if len(asign_ruta) > 0:
            # Tomar el patio principal (con más buses)
            asign_principal = asign_ruta.nlargest(1, "buses").iloc[0]
            patio_id = asign_principal["patio_id"]
            costo_km = asign_principal["costo"]
            buses_asign = asign_principal["buses"]
        else:
            patio_id = "N/A"
            costo_km = 0
            buses_asign = 0
        
        resultados.append({
            "geo_code": geo_code,
            "PVR": int(pvr_val),
            "patio_asignado": patio_id,
            "buses_en_patio_principal": int(buses_asign),
            "costo_km": round(costo_km, 2)
        })
    
    df = pd.DataFrame(resultados)
    df.to_csv(os.path.join(OUTPUT_DIR, "tabla_top_rutas.csv"), index=False)
    print(f"✓ Generado: tabla_top_rutas.csv ({len(df)} filas)")

def generate_patios_table():
    """Genera tabla_patios.csv: capacidad escalada, buses asignados, %utilización."""
    with open(os.path.join(Config.DATA_PROCESSED, "capacidades_patios.json"), "r") as f:
        caps_data = json.load(f)
    
    resumen = pd.read_csv(os.path.join(Config.DATA_RESULTS, "resumen_por_patio_lp.csv"))
    
    # Capacidades base y escaladas (1.2x según el run)
    rows = []
    for _, row in resumen.iterrows():
        patio_id_raw = row["patio_id"]
        buses_asignados = row["buses_asignados"]
        
        # Manejar patio "overflow" especial
        if str(patio_id_raw) == "overflow":
            rows.append({
                "patio_id": "overflow",
                "capacidad_base": 0,
                "capacidad_escalada": 0,
                "buses_asignados": int(buses_asignados),
                "utilizacion_%": 0.0
            })
            continue
        
        # Convertir a int primero si es float, luego a string
        try:
            patio_id_int = int(float(patio_id_raw))
            patio_id_str = str(patio_id_int)
        except (ValueError, TypeError):
            patio_id_str = str(patio_id_raw)
            patio_id_int = patio_id_raw
        
        cap_base = caps_data["capacidades"].get(patio_id_str, 0)
        cap_escalada = int(round(cap_base * 1.2))
        
        utilizacion_pct = (buses_asignados / cap_escalada * 100) if cap_escalada > 0 else 0
        
        rows.append({
            "patio_id": patio_id_int,
            "capacidad_base": cap_base,
            "capacidad_escalada": cap_escalada,
            "buses_asignados": int(buses_asignados),
            "utilizacion_%": round(utilizacion_pct, 1)
        })
    
    df = pd.DataFrame(rows).sort_values("utilizacion_%", ascending=False)
    df.to_csv(os.path.join(OUTPUT_DIR, "tabla_patios.csv"), index=False)
    print(f"✓ Generado: tabla_patios.csv ({len(df)} filas)")
    print(f"  Capacidades encontradas: {sum(1 for r in rows if r['capacidad_base'] > 0)}/{len(rows)}")

def generate_utilizacion_plot():
    """Genera fig_utilizacion_patios.png: barra de %utilización por patio."""
    patios_df = pd.read_csv(os.path.join(OUTPUT_DIR, "tabla_patios.csv"))
    
    # Filtrar overflow y patios con capacidad > 0
    patios_df = patios_df[
        (patios_df["patio_id"] != "overflow") & 
        (patios_df["capacidad_escalada"] > 0)
    ].copy()
    
    if len(patios_df) == 0:
        print("⚠ No hay patios válidos para graficar")
        return
    
    plt.figure(figsize=(12, 7))
    bars = plt.bar(range(len(patios_df)), patios_df["utilizacion_%"], color="steelblue", alpha=0.7)
    plt.xlabel("Patio ID", fontsize=12, fontweight="bold")
    plt.ylabel("Utilización (%)", fontsize=12, fontweight="bold")
    plt.title("Utilización de Capacidad por Patio (Escalada 1.2x)", fontsize=14, fontweight="bold")
    plt.xticks(range(len(patios_df)), patios_df["patio_id"], rotation=45, ha="right")
    plt.grid(axis="y", alpha=0.3, linestyle="--")
    plt.ylim(0, max(110, patios_df["utilizacion_%"].max() * 1.1))
    
    # Colorear barras según utilización
    for i, (bar, val) in enumerate(zip(bars, patios_df["utilizacion_%"])):
        if val >= 90:
            bar.set_color("crimson")
        elif val >= 70:
            bar.set_color("orange")
        else:
            bar.set_color("steelblue")
    
    # Anotar valores y capacidades
    for i, (val, cap, buses) in enumerate(zip(
        patios_df["utilizacion_%"], 
        patios_df["capacidad_escalada"],
        patios_df["buses_asignados"]
    )):
        plt.text(i, val + max(5, patios_df["utilizacion_%"].max() * 0.02), 
                f"{val:.1f}%\n({buses}/{cap})", 
                ha="center", fontsize=9, fontweight="bold")
    
    plt.axhline(y=100, color="red", linestyle="--", alpha=0.5, label="100% (saturación)")
    plt.legend()
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "fig_utilizacion_patios.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Generado: fig_utilizacion_patios.png ({len(patios_df)} patios)")

def generate_contribucion_objetivo():
    """Genera fig_contribucion_objetivo.png: top-10 aportes al objetivo (km)."""
    asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
    
    # Cargar nombres cortos de rutas
    try:
        crosswalk = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv"))
        route_names = dict(zip(crosswalk["geo_code"], crosswalk["gtfs_route_short"]))
    except:
        route_names = {}
    
    # Calcular contribución por asignación
    asign["contribucion_km"] = asign["buses"] * asign["costo"]
    
    # Agrupar por ruta y sumar contribuciones
    contrib = asign.groupby("geo_code")["contribucion_km"].sum().reset_index()
    contrib = contrib.nlargest(10, "contribucion_km").sort_values("contribucion_km", ascending=True)
    
    # Agregar nombre corto de ruta
    contrib["route_name"] = contrib["geo_code"].apply(
        lambda x: route_names.get(x, x) if route_names else x
    )
    
    plt.figure(figsize=(10, 7))
    plt.barh(range(len(contrib)), contrib["contribucion_km"], color="coral", alpha=0.7)
    plt.xlabel("Contribución al Objetivo (km)", fontsize=12, fontweight="bold")
    plt.ylabel("Ruta", fontsize=12, fontweight="bold")
    plt.title("Top 10 Rutas por Contribución al Objetivo Total", fontsize=14, fontweight="bold")
    plt.yticks(range(len(contrib)), contrib["route_name"])
    plt.grid(axis="x", alpha=0.3, linestyle="--")
    
    # Anotar valores
    for i, val in enumerate(contrib["contribucion_km"]):
        plt.text(val + max(50, val * 0.02), i, f"{val:.0f} km", va="center", fontsize=10, fontweight="bold")
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "fig_contribucion_objetivo.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✓ Generado: fig_contribucion_objetivo.png")

def generate_mapa_asignaciones():
    """Genera fig_mapa_asignaciones.png: diagrama visual de rutas → patios."""
    import geopandas as gpd
    
    asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
    
    # Cargar nombres cortos
    try:
        crosswalk = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv"))
        route_names = dict(zip(crosswalk["geo_code"], crosswalk["gtfs_route_short"]))
    except:
        route_names = {}
    
    # Agregar nombres a asignaciones
    asign["route_name"] = asign["geo_code"].apply(
        lambda x: route_names.get(x, x) if route_names else x
    )
    
    # Agrupar por patio y listar rutas asignadas
    patios_rutas = asign.groupby("patio_id").agg({
        "route_name": lambda x: ", ".join(sorted(set(x))),
        "buses": "sum"
    }).reset_index()
    patios_rutas.columns = ["patio_id", "rutas_asignadas", "total_buses"]
    
    # Crear diagrama de barras horizontales agrupadas
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Preparar datos: top 10 patios por número de rutas asignadas
    patios_rutas["num_rutas"] = patios_rutas["rutas_asignadas"].apply(lambda x: len(x.split(", ")))
    top_patios = patios_rutas.nlargest(10, "num_rutas").sort_values("num_rutas", ascending=True)
    
    # Crear barras
    y_pos = range(len(top_patios))
    bars = ax.barh(y_pos, top_patios["num_rutas"], color="steelblue", alpha=0.7)
    
    # Etiquetas
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"Patio {int(row['patio_id'])}" for _, row in top_patios.iterrows()])
    ax.set_xlabel("Número de Rutas Asignadas", fontsize=12, fontweight="bold")
    ax.set_title("Mapa de Asignaciones: Rutas por Patio\n(Top 10 Patios)", 
                 fontsize=14, fontweight="bold", pad=20)
    ax.grid(axis="x", alpha=0.3, linestyle="--")
    
    # Anotar número de rutas y buses
    for i, (_, row) in enumerate(top_patios.iterrows()):
        num_rutas = row["num_rutas"]
        total_buses = row["total_buses"]
        ax.text(num_rutas + 0.5, i, f"{int(num_rutas)} rutas\n{int(total_buses)} buses", 
                va="center", fontsize=9)
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "fig_mapa_asignaciones.png"), dpi=150, bbox_inches="tight")
    plt.close()
    
    # También crear una tabla detallada
    tabla_detalle = asign.groupby("patio_id").agg({
        "route_name": lambda x: sorted(set(x)),
        "geo_code": lambda x: sorted(set(x)),
        "buses": "sum"
    }).reset_index()
    
    # Expandir lista de rutas a múltiples filas
    rows_expanded = []
    for _, row in tabla_detalle.iterrows():
        for route_name, geo_code in zip(row["route_name"], row["geo_code"]):
            rows_expanded.append({
                "patio_id": row["patio_id"],
                "route_name": route_name,
                "geo_code": geo_code,
                "total_buses_patio": int(row["buses"])
            })
    
    df_expanded = pd.DataFrame(rows_expanded)
    df_expanded.to_csv(os.path.join(OUTPUT_DIR, "tabla_mapa_asignaciones.csv"), index=False)
    
    print(f"✓ Generado: fig_mapa_asignaciones.png")
    print(f"✓ Generado: tabla_mapa_asignaciones.csv ({len(df_expanded)} asignaciones)")

def copy_sensitivity_files():
    """Copia sensitivity_capacities.csv y shadow_like_by_depot.csv a report/."""
    import shutil
    
    files_to_copy = [
        "sensitivity_capacities.csv",
        "shadow_like_by_depot.csv"
    ]
    
    for filename in files_to_copy:
        src = os.path.join(Config.DATA_RESULTS, filename)
        dst = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"✓ Copiado: {filename}")
        else:
            print(f"⚠ No encontrado: {filename}")

def main():
    print("=" * 70)
    print("GENERANDO ARTEFACTOS DE REPORTE")
    print("=" * 70)
    print()
    
    generate_top_rutas_table()
    generate_patios_table()
    generate_utilizacion_plot()
    generate_contribucion_objetivo()
    generate_mapa_asignaciones()
    # Generar mapa geográfico
    try:
        from generate_mapa_geografico import generate_mapa_geografico
        generate_mapa_geografico()
    except Exception as e:
        print(f"⚠ Mapa geográfico no disponible: {e}")
    copy_sensitivity_files()
    
    print()
    print("=" * 70)
    print("✓ Todos los artefactos generados en:", OUTPUT_DIR)
    print("=" * 70)

if __name__ == "__main__":
    main()

