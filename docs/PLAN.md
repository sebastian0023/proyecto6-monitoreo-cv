# Plan del Proyecto 6: centro de monitoreo de computer vision

Entrega individual de Sebastián (@sebastian0023). **Fecha: viernes 13 de noviembre de 2026** (la hora oficial es la de Canvas, ver #2).
Guía: `guia-proyecto-6.html` (100 puntos base y extras sin límite).

## 1. Qué se entrega

Un portal que convierte un stream de video en inferencias reales de un detector, eventos, imágenes y alertas que se pueden investigar. Se evalúa el monitoreo y su evidencia. No se mide si el modelo acierta: no hay etiquetas, accuracy ni mAP.

Base obligatoria (100 puntos):

| Criterio | Puntos | Qué hay que demostrar | Issue |
|---|---:|---|---|
| R1 Fuente y modelo | 15 | Stream con ritmo declarado, inferencias reales e identidad del modelo | #3 |
| R2 Métricas | 25 | Una métrica por grupo G1–G7, cada una con definición, datos, cálculo, trazabilidad y recálculo | #4, #8 |
| R3 Confianza | 15 | Dos umbrales justificados, tres zonas, referencia, ventanas y regla de cambio sostenido | #5 |
| R4 Eventos e imágenes | 15 | Eventos persistentes y consultables, con imágenes vinculadas que no caducan | #4, #6 |
| R5 Alertas | 15 | Reglas explícitas, alertas reales vinculadas a sus eventos y vista en el portal | #7 |
| R6 Demostración | 10 | Escenarios C1 (operación normal) y C2 (baja confianza) | #9 |
| R7 Repositorio | 5 | README reproducible, índice de evidencias y autoría | #10 |

## 2. Decisiones

| Tema | Decisión | Por qué |
|---|---|---|
| Fuente | Videos propios grabados con la cámara de la Mac y reproducidos como stream a 5 cuadros/s. El mismo código lee la webcam en vivo | El carrito de P5 no está disponible y la guía no lo exige ni da puntos por él. Con videos en el repo, el evaluador repite C1 y C2 sin mi cámara |
| Tarea | Detección de objetos | Reutiliza el detector de P5, que ya está probado |
| Modelo | YOLOX-Nano preentrenado en COCO (80 clases), ONNX en CPU, sin entrenamiento | Pesos públicos con SHA-256 y licencia Apache-2.0; no requiere AWS. Medido en la Mac M4: 8.3 ms por cuadro (p50) |
| Piso del detector | 0.10, en lugar del 0.30 de P5 | Debe quedar por debajo del umbral inferior para que la zona de baja confianza sea visible. Con 0.10, las 78 fotos del carrito muestran 14 cuadros con mejor puntuación entre 0.10 y 0.30 que P5 descartaba |
| Repositorio | Repo personal nuevo, separado del del equipo | Historial y autoría individuales; la entrega de P5 queda intacta |
| Plataforma | Python 3.12, onnxruntime, OpenCV, SQLite, FastAPI con HTML simple y psutil. Sin Docker ni nube | Lo mínimo para que el evaluador lo corra en su máquina |

## 3. Componentes reutilizados (para R7.3)

| Componente | Origen | Autor | Uso |
|---|---|---|---|
| Pesos `yolox_nano.onnx` 0.1.1rc0 | github.com/Megvii-BaseDetection/YOLOX, SHA-256 `c789161e…0b7d` | Megvii (Apache-2.0) | Sin cambios |
| Letterbox, decodificación y NMS del detector | `Proyecto5/src/p5/detector_onnx.py` de sebastian0023/Proyecto-3-Clasificador-de-imagenes, tag `p5-entrega` (b63ddbc) | Edith (@edithflor), equipo de P5 | Adaptado: piso configurable, tiempos por etapa y sin el contrato de P5 |
| Descarga del modelo con verificación | `Proyecto5/scripts/descargar_modelo.py`, mismo tag | Edith (@edithflor) | Adaptado |
| 78 fotos del carrito (opcional, #13) | `Proyecto5/datos/evaluacion/S1…S6`, mismo tag | Capturas de Bryan (@BryanRomoG) | Solo como segunda fuente; sus anotaciones no se usan |

El resto es aportación propia: lectura del stream, política de confianza, eventos, capturas, reglas de alerta, métricas, portal, escenarios y evidencias. Cada archivo adaptado lleva un encabezado con su origen.

## 4. Arquitectura

```
fuente (video / carpeta / webcam, 5 cuadros/s)
  → detector YOLOX (tiempos por etapa)
  → política: confianza del cuadro, zona, ventana
  → evento + captura (SQLite + JSONL + JPEG)
  → reglas de alerta por ventana
  → portal: eventos y alertas, con enlaces a imágenes y configuración
```

Estructura prevista:

```
proyecto6-monitoreo-cv/
├── src/p6/
│   ├── fuente.py       lector de video, carpeta o webcam con ritmo declarado
│   ├── detector.py     YOLOX en ONNX (adaptado de P5)
│   ├── politica.py     zonas, ventanas y reglas
│   ├── almacen.py      SQLite + exportación JSONL + capturas
│   ├── monitorear.py   CLI que corre todo el recorrido
│   ├── metricas.py     calcula y recalcula G1–G7 desde la base de datos
│   └── portal.py       FastAPI: eventos, alertas e imágenes
├── config/monitoreo.yaml   piso, umbrales, ventana, reglas, política de capturas
├── modelo/descriptor.yaml  URL, versión, SHA-256 y clases (los pesos no van en Git)
├── datos/videos/           referencia.mp4, normal.mp4, baja_confianza.mp4 (640×480)
├── scripts/                descargar_modelo.py, preparar_video.py
├── evidencias/             evidencia de entrega e índice
├── docs/                   este plan, métricas, política y decisiones
└── tests/
```

Comandos previstos (se confirman en #3 y #10):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/descargar_modelo.py --destino modelo/
python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 --config config/monitoreo.yaml --run-id c1-normal
python -m p6.metricas --db resultados/monitoreo.db --run-id c1-normal
python -m p6.portal --db resultados/monitoreo.db        # http://localhost:8000
```

## 5. Contratos

### Evento (uno por cuadro procesado)

| Campo | Tipo | Notas |
|---|---|---|
| `event_id` | texto | `<run_id>-<frame_id>` |
| `run_id`, `frame_id` | texto, entero | `frame_id` correlativo dentro de la corrida |
| `source_id`, `source_kind` | texto | por ejemplo `video:normal.mp4`, `webcam:0` |
| `t_capture_utc`, `t_mono_ms` | texto ISO, número | reloj de pared y monotónico |
| `task` | texto | `detection` |
| `model_version`, `model_sha256` | texto | del descriptor y del archivo cargado |
| `config_sha256` | texto | hash de `config/monitoreo.yaml` completo |
| `status` | texto | `ok`, `sin_detecciones` o `error` |
| `error_msg` | texto o nulo | solo con `error` |
| `detections` | lista | `{class_id, class_name, score, bbox}` de cada detección con puntuación ≥ piso |
| `frame_score` | número o nulo | puntuación más alta del cuadro; nulo si no hay detecciones o hubo error |
| `zone` | texto o nulo | `aceptada`, `duda`, `baja`; nulo si `frame_score` es nulo |
| `window_id` | entero | ventana a la que pertenece |
| `t_pre_ms`, `t_infer_ms`, `t_post_ms` | número | preprocesamiento, modelo y posprocesamiento |
| `rss_mb` | número | memoria del proceso al terminar el cuadro |
| `warmup` | booleano | verdadero en los primeros 5 cuadros, que se excluyen de G1 |
| `image_ref`, `image_sha256` | texto o nulo | captura conservada, si la política la guardó |

### Alerta

| Campo | Notas |
|---|---|
| `alert_id`, `rule_id`, `run_id` | identidad y regla que la generó |
| `status` | `abierta` o `cerrada` |
| `opened_at`, `closed_at` | instante y ventana de apertura y cierre |
| `severity` | `warning` o `critical` |
| `reason` | texto con los valores medidos y los límites de la regla |
| `window_ids`, `event_ids` | ventanas y eventos que la explican |
| `config_sha256` | configuración vigente |
| `suggested_action` | acción sugerida |

## 6. Política de confianza

- **Unidad: el cuadro.** Su confianza es la puntuación más alta entre sus detecciones. Un cuadro sin detecciones tiene el estado `sin_detecciones`: no recibe confianza cero ni entra en el cálculo de baja confianza.
- **Tres zonas.** `aceptada` si s ≥ umbral superior; `duda` si inferior ≤ s < superior; `baja` si s < inferior. Una igualdad con el inferior cuenta como duda y una igualdad con el superior como aceptada.
- **Umbrales.** Se eligen en #5 solo con `referencia.mp4`, nunca con los videos de los escenarios. Propuesta: inferior = percentil 10 y superior = percentil 50 de la confianza por cuadro en la referencia, redondeados a 0.05. Restricciones: piso (0.10) < inferior < superior ≤ 1.
- **Ventana.** 20 cuadros procesados consecutivos sin solapamiento (4 s a 5 cuadros/s). Una ventana tiene evidencia suficiente si al menos 10 de sus cuadros tienen detecciones; si no, se marca `insuficiente`, que no equivale a normal.
- **Referencia.** Se guardan en `evidencias/referencia/` la proporción de baja confianza de la referencia (p_ref), su histograma, la configuración y el run_id.

Los valores 20 / 10 / 0.50 / 0.20 / 3 de esta sección y de la siguiente son de partida; se confirman y justifican en #5 con la referencia.

## 7. Reglas de alerta

| Regla | Condición | Severidad | Acción sugerida |
|---|---|---|---|
| A · baja confianza | En una ventana suficiente, la proporción de cuadros en zona baja es ≥ 0.50 | warning | Revisar la captura, la iluminación y el enfoque |
| B · cambio sostenido | La proporción baja supera p_ref + 0.20 en 3 ventanas suficientes seguidas | critical | Investigar un cambio de escena o de cámara; comparar con la referencia |
| C · evidencia insuficiente (opcional) | 3 ventanas `insuficiente` seguidas | info | Revisar que la fuente siga enviando imágenes con objetos |

- Una alerta se abre cuando su condición se cumple y se cierra en la primera ventana suficiente en que deja de cumplirse. Un episodio continuo produce una sola alerta, no una por ventana.
- Las ventanas insuficientes no suman ni rompen la racha de la regla B, y no cierran una alerta abierta.
- Cada alerta guarda las ventanas y los eventos que la explican, y el portal enlaza a ellos.

## 8. Política de capturas

Se conservan sin caducidad, en `resultados/<run_id>/capturas/` y luego en `evidencias/`:

- todos los cuadros en zona baja;
- todos los cuadros de las ventanas que abrieron una alerta;
- 1 de cada 20 cuadros en operación normal.

No se guardan todos los cuadros. Cada captura tiene su `event_id`, su SHA-256 y una ruta que el portal puede abrir.

## 9. Métricas base (una por grupo; los 7 grupos aplican)

Para cada métrica, `docs/metricas.md` (#4) fija las cinco comprobaciones de la rúbrica: M1 definición, M2 adquisición, M3 cálculo, M4 trazabilidad y M5 recálculo. Las cinco salen del mismo diseño:

- **M2:** los datos crudos están en cada evento o alerta.
- **M3:** `p6.metricas` calcula por ventana y por corrida.
- **M4:** cada resultado lista sus `window_id` y su rango de `event_id`.
- **M5:** `python -m p6.metricas --recalcular` recalcula desde la base de datos y lo compara con lo guardado, y una prueba lo comprueba contra valores calculados a mano.

| Grupo | Métrica | Definición | Población y exclusiones | Sin datos |
|---|---|---|---|---|
| G1 Servicio | Tiempo de inferencia p50 y p95 (ms) | `t_infer_ms + t_post_ms`; percentil por rango más cercano | Cuadros con inferencia completada; excluye `warmup` y `error` | «sin datos», nunca 0 |
| G2 Stream | Cuadros procesados por segundo | Cuadros con inferencia completada / segundos monotónicos entre el primer y el último cuadro de la ventana | Por ventana y por corrida | «sin datos» |
| G3 Recursos | RAM del proceso (MB) | RSS con psutil al terminar cada cuadro; se reporta el máximo y el último de la ventana | Todos los cuadros | «sin datos» |
| G4 Predicciones | Proporción de baja confianza | Cuadros en zona baja / cuadros con detecciones | Excluye `sin_detecciones` y `error`; requiere el mínimo de 10 cuadros | `insuficiente` |
| G5 Trazabilidad | Cobertura de trazabilidad | Eventos con todos los campos obligatorios y, si tienen `image_ref`, archivo existente con SHA-256 coincidente / eventos totales | Toda la corrida | «sin datos» si la corrida está vacía |
| G6 Versiones | Coincidencia de versión del modelo | Eventos con `model_sha256` igual al del descriptor / eventos totales; además, lista de versiones distintas | Toda la corrida | «sin datos» |
| G7 Alertas | Alertas activas | Alertas abiertas al cierre de cada ventana | Serie por ventana | 0 es un valor válido |

## 10. Escenarios obligatorios

| Escenario | Entrada | Resultado esperado | Evidencia en `evidencias/escenarios/` |
|---|---|---|---|
| C1 operación normal | `datos/videos/normal.mp4`, otra toma de la escena de referencia | Inferencias reales; la mayoría de cuadros en zona aceptada o duda; métricas coherentes; sin alertas falsas, o con alertas que cumplen su regla | Comando, `run.json`, eventos, alertas, métricas, capturas y capturas de pantalla del portal |
| C2 baja confianza | `datos/videos/baja_confianza.mp4`: poca luz, desenfoque, objetos lejos o tapados a medias | Cuadros en zona baja, capturas conservadas y alerta A abierta según su regla; las puntuaciones no se modifican | Lo mismo, más la ventana que disparó la alerta |

C1 y C2 usan el mismo modelo y la misma configuración (mismo `config_sha256`).

## 11. Cronograma

| Día | Issues | Resultado al final del día |
|---|---|---|
| Martes 10 (noche) | #1, #2 | Los 3 videos grabados; hora de entrega y rúbrica para agentes a la mano |
| Miércoles 11 | #3, #4, #5 | Un video produce eventos reales; contrato y métricas definidos; umbrales y reglas elegidos con la referencia |
| Jueves 12 | #6, #7, #8, #9 | Eventos, capturas y alertas en el portal; las 7 métricas se recalculan; C1 y C2 corridos con evidencia |
| Viernes 13 | #10, luego #11–#14 | README probado desde un clon limpio, índice de evidencias, autoevaluación y entrega; extras si sobra tiempo |

## 12. Si hay retraso

Se recorta en este orden:

1. los extras (#11–#14);
2. el modo webcam en vivo, porque los videos bastan para la base;
3. el diseño del portal, porque dos tablas con enlaces bastan.

No se recorta: las 7 métricas ni los dos escenarios (35 puntos), ni el README reproducible.

## 13. Extras (se suman sin límite; cuentan solo si están completos)

| Issue | Tipo | Nivel buscado | Puntos |
|---|---|---|---:|
| #11 | Métricas: cuadros sin detecciones, detecciones por cuadro y cuadros capturados por segundo | Sencillo o por ventana | 3–5 cada una |
| #12 | Funcionalidad: exportar eventos a CSV desde el portal | Sencillo | 5 |
| #13 | Funcionalidad: las 78 fotos del carrito como segunda fuente seleccionable | Sencillo | 5 |
| #14 | Escenario: interrupción del stream y recuperación | Secuencia con recuperación | 5–8 |

## 14. Riesgos

| Riesgo | Mitigación |
|---|---|
| Solo hay 3 días de trabajo | Orden de recorte de la sección 12; los extras van al final |
| macOS no deja usar la cámara | Dar permiso en Configuración → Privacidad → Cámara; los videos de QuickTime no dependen de eso |
| `baja_confianza.mp4` no baja lo suficiente las puntuaciones | Comprobarlo apenas funcione #3 y, si hace falta, volver a grabar con menos luz. Los umbrales no se mueven después de ver C2 |
| Videos demasiado pesados para Git | `scripts/preparar_video.py` los reduce a 640×480; los originales quedan fuera de Git |
| El `python3` del sistema es 3.14 | Crear el entorno con `python3.12` |
| Hora de entrega y rúbrica para agentes desconocidas | #2 |

## 15. Mapa de la rúbrica

| Subcriterio | Issue | Evidencia |
|---|---|---|
| R1.1 stream con ritmo declarado | #3 | `run.json` (fuente, ritmo y muestreo) |
| R1.2 inferencias reales | #3, #9 | eventos con detecciones, `model_sha256` |
| R1.3 identidad del modelo | #3, #10 | `modelo/descriptor.yaml`, README |
| R2 métricas (5 comprobaciones × 7 grupos) | #4, #8 | `docs/metricas.md`, `evidencias/metricas/` |
| R3.1 umbrales justificados | #5 | `evidencias/referencia/` |
| R3.2 tres zonas y piso visible | #3, #5 | configuración y eventos con zona |
| R3.3 referencia, ventanas y regla sostenida | #5, #7 | `docs/politica.md`, regla B |
| R4.1 campos del evento | #4 | contrato y eventos |
| R4.2 eventos persistentes y consultables | #6 | SQLite y portal |
| R4.3 imágenes vinculadas sin caducidad | #6 | `capturas/` y G5 |
| R5.1 reglas explícitas | #5, #7 | `config/monitoreo.yaml`, `docs/politica.md` |
| R5.2 alertas vinculadas a eventos | #7 | `alertas.jsonl` |
| R5.3 alertas en el portal | #7 | capturas de pantalla |
| R6.1 C1 | #9 | `evidencias/escenarios/c1-normal/` |
| R6.2 C2 | #9 | `evidencias/escenarios/c2-baja-confianza/` |
| R7.1 instalación y comandos | #10 | README |
| R7.2 evidencias con revisión Git | #10 | `evidencias/INDICE.md` |
| R7.3 autoría y reutilizados | #10 | sección 3 de este plan y README |
