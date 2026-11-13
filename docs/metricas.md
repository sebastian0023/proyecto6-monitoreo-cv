# Métricas base (G1–G7)

Una métrica por grupo, definida antes de calcular nada. Cada una responde lo que pide la comprobación M1 de la rúbrica: qué mide, unidad, fórmula, población, ventana y exclusiones; y deja fijado cómo se obtiene (M2), cómo se calcula con cero observaciones (M3), cómo se traza (M4) y cómo se recalcula (M5). Los campos salen de [`contrato.md`](contrato.md).

## 1. Inventario de grupos

Los 7 grupos aplican. No hay exclusiones que justificar: el sistema hace inferencia sobre un stream (G1, G2), corre como un proceso medible (G3), produce puntuaciones sin etiquetas (G4), guarda eventos e imágenes (G5), usa una fuente y una versión de modelo observables (G6) y genera alertas (G7).

| Grupo | Métrica base | Campos que la sostienen | Aplica |
|---|---|---|---|
| G1 Salud y rendimiento del servicio | Latencia de inferencia p50 y p95 | `t_infer_ms`, `t_post_ms` | sí |
| G2 Captura y procesamiento del stream | Cuadros procesados por segundo | `t_mono_ms`, `status` | sí |
| G3 Uso de recursos | RAM del proceso | `rss_mb` | sí |
| G4 Comportamiento de las predicciones | Proporción de baja confianza | `zone`, `status` | sí |
| G5 Datos y trazabilidad | Cobertura de trazabilidad | todos los campos del contrato, `image_ref`, `image_sha256` y el archivo de la captura | sí |
| G6 Dispositivos, fuentes y versiones | Coincidencia de versión del modelo | `model_sha256`, `model_version` y el descriptor | sí |
| G7 Alertas, recuperación y costos | Alertas activas | tabla de alertas (`opened_window_id`, `closed_window_id`, `status`) | sí |

**Una métrica distinta por grupo.** Ninguna cubre dos grupos: cada una usa campos distintos y su resultado no se puede obtener de otra. G1 mide el tiempo del modelo y G2 el ritmo del flujo (usan `t_infer_ms` y `t_mono_ms`, que son relojes diferentes); G4 cuenta cuadros por zona y G5 cuenta eventos completos; G6 compara versiones y G7 cuenta alertas. Las métricas adicionales de #11 son otras y no se cuentan como base.

## 2. Definiciones comunes

- **Corrida:** un recorrido de una fuente con un `run_id`. Sus eventos están en la base de datos `resultados/monitoreo.db` y se exportan a `resultados/<run_id>/eventos.jsonl` (ver [`capturas.md`](capturas.md)).
- **Cuadro procesado:** un evento, con cualquier `status`.
- **Ventana:** 20 cuadros procesados consecutivos, sin solapamiento (4 s a 5 cuadros/s). Su número es `window_id = (frame_id − 1) // 20 + 1`. La última ventana de una corrida puede tener menos de 20 cuadros: se calcula igual y se marca `completa: false`. El tamaño (20) está confirmado en [`politica.md`](politica.md).
- **Percentil por rango más cercano:** con los *n* valores ordenados de menor a mayor, el percentil *p* es el valor de la posición ⌈*p*/100 · *n*⌉ (empezando en 1, mínimo 1). No se interpola.
- **«sin datos» e «insuficiente»:** una métrica sin observaciones devuelve `sin datos`, nunca 0. Una métrica que necesita un mínimo de observaciones y no lo alcanza devuelve `insuficiente`. Ninguno de los dos equivale a «normal». La única excepción es G7, donde 0 alertas es un valor válido.
- **Trazabilidad (M4):** cada resultado lleva su `run_id`, su `window_id` (o `corrida`), el número de observaciones y el rango de `event_id` que lo respalda, de modo que se puede ir de la cifra a los eventos.
- **Recálculo (M5):** `python -m p6.metricas --recalcular --db resultados/monitoreo.db --run-id <run_id>` vuelve a calcular todo desde los eventos y alertas guardados y lo compara campo por campo con lo guardado (sección 5). Cada sección trae un ejemplo con números pequeños; `tests/test_metricas.py` comprueba el código contra esos números.

## 3. Métricas

### G1 · Latencia de inferencia p50 y p95

| | |
|---|---|
| **Qué mide** | Cuánto tarda el sistema en inferir un cuadro: el modelo y el posprocesamiento (decodificación y NMS). Es el tiempo de servicio, separado de la captura y de la espera entre cuadros |
| **Unidad** | milisegundos |
| **Fórmula** | Para cada cuadro, `x = t_infer_ms + t_post_ms`. Se reportan el percentil 50 y el 95 de las `x` por rango más cercano |
| **Población** | Eventos con `status` igual a `ok` o `sin_detecciones` (la inferencia se completó) y `warmup` falso |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | `warmup` (los primeros 5 cuadros incluyen la carga y el calentamiento del modelo); `error` (no hay tiempo de inferencia). `t_pre_ms` queda fuera porque depende de la resolución de la fuente más que del modelo; sigue visible en cada evento |
| **Sin observaciones** | `sin datos` |
| **Adquisición (M2)** | `time.perf_counter()` alrededor de cada etapa dentro de `DetectorONNX.detectar` ([`detector.py`](../src/p6/detector.py)); los tiempos se guardan en el evento. Ya se produce en H1 |
| **Trazabilidad (M4)** | `run_id`, `window_id`, *n* y rango de `event_id` de los cuadros usados |
| **Nota** | Con menos de 20 cuadros el p95 es el valor máximo; por eso se reporta *n* junto al resultado |

**Ejemplo (ilustrativo).** Cinco cuadros con `x` = 6, 7, 8, 9 y 40 ms. p50: posición ⌈0.50 · 5⌉ = 3, vale **8 ms**. p95: posición ⌈0.95 · 5⌉ = 5, vale **40 ms**.

### G2 · Cuadros procesados por segundo

| | |
|---|---|
| **Qué mide** | El ritmo real con que el sistema completa inferencias, para compararlo con el ritmo declarado de la fuente (5 cuadros/s) |
| **Unidad** | cuadros por segundo |
| **Fórmula** | Sean *n* los cuadros de la población, ordenados por `frame_id`. `fps = (n − 1) / ((t_mono_ms del último − t_mono_ms del primero) / 1000)`. Se usa *n* − 1 porque *n* cuadros delimitan *n* − 1 intervalos |
| **Población** | Eventos con `status` igual a `ok` o `sin_detecciones` (inferencia completada). No excluye `warmup`: mide el flujo, no el rendimiento del modelo |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | Los cuadros con `error` no cuentan como procesados |
| **Sin observaciones** | `sin datos` con *n* < 2 o con intervalo de tiempo nulo |
| **Adquisición (M2)** | `t_mono_ms` es `time.monotonic()` al entregar cada cuadro ([`fuente.py`](../src/p6/fuente.py), `_cuadro`). Ya se produce en H1 |
| **Trazabilidad (M4)** | `run_id`, `window_id`, *n*, rango de `event_id` y los dos instantes usados |
| **Nota** | Con `--sin-pausa` el valor es la velocidad de procesamiento y no el ritmo declarado. Una corrida normal con ritmo 5 da un valor cercano a 5 |

**Ejemplo (ilustrativo).** Cinco cuadros con `t_mono_ms` = 0, 200, 400, 600 y 800. Intervalo: 0.8 s. **fps = 4 / 0.8 = 5.0 cuadros/s**.

### G3 · RAM del proceso

| | |
|---|---|
| **Qué mide** | La memoria residente (RSS) del proceso `monitorear`, no la del equipo |
| **Unidad** | MiB (2^20 bytes), campo `rss_mb` |
| **Fórmula** | Máximo y último valor de `rss_mb` en la ventana. Por corrida, el máximo de toda la corrida y el último |
| **Población** | Todos los eventos, con cualquier `status` y también `warmup` (la memoria de la carga del modelo es parte del uso real) |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | Ninguna |
| **Sin observaciones** | `sin datos` |
| **Adquisición (M2)** | `psutil.Process().memory_info().rss` al terminar cada cuadro ([`monitorear.py`](../src/p6/monitorear.py)). Ya se produce en H1 |
| **Trazabilidad (M4)** | `run_id`, `window_id`, *n*, rango de `event_id`, y el `event_id` donde ocurrió el máximo |
| **Nota** | «Último» es el del `frame_id` más alto de la ventana |

**Ejemplo (ilustrativo).** Tres cuadros con `rss_mb` = 200.0, 210.5 y 209.8. **Máximo 210.5 MiB, último 209.8 MiB**.

### G4 · Proporción de baja confianza

| | |
|---|---|
| **Qué mide** | Qué parte de los cuadros con detecciones quedó en la zona `baja`, es decir, con `frame_score` por debajo del umbral inferior. No mide aciertos: describe las salidas del modelo |
| **Unidad** | proporción entre 0 y 1 |
| **Fórmula** | `p = (cuadros con zone = baja) / (cuadros con status = ok)` |
| **Población** | Eventos con `status` igual a `ok`. El denominador son los cuadros **con detecciones** |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | `sin_detecciones` y `error` (no tienen puntuación; no equivalen a confianza cero). `warmup` no se excluye |
| **Sin observaciones** | `insuficiente` si hay menos de 10 cuadros con detecciones (mínimo confirmado en [`politica.md`](politica.md)). `sin datos` si no hay eventos |
| **Adquisición (M2)** | `frame_score` es el máximo de los `score` que entrega el detector sin modificar; `zone` la asigna la política de #5 con los umbrales de `config/monitoreo.yaml`. Ya se produce en H3 (#5) |
| **Trazabilidad (M4)** | `run_id`, `window_id`, cuadros en baja, cuadros con detecciones, rango de `event_id` |

**Ejemplo (ilustrativo).** Una ventana de 20 cuadros: 4 `sin_detecciones` y 16 `ok`, de los cuales 6 en zona `baja`. **p = 6 / 16 = 0.375**. Otra ventana con solo 8 cuadros `ok` devuelve **insuficiente**, no 0.

### G5 · Cobertura de trazabilidad

| | |
|---|---|
| **Qué mide** | Qué parte de los eventos guardados se puede explicar de punta a punta: tienen todos los campos del contrato y, si conservan una captura, el archivo existe y es el mismo |
| **Unidad** | proporción entre 0 y 1 |
| **Fórmula** | `cobertura = eventos que cumplen (a) y (b) / eventos guardados`. (a): pasa `validar_evento` con el contrato completo (H4). (b): si `image_ref` no es nulo, el archivo existe y su SHA-256 es igual a `image_sha256` |
| **Población** | Todos los eventos guardados de la ventana o de la corrida |
| **Ventana** | Por corrida; por ventana cuando se pide |
| **Exclusiones** | Ninguna. Los eventos que no cumplieron el contrato al capturarse no se guardan (van a `rechazados.jsonl`): se informan aparte como `eventos_rechazados` en `run.json` y no están en el denominador |
| **Sin observaciones** | `sin datos` si la corrida no tiene eventos |
| **Adquisición (M2)** | Los campos y las capturas con su SHA-256 los escribe `monitorear` ([`capturas.md`](capturas.md)); `capturas.verificar` comprueba cada archivo. El cálculo vuelve a leer los datos guardados y los archivos. Ya se produce en H4 (#6) |
| **Trazabilidad (M4)** | `run_id`, total, cumplen, y la lista de `event_id` que no cumplen con su motivo |

**Ejemplo (ilustrativo).** 10 eventos guardados: uno al que le falta un campo y otro cuyo `image_ref` apunta a un archivo que ya no existe. **cobertura = 8 / 10 = 0.8**, con 2 `event_id` listados como incumplidos.

### G6 · Coincidencia de versión del modelo

| | |
|---|---|
| **Qué mide** | Si los eventos fueron producidos por el modelo que la configuración declara, y qué versiones aparecen realmente |
| **Unidad** | proporción entre 0 y 1, más una lista de versiones distintas con su conteo |
| **Fórmula** | `coincidencia = eventos con model_sha256 igual al sha256 de modelo/descriptor.yaml / eventos guardados`. La lista agrupa los eventos por (`model_version`, `model_sha256`) |
| **Población** | Todos los eventos guardados |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | Ninguna |
| **Sin observaciones** | `sin datos` si no hay eventos |
| **Adquisición (M2)** | `model_sha256` es el SHA-256 del archivo de pesos realmente cargado, calculado al abrir el modelo ([`detector.py`](../src/p6/detector.py), `desde_config`), que además se niega a cargar pesos con otro hash. Ya se produce en H1 |
| **Trazabilidad (M4)** | `run_id`, el hash esperado, los conteos por versión y el rango de `event_id` |

**Ejemplo (ilustrativo).** 10 eventos: 9 con el hash del descriptor y 1 con otro. **coincidencia = 9 / 10 = 0.9**, y la lista muestra dos versiones, una con 9 eventos y otra con 1.

### G7 · Alertas activas

| | |
|---|---|
| **Qué mide** | Cuántas alertas están abiertas al cierre de cada ventana |
| **Unidad** | número de alertas |
| **Fórmula** | Una alerta está activa al cierre de la ventana *w* si `opened_window_id ≤ w` y (`closed_window_id` es nulo o `closed_window_id > w`). La métrica es la cantidad de alertas activas por ventana. Por corrida se reportan el máximo simultáneo y las abiertas al final |
| **Población** | Las alertas de la corrida (todas las reglas) |
| **Ventana** | Serie por ventana y resumen por corrida |
| **Exclusiones** | Ninguna |
| **Sin observaciones** | **0 es un valor válido**: una corrida sin alertas tiene 0 en cada ventana. No se usa `sin datos` |
| **Adquisición (M2)** | Las alertas las genera la política sobre las ventanas de la corrida (#7) y se guardan con el contrato de alerta. Se produce desde #7 |
| **Trazabilidad (M4)** | Por ventana, los `alert_id` activos; cada alerta lleva sus `window_ids` y `event_ids` |

**Ejemplo (ilustrativo).** La alerta A se abre en la ventana 2 y se cierra en la 5; la alerta B se abre en la 4 y sigue abierta. Serie de la ventana 1 a la 6: **0, 1, 1, 2, 1, 1** (en la 5, A ya está cerrada). Máximo simultáneo 2; abiertas al final 1.

## 4. Resumen de tratamiento sin observaciones

| Métrica | Sin observaciones | No alcanza el mínimo |
|---|---|---|
| G1 latencia | `sin datos` | no aplica (se reporta *n*) |
| G2 cuadros/s | `sin datos` (*n* < 2) | no aplica |
| G3 RAM | `sin datos` | no aplica |
| G4 baja confianza | `sin datos` | `insuficiente` (< 10 cuadros con detecciones) |
| G5 trazabilidad | `sin datos` | no aplica |
| G6 versión | `sin datos` | no aplica |
| G7 alertas activas | 0 | no aplica |

## 5. Cálculo, almacenamiento y recálculo

Implementación: [`src/p6/metricas.py`](../src/p6/metricas.py), una función por métrica (`g1_latencia` … `g7_alertas_corrida`).

- **Solo datos primarios.** Se calcula con las filas de `eventos` y `alertas` de la base de datos y con los archivos de captura (G5). No usa `run.json` ni ningún resultado ya agregado.
- **Cuándo se calcula.** `python -m p6.monitorear` lo hace al terminar cada corrida. También se puede hacer a mano con `python -m p6.metricas --db resultados/monitoreo.db --run-id <run_id>`.
- **Dónde se guarda.** En la tabla `metricas` de la base de datos y en `resultados/<run_id>/metricas.json`. El documento tiene un bloque `corrida` y una lista `ventanas`, con las 7 métricas en cada uno.
- **Estado de cada resultado.** `ok`, `sin datos` (sin observaciones; el valor es `null`, nunca 0) o `insuficiente` (G4 con menos de 10 cuadros con detecciones). G7 siempre es `ok`: 0 alertas es un valor válido.
- **Trazabilidad (M4).** Cada resultado lleva `n`, `window_ids`, `event_id_desde` y `event_id_hasta` de la población que usó, y los excluidos por motivo. Además, G3 lleva el `event_id` del máximo, G5 la lista de eventos que no cumplen con su motivo y G7 los `alert_id` activos.
- **Valor esperado de G6.** Es el `sha256` de `modelo/descriptor.yaml` del repositorio (opción `--descriptor`).
- **Recálculo (M5).** `--recalcular` vuelve a calcular el documento desde la base de datos (en modo de solo lectura) y lo compara campo por campo con el guardado, con tolerancia de 1e-9 en los números. Informa por métrica si coincide en la corrida y en todas las ventanas, lista las diferencias y termina con código 0 si todo coincide o 1 si no. `--salida archivo.txt` guarda el informe.

```bash
export PYTHONPATH=src
python -m p6.metricas --db resultados/monitoreo.db --run-id c2-baja-confianza --recalcular
# G1: coincide (corrida y 8 ventanas) … G7: coincide … resultado: todo coincide
```

Pruebas (`tests/test_metricas.py`): cada métrica con el ejemplo de la sección 3, incluidos sus casos `sin datos` e `insuficiente`; el documento por corrida y por ventana con su trazabilidad; y el recálculo, que coincide y detecta un dato primario alterado.

Los resultados de C1 y C2 y su recálculo están en [`evidencias/metricas/`](../evidencias/metricas/).

## 6. Métricas adicionales (extras, #11)

Tres indicadores más del grupo **G4** (comportamiento de las predicciones). Son distintos de su métrica base (la proporción de baja confianza): usan otra parte de la salida del modelo y su resultado no se deduce de ella. Se calculan con el mismo código, el mismo recálculo y la misma trazabilidad que las métricas base, en un bloque `extras` aparte, por corrida y por cada ventana (`metricas.json` → `corrida.extras` y `ventanas[i].extras`).

**Población común:** cuadros con inferencia completada (`status` `ok` o `sin_detecciones`). Los cuadros con `error` se excluyen y se cuentan aparte, porque no tienen salida del modelo. Si no hay cuadros en la población, el estado es `sin datos`. La **unidad de conteo** de E2 y E3 es la detección: una candidata con puntuación ≥ piso (0.10) que sobrevivió al NMS.

### E1 · Proporción de cuadros sin detecciones

| | |
|---|---|
| **Qué mide** | Qué parte de los cuadros procesados no tuvo ninguna detección sobre el piso. No es un error ni confianza cero: es un estado aparte |
| **Unidad** | proporción entre 0 y 1, con los conteos |
| **Fórmula** | `cuadros con status = sin_detecciones / cuadros con inferencia completada` |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | `error` |
| **Sin observaciones** | `sin datos` |
| **Adquisición** | `status` de cada evento (`monitorear.py`, según la salida del detector) |
| **Código** | `metricas.py::e1_sin_detecciones` |

**Ejemplo (ilustrativo).** 7 cuadros con detecciones, 2 sin detecciones y 1 con error: **E1 = 2 / 9 = 0.2222**, con el error excluido.

### E2 · Detecciones por cuadro

| | |
|---|---|
| **Qué mide** | Cuántas detecciones entrega el modelo por cuadro, como distribución. Un cambio indica que el modelo «ve» más o menos objetos de lo habitual |
| **Unidad** | detecciones por cuadro |
| **Fórmula** | Para cada cuadro, `n = len(detections)` (0 en los cuadros sin detecciones). Se reportan la media, el p50 y el p90 por rango más cercano, el máximo, el total y el histograma `{n: cuadros}` |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | `error` |
| **Sin observaciones** | `sin datos` |
| **Adquisición** | `detections` de cada evento |
| **Código** | `metricas.py::e2_detecciones_por_cuadro` |

**Ejemplo (ilustrativo).** Cuadros con 0, 1, 1, 2 y 3 detecciones: **media 7 / 5 = 1.4**, p50 = 1 (posición 3 de 5), p90 = 3 (posición 5), máximo 3, histograma `{0: 1, 1: 2, 2: 1, 3: 1}`.

### E3 · Predicciones por clase

| | |
|---|---|
| **Qué mide** | Qué clases predice el modelo y con qué frecuencia. En una escena fija, la aparición de clases nuevas indica que el modelo está confundido |
| **Unidad** | detecciones por clase (y su proporción); además, cuadros por la clase de su mejor detección |
| **Fórmula** | `detecciones_por_clase[c]` = detecciones de la clase c; `proporcion_por_clase[c]` = esas detecciones / total de detecciones; `cuadros_por_mejor_clase[c]` = cuadros cuya detección de mayor puntuación es de la clase c |
| **Ventana** | Por ventana y por corrida |
| **Exclusiones** | `error` |
| **Sin observaciones** | `sin datos` si no hay cuadros. Con cuadros pero sin detecciones, el resultado es una distribución vacía (`{}`), que es un dato válido |
| **Adquisición** | `detections[].class_name` y `score` de cada evento |
| **Código** | `metricas.py::e3_predicciones_por_clase` |

**Ejemplo (ilustrativo).** Cuadro 1: person 0.9 y chair 0.3; cuadro 2: person 0.8; cuadro 3: cup 0.6 y person 0.5; cuadro 4: sin detecciones. Detecciones por clase **person 3, chair 1, cup 1** (proporciones 0.6, 0.2, 0.2); cuadros por mejor clase **person 2, cup 1**.

**Pruebas y recálculo.** `tests/test_metricas.py` comprueba los tres ejemplos de arriba y sus casos `sin datos`. `python -m p6.metricas --recalcular` informa E1, E2 y E3 junto con G1–G7.
