# Guion Detallado: Implementación del Software - Entrega 2

**Duración estimada:** 8-12 minutos (antes de edición)
**Objetivo:** Mostrar avances en implementación, código, desafíos y soluciones

---

## 🎬 INTRODUCCIÓN DINÁMICA (1-2 minutos)

### Hook inicial

```
"Hola, soy [Tu nombre] y voy a llevarlos detrás de cámaras de cómo 
implementamos el modelo matemático que Valeria y Camila describieron.

La parte interesante es que la formulación matemática es elegante, 
pero traducirla a código Python requiere pensar en validaciones, 
manejo de errores, y casos especiales que no siempre son obvios 
en el papel.

Vamos a ver el código real, los desafíos que enfrentamos, y cómo 
logramos que funcione con datos reales de Bogotá."
```

### Transición

```
"Primero, déjenme mostrarles la arquitectura general del código, 
y luego entramos en los detalles interesantes."
```

---

## 🏗️ ARQUITECTURA Y DISEÑO (2-3 minutos)

### Mostrar estructura del proyecto

**Abrir terminal/VSCode mostrando estructura:**

```
src/
├── model/
│   ├── assign_lp.py      ← Modelo principal
│   └── assign_mip.py     ← Variante MIP
├── features/
│   ├── crosswalk.py      ← Matching GTFS ↔ Geo
│   ├── pvr_gtfs.py        ← Cálculo de PVR
│   └── cost_matrix.py     ← Matrices de costos
└── cli.py                 ← Interfaz de línea de comandos
```

**Explicar:**

```
"Usamos una arquitectura modular. Cada componente tiene una 
responsabilidad clara. El modelo LP está en assign_lp.py como 
una clase orientada a objetos, lo que nos permite reutilizar 
código y hacer pruebas más fáciles."
```

### Mostrar clase ModeloAsignacionLP

**Abrir `assign_lp.py` líneas 30-59:**

```
"Esta es la clase principal. Vean el constructor - tiene muchos 
parámetros opcionales porque queríamos flexibilidad. Por ejemplo, 
`kmax` para limitar patios por ruta, `max_distance_km` para 
filtrar asignaciones muy lejanas, o `overflow_penalty_km` para 
manejar déficit de capacidad.

Esto es importante porque durante el desarrollo descubrimos que 
necesitábamos probar diferentes escenarios, y tener estos flags 
nos ahorró mucho tiempo."
```

**Destacar líneas 58-59:**

```
"Noten estas dos líneas importantes:
- `self.A` es la matriz de compatibilidad que mencionaron en la 
  formulación
- `self.z` son las variables binarias opcionales - solo se crean 
  si usamos `kmax`

Esto es diseño eficiente: no creamos variables que no vamos a usar."
```

---

## 🧩 CONSTRUCCIÓN DE LA MATRIZ DE COMPATIBILIDAD (2 minutos)

### Mostrar método _build_compatibility_matrix

**Abrir `assign_lp.py` líneas 108-131:**

```
"Ahora vamos a lo interesante. La matriz A[r,p] parece simple 
en la formulación, pero implementarla requiere pensar en casos 
especiales.

Vean este método. Recorre todas las rutas y patios, y para cada 
par verifica dos cosas:
1. ¿Existe un costo finito? Si no, A[r,p] = 0
2. Si pasamos un umbral de distancia máxima, ¿está dentro del 
   límite?

Esto es importante porque en datos reales, a veces hay rutas 
que teóricamente podrían ir a un patio, pero operativamente 
no tiene sentido si está a 50 km de distancia."
```

**Pausa en línea 117-118:**

```
"Acá está el chequeo: si el costo es None o no es finito 
(math.isfinite), marcamos como incompatible. Esto previene 
errores raros donde el solver podría intentar usar valores 
NaN o infinito."
```

**Mostrar output real:**

```
"Cuando ejecutamos esto, vemos: '✓ Matriz de compatibilidad: 
363 pares viables de 363 posibles'. Esto nos dice que todas 
las rutas tienen al menos un patio compatible, lo cual es 
crucial para que el modelo sea factible."
```

---

## 🎯 CONSTRUCCIÓN DEL MODELO PULP (3-4 minutos)

### Variables de decisión

**Abrir `assign_lp.py` líneas 138-142:**

```
"Ahora la parte clave: construir el modelo en PuLP. PuLP es 
una librería de Python que actúa como wrapper para solvers 
como CBC, GLPK, o CPLEX.

Primero creamos las variables x[r,p]. Noten el parámetro `cat`:
- Si `relax=False`, son enteras ('Integer') - es nuestro 
  modelo de transporte
- Si `relax=True`, son continuas ('Continuous') - para obtener 
  duales y costos reducidos

PuLP maneja esto internamente, pero nosotros controlamos qué 
tipo queremos."
```

### Función objetivo

**Mostrar líneas 151-156:**

```
"La función objetivo es una suma lineal. Pero aquí hay un detalle 
importante: solo sumamos sobre pares compatibles.

Fíjense en el `if self.A.get((r, p), 0) == 1`. Esto asegura que 
no estamos optimizando sobre asignaciones imposibles. Es más 
eficiente que dejar que el solver descubra que x[r,p] = 0 para 
pares incompatibles."
```

### Restricción (1): Demanda

**Mostrar líneas 158-163:**

```
"La primera restricción es directa: cada ruta debe cubrir 
exactamente su PVR. Iteramos sobre rutas y forzamos que la 
suma de buses asignados iguale el PVR requerido.

Noten que usamos `int(self.pvr[r])` - esto es porque PuLP 
espera números enteros en restricciones de igualdad cuando 
las variables son enteras."
```

**Destacar nombres de restricciones:**

```
"Y aquí está algo que aprendimos tarde: le damos nombres a las 
restricciones con `f"Demanda_Ruta_{r}"`. ¿Por qué? Porque luego 
cuando queremos exportar precios sombra (duales), necesitamos 
poder identificarlas. Sin nombres, es imposible saber qué 
restricción corresponde a qué ruta."
```

### Restricción (2): Capacidad

**Mostrar líneas 165-171:**

```
"La segunda restricción limita la capacidad de cada patio. 
Iteramos sobre patios y aplicamos un límite superior.

Fíjense que también filtramos por compatibilidad aquí: solo 
sumamos sobre rutas compatibles. Esto hace el modelo más 
compacto y rápido de resolver."
```

### Restricción (3): Compatibilidad

**Mostrar líneas 173-181:**

```
"Esta es la restricción que más nos costó implementar correctamente. 
Tenemos dos casos:

Si A[r,p] = 0 (incompatible), simplemente forzamos x[r,p] = 0. 
Fácil.

Pero si A[r,p] = 1 (compatible), necesitamos acotar: 
x[r,p] <= PVR[r] * A[r,p] = PVR[r]

Esto previene que asignemos más buses de los que necesita una 
ruta a un solo patio. Es redundante con la restricción de demanda, 
pero ayuda al solver a entender mejor el problema."
```

### Variables opcionales z[r,p]

**Mostrar líneas 183-198:**

```
"Y aquí está la parte más avanzada: las variables z[r,p] para 
limitar patios por ruta. Esto convierte nuestro LP en un MIP.

Solo se activa si pasamos `--kmax`. Por ejemplo, si kmax=2, 
cada ruta puede usar máximo 2 patios. Esto puede ser útil 
operativamente - menos complejidad logística.

Las restricciones (4a) y (4b) vinculan x[r,p] con z[r,p]. Si 
z[r,p] = 0, entonces x[r,p] = 0. Si z[r,p] = 1, entonces 
x[r,p] puede ser hasta PVR[r]."
```

---

## 🚀 EJECUCIÓN Y CLI (2 minutos)

### Mostrar CLI

**Abrir `cli.py` líneas 125-133:**

```
"El modelo se ejecuta desde la línea de comandos. Vean cómo 
pasamos los parámetros: `--capacities-scale` para escalar 
capacidades, `--overflow-penalty-km` para usar un patio virtual 
con penalización.

Esto nos permite probar diferentes escenarios sin cambiar código. 
Muy útil durante el desarrollo."
```

### Ejecutar comando real

**Mostrar terminal ejecutando:**

```bash
python -m src.cli solve --mode lp --objective distancia --capacities-scale 1.2
```

```
"Cuando ejecutamos esto, el modelo:
1. Carga los datos (matrices, PVR, capacidades)
2. Construye la matriz de compatibilidad
3. Valida que todas las rutas tengan al menos un patio compatible
4. Construye el modelo en PuLP
5. Resuelve con CBC
6. Exporta resultados a CSV

Todo en unos segundos. Muy rápido."
```

**Mostrar output real:**

```
"Vean el output: '✓ Matriz de compatibilidad: 363 pares viables'. 
Esto confirma que el modelo encontró asignaciones para todas 
las rutas."
```

---

## 🐛 DESAFÍOS Y SOLUCIONES (3-4 minutos)

### Desafío 1: Validación de cobertura

**Mostrar código `assign_lp.py` líneas 89-94:**

```
"El primer desafío grande fue: ¿qué pasa si una ruta no tiene 
ningún patio compatible? 

Inicialmente, el modelo simplemente fallaba con un error críptico 
del solver. No era claro qué estaba mal.

Así que agregamos esta validación explícita ANTES de construir 
el modelo. Si encontramos rutas sin compatibilidad, abortamos 
con un mensaje claro que dice exactamente qué rutas son el 
problema.

Esto nos ahorró horas de debugging. Ahora sabemos inmediatamente 
si hay un problema de datos."
```

**Mostrar ejemplo de error:**

```
"Por ejemplo, si el crosswalk no está completo, obtenemos: 
'Rutas sin compatibilidad con ningún patio: RUTA_X, RUTA_Y'. 
Muy claro."
```

### Desafío 2: Capacidad insuficiente

**Mostrar código líneas 102-106:**

```
"Otro desafío: ¿qué pasa si ΣPVR > ΣCapacidad? El modelo es 
infactible, pero el mensaje del solver no es muy útil.

Agregamos esta validación que calcula el déficit y sugiere 
soluciones: 'Usa --capacities-scale <factor> o ajusta 
capacidades_patios.json'.

Esto transforma un error frustrante en una guía de acción."
```

**Contar historia:**

```
"La primera vez que ejecutamos con datos reales, obtuvimos 
déficit de 247 buses. No sabíamos si era un error de datos 
o si realmente necesitábamos más capacidad. Al agregar esta 
validación, inmediatamente supimos que necesitábamos escalar 
capacidades, y el flag `--capacities-scale` nos permitió 
probar diferentes factores sin editar archivos manualmente."
```

### Desafío 3: Exportación de duales

**Mostrar código líneas 242-256:**

```
"Este fue frustrante. Queríamos exportar precios sombra de 
capacidad para análisis de sensibilidad, pero PuLP con CBC 
no siempre expone los duales fácilmente.

El problema era que sin nombres en las restricciones, no 
podíamos identificarlas después de resolver.

Solución: agregamos nombres explícitos a todas las restricciones 
de capacidad: `f"Capacidad_Patio_{p}"`. Luego, después de resolver, 
iteramos sobre las restricciones, buscamos las que empiezan con 
ese prefijo, y extraemos el atributo `pi` que contiene el precio 
sombra.

Funciona... cuando funciona. A veces CBC no expone los duales, 
así que tenemos un try-except que falla silenciosamente si no 
están disponibles."
```

**Mostrar código alternativo:**

```
"Por eso también implementamos `shadow_like_by_depot.csv` en 
el análisis de sensibilidad. En lugar de confiar en duales, 
recalculamos el modelo aumentando capacidad de cada patio en +1 
y medimos el cambio en el objetivo. Es más lento pero más confiable."
```

### Desafío 4: Manejo de tipos (patio_id)

**Contar historia:**

```
"Un bug sutil que nos tomó tiempo: los `patio_id` venían como 
strings del JSON, pero en las asignaciones eran floats (12.0 en 
lugar de "12"). Cuando intentábamos hacer merge o lookup, fallaba 
silenciosamente porque "12" != 12.0.

Solución: normalizamos todo a string desde el principio, y 
convertimos a int solo cuando necesitamos hacer cálculos."
```

**Mostrar código relevante:**

```
"En el script de reportes, tenemos esta línea que maneja esto:
`patio_id_str = str(int(float(patio_id_raw)))`

Parece complicado, pero maneja todos los casos: float, int, 
string, incluso "overflow" como caso especial."
```

### Desafío 5: Matriz de compatibilidad eficiente

**Mostrar código líneas 113-129:**

```
"Inicialmente, construíamos la matriz A[r,p] durante la construcción 
del modelo. Pero para problemas grandes, esto era lento porque 
iterábamos sobre todas las restricciones.

Movimos la construcción a `cargar_datos()`, antes de construir el 
modelo. Ahora es más rápido y podemos validar cobertura temprano.

También agregamos el log de cuántos pares son viables, lo cual 
es útil para debugging."
```

---

## 📊 RESULTADOS Y VISUALIZACIONES (2 minutos)

### Mostrar archivos generados

**Abrir carpeta `data/results/`:**

```
"Después de resolver, generamos varios archivos de salida:

- `asignaciones_lp.csv`: Cada fila es una asignación (ruta → 
  patio, buses, costo)
- `resumen_por_patio_lp.csv`: Total de buses por patio
- `resumen_ejecutivo_lp.txt`: Estadísticas globales

Estos son fáciles de analizar en Excel o Python."
```

### Mostrar script de visualización

**Abrir `generate_report.py`:**

```
"Para las visualizaciones, creamos scripts separados que leen 
los resultados y generan gráficos con matplotlib.

Por ejemplo, este script genera:
- Gráfico de utilización de patios (barras con colores según %)
- Gráfico de contribución al objetivo (top 10 rutas)
- Mapas geográficos mostrando asignaciones

La ventaja es que podemos regenerar los gráficos fácilmente 
si cambiamos los datos o queremos diferentes visualizaciones."
```

**Mostrar ejemplo de gráfico:**

```
"Aquí vemos el gráfico de utilización. Noten que:
- Las barras rojas son patios saturados (100%)
- Las azules tienen disponibilidad
- Las anotaciones muestran tanto el porcentaje como los números 
  absolutos (buses/capacidad)

Esto hace que sea fácil interpretar visualmente."
```

---

## 🎨 DETALLES DE ELEGANCIA DEL CÓDIGO (2 minutos)

### Diseño extensible

```
"Una cosa de la que estoy orgulloso es cómo el código maneja 
casos opcionales sin complicarse demasiado.

Por ejemplo, el flag `--kmax` activa variables z[r,p] y 
restricciones adicionales, pero si no lo pasas, simplemente 
no se crean. El resto del código funciona igual.

Esto es extensibilidad: podemos agregar nuevas características 
sin romper lo existente."
```

### Manejo de errores robusto

```
"Otro aspecto importante: validaciones tempranas. En lugar de 
dejar que el solver falle con errores crípticos, validamos 
datos antes de construir el modelo.

Si algo está mal, el usuario sabe exactamente qué corregir. 
Esto hace el código más usable."
```

### Separación de responsabilidades

```
"La clase ModeloAsignacionLP tiene métodos claros:
- `cargar_datos()`: Lee archivos
- `_build_compatibility_matrix()`: Construye A[r,p]
- `construir_modelo()`: Crea el modelo PuLP
- `resolver()`: Ejecuta el solver
- `exportar()`: Guarda resultados

Cada método hace una cosa bien. Esto facilita testing y 
mantenimiento."
```

---

## 🔧 CASOS ESPECIALES Y TRICKS (1-2 minutos)

### Overflow patio

```
"Un caso especial interesante: el patio overflow. Si hay déficit 
de capacidad, podemos crear un patio virtual con capacidad 
infinita pero costo penalizado muy alto.

Esto hace el problema siempre factible, pero penaliza asignaciones 
al overflow. Es útil para análisis de 'qué pasa si no tenemos 
suficiente capacidad'."
```

**Mostrar código líneas 159-181 del archivo:**

```
"Cuando activamos overflow, agregamos este patio especial con 
costos calculados como múltiplo del costo máximo real. Así el 
solver solo lo usa si realmente no hay otra opción."
```

### Escalado de capacidades

```
"Otra característica útil: escalado de capacidades. En lugar de 
editar manualmente el JSON, podemos pasar `--capacities-scale 1.2` 
y todas las capacidades se multiplican por ese factor.

Útil para análisis de sensibilidad. Probamos 0.8x, 1.0x, 1.2x 
y vemos cómo cambia el objetivo."
```

### Relajación LP para duales

```
"Para obtener precios sombra, resolvemos la relajación LP 
(variables continuas). Esto nos da duales que indican cuánto 
cambiaría el objetivo si aumentamos capacidad en un patio.

Pero como mencioné, CBC no siempre los expone, así que tenemos 
el método alternativo de recalcular con +1 capacidad."
```

---

## 📈 RESULTADOS REALES (1-2 minutos)

### Mostrar resultados

**Abrir `data/results/asignaciones_lp.csv`:**

```
"Con datos reales de Bogotá, resolvimos 33 rutas, 11 patios, 
1,908 buses. El objetivo óptimo fue 14,746 km.

Pero lo interesante es que 10 de 11 patios están completamente 
saturados al 100%. Solo el Patio 25 tiene disponibilidad. Esto 
nos dice que la solución está muy ajustada - cualquier crecimiento 
requeriría más capacidad."
```

### Mostrar gráficos generados

```
"Los gráficos muestran esto claramente. Vean el de utilización: 
10 barras rojas al 100%, una azul al 73%.

Y el mapa geográfico muestra visualmente cómo las rutas se 
conectan a los patios. Es fácil ver patrones geográficos."
```

---

## 🎓 LECCIONES APRENDIDAS (1 minuto)

### Resumen de aprendizajes

```
"Para cerrar, algunas lecciones que aprendimos:

1. **Validación temprana es clave**: Mejor detectar problemas 
   antes de construir el modelo que después.

2. **Nombres en restricciones**: Aunque parezca trivial, hacer 
   debugging y exportar duales sin nombres es muy difícil.

3. **Código modular**: Separar carga de datos, construcción del 
   modelo, y exportación facilita testing y debugging.

4. **Mensajes de error útiles**: En lugar de 'solver failed', 
   mejor decir 'capacidad insuficiente, usa --capacities-scale'.

5. **Flexibilidad desde el inicio**: Los flags opcionales que 
   agregamos al principio nos ahorraron mucho tiempo después."
```

---

## 🎬 CIERRE (30 segundos)

```
"En resumen, implementar el modelo matemático fue un proceso 
iterativo donde encontramos desafíos y los resolvimos uno por 
uno. El código resultante es robusto, extensible, y produce 
resultados que podemos analizar y visualizar fácilmente.

Lo mejor es que todo está documentado y modular, así que si 
necesitamos agregar nuevas características o corregir bugs, 
es relativamente fácil.

Gracias por su atención, y ahora pasamos a los resultados 
detallados."
```

---

## 📝 NOTAS PARA LA GRABACIÓN

### Timing sugerido por sección:

1. **Introducción:** 1-2 min
2. **Arquitectura:** 2-3 min
3. **Matriz compatibilidad:** 2 min
4. **Construcción modelo:** 3-4 min
5. **Ejecución CLI:** 2 min
6. **Desafíos:** 3-4 min
7. **Resultados:** 1-2 min
8. **Casos especiales:** 1-2 min
9. **Lecciones:** 1 min
10. **Cierre:** 30 seg

**Total:** ~18-22 minutos (la editora lo cortará a 5-15 min)

### Tips para hacerlo dinámico:

1. **Cambiar de pantalla frecuentemente**: Código → Terminal → Resultados → Gráficos
2. **Usar zoom en código**: Resaltar líneas específicas con el cursor
3. **Ejecutar comandos en vivo**: Muestra la ejecución real, no solo screenshots
4. **Mostrar errores y cómo los resolviste**: Más interesante que solo éxito
5. **Comparar antes/después**: "Antes fallaba así... ahora funciona así"
6. **Pausas naturales**: Después de cada desafío, pausa para resumir
7. **Tono conversacional**: Habla como si explicaras a un compañero, no como conferencia

### Elementos visuales a capturar:

- **Screenshots de código** con syntax highlighting
- **Terminal ejecutando comandos** (mostrar output en tiempo real)
- **Gráficos generados** (zoom en detalles importantes)
- **Archivos CSV abiertos** (mostrar datos reales)
- **Comparaciones** (antes/después, con/sin validación)

### Transiciones sugeridas:

```
"Ahora que vimos la arquitectura..." [cambiar a código]
"Pero aquí viene el desafío..." [cambiar a error]
"Y así lo resolvimos..." [cambiar a código corregido]
"Veamos si funciona..." [ejecutar comando]
"Perfecto, ahora los resultados..." [mostrar gráficos]
```

