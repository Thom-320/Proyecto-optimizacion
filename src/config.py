"""
Configuración global del pipeline SITP utilizando estructura modular.
"""
from dataclasses import dataclass
import os
from datetime import datetime


@dataclass
class Config:
    # URLs de datos abiertos
    URL_ZONAS = (
        "https://datosabiertos-transmilenio.hub.arcgis.com/api/download/v1/items/"
        "0e6721644ae54ebd8d28c70ee82e2ace/geojson?layers=18"
    )
    URL_PATIOS = (
        "https://datosabiertos-transmilenio.hub.arcgis.com/api/download/v1/items/"
        "1176a253e63a4de8a33332195a5d7b92/geojson?layers=1"
    )
    URL_RUTAS = (
        "https://datosabiertos-transmilenio.hub.arcgis.com/api/download/v1/items/"
        "6f412f25a90a4fa7b129b6aaa94e1965/geojson?layers=15"
    )
    URL_PARADEROS = (
        "https://datosabiertos.bogota.gov.co/dataset/5ba19d20-06af-4c04-b50c-8ecb9472327d/"
        "resource/624bb288-2a6d-466f-801a-93e5497cd879/download/paraderos.json"
    )
    URL_GTFS = "https://storage.googleapis.com/gtfs-estaticos/GTFS-2025-09-17.zip"

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
    DATA_RAW = os.path.join(DATA_DIR, "raw")
    DATA_PROCESSED = os.path.join(DATA_DIR, "processed")
    DATA_RESULTS = os.path.join(DATA_DIR, "results")
    DATA_SENSITIVITY = os.path.join(DATA_DIR, "sensitivity")

    LOCALIDADES = ["Bosa/Auto. Sur", "Kennedy/Las Américas"]
    ZONAS_DESTINO = ["Bosa", "Americas"]
    NUM_LOCALIDAD = [7, 8]
    TIPO_RUTA = [3]

    PEAK_START = "07:00"
    PEAK_END = "09:00"
    LAYOVER_FACTOR = 0.15

    VELOCIDAD_PROMEDIO = 20
    USE_OSRM = False
    OSRM_URL = "http://router.project-osrm.org"
    TERMINAL_SELECTION_MODE = "weighted"

    CAPACIDAD_PATIO_DEFAULT = 15
    CAPACIDAD_ESTIMACION_FACTOR = 0.002
    CRS_PROYECCION = "EPSG:3116"

    SOLVER_TIME_LIMIT = 300
    SOLVER_GAP = 0.02


def crear_directorios() -> None:
    """Crea todos los directorios necesarios para el pipeline."""
    os.makedirs(Config.DATA_RAW, exist_ok=True)
    os.makedirs(Config.DATA_PROCESSED, exist_ok=True)
    os.makedirs(Config.DATA_RESULTS, exist_ok=True)
    os.makedirs(Config.DATA_SENSITIVITY, exist_ok=True)


def timestamp() -> str:
    """Devuelve un timestamp legible para etiquetar archivos."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


__all__ = ["Config", "crear_directorios", "timestamp"]
