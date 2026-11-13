# Métricas G1–G7 y adicionales

Resultado de las 7 métricas base (definidas en [`docs/metricas.md`](../../docs/metricas.md)) y de las 3 adicionales (§6 del mismo documento) para cada corrida de [`evidencias/escenarios/`](../escenarios/), y su recálculo desde la base de datos.

| Archivo | Contenido |
|---|---|
| `c1-normal.json`, `c2-baja-confianza.json`, `c3-interrupcion.json`, `carrito-p5.json` | El documento completo de cada corrida: bloque `corrida` y una entrada por ventana. Cada uno tiene las 7 métricas base y el bloque `extras` (E1–E3), con su estado y su población (`n`, `window_ids`, rango de `event_id`, excluidos) |
| `recalculo-<run_id>.txt` | Salida de `--recalcular` sobre `evidencias/escenarios/monitoreo.db`. En las cuatro corridas, G1–G7 y E1–E3 coinciden en la corrida y en todas sus ventanas |

## Métricas base (C1 y C2)

| Grupo | Métrica | C1 `c1-normal` | C2 `c2-baja-confianza` | Población |
|---|---|---|---|---|
| G1 | Latencia de inferencia p50 / p95 | 18.820 / 23.847 ms | 19.869 / 23.218 ms | 142 cuadros (cuadros 6 a 147; se excluyen los 5 de warmup) |
| G2 | Cuadros procesados por segundo | 4.999 | 4.999 | 147 cuadros en 29.205 s |
| G3 | RAM del proceso (máximo / último) | 183.61 / 160.86 MiB | 184.47 / 184.47 MiB | 147 eventos |
| G4 | Proporción de baja confianza | **0.0** (0 de 147) | **0.8707** (128 de 147) | cuadros con detecciones |
| G5 | Cobertura de trazabilidad | 1.0 (147 de 147) | 1.0 (147 de 147) | eventos guardados; capturas verificadas por SHA-256 |
| G6 | Coincidencia de versión del modelo | 1.0 (147 de 147, 1 versión) | 1.0 (147 de 147, 1 versión) | eventos guardados contra `modelo/descriptor.yaml` |
| G7 | Alertas activas por ventana | 0, 0, 0, 0, 0, 0, 0, 0 | 1, 1, 2, 2, 2, 2, 2, 2 | alertas de la corrida (C2: A abierta desde la ventana 1, B desde la 3) |

Por ventana (en los JSON), la ventana 8 de cada corrida tiene 7 cuadros: G4 es `insuficiente` (menos de 10 cuadros con detecciones) y no se reporta como 0.

Coherencia entre las dos corridas:
- Las métricas técnicas (G1, G2, G3, G5 y G6) son prácticamente iguales: mismo modelo, misma configuración y mismo equipo.
- Cambian las que describen las salidas: G4, G7 y las adicionales.

## Corridas de los extras

| | C3 `c3-interrupcion` | Carrito `carrito-p5` |
|---|---|---|
| G2 cuadros/s (corrida) | **3.972** (la ventana 4, la del corte, da 1.939; las demás ~5.0) | 4.998 |
| G4 proporción baja | 0.0 (0 de 117) | 0.7742 (48 de 62); la ventana 1 es `insuficiente` |
| G7 alertas activas por ventana | 0 en las 6 (la alerta F se abrió y cerró dentro de la ventana 4) | 0, 1, 1, 2 |
| G5 / G6 | 1.0 / 1.0 | 1.0 / 1.0 |

## Métricas adicionales (extras, #11)

| | C1 | C2 | C3 | Carrito |
|---|---|---|---|---|
| E1 proporción sin detecciones | 0.0 (0 de 147) | 0.0 (0 de 147) | 0.0 (0 de 117) | 0.2051 (16 de 78) |
| E2 detecciones por cuadro: media / p50 / p90 / máx. | 1.027 / 1 / 1 / 2 | 1.136 / 1 / 2 / 3 | 1.026 / 1 / 1 / 2 | 2.128 / 2 / 5 / 7 |
| E3 detecciones por clase | person 147, chair 3, bottle 1 | person 156, kite 4, frisbee 3, cat 2, donut 2 | person 117, chair 3 | 25 clases: person 31, dog 20, cat 18, … |

## Recalcular

```bash
export PYTHONPATH=src
for r in c1-normal c2-baja-confianza c3-interrupcion carrito-p5; do
  python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id $r --recalcular
done
```

El recálculo vuelve a calcular todo desde las filas de `eventos` y `alertas` y desde los archivos de `capturas/`, y lo compara campo por campo con lo guardado. Termina con código 0 si todo coincide.

Para comprobar un número a mano, por ejemplo G4 de C2: en `evidencias/escenarios/c2-baja-confianza/eventos.jsonl` hay 147 eventos con `status` `ok`, y 128 de ellos tienen `zone` `baja`. 128 / 147 = 0.8707.
