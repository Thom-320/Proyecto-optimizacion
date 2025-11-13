"""
Test de compatibilidad: verificar que A[r,p]=0 bloquee variables.
"""
import json
import os
import tempfile

import pandas as pd
import pytest

from src.config import Config
from src.model.assign_lp import ModeloAsignacionLP


@pytest.fixture
def temp_data_dir_incompatible():
    """Crea datos con algunas incompatibilidades."""
    with tempfile.TemporaryDirectory() as tmpdir:
        processed = os.path.join(tmpdir, "processed")
        os.makedirs(processed, exist_ok=True)
        
        # Datos: 2 rutas (R1, R2), 2 patios (P1, P2)
        # R1 puede ir a P1 y P2
        # R2 solo puede ir a P2 (no tiene costo en P1)
        distancias = {
            "P1": {"R1": 10.0},  # R2 no tiene costo aquí
            "P2": {"R1": 15.0, "R2": 8.0},
        }
        tiempos = {
            "P1": {"R1": 30.0},
            "P2": {"R1": 45.0, "R2": 24.0},
        }
        
        pvr_data = pd.DataFrame({
            "geo_code": ["R1", "R2"],
            "PVR": [5, 3],
        })
        
        capacidades = {
            "capacidades": {"P1": 10, "P2": 10},
            "metadata": {
                "P1": {"metodo": "cap_total", "estimado": False},
                "P2": {"metodo": "cap_total", "estimado": False},
            },
            "cap_total": 20,
        }
        
        with open(os.path.join(processed, "matriz_distancias.json"), "w") as f:
            json.dump(distancias, f)
        with open(os.path.join(processed, "matriz_tiempos.json"), "w") as f:
            json.dump(tiempos, f)
        pvr_data.to_csv(os.path.join(processed, "pvr_por_ruta.csv"), index=False)
        with open(os.path.join(processed, "capacidades_patios.json"), "w") as f:
            json.dump(capacidades, f)
        
        original = Config.DATA_PROCESSED
        Config.DATA_PROCESSED = processed
        yield processed
        Config.DATA_PROCESSED = original


def test_compatibility_matrix_built(temp_data_dir_incompatible):
    """Verifica que la matriz A[r,p] se construye correctamente."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    
    # A[R1, P1] = 1 (existe costo)
    assert modelo.A.get(("R1", "P1"), 0) == 1
    # A[R1, P2] = 1 (existe costo)
    assert modelo.A.get(("R1", "P2"), 0) == 1
    # A[R2, P1] = 0 (no existe costo)
    assert modelo.A.get(("R2", "P1"), 0) == 0
    # A[R2, P2] = 1 (existe costo)
    assert modelo.A.get(("R2", "P2"), 0) == 1


def test_incompatible_pairs_blocked(temp_data_dir_incompatible):
    """Verifica que pares incompatibles no reciban asignación."""
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
    modelo.cargar_datos()
    modelo.construir_modelo()
    assert modelo.resolver()
    
    modelo.exportar()
    
    asignaciones = modelo.resultados_df
    
    # R2 no debe estar asignada a P1 (incompatible)
    r2_p1 = asignaciones[(asignaciones["geo_code"] == "R2") & (asignaciones["patio_id"] == "P1")]
    assert len(r2_p1) == 0, "R2 no debe tener buses en P1 (incompatible)"
    
    # R2 debe estar solo en P2
    r2_p2 = asignaciones[(asignaciones["geo_code"] == "R2") & (asignaciones["patio_id"] == "P2")]
    assert len(r2_p2) > 0, "R2 debe tener buses en P2"
    suma_r2_p2 = r2_p2["buses"].sum()
    assert abs(suma_r2_p2 - 3) < 1e-3, f"R2 debe tener 3 buses en P2, tiene {suma_r2_p2}"


def test_coverage_validation_aborts(temp_data_dir_incompatible):
    """Verifica que si una ruta no tiene compatibilidad, se aborta."""
    with tempfile.TemporaryDirectory() as tmpdir:
        processed = os.path.join(tmpdir, "processed")
        os.makedirs(processed, exist_ok=True)
        
        # Ruta R3 sin compatibilidad con ningún patio
        distancias = {
            "P1": {"R1": 10.0},
            "P2": {"R1": 15.0},
        }
        tiempos = {
            "P1": {"R1": 30.0},
            "P2": {"R1": 45.0},
        }
        
        pvr_data = pd.DataFrame({
            "geo_code": ["R1", "R3"],  # R3 no tiene costos
            "PVR": [5, 3],
        })
        
        capacidades = {
            "capacidades": {"P1": 10, "P2": 10},
            "metadata": {
                "P1": {"metodo": "cap_total", "estimado": False},
                "P2": {"metodo": "cap_total", "estimado": False},
            },
            "cap_total": 20,
        }
        
        with open(os.path.join(processed, "matriz_distancias.json"), "w") as f:
            json.dump(distancias, f)
        with open(os.path.join(processed, "matriz_tiempos.json"), "w") as f:
            json.dump(tiempos, f)
        pvr_data.to_csv(os.path.join(processed, "pvr_por_ruta.csv"), index=False)
        with open(os.path.join(processed, "capacidades_patios.json"), "w") as f:
            json.dump(capacidades, f)
        
        original = Config.DATA_PROCESSED
        Config.DATA_PROCESSED = processed
        
        try:
            modelo = ModeloAsignacionLP(objetivo="distancia", relax=False)
            with pytest.raises(ValueError, match="sin compatibilidad"):
                modelo.cargar_datos()
        finally:
            Config.DATA_PROCESSED = original


def test_max_distance_threshold(temp_data_dir_incompatible):
    """Verifica que el umbral de distancia máxima funcione."""
    # Con umbral de 12km, R1->P2 (15km) debería quedar excluido
    modelo = ModeloAsignacionLP(objetivo="distancia", relax=False, max_distance_km=12.0)
    modelo.cargar_datos()
    
    # A[R1, P2] debe ser 0 por exceder umbral
    assert modelo.A.get(("R1", "P2"), 0) == 0, "R1->P2 debe ser incompatible por distancia > 12km"
    # A[R1, P1] debe ser 1 (dentro del umbral)
    assert modelo.A.get(("R1", "P1"), 0) == 1, "R1->P1 debe ser compatible (10km <= 12km)"
    # A[R2, P2] debe ser 1 (dentro del umbral)
    assert modelo.A.get(("R2", "P2"), 0) == 1, "R2->P2 debe ser compatible (8km <= 12km)"

