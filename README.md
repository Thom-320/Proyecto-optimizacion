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
python -m src.cli costs --terminal-mode weighted
python -m src.cli solve --mode lp --objective distancia
python -m src.cli diagnose  # Validar cobertura y factibilidad
```

## Modelo de Optimización

### Formulación Matemática

El modelo de transporte resuelve la asignación óptima de buses a patios con la siguiente formulación:

**Conjuntos:**
- $R$ = conjunto de rutas
- $P$ = conjunto de patios

**Parámetros:**
- $\mathrm{PVR}_r$ = Peak Vehicle Requirement de la ruta $r$
- $\mathrm{Cap}_p$ = Capacidad máxima del patio $p$ (número de buses)
- $c_{rp} \geq 0$ = Costo unitario (distancia en km o tiempo en min) de asignar un bus de la ruta $r$ al patio $p$
- $A_{rp} \in \{0,1\}$ = Matriz de compatibilidad (1 si el par (ruta, patio) es viable, 0 en otro caso)
- $K_{\max}$ = Límite máximo de patios por ruta (opcional, solo si se usa `--kmax`)

**Variables:**
- $x_{rp} \in \mathbb{Z}_{\geq 0}$ = Número de buses de la ruta $r$ asignados al patio $p$
- $z_{rp} \in \{0,1\}$ = Variable binaria que indica si la ruta $r$ utiliza el patio $p$ (opcional, solo si $K_{\max} > 0$)

**Función Objetivo:**
$$\min \sum_{r \in R} \sum_{p \in P} c_{rp} \cdot x_{rp}$$

**Restricciones:**

1. **Demanda:** Cada ruta debe cubrir exactamente su PVR:
   $$\sum_{p \in P} x_{rp} = \mathrm{PVR}_r \quad \forall r \in R$$

2. **Capacidad:** Los patios no pueden exceder su capacidad:
   $$\sum_{r \in R} x_{rp} \leq \mathrm{Cap}_p \quad \forall p \in P$$

3. **Compatibilidad:** Solo se pueden asignar buses a pares compatibles:
   $$x_{rp} \leq A_{rp} \cdot \mathrm{PVR}_r \quad \forall r \in R, p \in P$$

4. **Límite de patios por ruta** (opcional, si `--kmax` > 0):
   $$\sum_{p \in P} z_{rp} \leq K_{\max} \quad \forall r \in R$$
   $$x_{rp} \leq \mathrm{PVR}_r \cdot z_{rp} \quad \forall r \in R, p \in P$$

**Compatibilidad $A_{rp}$:**

La matriz $A_{rp}$ se define como:
- $A_{rp} = 1$ si existe un costo $c_{rp}$ finito (y opcionalmente si distancia $\leq$ `--max-distance-km`)
- $A_{rp} = 0$ en otro caso

El modelo valida que toda ruta tenga al menos un patio compatible; si alguna ruta tiene $A_{rp} = 0$ para todo $p$, el modelo aborta con un mensaje de error.

## Fase de Crosswalk

1. `python -m src.cli crosswalk` genera `data/processed/route_crosswalk.csv`.
2. El matching se realiza en tres pasos: coincidencia exacta, tokens y heurística geoespacial.
3. Los resultados se resumen en `data/processed/crosswalk_report.txt`.
4. Si alguna ruta queda sin match, edita `data/processed/route_crosswalk_manual.csv` (mismas columnas) y vuelve a ejecutar el subcomando. Las entradas manuales tienen prioridad.

## PVR con fecha explícita

`python -m src.cli pvr --date YYYY-MM-DD` calcula el Peak Vehicle Requirement para la fecha indicada.  
Si no se especifica `--date`, el sistema toma el último lunes válido del `feed_info.txt` del GTFS y deja registro en la consola.

## Matrices de costos

`python -m src.cli costs --terminal-mode weighted` consume el crosswalk y el PVR; únicamente se consideran rutas con correspondencia GTFS↔geo.  
El modo por defecto (`weighted`) toma el terminal más representativo; existen alternativas `--terminal-mode max_arrivals`, `conservative` y `conservative=max`.

## Solver (LP/MIP)

### Modo LP (Transporte)

`python -m src.cli solve --mode lp --objective distancia` resuelve el modelo de transporte con variables enteras $x_{rp}$.

**Flags disponibles:**
- `--objective {distancia,tiempo}`: Objetivo a minimizar (default: `distancia`)
- `--capacities-scale <factor>`: Factor multiplicador para escalar todas las capacidades (default: 1.0). Útil si $\Sigma_r \mathrm{PVR}_r > \Sigma_p \mathrm{Cap}_p$.
- `--kmax <K>`: Límite máximo de patios por ruta. Activa variables $z_{rp}$ y restricciones (4a)(4b), transformando el problema en un MIP.
- `--max-distance-km <d>`: Umbral máximo de distancia para considerar compatible un par (ruta, patio).

**Ejemplos:**
```bash
# Caso base
python -m src.cli solve --mode lp --objective distancia

# Escalar capacidades si hay déficit
python -m src.cli solve --mode lp --objective distancia --capacities-scale 1.2

# Limitar a máximo 2 patios por ruta
python -m src.cli solve --mode lp --objective distancia --kmax 2

# Solo considerar asignaciones con distancia <= 50km
python -m src.cli solve --mode lp --objective distancia --max-distance-km 50
```

### Modo LP Relajación

`python -m src.cli solve --mode lp_relax --objective distancia` resuelve el modelo con variables continuas (relajación). Útil para obtener precios sombra (duales) de capacidad y costos reducidos, exportados en:
- `data/results/duales_capacidad_lp.csv`
- `data/results/reduced_costs_lp.csv`

### Modo MIP

`python -m src.cli solve --mode mip --objective distancia` expande a buses individuales (modelo binario por bus).

**Resultados guardados en `data/results/`:**
- `asignaciones_lp.csv`: Asignaciones (ruta, patio, buses, costo)
- `resumen_por_patio_lp.csv`: Total de buses asignados por patio
- `resumen_ejecutivo_lp.txt`: Resumen ejecutivo (fecha, estadísticas, costo total)

## Diagnóstico y Validación

`python -m src.cli diagnose` valida:
- ✅ Cobertura de crosswalk (rutas con match GTFS)
- ✅ PVR > 0 para todas las rutas
- ✅ Matriz de costos completa
- ✅ Cobertura $A_{rp}$ (rutas con al menos un patio compatible)
- ✅ Factibilidad por capacidad: $\Sigma_r \mathrm{PVR}_r \leq \Sigma_p \mathrm{Cap}_p$

El reporte se guarda en `data/results/diagnose_report.txt`. Si hay problemas, el comando retorna código de salida ≠ 0.

## Análisis de Sensibilidad

`python -m src.cli sensitivity --capacities-scale 0.8 1.0 1.2` ejecuta el modelo con diferentes escalas de capacidad y exporta:
- `data/results/sensitivity_capacities.csv`: Objetivo y factibilidad por escala
- `data/results/shadow_like_by_depot.csv`: Aproximación de precios sombra (delta objetivo por +1 capacidad)

## Cómo Interpretar Resultados

### Asignaciones (`asignaciones_lp.csv`)

Cada fila representa una asignación (ruta → patio):
- `geo_code`: Código de la ruta geoespacial
- `patio_id`: ID del patio
- `buses`: Número de buses asignados (entero)
- `costo`: Costo unitario (km o min)

**Ejemplo:**
```
geo_code,patio_id,buses,costo
RUTA_01,PATIO_5,3,12.5
RUTA_01,PATIO_7,2,18.3
```

### Resumen por Patio (`resumen_por_patio_lp.csv`)

Muestra la utilización de capacidad por patio:
- `patio_id`: ID del patio
- `buses_asignados`: Total de buses asignados
- **Verificar:** `buses_asignados <= Cap[p]` para cada patio

### Patios Saturados

Un patio está saturado si `buses_asignados ≈ Cap[p]` (slack de la restricción de capacidad cercano a 0). Puedes verificar en `resumen_por_patio_lp.csv` comparando con `capacidades_patios.json`.

### Sensibilidad

- **Precios sombra (duales):** Valores altos indican que aumentar capacidad en ese patio reduce significativamente el objetivo.
- **Costos reducidos:** Valores negativos indican asignaciones que mejorarían el objetivo si fueran activadas (pero están bloqueadas por compatibilidad o capacidad).

### Solución Infactible

Si el solver retorna error:
1. Verifica cobertura: `python -m src.cli diagnose`
2. Si hay déficit de capacidad, usa `--capacities-scale <factor> > 1.0`
3. Si hay rutas sin compatibilidad, completa `route_crosswalk_manual.csv` o ajusta `--max-distance-km`

## Tests

Ejecutar tests mínimos:

```bash
pytest tests/test_lp_small.py -v  # Problema toy con 2 rutas, 2 patios
pytest tests/test_compat.py -v   # Validación de compatibilidad A[r,p]
```

## Notas importantes

- Los datos crudos y resultados están en `data/` (ignorados por git).
- Asegúrate de correr `crosswalk` antes de `pvr` y `costs`.
- Si el solver indica capacidad insuficiente, usa `--capacities-scale` o ajusta `data/processed/capacidades_patios.json`.
- El modelo valida automáticamente que toda ruta tenga al menos un patio compatible antes de resolver.
