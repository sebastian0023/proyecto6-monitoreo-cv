# Proyecto 6: centro de monitoreo de computer vision

Entrega individual de Sebastián (@sebastian0023) para Integración de Servicios de Aprendizaje Automático (ITESO).

Un detector YOLOX-Nano procesa un stream de video. Sus inferencias se convierten en eventos, imágenes y alertas que se consultan en un portal.

**Estado:** en construcción. El plan, las decisiones y el cronograma están en [`docs/PLAN.md`](docs/PLAN.md). El avance se sigue en los issues del hito «Entrega P6».

## Instalación y primera corrida

Requiere Python 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src                      # el paquete p6 no se instala
python scripts/descargar_modelo.py --destino modelo/    # verifica el SHA-256

python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id demo
python -m pytest
```

Cada corrida guarda sus eventos en la base de datos `resultados/monitoreo.db` y escribe en `resultados/<run_id>/`:
- `run.json`: fuente, ritmo y muestreo, modelo y configuración con su SHA-256, política, entorno y totales por zona y por ventana.
- `eventos.jsonl` y `alertas.jsonl`, exportados desde la base de datos.
- `capturas/`: los JPEG conservados según la política de capturas.
- `metricas.json`: las 7 métricas (G1–G7) por corrida y por ventana. Se recalculan desde la base de datos con `python -m p6.metricas --run-id <run_id> --recalcular`.

Para consultar los eventos y las alertas en el portal (`/eventos`, `/alertas`, `/corridas`):

```bash
python -m p6.portal --db resultados/monitoreo.db      # http://127.0.0.1:8000
```

La fuente puede ser un video, una carpeta de imágenes o la webcam (`--fuente webcam:0`). `--sin-pausa` omite la espera entre cuadros.

**Nota para macOS:** no se usa `pip install -e .` porque deja un archivo `.pth` que macOS marca como oculto en carpetas sincronizadas con iCloud y Python 3.12 lo ignora. Por eso los comandos usan `PYTHONPATH=src`.

## Documentos

- [`docs/PLAN.md`](docs/PLAN.md): plan, decisiones y cronograma.
- [`docs/contrato.md`](docs/contrato.md): campos del evento y de la alerta, y su validación.
- [`docs/politica.md`](docs/politica.md): umbrales, zonas, ventanas y reglas de alerta, justificados con la referencia.
- [`docs/capturas.md`](docs/capturas.md): base de datos, política de capturas y portal.
- [`docs/metricas.md`](docs/metricas.md): las 7 métricas base (G1–G7), con definición, fórmula y ejemplo.

Las instrucciones completas, el índice de evidencias y la autoría se cierran en #10.
