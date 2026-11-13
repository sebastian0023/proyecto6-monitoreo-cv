# Proyecto 6: centro de monitoreo de computer vision

Entrega individual de **Sebastián** (@sebastian0023) para Integración de Servicios de Aprendizaje Automático (ITESO).

Un detector de objetos YOLOX-Nano procesa un video como stream a 5 cuadros por segundo. Cada inferencia real se convierte en un evento con su zona de confianza. Algunos cuadros conservan su imagen. Las reglas por ventana generan alertas, y todo se consulta en un portal web con sus métricas. No se mide si el modelo acierta: se vigila su operación y su confianza.

**Índice de evidencias por criterio de la rúbrica:** [`evidencias/INDICE.md`](evidencias/INDICE.md).

## Resultados

| Escenario | Entrada | Zonas (aceptada / duda / baja) | Alertas | Evidencia |
|---|---|---|---|---|
| Referencia `ref-01` | `referencia.mp4` | 51 / 93 / 3 | ninguna | [`evidencias/referencia/`](evidencias/referencia/) |
| C1 operación normal `c1-normal` | `normal.mp4` | 129 / 18 / 0 | ninguna | [`evidencias/escenarios/c1-normal/`](evidencias/escenarios/c1-normal/) |
| C2 baja confianza `c2-baja-confianza` | `baja_confianza.mp4` | 0 / 19 / 128 | A (ventana 1) y B (ventana 3) | [`evidencias/escenarios/c2-baja-confianza/`](evidencias/escenarios/c2-baja-confianza/) |

Las tres corridas tienen 147 cuadros, el mismo modelo (SHA-256 `c789161e…`) y la misma configuración (SHA-256 `11b06253…`). Las métricas G1–G7 de C1 y C2 y su recálculo están en [`evidencias/metricas/`](evidencias/metricas/).

## Arquitectura

```
video / carpeta / webcam ──► fuente.py ──► detector.py ──► politica.py ──► alertas.py
  (5 cuadros/s declarados,     (YOLOX-Nano ONNX,   (zona por cuadro,   (reglas A y B
   muestreo 1 de cada k)        piso 0.10, NMS)     ventana de 20)      por ventana)
                                                          │                  │
                                                          ▼                  ▼
                               capturas.py ◄──── monitorear.py (cierra cada ventana)
                               (JPEG + SHA-256)          │
                                                          ▼
                     almacen.py: resultados/monitoreo.db (corridas, eventos, alertas, métricas)
                       │                 │                          │
                       ▼                 ▼                          ▼
              eventos.jsonl,       metricas.py (G1–G7,        portal.py (FastAPI, solo lectura):
              alertas.jsonl        cálculo y recálculo)       eventos, alertas, capturas, configuración
```

| Módulo (`src/p6/`) | Qué hace |
|---|---|
| `fuente.py` | Lee video, carpeta de imágenes o webcam y entrega cuadros al ritmo declarado |
| `detector.py` | YOLOX-Nano en ONNX Runtime (CPU): letterbox, inferencia, decodificación y NMS, con tiempos por etapa |
| `config.py` | Lee y valida `config/monitoreo.yaml` |
| `politica.py` | Zona de cada cuadro y resumen por ventana (suficiente o insuficiente) |
| `alertas.py` | Reglas A y B con su ciclo de vida |
| `capturas.py` | Qué cuadros se conservan como imagen y su verificación por SHA-256 |
| `contrato.py` | Campos del evento y de la alerta, y su validación |
| `almacen.py` | Base de datos SQLite y exportación a JSONL |
| `metricas.py` | Las 7 métricas base por corrida y por ventana, y su recálculo |
| `monitorear.py` | CLI que corre el recorrido completo |
| `portal.py` | Portal web de consulta |

## Requisitos

- Python 3.12. Probado en macOS 26 con Apple M4 y CPU, sin GPU.
- Unos 300 MB para el entorno virtual. El modelo pesa 3.7 MB y se descarga de su release público.
- No necesita Docker, nube ni credenciales.

## Instalación

```bash
git clone https://github.com/sebastian0023/proyecto6-monitoreo-cv.git
cd proyecto6-monitoreo-cv
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src                                   # el paquete p6 no se instala; ver nota de macOS
python scripts/descargar_modelo.py --destino modelo/    # falla si el SHA-256 no coincide
python -m pytest                                        # 160 pruebas
```

`export PYTHONPATH=src` hace falta en cada terminal nueva.

## Ejecutar los escenarios

Cada comando procesa el video a 5 cuadros/s reales (unos 30 s) y deja todo en `resultados/`:

```bash
# Referencia (con ella se eligieron los umbrales; ver docs/politica.md)
python -m p6.monitorear --fuente datos/videos/referencia.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id ref-01
python scripts/calibrar_referencia.py --run resultados/ref-01 \
    --salida resultados/calibracion --verificar

# C1 · operación normal
python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id c1-normal

# C2 · baja confianza
python -m p6.monitorear --fuente datos/videos/baja_confianza.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id c2-baja-confianza
```

Cada corrida guarda sus eventos, alertas y métricas en `resultados/monitoreo.db` y escribe en `resultados/<run_id>/`:

| Archivo | Contenido |
|---|---|
| `run.json` | Fuente, ritmo y muestreo; modelo y configuración con su SHA-256; política, reglas y política de capturas; entorno y commit de Git; totales por zona y por ventana; resumen de alertas |
| `eventos.jsonl` | Un evento por cuadro, con sus detecciones, zona, ventana, tiempos y captura (exportado de la base de datos) |
| `alertas.jsonl` | Las alertas, con regla, motivo, ventanas, eventos y acción sugerida |
| `metricas.json` | G1–G7 por corrida y por ventana |
| `capturas/` | Las imágenes conservadas, nombradas con su `event_id` |

Otras opciones:
- `--sin-pausa` procesa sin esperar entre cuadros.
- `--sobrescribir` repite una corrida con el mismo `run_id`.
- `--fuente webcam:0` usa la cámara.
- `--fuente <carpeta>` usa una carpeta de imágenes. Por ejemplo, `--fuente datos/carrito --run-id carrito-p5` usa las 78 fotos del carrito del Proyecto 5 (extra #13; ver [`datos/carrito/README.md`](datos/carrito/README.md)).

## Portal

```bash
python -m p6.portal --db resultados/monitoreo.db           # http://127.0.0.1:8000
python -m p6.portal --db evidencias/escenarios/monitoreo.db  # las corridas entregadas, sin volver a correr nada
```

| Página | Contenido |
|---|---|
| `/eventos` | Eventos con filtros por corrida, estado, zona, ventana y captura |
| `/eventos/{event_id}` | La captura con sus cajas (con el SHA-256 verificado), las detecciones, la zona, la ventana, las alertas y el enlace a la configuración |
| `/alertas` | Alertas con estado, momento, motivo, severidad y filtros |
| `/alertas/{alert_id}` | La regla, sus ventanas y los cuadros que la causaron, con miniaturas |
| `/corridas` | La identidad de cada corrida, sus zonas, ventanas y alertas |
| `/configuracion/{sha256}` | La configuración exacta que produjo los eventos |

También hay una API JSON en `/api/eventos` y `/api/alertas`.

## Métricas y recálculo

```bash
python -m p6.metricas --db resultados/monitoreo.db --run-id c2-baja-confianza               # calcula y guarda
python -m p6.metricas --db resultados/monitoreo.db --run-id c2-baja-confianza --recalcular  # recalcula y compara
```

`--recalcular` vuelve a calcular las 7 métricas desde los eventos, las alertas y las capturas guardadas, y las compara campo por campo con lo guardado. Termina con código 0 si coincide. Las definiciones están en [`docs/metricas.md`](docs/metricas.md).

## Configuración y modelo

[`config/monitoreo.yaml`](config/monitoreo.yaml) está **congelada**: su SHA-256 va en cada `run.json`, evento y alerta. Contiene:

- **Fuente:** 5 cuadros/s, con 5 cuadros de warmup.
- **Detector:** entrada de 416, piso 0.10, NMS 0.45 y hasta 100 detecciones.
- **Umbrales:** inferior 0.85 y superior 0.90.
- **Ventana:** 20 cuadros, con un mínimo de 10 con detecciones para ser suficiente.
- **Referencia:** `ref-01`, con p_ref = 0.0204.
- **Reglas:** A (≥ 0.50) y B (> p_ref + 0.20 en 3 ventanas).

La justificación de cada valor está en [`docs/politica.md`](docs/politica.md).

| Modelo | |
|---|---|
| Detector | YOLOX-Nano preentrenado en COCO 2017, 80 clases. Sin entrenamiento propio |
| Archivo y versión | `yolox_nano.onnx`, release `0.1.1rc0` de [Megvii-BaseDetection/YOLOX](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0), 3 659 407 bytes |
| SHA-256 | `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` (se verifica al descargar y al cargar) |
| Licencia | Apache-2.0 |
| Clases | Las 80 de COCO, en [`modelo/descriptor.yaml`](modelo/descriptor.yaml) |
| Preprocesamiento | Letterbox a 416×416: escala proporcional, relleno gris 114, BGR, float32 de 0 a 255 sin normalizar |
| Posprocesamiento | Decodificación de la rejilla (strides 8/16/32); score = objectness × prob. de clase; piso 0.10; NMS por clase con IoU 0.45 |
| Entorno | ONNX Runtime 1.30.0 en CPU, Python 3.12, OpenCV 5.0; cada `run.json` registra SO, versiones y commit |

## Documentos

- [`docs/PLAN.md`](docs/PLAN.md): plan inicial, decisiones y cronograma.
- [`docs/contrato.md`](docs/contrato.md): campos del evento y de la alerta, y su validación.
- [`docs/politica.md`](docs/politica.md): umbrales, zonas, ventanas y reglas de alerta, justificados con la referencia.
- [`docs/capturas.md`](docs/capturas.md): base de datos, política de capturas y portal.
- [`docs/metricas.md`](docs/metricas.md): inventario G1–G7 y definición de cada métrica.
- [`datos/videos/README.md`](datos/videos/README.md): cómo se grabaron los videos y qué baja la confianza de este detector.

## Autoría y componentes reutilizados

**Autor:** Sebastián (@sebastian0023). Es una entrega individual en un repositorio personal, separado del repositorio del equipo del Proyecto 5.

**Aportación propia:**
- Grabación y preparación de los tres videos.
- Lectura del stream con ritmo declarado.
- Política de confianza, con la elección de umbrales a partir de la referencia.
- Contrato de evento y alerta.
- Eventos persistentes en SQLite, política de capturas, reglas de alerta, métricas G1–G7 y su recálculo.
- Portal, escenarios, evidencias y pruebas.

**Componentes reutilizados:**

| Componente | Origen | Autor | Uso |
|---|---|---|---|
| Pesos `yolox_nano.onnx` 0.1.1rc0 | [Megvii-BaseDetection/YOLOX](https://github.com/Megvii-BaseDetection/YOLOX), SHA-256 `c789161e…0b7d` | Megvii (Apache-2.0) | Sin cambios |
| Letterbox, decodificación y NMS del detector | `Proyecto5/src/p5/detector_onnx.py` de sebastian0023/Proyecto-3-Clasificador-de-imagenes, tag `p5-entrega` | Edith (@edithflor), equipo de P5 | Adaptado en `src/p6/detector.py`: piso configurable, cuadros en memoria, tiempos por etapa y sin el contrato de P5 |
| Descarga del modelo con verificación | `Proyecto5/scripts/descargar_modelo.py`, mismo tag | Edith (@edithflor) | Adaptado en `scripts/descargar_modelo.py` |
| Descriptor del modelo | `Proyecto5/modelo/descriptor.yaml`, mismo tag | Edith (@edithflor) | Adaptado en `modelo/descriptor.yaml`, sin las clases de obstáculo de P5 |

Cada archivo adaptado lleva un encabezado con su origen.

**Bibliotecas:** onnxruntime, NumPy, OpenCV, Pillow, PyYAML, psutil, FastAPI, Uvicorn, Jinja2 y pytest. Las versiones están fijadas en `requirements.txt`.

**Herramientas de asistencia:** el código y la documentación se desarrollaron con ayuda de Claude Code (Anthropic), un asistente de programación; los commits lo indican con la línea `Co-Authored-By`. Las decisiones del proyecto, las grabaciones y la revisión de los resultados son del autor.

## Extras

Por ahora **no se reclaman puntos extra**. Los extras planeados están en los issues #11 a #14 del repositorio. El inventario está en [`evidencias/INDICE.md`](evidencias/INDICE.md#6-extras) y se actualizará si se agregan.

## Límites conocidos

- **Umbrales relativos a la escena.**
  - La referencia es estrecha: su `frame_score` va de 0.83 a 0.95, porque la persona domina la imagen y el detector la puntúa de forma muy estable.
  - Por eso los umbrales (0.85 y 0.90) están a solo 0.05 de distancia. «Baja» significa por debajo de lo normal en esta escena, no baja en términos absolutos.
  - Otra escena o cámara requiere una referencia nueva.
- **Videos cortos.** Son de unos 30 s (147 cuadros, 7 ventanas completas y una parcial). Alcanza para las reglas (B necesita 3 ventanas), pero son pocas ventanas.
- **Estados no ejercitados en C1 y C2.** Los cuadros `sin_detecciones` y `error`, y las ventanas `insuficiente` salvo la última parcial, no aparecen en las corridas entregadas. Están implementados y probados con datos sintéticos (`tests/`).
- **Alertas de C2.** Terminan abiertas, porque la última ventana es insuficiente y no puede cerrarlas. La regla C (evidencia insuficiente sostenida) es opcional y no se implementó.
- **Latencia.** A ritmo real (5 cuadros/s con espera) la latencia de inferencia ronda 18.5 ms. Sin espera ronda 7 ms. Las puntuaciones son idénticas en los dos casos.
- **Alcance.** Una sola fuente por corrida y una base de datos local. El portal no tiene autenticación y está pensado para uso local.
- **Privacidad.** Los videos y las capturas muestran al autor.
- **La confianza no es acierto.** Ninguna métrica mide si las detecciones son correctas, y la regla B detecta un cambio respecto de la referencia, no confirma drift.

## Diferencias con el plan

| Plan ([`docs/PLAN.md`](docs/PLAN.md)) | Entrega | Por qué |
|---|---|---|
| Videos de unos 60 s | Unos 30 s | Así se grabaron; alcanzan para las reglas |
| `baja_confianza.mp4` con poca luz y desenfoque | Poca luz y la persona solo en parte dentro del cuadro | Oscurecer o desenfocar no bajaba las puntuaciones de este detector ([`datos/videos/README.md`](datos/videos/README.md)) |
| Política de capturas en `config/monitoreo.yaml` | Constantes en `src/p6/capturas.py`, registradas en cada `run.json` | La configuración ya estaba congelada y las capturas no cambian puntuaciones, zonas ni alertas |
| G2 = n / intervalo | G2 = (n − 1) / intervalo | n cuadros delimitan n − 1 intervalos |
| Regla C opcional | No implementada | Opcional en el plan y en la rúbrica |
| `pip install -e .` | `export PYTHONPATH=src` | Ver la nota de macOS |

## Nota para macOS

No se usa `pip install -e .`: en carpetas sincronizadas con iCloud, macOS marca como oculto el archivo `.pth` que crea, y Python 3.12 lo ignora. Por eso los comandos usan `PYTHONPATH=src`, que en Linux funciona igual. En Windows PowerShell sería `$env:PYTHONPATH="src"` (no probado).
