# Contrato del evento y de la alerta

Versión 1. Lo que guarda cada evento y cada alerta, y las reglas que se validan en código ([`src/p6/contrato.py`](../src/p6/contrato.py)). Las métricas de [`metricas.md`](metricas.md) se calculan solo con estos campos. Cubre R4.1 de la rúbrica y la definición (M1) de las métricas que dependen de ellos.

## 1. Convenciones

| Tipo | Significa |
|---|---|
| texto | Cadena no vacía |
| entero | Número entero (no booleano) |
| número | Número finito, entero o decimal |
| booleano | `true` o `false` |
| fecha | Texto ISO 8601, por ejemplo `2026-11-12T06:10:00.123+00:00` (UTC) |
| lista | Arreglo JSON |

**Nulo.** Un campo marcado «puede ser nulo» debe estar presente con valor `null` cuando se cumple la condición indicada. Un campo ausente es un error, aunque su valor fuera a ser `null`.

**Etapas.** El contrato se completa a medida que avanza el proyecto. Cada campo dice desde qué etapa es obligatorio y una etapa exige también todo lo anterior:

| Etapa | Issue | Qué agrega |
|---|---|---|
| H1 | #3 | Lo que produce el detector sobre cada cuadro |
| H3 | #5 | La zona de confianza y la ventana |
| H4 | #6 | La captura vinculada |

Los eventos de esta versión del código cumplen **H3** (`ETAPA_CONTRATO` en `monitorear.py`). #6 sube la etapa a H4.

## 2. Evento

Un evento por cuadro procesado. Se guarda en `eventos.jsonl` (una línea JSON por evento) y, desde #6, en la base de datos.

| Campo | Tipo | Desde | Nulo | Descripción |
|---|---|---|---|---|
| `event_id` | texto | H1 | no | `<run_id>-<frame_id>`. Identifica el evento |
| `run_id` | texto | H1 | no | Corrida a la que pertenece |
| `frame_id` | entero ≥ 1 | H1 | no | Correlativo dentro de la corrida, en el orden en que se procesaron los cuadros |
| `source_id` | texto | H1 | no | Fuente, por ejemplo `video:normal.mp4`, `carpeta:fotos`, `webcam:0` |
| `source_kind` | texto | H1 | no | `video`, `carpeta` o `webcam` |
| `origen` | texto | H1 | no | De dónde salió el cuadro, por ejemplo `cuadro 19 de normal.mp4`. Permite volver al cuadro original |
| `t_capture_utc` | fecha | H1 | no | Reloj de pared al entregar el cuadro (UTC) |
| `t_mono_ms` | número | H1 | no | Reloj monotónico en milisegundos. Solo se compara con otros cuadros de la misma corrida |
| `task` | texto | H1 | no | Siempre `detection` |
| `model_version` | texto | H1 | no | Versión del descriptor del modelo, por ejemplo `0.1.1rc0` |
| `model_sha256` | texto | H1 | no | SHA-256 del archivo de pesos cargado (64 caracteres hexadecimales en minúscula) |
| `config_sha256` | texto | H1 | no | SHA-256 de `config/monitoreo.yaml` completo |
| `status` | texto | H1 | no | `ok`, `sin_detecciones` o `error` (ver abajo) |
| `error_msg` | texto | H1 | sí | Motivo del fallo. Obligatorio con `error`; nulo en los demás casos |
| `detections` | lista | H1 | no | Cada detección con puntuación ≥ piso del detector. Vacía con `sin_detecciones` y con `error` |
| `frame_score` | número | H1 | sí | Puntuación más alta entre las detecciones del cuadro. Nulo sin detecciones o con error |
| `zone` | texto | H3 | sí | `aceptada`, `duda` o `baja`. Nulo si `frame_score` es nulo |
| `window_id` | entero ≥ 1 | H3 | no | Ventana del cuadro: `(frame_id − 1) // 20 + 1` (20 cuadros consecutivos sin solapamiento; tamaño en `config/monitoreo.yaml`, ver [`politica.md`](politica.md)) |
| `t_pre_ms` | número ≥ 0 | H1 | sí | Preprocesamiento (letterbox). Nulo solo con `error` |
| `t_infer_ms` | número ≥ 0 | H1 | sí | Inferencia del modelo. Nulo solo con `error` |
| `t_post_ms` | número ≥ 0 | H1 | sí | Posprocesamiento (decodificación y NMS). Nulo solo con `error` |
| `rss_mb` | número > 0 | H1 | no | Memoria residente del proceso al terminar el cuadro, en MiB (2^20 bytes) |
| `warmup` | booleano | H1 | no | Verdadero en los primeros `cuadros_warmup` (5) cuadros de la corrida |
| `image_ref` | texto | H4 | sí | Ruta relativa de la captura conservada. Nulo si la política no guardó este cuadro |
| `image_sha256` | texto | H4 | sí | SHA-256 de la captura. Va junto con `image_ref`: ambos nulos o ambos con valor |

**Cada detección** de `detections`:

| Campo | Tipo | Descripción |
|---|---|---|
| `class_id` | entero | Índice de la clase en `modelo/descriptor.yaml` (COCO, 0 a 79) |
| `class_name` | texto | Nombre de la clase |
| `score` | número en [0, 1] | Objectness × probabilidad de la clase. Es la salida del modelo sin modificar; no es la probabilidad de acertar |
| `bbox` | lista de 4 números | `[x1, y1, x2, y2]` en píxeles del cuadro original |

### Estados del cuadro

| `status` | Cuándo | `detections` | `frame_score` | `zone` |
|---|---|---|---|---|
| `ok` | El detector corrió y hubo al menos una detección ≥ piso | no vacía | máximo de sus `score` | `aceptada`, `duda` o `baja` |
| `sin_detecciones` | El detector corrió y nada superó el piso | vacía | nulo | nulo |
| `error` | El cuadro no se pudo leer o el detector falló | vacía | nulo | nulo |

`sin_detecciones` y `error` son estados aparte: no tienen confianza cero y no entran en el cálculo de baja confianza.

### Zonas

Las asigna la política ([`politica.md`](politica.md)). Con el umbral inferior `u_inf` (0.85) y el superior `u_sup` (0.90) de `config/monitoreo.yaml`, sobre `frame_score` = s:

- `aceptada`: s ≥ `u_sup`.
- `duda`: `u_inf` ≤ s < `u_sup`.
- `baja`: s < `u_inf`.

«Aceptada» significa aceptada por la política, no que la detección sea correcta.

### Reglas entre campos

Además del tipo de cada campo, se rechaza un evento si:

- `event_id` no es `<run_id>-<frame_id>`, o `frame_id` < 1.
- `task` no es `detection`, `source_kind` no es uno de los tres tipos, o `status` no es uno de los tres estados.
- `model_sha256` o `config_sha256` no son SHA-256 en hexadecimal minúscula.
- `error_msg` es nulo con `error`, o tiene valor con otro estado.
- `detections` está vacía con `ok`, o tiene elementos con `sin_detecciones` o `error`.
- Una detección tiene `score` fuera de [0, 1] o un `bbox` que no son 4 números.
- `frame_score` es nulo habiendo detecciones, tiene valor sin detecciones, o no es el máximo de los `score`.
- Un tiempo es nulo con un estado distinto de `error`, o es negativo. `rss_mb` no es positivo.
- (H3) `zone` no es una zona válida, es nula habiendo `frame_score`, o tiene valor sin él. `window_id` < 1.
- (H4) Solo uno de `image_ref` e `image_sha256` es nulo, o `image_sha256` no es un SHA-256.

### Ejemplo (ilustrativo)

Los valores están inventados para mostrar la forma. No salen de ninguna corrida; las corridas reales están en `resultados/<run_id>/eventos.jsonl`.

```json
{
  "event_id": "ejemplo-7", "run_id": "ejemplo", "frame_id": 7,
  "source_id": "video:normal.mp4", "source_kind": "video", "origen": "cuadro 19 de normal.mp4",
  "t_capture_utc": "2026-11-12T06:10:00.123+00:00", "t_mono_ms": 1200.5,
  "task": "detection", "model_version": "0.1.1rc0",
  "model_sha256": "c789161e…(64 caracteres)", "config_sha256": "b2f0…(64 caracteres)",
  "status": "ok", "error_msg": null,
  "detections": [
    {"class_id": 0, "class_name": "person", "score": 0.912, "bbox": [210.5, 40.0, 470.2, 480.0]},
    {"class_id": 56, "class_name": "chair", "score": 0.143, "bbox": [5.0, 220.1, 90.4, 400.0]}
  ],
  "frame_score": 0.912, "zone": "aceptada", "window_id": 1,
  "t_pre_ms": 1.1, "t_infer_ms": 6.4, "t_post_ms": 0.6, "rss_mb": 212.4, "warmup": false,
  "image_ref": null, "image_sha256": null
}
```

## 3. Alerta

Una alerta por episodio continuo de una regla (ver `docs/PLAN.md`, sección 7): se abre cuando se cumple la condición y se cierra en la primera ventana suficiente en que deja de cumplirse. Se guarda en `alertas.jsonl` y, desde #7, en la base de datos.

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `alert_id` | texto | no | Identifica la alerta, por ejemplo `<run_id>-<rule_id>-<n>` |
| `rule_id` | texto | no | Regla que la generó (`A`, `B`, `C`), definida en `config/monitoreo.yaml` |
| `run_id` | texto | no | Corrida |
| `status` | texto | no | `abierta` o `cerrada` |
| `opened_at` | fecha | no | Instante en que se abrió |
| `opened_window_id` | entero ≥ 1 | no | Ventana en que se abrió. Debe estar en `window_ids` |
| `closed_at` | fecha | sí | Instante de cierre. Nulo mientras esté abierta |
| `closed_window_id` | entero | sí | Ventana de cierre. Nulo mientras esté abierta |
| `severity` | texto | no | `info`, `warning` o `critical` |
| `reason` | texto | no | Qué se midió y contra qué límite, con los valores |
| `window_ids` | lista de enteros | no | Ventanas que explican la alerta (no vacía) |
| `event_ids` | lista de textos | no | Eventos que explican la alerta (no vacía) |
| `config_sha256` | texto | no | Configuración vigente al abrirla |
| `suggested_action` | texto | no | Acción sugerida para quien la investiga |

Se rechaza una alerta si `severity` o `status` no son valores válidos, si está abierta con campos de cierre, si está cerrada sin ellos, si `window_ids` o `event_ids` están vacías o si `opened_window_id` no está en `window_ids`.

### Ejemplo (ilustrativo)

Valores inventados; las alertas reales salen de #7.

```json
{
  "alert_id": "ejemplo-A-1", "rule_id": "A", "run_id": "ejemplo", "status": "abierta",
  "opened_at": "2026-11-12T06:20:00+00:00", "opened_window_id": 2,
  "closed_at": null, "closed_window_id": null, "severity": "warning",
  "reason": "proporción de baja confianza 0.85 ≥ 0.50 en la ventana 2 (17 de 20 cuadros)",
  "window_ids": [2], "event_ids": ["ejemplo-21", "ejemplo-22", "ejemplo-23"],
  "config_sha256": "b2f0…(64 caracteres)",
  "suggested_action": "Revisar la captura, la iluminación y el enfoque"
}
```

## 4. Validación en código

- `validar_evento(evento, etapa)` y `validar_alerta(alerta)` devuelven la lista de problemas; vacía significa que cumple.
- `monitorear` valida cada evento antes de guardarlo. Uno que no cumple **no entra** en `eventos.jsonl`: se escribe en `rechazados.jsonl` con sus motivos y se cuenta en `run.json`:

```json
"contrato": {"documento": "docs/contrato.md", "etapa": "H3"},
"totales": {"eventos_aceptados": 147, "eventos_rechazados": 0, "motivos_rechazo": {}}
```

- Si hay rechazados, el comando termina con código 1 e imprime cada uno con su motivo.
- Pruebas: `tests/test_contrato.py` (cada campo, cada regla y el conteo) y `tests/test_monitorear.py` (los eventos reales cumplen el contrato; uno incompleto se rechaza y se cuenta).

Comprobar el evento de una corrida:

```bash
export PYTHONPATH=src
python -m p6.monitorear --fuente datos/videos/normal.mp4 --sin-pausa --run-id demo | tail -3
# contrato (etapa H3): 147 eventos aceptados, 0 rechazados
```

## 5. Correspondencia con la rúbrica (R4.1)

| Pide la rúbrica | Campo |
|---|---|
| Identidad | `event_id`, `run_id`, `frame_id` |
| Fecha | `t_capture_utc`, `t_mono_ms` |
| Fuente | `source_id`, `source_kind`, `origen` |
| Modelo | `model_version`, `model_sha256` |
| Estado | `status`, `error_msg` |
| Predicción | `detections` (lista vacía con estado explícito si no hay) |
| Confianza, cuando exista | `frame_score` y `score` de cada detección; nulo si no corresponde |
| Configuración usada | `config_sha256` |
