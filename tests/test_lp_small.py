"""
Test del modelo LP con problema pequeño (2 rutas, 2 patios).
"""
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import pulp
import pytest

from src.config import Config
from src.model.assign_lp import ModeloAsignacionLP


@pytest.fixture
def temp_data_dir():
    """Crea directorios temporales y retorna la ruta."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear estructura de directorios
        processed = os.path.join(tmpdir, "processed")
        os.makedirs(processed, exist_ok=True)
        
        # Datos toy: 2 rutas (R1, R2), 2 patios (P1, P2)
        # PVR: R1=5, R2=3
        # Capacidades: P1=4, P2=6
        # Costos:
        #   R1->P1: 10km, R1->P2: 15km
        #   R2->P1: 12km, R2->P2: 8km
        # Solución esperada: R1->P1=5, R2->P2=3 (costo total = 5*10 + 3*8 = 74km)
        # Pero P1 tiene capacidad 4, así que: R1->P1=4, R1->P2=1, R2->P2=3
        # Costo óptimo = 4*10 + 1*15 + 3*8 = 40 + 15 + 24 = 79km
        
        distancias = {
            "P1": {"R1": 10.0, "R2": 12.0},
            "P2": {"R1": 15.0, "R2": 8.0},
        }
        tiempos = {
            "P1": {"R1": 30.0, "R2": 36.0},
            "P2": {"R1": 45.0, "R2": 24.0},
        }
        
        pvr_data = pd.DataFrame({
            "geo_code": ["R1", "R2"],
            "PVR": [5, 3],
        })
        
        capacidades = {
            "capacidades": {"P1": 4, "P2": 6},
            "metadata": {
                "P1": {"metodo": "cap_total", "estimado": False},
                "P2": {"metodo": "cap_total", "estimado": False},
            },
            "cap_total": 10,
        }
        
        # Escribir archivos temporales
        with open(os.path.join(processed, "matriz_distancias.json"), "w") as f:
            json.dump(distancias, f)
        with open(os.path.join(processed, "matriz_tiempos.json"), "w") as f:
            json.dump(tiempos, f)
        pvr_data.to_csv(os.path.join(processed, "pvr_por_ruta.csv"), index=False)
        with open(os.path.join(processed, "capacidades_patios.json"), "w") as f:
            json.dump(capacidades, f)
        
        # Guardar DATA_PROCESSED original y reemplazar temporalmente
        original = Config.DATA_PROCESSED
        Config.DATA_PROCESSED = processed
        yield processed
        Config.DATA_PROCESSED = original


def test_lp_feasibility(temp_data_dir):
    """Verifica que el modelo sea factible."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    
    assert modelo.rutas == ["R1", "R2"]
    assert modelo.patios == ["P1", "P2"]
    assert modelo.pvr["R1"] == 5
    assert modelo.pvr["R2"] == 3
    
    factible = modelo.resolver()
    assert factible, "El modelo debe ser factible"


def test_lp_demand_constraint(temp_data_dir):
    """Verifica que se cumple sum_p x[r,p] = PVR[r]."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    assert modelo.resolver()
    
    modelo.exportar()
    
    # Verificar que cada ruta tenga exactamente su PVR asignado
    asignaciones = modelo.resultados_df
    suma_por_ruta = asignaciones.groupby("geo_code")["buses"].sum()
    
    assert abs(suma_por_ruta.get("R1", 0) - 5) < 1e-3, f"R1 debe tener 5 buses, tiene {suma_por_ruta.get('R1', 0)}"
    assert abs(suma_por_ruta.get("R2", 0) - 3) < 1e-3, f"R2 debe tener 3 buses, tiene {suma_por_ruta.get('R2', 0)}"


def test_lp_capacity_constraint(temp_data_dir):
    """Verifica que se cumple sum_r x[r,p] <= Cap[p]."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    assert modelo.resolver()
    
    modelo.exportar()
    
    asignaciones = modelo.resultados_df
    suma_por_patio = asignaciones.groupby("patio_id")["buses"].sum()
    
    assert suma_por_patio.get("P1", 0) <= 4 + 1e-3, f"P1 no debe exceder capacidad 4, tiene {suma_por_patio.get('P1', 0)}"
    assert suma_por_patio.get("P2", 0) <= 6 + 1e-3, f"P2 no debe exceder capacidad 6, tiene {suma_por_patio.get('P2', 0)}"


def test_lp_objective(temp_data_dir):
    """Verifica el objetivo óptimo esperado."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    assert modelo.resolver()
    
    objetivo_optimo = float(pulp.value(modelo.modelo.objective))
    
    # Solución esperada: R1->P1=4, R1->P2=1, R2->P2=3
    # Costo = 4*10 + 1*15 + 3*8 = 79km
    assert abs(objetivo_optimo - 79.0) < 1e-3, f"Objetivo esperado ~79km, obtenido {objetivo_optimo}km"


def test_lp_variables_integer(temp_data_dir):
    """Verifica que las variables x[r,p] sean enteras cuando relax=False."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    assert modelo.resolver()
    
    modelo.exportar()
    
    # Todas las asignaciones deben ser enteras
    asignaciones = modelo.resultados_df
    for _, row in asignaciones.iterrows():
        assert abs(row["buses"] - round(row["buses"])) < 1e-3, f"Asignación debe ser entera: {row['buses']}"

