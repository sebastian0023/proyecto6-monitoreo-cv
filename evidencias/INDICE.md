# Índice de evidencias

Relaciona cada criterio de la rúbrica ([`docs/prompt-evaluacion-proyecto-6.md`](../docs/prompt-evaluacion-proyecto-6.md)) con los archivos, los identificadores, la configuración y la revisión de Git que lo sostienen. Todas las rutas son relativas a la raíz del repositorio.

Para verificar se necesita la instalación del [README](../README.md#instalación) y `export PYTHONPATH=src`. Ninguna comprobación de este índice requiere volver a correr los escenarios: `evidencias/escenarios/monitoreo.db` contiene las corridas entregadas.

## 1. Identidad

| | |
|---|---|
| Estudiante | Sebastián (@sebastian0023), entrega individual |
| Repositorio | `sebastian0023/proyecto6-monitoreo-cv`, rama `main`, tag `p6-entrega` |
| Tarea | Detección de objetos |
| Fuente | Videos propios (`datos/videos/`) reproducidos como stream a 5 cuadros/s; muestreo 1 de cada 3 cuadros de un video de 15 cuadros/s |
| Modelo | YOLOX-Nano `0.1.1rc0`, `modelo/yolox_nano.onnx`, SHA-256 `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` (`modelo/descriptor.yaml`) |
| Configuración | `config/monitoreo.yaml`, SHA-256 `11b0625330078e09f04f6d8c45efe9e09997a28d34afbaf07a75978e4b500a3f`, la misma en la referencia, C1 y C2 |
| Entorno | macOS 26 (arm64, Apple M4), Python 3.12.13, onnxruntime 1.30.0 en CPU (en cada `run.json`) |

| Video | SHA-256 |
|---|---|
| `datos/videos/referencia.mp4` | `ac2d62846cc0d020d753ae48b50d6c0972ec9df5b32c5f0c3cb1cc14db2c0d84` |
| `datos/videos/normal.mp4` | `01ad6ffa103aaf49f938bb081795267498a45199db9ad7ebc08755d57cb6cf19` |
| `datos/videos/baja_confianza.mp4` | `9393e680716f14652a69f9d66b927a8853658b59553fb6c53c0115ef029876bb` |

## 2. Revisiones de Git

Las evidencias se generaron con un commit de código ya confirmado, con el árbol limpio, y se incorporaron en el commit siguiente. Cada `run.json` registra el commit con que corrió (`entorno.git_commit`) y si el árbol tenía cambios (`entorno.git_arbol_con_cambios`).

| Evidencia | Generada con el commit | Incorporada en | Árbol limpio |
|---|---|---|---|
| Calibración previa `ref-00` (`evidencias/referencia/calibracion-previa/`) | `8414427` | `c7a54a9` | no: había un archivo nuevo sin seguimiento (`scripts/calibrar_referencia.py`); el código de `src/p6` es el del commit |
| Referencia `ref-01` (`evidencias/referencia/`) | `ff2fcb9` (configuración congelada) | `c7a54a9` | sí |
| C1 `c1-normal`, C2 `c2-baja-confianza`, C3 `c3-interrupcion` y `carrito-p5` (`evidencias/escenarios/`, `evidencias/metricas/`, `evidencias/extras/`) | `3dc1c44` | el commit siguiente | sí |

C1 y C2 se corrieron primero con `9a4ba47` (evidencia en `675c8fe`). Al agregar los extras (#11 a #14) se volvieron a correr con `3dc1c44`, que ya contiene el código de los extras, para que toda la evidencia corresponda al mismo código. Las zonas, ventanas, alertas y capturas de C1 y C2 son idénticas en las dos revisiones; solo cambian las marcas de tiempo, la latencia y la RAM.

Después de `3dc1c44` solo cambian la documentación y las evidencias, no el código. El tag `p6-entrega` marca la revisión entregada.

## 3. Criterios R1 a R7

### R1 · Fuente visual y modelo

| Subcriterio | Evidencia | Cómo verificar |
|---|---|---|
| R1.1 Stream con ritmo o muestreo documentado | `src/p6/fuente.py`. `run.json` → `fuente`: ritmo declarado 5, `muestreo.k` = 3, `fps_video` 15. Ritmo medido: 5.021 cuadros/s (`totales.cuadros_por_s_medido`) y G2 4.999 en C1 | `evidencias/escenarios/c1-normal/run.json`; `tests/test_fuente.py` (muestreo 1 de cada k y espera entre entregas) |
| R1.2 Inferencias reales atribuibles al modelo | Cada evento lleva sus `detections` con `score` y `bbox` y el `model_sha256` del archivo cargado. `salida.txt` de cada escenario muestra cuadro por cuadro | `evidencias/escenarios/*/eventos.jsonl`; `tests/test_detector.py::test_modelo_real_detecta_a_la_persona_de_un_cuadro_conocido` |
| R1.3 Modelo, versión, clases, preprocesamiento y entorno | `modelo/descriptor.yaml` (URL, versión, bytes, SHA-256, licencia, 80 clases, entrada y salida), [README → Configuración y modelo](../README.md#configuración-y-modelo), `run.json` → `modelo` y `entorno` | `python scripts/descargar_modelo.py --destino modelo/` verifica el SHA-256 |

### R2 · Métricas G1–G7

Los 7 grupos aplican y no hay exclusiones: [`docs/metricas.md`](../docs/metricas.md), sección 1. Hay una métrica base por grupo y ninguna se repite entre grupos.

| Grupo · métrica base | M1 Definición | M2 Adquisición | M3 Cálculo y resultado | M4 Trazabilidad | M5 Recálculo |
|---|---|---|---|---|---|
| G1 · Latencia de inferencia p50/p95 | `docs/metricas.md` §3 G1 | `t_infer_ms`, `t_post_ms` medidos con `time.perf_counter` en `detector.py` | `metricas.py::g1_latencia`; C1 18.8/23.8 ms, C2 19.9/23.2 ms | `n` 142, `window_ids`, rango `c1-normal-6`…`c1-normal-147`, excluidos (5 de warmup) | ver abajo |
| G2 · Cuadros procesados por segundo | §3 G2 | `t_mono_ms` (`time.monotonic`) al entregar cada cuadro, en `fuente.py` | `g2_cuadros_por_s`; C1 4.999, C2 4.999 | `n`, intervalo, rango de eventos | ver abajo |
| G3 · RAM del proceso | §3 G3 | `rss_mb` con psutil al terminar cada cuadro, en `monitorear.py` | `g3_ram`; máx. 183.6 y 184.5 MiB | `event_id_max`, rango | ver abajo |
| G4 · Proporción de baja confianza | §3 G4 | `zone` y `status` de cada evento (`politica.py`) | `g4_baja_confianza`; C1 0.0 (0/147), C2 0.8707 (128/147); `insuficiente` en la ventana parcial | `baja`, `con_detecciones`, excluidos, rango | ver abajo |
| G5 · Cobertura de trazabilidad | §3 G5 | Contrato de cada evento y archivos de captura con su SHA-256 (`capturas.py`) | `g5_trazabilidad`; 1.0 en C1 y C2 | `cumplen`, `total`, lista de eventos que no cumplen (vacía) | ver abajo |
| G6 · Coincidencia de versión del modelo | §3 G6 | `model_sha256` calculado al cargar los pesos (`detector.py`) | `g6_version`; 1.0 con 1 versión en C1 y C2 | `versiones` con conteo, SHA-256 esperado | ver abajo |
| G7 · Alertas activas | §3 G7 | Tabla `alertas`, generada por `alertas.py` | `g7_alertas_*`; C1 0 en las 8 ventanas, C2 1, 1, 2, 2, 2, 2, 2, 2 | `alert_ids` activos por ventana | ver abajo |

- **Resultados:** `evidencias/metricas/c1-normal.json` y `c2-baja-confianza.json`, por corrida y por ventana. Son los mismos que los `metricas.json` de cada escenario y que la tabla `metricas` de la base de datos.
- **Cero observaciones:** `sin datos` (valor `null`) e `insuficiente`; G7 admite 0 ([`docs/metricas.md`](../docs/metricas.md) §4 y §5).
- **M5, recálculo desde datos primarios:** `evidencias/metricas/recalculo-*.txt`, donde las 7 métricas coinciden en la corrida y en las 8 ventanas.

  ```bash
  python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id c2-baja-confianza --recalcular
  ```

- **Pruebas:** `tests/test_metricas.py` comprueba cada métrica contra el ejemplo calculado a mano de `docs/metricas.md`.

### R3 · Umbrales y monitoreo de confianza

| Subcriterio | Evidencia | Cómo verificar |
|---|---|---|
| R3.1 Dos umbrales justificados con la referencia | `config/monitoreo.yaml` → `confianza`: inferior 0.85, superior 0.90. Salen de los percentiles 10 (0.8657) y 50 (0.8956) de `ref-01`, redondeados a 0.05 ([`docs/politica.md`](../docs/politica.md) §4). `evidencias/referencia/`: `calibracion.json`, `histograma.svg`, `histograma.csv` | `python scripts/calibrar_referencia.py --run <corrida de referencia> --salida /tmp/cal --verificar` (código 0) |
| R3.2 Tres zonas, piso visible y cuadros sin detecciones aparte | `docs/politica.md` §2 y §3: piso 0.10, NMS 0.45, igualdades, denominador = cuadros con detecciones. Cada evento lleva `zone` y `status`; `sin_detecciones` y `error` no tienen zona. Las dos zonas bajas se observan en C2 (19 en duda y 128 en baja). Los cuadros sin detecciones se observan aparte en la corrida `carrito-p5` (16, sin zona, fuera del denominador de G4) | Portal `/eventos?zone=ninguna`; `tests/test_politica.py`, `tests/test_contrato.py` |
| R3.3 Referencia, ventanas, mínimo y regla sostenida; insuficiente ≠ normal | `config/monitoreo.yaml` → `referencia` (`ref-01`, `p_ref` 0.0204) y `alertas.B` (> p_ref + 0.20 en 3 ventanas). Ventana de 20 cuadros, mínimo de 10 con detecciones ([`docs/politica.md`](../docs/politica.md) §5 y §6). La regla B se abre en C2, ventana 3. La ventana 1 de `carrito-p5` es insuficiente (9 de 20 con detecciones) y no abre ninguna regla | `tests/test_alertas.py`: las ventanas insuficientes no suman ni rompen la racha, y la referencia real no dispara alertas |

### R4 · Eventos e imágenes

| Subcriterio | Evidencia | Cómo verificar |
|---|---|---|
| R4.1 Identidad, fecha, fuente, modelo, estado, predicción, confianza y configuración | [`docs/contrato.md`](../docs/contrato.md), con la correspondencia en §5. Validación en `src/p6/contrato.py`: 147 aceptados y 0 rechazados por corrida (`run.json` → `totales`) | Cualquier línea de `evidencias/escenarios/*/eventos.jsonl` |
| R4.2 Persistencia y consulta en el portal, con vínculos | Base de datos `evidencias/escenarios/monitoreo.db` (tablas `corridas`, `eventos`, `alertas`, `metricas`). Portal `/eventos` y `/eventos/{id}`, con enlaces a la captura, la ventana, las alertas, la corrida y la configuración. Pantallas en `evidencias/escenarios/*/portal/` ([`docs/capturas.md`](../docs/capturas.md) §3) | `python -m p6.portal --db evidencias/escenarios/monitoreo.db` |
| R4.3 Imágenes con política documentada, vinculadas y sin caducidad | [`docs/capturas.md`](../docs/capturas.md) §2: zona baja, ventana que abre alerta y 1 de cada 20; sin caducidad. Cada evento con captura lleva `image_ref`, `image_sha256` e `image_reason`. `evidencias/escenarios/*/capturas/`: 8 en C1 y 139 en C2. G5 = 1.0 verifica cada archivo por SHA-256 | Portal: «SHA-256 verificado» en el detalle; `tests/test_capturas.py`, `tests/test_portal.py` (capturas borradas o alteradas se muestran como rotas) |

### R5 · Alertas

| Subcriterio | Evidencia | Cómo verificar |
|---|---|---|
| R5.1 Reglas explícitas con ventana, persistencia y datos insuficientes | `config/monitoreo.yaml` → `alertas` (A y B con severidad y acción sugerida). [`docs/politica.md`](../docs/politica.md) §6: condición, ciclo de vida, y que las ventanas insuficientes no abren, no cierran y no rompen la racha. Implementadas en `src/p6/alertas.py` | `tests/test_alertas.py` (secuencias sintéticas) |
| R5.2 Alertas reales vinculadas a regla, configuración y eventos | `evidencias/escenarios/c2-baja-confianza/alertas.jsonl`: `c2-baja-confianza-A-1` (ventana 1) y `c2-baja-confianza-B-1` (ventana 3), cada una con `rule_id`, `config_sha256`, `window_ids` 1–7 y 121 `event_ids`. Las líneas `ALERTA … abierta` están en `salida.txt` | `evidencias/escenarios/c2-baja-confianza/README.md` |
| R5.3 Alertas en el portal con momento, motivo, severidad y acción | `/alertas` y `/alertas/{id}`. Pantallas `evidencias/escenarios/c2-baja-confianza/portal/3-alertas.png`, `4-alerta-A-detalle.png` y `5-alerta-B-detalle.png` | `python -m p6.portal --db evidencias/escenarios/monitoreo.db` → `/alertas` |

### R6 · Demostración

| Subcriterio | Evidencia |
|---|---|
| R6.1 C1 operación normal | [`evidencias/escenarios/c1-normal/README.md`](escenarios/c1-normal/README.md): entrada, comando, commit, esperado frente a observado, eventos, métricas y portal. 129 aceptados, 18 en duda, 0 en baja y ninguna alerta |
| R6.2 C2 baja confianza | [`evidencias/escenarios/c2-baja-confianza/README.md`](escenarios/c2-baja-confianza/README.md): 128 de 147 cuadros en baja con puntuaciones reales, 139 capturas, alerta A (y B) según su regla, y el recorrido de la alerta a los cuadros en el portal |

### R7 · Repositorio y reproducibilidad

| Subcriterio | Evidencia |
|---|---|
| R7.1 Instalación, dependencias, configuración y comandos | [README](../README.md): instalación, escenarios, portal, métricas y pruebas. `requirements.txt` con versiones fijas. `config/monitoreo.yaml`. Probado desde un clon limpio con un entorno nuevo |
| R7.2 Evidencias verificables y vinculadas a la revisión de Git | Este índice (sección 2, revisiones). Un README por carpeta de evidencias, con comando, commit y pasos para recalcular. Base de datos reubicable en `evidencias/escenarios/` |
| R7.3 Autoría, aportación propia, reutilizados y origen del modelo | [README → Autoría y componentes reutilizados](../README.md#autoría-y-componentes-reutilizados). Encabezados de origen en `src/p6/detector.py`, `scripts/descargar_modelo.py` y `modelo/descriptor.yaml` |

## 4. Recorrido de una muestra

El cuadro `c2-baja-confianza-26`, de la entrada a la alerta:

| Paso | Dónde | Valor |
|---|---|---|
| Entrada | `datos/videos/baja_confianza.mp4` | cuadro 76 del video (`origen`), entregado el 2026-11-13 a las 00:25:30.986 UTC |
| Salida del modelo | `eventos.jsonl` → `detections` | `person` 0.4284 y `donut` 0.2517, ambos sobre el piso 0.10 |
| Evento | `eventos.jsonl`, tabla `eventos` | `status` ok, `frame_score` 0.428433, `zone` baja (< 0.85), `window_id` 2 |
| Captura | `evidencias/escenarios/c2-baja-confianza/capturas/c2-baja-confianza-26.jpg` | `image_reason` baja, SHA-256 `675867b915b34fddc8ddf4ef8d07a793f3eae8c5a1e423dd63d0a8e4ea9d04e3` |
| Ventana | `metricas.json` → `ventanas[1].G4` | ventana 2: 17 de 20 en baja, proporción 0.85 (eventos `c2-baja-confianza-21` … `-40`) |
| Alertas | `alertas.jsonl` | está en los `event_ids` de `c2-baja-confianza-A-1` y de `c2-baja-confianza-B-1` |
| Portal | `/eventos/c2-baja-confianza-26` | pantalla `evidencias/escenarios/c2-baja-confianza/portal/2-evento-detalle-con-captura.png` |

```bash
grep '"c2-baja-confianza-26"' evidencias/escenarios/c2-baja-confianza/eventos.jsonl
shasum -a 256 evidencias/escenarios/c2-baja-confianza/capturas/c2-baja-confianza-26.jpg
```

## 5. Evidencias esperadas por la rúbrica

| # | La rúbrica pide | Dónde |
|---|---|---|
| 1 | README con instalación, dependencias, ejecución, arquitectura y límites | [README](../README.md) |
| 2 | Identidad, aporte individual, reutilizados y origen del modelo | README → Autoría y componentes reutilizados; Configuración y modelo |
| 3 | Configuración reproducible de fuente, modelo, muestreo, umbrales, referencia, ventanas y alertas | `config/monitoreo.yaml`, `modelo/descriptor.yaml` |
| 4 | Inventario G1–G7 con aplicabilidad, métrica base, definición y evidencias | `docs/metricas.md` §1 y §3; sección R2 de este índice |
| 5 | Observaciones y métricas en formato recalculable | `eventos.jsonl`, `alertas.jsonl`, `metricas.json`, `monitoreo.db` |
| 6 | Eventos, alertas e imágenes vinculados por IDs | `event_id`, `alert_id`, `event_ids`, `window_ids`, `image_ref` con su SHA-256 (sección 4) |
| 7 | Entradas, comandos y resultados de C1/C2 con identidad de ejecución y revisión | `evidencias/escenarios/*/README.md`, `salida.txt` y `run.json` |
| 8 | Evidencia de las consultas del portal | `evidencias/escenarios/*/portal/*.png`, `evidencias/escenarios/configuracion.png` y el portal sobre `monitoreo.db` |
| 9 | Índice de criterios, archivos, IDs, configuración y revisión | este archivo |
| 10 | Inventario de extras o declaración de no presentarlos | sección 6 |

## 6. Extras

Inventario completo, con tipo, nivel pedido, evidencia y cómo verificar: [`evidencias/extras/README.md`](extras/README.md).

| ID | Tipo | Elemento | Nivel pedido | Evidencia principal |
|---|---|---|---|---|
| X1 | Funcionalidad | Exportar a CSV los eventos filtrados desde el portal (#12) | 10 | `/eventos.csv`; `evidencias/extras/csv/` |
| X2 | Funcionalidad | Fotos del carrito de P5 como segunda fuente (#13) | 5 | `datos/carrito/`; `evidencias/escenarios/carrito-p5/` |
| X3 | Métrica | E1 · proporción de cuadros sin detecciones (G4) (#11) | 5 | `docs/metricas.md` §6; `extras.E1` en `evidencias/metricas/*.json` |
| X4 | Métrica | E2 · detecciones por cuadro (G4) (#11) | 5 | `docs/metricas.md` §6; `extras.E2` |
| X5 | Métrica | E3 · predicciones por clase (G4) (#11) | 5 | `docs/metricas.md` §6; `extras.E3` |
| X6 | Escenario | C3 · interrupción del stream y recuperación (#14) | 10 | `evidencias/escenarios/c3-interrupcion/`; regla F (`docs/politica.md` §9) |

Ninguno repite un requisito base. El carrito se reclama solo como funcionalidad, no también como escenario.
