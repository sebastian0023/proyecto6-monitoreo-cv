# Escenarios C1 y C2

Los dos escenarios obligatorios, corridos con inferencia real, el **mismo modelo** y la **misma configuración** que la referencia.

| | C1 · operación normal | C2 · baja confianza |
|---|---|---|
| `run_id` | [`c1-normal`](c1-normal/) | [`c2-baja-confianza`](c2-baja-confianza/) |
| Entrada | `datos/videos/normal.mp4` | `datos/videos/baja_confianza.mp4` |
| Cuadros | 147 a 5.0 cuadros/s | 147 a 5.0 cuadros/s |
| Zonas (aceptada / duda / baja) | 129 / 18 / 0 | 0 / 19 / 128 |
| Proporción baja (G4) | 0.0 | 0.8707 |
| Alertas | ninguna | A (ventana 1) y B (ventana 3), abiertas |
| Capturas | 8 (muestra) | 139 (128 baja, 10 ventana_alerta, 1 muestra) |
| Trazabilidad (G5) y versión (G6) | 1.0 y 1.0 | 1.0 y 1.0 |

**Identidad común de las dos corridas** (en cada `run.json`):

| | |
|---|---|
| Código | commit `9a4ba47`, árbol limpio (`git_arbol_con_cambios: false`) |
| Modelo | YOLOX-Nano `0.1.1rc0`, SHA-256 `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` |
| Configuración | `config/monitoreo.yaml`, SHA-256 `11b0625330078e09f04f6d8c45efe9e09997a28d34afbaf07a75978e4b500a3f`, la misma de la referencia (`evidencias/referencia/`) |
| Umbrales | inferior 0.85, superior 0.90 (elegidos solo con la referencia, ver `docs/politica.md`) |
| Fecha | 2026-11-12, C1 de 07:15:45 a 07:16:14 UTC y C2 de 07:16:14 a 07:16:43 UTC |
| Entorno | macOS 26 (Apple M4), Python 3.12.13, onnxruntime 1.30.0, CPU |

Las evidencias se generaron con el código del commit `9a4ba47` y se incorporan en el commit siguiente.

## Contenido

```
escenarios/
├── monitoreo.db          base de datos con las dos corridas (eventos, alertas, métricas y la configuración)
├── configuracion.png     el portal mostrando la configuración usada, con su SHA-256 verificado
├── c1-normal/            README, salida.txt, run.json, eventos.jsonl, alertas.jsonl, metricas.json, capturas/, portal/
└── c2-baja-confianza/    lo mismo
```

`monitoreo.db` guarda la carpeta de cada corrida como ruta relativa, así que el portal y el recálculo funcionan directamente sobre esta carpeta, sin volver a correr nada:

```bash
export PYTHONPATH=src
python -m p6.portal --db evidencias/escenarios/monitoreo.db          # http://127.0.0.1:8000
python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id c2-baja-confianza --recalcular
```

## Reproducir desde cero

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python scripts/descargar_modelo.py --destino modelo/
python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id c1-normal
python -m p6.monitorear --fuente datos/videos/baja_confianza.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id c2-baja-confianza
python -m p6.portal --db resultados/monitoreo.db
```

Las puntuaciones del modelo son deterministas en CPU: una corrida nueva da las mismas zonas, ventanas y alertas. Cambian las marcas de tiempo, los tiempos de inferencia y la RAM.
