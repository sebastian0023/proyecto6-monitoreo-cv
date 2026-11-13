# Escenarios

Los dos escenarios obligatorios (C1 y C2) y dos corridas de los extras (C3 y el carrito). Todos se corrieron con inferencia real, el **mismo modelo** y la **misma configuración** que la referencia.

| | C1 · operación normal | C2 · baja confianza | C3 · interrupción (extra) | Carrito (extra) |
|---|---|---|---|---|
| `run_id` | [`c1-normal`](c1-normal/) | [`c2-baja-confianza`](c2-baja-confianza/) | [`c3-interrupcion`](c3-interrupcion/) | [`carrito-p5`](carrito-p5/) |
| Entrada | `normal.mp4` | `baja_confianza.mp4` | `normal.mp4` con `--simular-corte 70:6` | `datos/carrito/` (78 fotos) |
| Cuadros | 147 | 147 | 117 (30 perdidos en el corte) | 78 (16 sin detecciones) |
| Zonas (aceptada / duda / baja) | 129 / 18 / 0 | 0 / 19 / 128 | 99 / 18 / 0 | 1 / 13 / 48 |
| G4 proporción baja | 0.0 | 0.8707 | 0.0 | 0.7742 |
| Alertas | ninguna | A (ventana 1), B (ventana 3) | F: 6.20 s sin cuadros, recuperada | A (ventana 2), B (ventana 4) |
| Capturas | 8 | 139 | 6 | 62 |
| G5 / G6 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |

**Identidad común** (en cada `run.json`):

| | |
|---|---|
| Código | commit `3dc1c44`, árbol limpio (`git_arbol_con_cambios: false`) |
| Modelo | YOLOX-Nano `0.1.1rc0`, SHA-256 `c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d` |
| Configuración | `config/monitoreo.yaml`, SHA-256 `11b0625330078e09f04f6d8c45efe9e09997a28d34afbaf07a75978e4b500a3f`, la misma de la referencia (`evidencias/referencia/`) |
| Umbrales | inferior 0.85, superior 0.90 (elegidos solo con la referencia, ver `docs/politica.md`) |
| Fecha | 2026-11-13, de 00:24:56 a 00:26:40 UTC, una corrida tras otra |
| Entorno | macOS 26 (Apple M4), Python 3.12.13, onnxruntime 1.30.0, CPU |

Las evidencias se generaron con el código del commit `3dc1c44` y se incorporan en el commit siguiente.

C1 y C2 dan exactamente las mismas zonas, ventanas, alertas y capturas que en la primera entrega de la base (`9a4ba47`): el modelo es determinista en CPU. Solo cambian las marcas de tiempo, la latencia y la RAM.

## Contenido

```
escenarios/
├── monitoreo.db          base de datos con las 4 corridas (eventos, alertas, métricas y la configuración)
├── configuracion.png     el portal mostrando la configuración usada, con su SHA-256 verificado
├── c1-normal/            README, salida.txt, run.json, eventos.jsonl, alertas.jsonl, metricas.json, capturas/, portal/
├── c2-baja-confianza/    lo mismo
├── c3-interrupcion/      lo mismo (extra #14)
└── carrito-p5/           lo mismo (extra #13)
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
python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 --config config/monitoreo.yaml --run-id c1-normal
python -m p6.monitorear --fuente datos/videos/baja_confianza.mp4 --ritmo 5 --config config/monitoreo.yaml --run-id c2-baja-confianza
python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 --config config/monitoreo.yaml --run-id c3-interrupcion --simular-corte 70:6
python -m p6.monitorear --fuente datos/carrito --ritmo 5 --config config/monitoreo.yaml --run-id carrito-p5
python -m p6.portal --db resultados/monitoreo.db
```

Las puntuaciones del modelo son deterministas en CPU: una corrida nueva da las mismas zonas, ventanas, alertas y capturas. Cambian las marcas de tiempo, los tiempos de inferencia y la RAM. En C3, la duración exacta del hueco puede variar unas centésimas.
