"""
Genera mapa geográfico visual de asignaciones ruta → patio.
"""
import os
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import json
from src.config import Config

OUTPUT_DIR = os.path.join(Config.DATA_RESULTS, "report")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_mapa_geografico():
    """Genera mapa geográfico con líneas conectando rutas a patios."""
    try:
        # Cargar datos geoespaciales
        patios_gdf = gpd.read_file(os.path.join(Config.DATA_PROCESSED, "patios_bk.geojson"))
        rutas_gdf = gpd.read_file(os.path.join(Config.DATA_PROCESSED, "rutas_bk.geojson"))
        asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
        
        # Cargar nombres cortos
        try:
            crosswalk = pd.read_csv(os.path.join(Config.DATA_PROCESSED, "route_crosswalk.csv"))
            route_names = dict(zip(crosswalk["geo_code"], crosswalk["gtfs_route_short"]))
        except:
            route_names = {}
        
        # Preparar datos de patios
        patios_gdf["patio_id"] = patios_gdf.get("objectid", patios_gdf.get("OBJECTID", range(len(patios_gdf))))
        patios_gdf["patio_id"] = patios_gdf["patio_id"].astype(str)
        
        # Asegurar que asign también tenga patio_id como string
        asign["patio_id"] = asign["patio_id"].astype(str)
        
        # Obtener centroides de patios
        patios_gdf = patios_gdf.to_crs("EPSG:4326")
        patios_gdf["centroid_lon"] = patios_gdf.geometry.centroid.x
        patios_gdf["centroid_lat"] = patios_gdf.geometry.centroid.y
        
        # Preparar datos de rutas (terminales)
        # Usar el último punto de cada ruta como terminal
        rutas_gdf = rutas_gdf.to_crs("EPSG:4326")
        rutas_terminals = []
        for _, ruta in rutas_gdf.iterrows():
            geo_code = str(ruta.get("cod_linea", ruta.get("codigo", "")))
            if geo_code and geo_code in asign["geo_code"].values:
                # Obtener último punto de la línea
                if hasattr(ruta.geometry, 'coords'):
                    try:
                        coords = list(ruta.geometry.coords)
                        if coords:
                            last_point = coords[-1]  # Terminal
                            if len(last_point) >= 2:
                                lon, lat = last_point[0], last_point[1]
                                rutas_terminals.append({
                                    "geo_code": geo_code,
                                    "terminal_lon": lon,
                                    "terminal_lat": lat
                                })
                    except:
                        pass
        
        rutas_term_df = pd.DataFrame(rutas_terminals)
        
        # Merge con asignaciones para obtener patios
        asign_con_rutas = asign.merge(rutas_term_df, on="geo_code", how="inner")
        asign_con_patios = asign_con_rutas.merge(
            patios_gdf[["patio_id", "centroid_lon", "centroid_lat"]],
            on="patio_id",
            how="inner"
        )
        
        # Crear mapa
        fig, ax = plt.subplots(figsize=(16, 12))
        
        # Plot patios
        patios_gdf.plot(ax=ax, color="red", markersize=100, marker="s", 
                        label="Patios", edgecolor="black", linewidth=2, zorder=3)
        
        # Anotar IDs de patios
        for _, patio in patios_gdf.iterrows():
            if pd.notna(patio["centroid_lon"]) and pd.notna(patio["centroid_lat"]):
                patio_id_str = str(patio['patio_id'])
                if patio_id_str != 'nan' and patio_id_str:
                    try:
                        patio_label = f"P{int(float(patio_id_str))}"
                    except:
                        patio_label = f"P{patio_id_str}"
                    ax.annotate(patio_label, 
                               xy=(patio["centroid_lon"], patio["centroid_lat"]),
                               fontsize=8, fontweight="bold", ha="center", va="center",
                               bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="red", alpha=0.7))
        
        # Plot líneas de asignación (solo top asignaciones por volumen)
        top_asign = asign_con_patios.nlargest(20, "buses")
        
        for _, row in top_asign.iterrows():
            if pd.notna(row["terminal_lon"]) and pd.notna(row["terminal_lat"]):
                route_name = route_names.get(row["geo_code"], row["geo_code"])
                # Línea delgada para asignaciones pequeñas, gruesa para grandes
                width = max(0.5, min(3, row["buses"] / 50))
                alpha = min(0.6, max(0.2, row["buses"] / 100))
                
                ax.plot([row["terminal_lon"], row["centroid_lon"]],
                       [row["terminal_lat"], row["centroid_lat"]],
                       color="steelblue", linewidth=width, alpha=alpha, zorder=1)
        
        ax.set_xlabel("Longitud", fontsize=12, fontweight="bold")
        ax.set_ylabel("Latitud", fontsize=12, fontweight="bold")
        ax.set_title("Mapa Geográfico: Asignaciones Ruta → Patio\n(Top 20 asignaciones por volumen)", 
                     fontsize=14, fontweight="bold", pad=20)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right")
        
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, "fig_mapa_geografico.png"), dpi=150, bbox_inches="tight")
        plt.close()
        
        print(f"✓ Generado: fig_mapa_geografico.png")
        
    except Exception as e:
        print(f"⚠ Error generando mapa geográfico: {e}")
        print("  Generando diagrama alternativo...")
        
        # Fallback: diagrama de red simple
        generate_diagrama_red_simple()

def generate_diagrama_red_simple():
    """Genera un diagrama de red simple como alternativa."""
    asign = pd.read_csv(os.path.join(Config.DATA_RESULTS, "asignaciones_lp.csv"))
    
    # Agrupar por patio
    patios_rutas = asign.groupby("patio_id").agg({
        "geo_code": lambda x: list(set(x)),
        "buses": "sum"
    }).reset_index()
    
    # Crear diagrama de barras con lista de rutas
    fig, ax = plt.subplots(figsize=(14, 10))
    
    top_patios = patios_rutas.nlargest(10, "buses").sort_values("buses", ascending=True)
    
    y_pos = range(len(top_patios))
    bars = ax.barh(y_pos, top_patios["buses"], color="steelblue", alpha=0.7)
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"Patio {int(row['patio_id'])}" for _, row in top_patios.iterrows()])
    ax.set_xlabel("Total Buses Asignados", fontsize=12, fontweight="bold")
    ax.set_title("Asignaciones por Patio (Top 10)\nCon lista de rutas asignadas", 
                 fontsize=14, fontweight="bold", pad=20)
    ax.grid(axis="x", alpha=0.3, linestyle="--")
    
    # Mostrar lista de rutas
    for i, (_, row) in enumerate(top_patios.iterrows()):
        rutas_str = ", ".join(row["geo_code"][:5])  # Primeras 5
        if len(row["geo_code"]) > 5:
            rutas_str += f" +{len(row['geo_code']) - 5} más"
        ax.text(row["buses"] + 10, i, f"{int(row['buses'])} buses\n{rutas_str}", 
                va="center", fontsize=8)
    
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "fig_mapa_geografico.png"), dpi=150, bbox_inches="tight")
    plt.close()
    
    print(f"✓ Generado: fig_mapa_geografico.png (diagrama alternativo)")

if __name__ == "__main__":
    import os
    generate_mapa_geografico()

