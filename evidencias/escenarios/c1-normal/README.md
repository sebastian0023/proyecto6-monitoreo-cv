# C1 · Operación normal (`c1-normal`)

## Entrada y comando

- **Entrada:** `datos/videos/normal.mp4` (SHA-256 `01ad6ffa103aaf49f938bb081795267498a45199db9ad7ebc08755d57cb6cf19`). Es otra toma de la misma escena y la misma luz que la referencia: 640×480, 15 cuadros/s, 29.3 s.
- **Comando exacto** (commit `3dc1c44`, árbol limpio, 2026-11-13 00:24:56 UTC):

  ```bash
  export PYTHONPATH=src
  python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \
      --config config/monitoreo.yaml --run-id c1-normal
  ```

- **Configuración:** SHA-256 `11b06253…500a3f`, la misma que la referencia y C2.
- **Stream:** 1 de cada 3 cuadros del video, entregados a 5 cuadros/s con espera real (medido: 5.021 cuadros/s; G2: 4.999).

## Esperado y observado

| Esperado (`docs/PLAN.md`, sección 10) | Observado |
|---|---|
| Inferencias reales | 147 cuadros, los 147 con detecciones del modelo (SHA-256 `c789161e…`); 0 sin detecciones y 0 errores |
| La mayoría de cuadros en zona aceptada o duda | aceptada 129, duda 18, **baja 0**. `frame_score` de 0.8925 a 0.9234 (p50 0.9074) |
| Métricas coherentes | G1 p50 18.8 ms / p95 23.8 ms · G2 5.0 cuadros/s · G3 máx. 184 MiB · G4 0.0 (0 de 147) · G5 1.0 · G6 1.0 · G7 0 alertas en las 8 ventanas |
| (métricas adicionales, extra #11) | E1 0.0 sin detecciones · E2 1.03 detecciones por cuadro (máx. 2) · E3 person 147, chair 3, bottle 1 |
| Sin alertas falsas, o alertas que cumplen su regla | **Ninguna alerta.** Las 7 ventanas completas tienen proporción baja 0.0, por debajo de A (0.50) y de B (0.2204); la ventana 8 (7 cuadros) es insuficiente |
| Eventos persistidos y consultables | 147 eventos en `monitoreo.db` y en `eventos.jsonl`, contrato completo (etapa H4, 0 rechazados) |
| Capturas según la política | 8 capturas por muestra (cuadros 1, 21, …, 141), todas con SHA-256 verificado. No hay cuadros bajos ni ventanas con alerta |

La ausencia de alertas sale de una medición, no de falta de datos: G4 es 0.0 sobre 147 cuadros con detecciones, no «sin datos».

## Archivos

| Archivo | Contenido |
|---|---|
| `salida.txt` | Salida completa del comando (un renglón por cuadro, totales y métricas) |
| `run.json` | Fuente, ritmo y muestreo, modelo, configuración, política, entorno, commit y totales por zona y por ventana |
| `eventos.jsonl` | Los 147 eventos (exportados de la base de datos) |
| `alertas.jsonl` | Vacío: no hubo alertas |
| `metricas.json` | G1–G7 por corrida y por ventana (también en [`evidencias/metricas/`](../../metricas/)) |
| `capturas/` | Las 8 capturas JPEG, nombradas con su `event_id` |
| `portal/` | Capturas de pantalla del portal (abajo) |

## Portal

| Pantalla | Ruta |
|---|---|
| [`1-eventos-lista.png`](portal/1-eventos-lista.png) | `/eventos?run_id=c1-normal` |
| [`2-evento-detalle-con-captura.png`](portal/2-evento-detalle-con-captura.png) | `/eventos/c1-normal-21`: captura de muestra con SHA-256 verificado y enlace a la configuración |
| [`3-evento-sin-captura.png`](portal/3-evento-sin-captura.png) | `/eventos/c1-normal-2`: el portal dice que no tiene captura |
| [`4-alertas.png`](portal/4-alertas.png) | `/alertas?run_id=c1-normal`: sin alertas |
| [`5-corrida.png`](portal/5-corrida.png) | `/corridas/c1-normal`: identidad, zonas y proporción baja por ventana |

## Nota sobre la latencia

A 5 cuadros/s con espera entre cuadros, la latencia de inferencia (G1) fue de unos 19 ms (p50), y en las corridas sin espera (`--sin-pausa`) de unos 7 ms. Las puntuaciones son idénticas en los dos modos. Probablemente el procesador baja su frecuencia en la espera entre cuadros. Se reporta el valor medido en la corrida real.
