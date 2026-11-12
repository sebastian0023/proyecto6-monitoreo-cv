# Métricas G1–G7 de C1 y C2

Resultado de las 7 métricas base (definidas en [`docs/metricas.md`](../../docs/metricas.md)) para los dos escenarios, y su recálculo desde la base de datos.

| Archivo | Contenido |
|---|---|
| `c1-normal.json`, `c2-baja-confianza.json` | El documento completo de cada corrida: bloque `corrida` y una entrada por ventana, con las 7 métricas, su estado y su población (`n`, `window_ids`, rango de `event_id`, excluidos) |
| `recalculo-c1-normal.txt`, `recalculo-c2-baja-confianza.txt` | Salida de `--recalcular` sobre `evidencias/escenarios/monitoreo.db`: las 7 métricas coinciden en la corrida y en las 8 ventanas |

## Resultados por corrida

| Grupo | Métrica | C1 `c1-normal` | C2 `c2-baja-confianza` | Población |
|---|---|---|---|---|
| G1 | Latencia de inferencia p50 / p95 | 18.626 / 22.274 ms | 18.462 / 22.476 ms | 142 cuadros (cuadros 6 a 147; se excluyen los 5 de warmup) |
| G2 | Cuadros procesados por segundo | 4.998 | 4.999 | 147 cuadros en 29.21 s |
| G3 | RAM del proceso (máximo / último) | 182.08 / 158.67 MiB | 182.22 / 182.03 MiB | 147 eventos |
| G4 | Proporción de baja confianza | **0.0** (0 de 147) | **0.8707** (128 de 147) | cuadros con detecciones |
| G5 | Cobertura de trazabilidad | 1.0 (147 de 147) | 1.0 (147 de 147) | eventos guardados; capturas verificadas por SHA-256 |
| G6 | Coincidencia de versión del modelo | 1.0 (147 de 147, 1 versión) | 1.0 (147 de 147, 1 versión) | eventos guardados contra `modelo/descriptor.yaml` |
| G7 | Alertas activas por ventana | 0, 0, 0, 0, 0, 0, 0, 0 | 1, 1, 2, 2, 2, 2, 2, 2 | alertas de la corrida (C2: A abierta desde la ventana 1, B desde la 3) |

Por ventana (en los JSON), la ventana 8 de cada corrida tiene 7 cuadros: G4 es `insuficiente` (menos de 10 cuadros con detecciones) y no se reporta como 0.

Coherencia entre las dos corridas:
- Las métricas técnicas (G1, G2, G3, G5 y G6) son prácticamente iguales: mismo modelo, misma configuración y mismo equipo.
- Solo cambian las que describen las salidas: G4 y G7.

## Recalcular

```bash
export PYTHONPATH=src
python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id c1-normal --recalcular
python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id c2-baja-confianza --recalcular
```

El recálculo vuelve a calcular todo desde las filas de `eventos` y `alertas` y desde los archivos de `capturas/`, y lo compara campo por campo con lo guardado. Termina con código 0 si todo coincide. Para comprobar un número a mano, por ejemplo G4 de C2: en `evidencias/escenarios/c2-baja-confianza/eventos.jsonl` hay 147 eventos con `status` `ok`, y 128 de ellos tienen `zone` `baja`. 128 / 147 = 0.8707.
