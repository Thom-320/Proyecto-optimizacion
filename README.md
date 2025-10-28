# Pipeline SITP – Optimización de buses a patios

## Requerimientos rápidos

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Flujo reproducible

```bash
python -m src.cli extract
python -m src.cli process
python -m src.cli crosswalk
python -m src.cli pvr --date 2025-09-22
python -m src.cli costs
python -m src.cli solve --mode lp --objective distancia
```

## Fase de Crosswalk

1. `python -m src.cli crosswalk` genera `data/processed/route_crosswalk.csv`.
2. El matching se realiza en tres pasos: coincidencia exacta, tokens y heurística geoespacial.
3. Los resultados se resumen en `data/processed/crosswalk_report.txt`.
4. Si alguna ruta queda sin match, edita `data/processed/route_crosswalk_manual.csv` (mismas columnas) y vuelve a ejecutar el subcomando. Las entradas manuales tienen prioridad.

## PVR con fecha explícita

`python -m src.cli pvr --date YYYY-MM-DD` calcula el Peak Vehicle Requirement para la fecha indicada.  
Si no se especifica `--date`, el sistema toma el último lunes válido del `feed_info.txt` del GTFS y deja registro en la consola.

## Matrices de costos

`python -m src.cli costs` consume el crosswalk y el PVR; únicamente se consideran rutas con correspondencia GTFS↔geo.  
El modo por defecto (`weighted`) toma el terminal más representativo; existen alternativas `--terminal-mode max_arrivals`, `conservative` y `conservative=max`.

## Solver (LP/MIP)

`python -m src.cli solve --mode lp` resuelve el modelo de transporte con variables enteras `x[r,p]` (número de buses).  
`python -m src.cli solve --mode mip` expande a buses individuales. Los resultados se guardan en `data/results/`.

## Notas importantes

- Los datos crudos y resultados están en `data/` (ignorados por git).
- Asegúrate de correr `crosswalk` antes de `pvr` y `costs`.
- Si el solver indica capacidad insuficiente, ajusta `data/processed/capacidades_patios.json`.
