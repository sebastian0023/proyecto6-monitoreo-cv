# C3 · Interrupción del stream y recuperación (`c3-interrupcion`, extra #14)

Escenario adicional, distinto de C1 y C2. Prueba cómo se comporta el monitoreo cuando la fuente deja de entregar cuadros durante unos segundos y luego vuelve.

## Entrada y comando

- **Entrada:** `datos/videos/normal.mp4`, la misma escena de C1, para que la única diferencia sea el corte.
- **Comando exacto** (commit `3dc1c44`, árbol limpio, 2026-11-13 00:25:55 UTC):

  ```bash
  export PYTHONPATH=src
  python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \
      --config config/monitoreo.yaml --run-id c3-interrupcion --simular-corte 70:6
  ```

- **Qué simula `--simular-corte 70:6`:** después del cuadro 70, la fuente no entrega nada durante 6 s, como una cámara que se cuelga. Luego sigue donde estaría un stream en vivo: los cuadros de esos 6 s se pierden y la cadencia de 5 cuadros/s se reanuda sin ponerse al día. Ver `docs/politica.md` §9.
- **Configuración:** la misma de la referencia, C1 y C2 (SHA-256 `11b06253…500a3f`). La regla F es una constante del código y `run.json` la registra en `politica.regla_F`.

## Etapas: esperado y observado

| Etapa | Esperado | Observado |
|---|---|---|
| 1. Operación normal | Cuadros 1 a 70 a 5 cuadros/s, zonas como en C1 | Cuadros 1–70 aceptados o en duda; G2 de las ventanas 1 a 3: 4.994, 5.001, 5.002 |
| 2. Fallo | Sin cuadros durante 6 s después del cuadro 70; los cuadros de ese lapso no llegan | `run.json` → `fuente.simulacion_corte.ocurrio`: 6.0 s y 90 cuadros del video omitidos (6 s × 15 fps). El siguiente cuadro procesado es el 301 del video, y el anterior fue el 208 |
| 3. Diagnóstico | Una alerta F al pasar 1 s sin cuadros (5 intervalos), con la duración del hueco y los cuadros que lo delimitan | **`c3-interrupcion-F-1`** (critical): «sin cuadros de la fuente durante 6.20 s entre c3-interrupcion-70 (cuadro 208 de normal.mp4) y c3-interrupcion-71 (cuadro 301 de normal.mp4)…». Se abrió a las 00:26:10.342, 1 s después del cuadro 70. Acción sugerida: revisar la cámara o la conexión |
| 4. Recuperación | La alerta se cierra con el primer cuadro que llega y el ritmo vuelve a 5 cuadros/s | Cerrada con `c3-interrupcion-71` a las 00:26:15.543. G2 de las ventanas 5 y 6: 5.002 y 5.003 |
| 5. Verificación posterior | La caída se ve en las métricas de la ventana del corte y en la corrida; el corte no cambia las puntuaciones | G2 de la ventana 4: **1.939** cuadros/s (19 intervalos en 9.8 s), contra ~5.0 en el resto. G2 de la corrida: 3.972. 117 cuadros procesados (147 − 30). Zonas 99 / 18 / 0, sin alertas A ni B, y las mismas puntuaciones que C1 para los mismos cuadros del video |

G7 es 0 en todas las ventanas, porque mide las alertas activas **al cierre** de cada ventana y la alerta F se abrió y se cerró dentro de la ventana 4. El registro del episodio es la propia alerta, con sus dos instantes, y la caída de G2 en esa ventana.

## Archivos y portal

`salida.txt` (incluye la línea `ALERTA c3-interrupcion-F-1`), `run.json`, `eventos.jsonl`, `alertas.jsonl`, `metricas.json` y `capturas/` (6 de muestra).

| Pantalla | Ruta |
|---|---|
| [`1-alertas.png`](portal/1-alertas.png) | `/alertas?run_id=c3-interrupcion` |
| [`2-alerta-F-detalle.png`](portal/2-alerta-F-detalle.png) | `/alertas/c3-interrupcion-F-1`: condición, motivo, apertura y cierre, y los dos cuadros que delimitan el corte |
| [`3-evento-recuperacion.png`](portal/3-evento-recuperacion.png) | `/eventos/c3-interrupcion-71`: el primer cuadro después del corte (cuadro 301 del video), enlazado a la alerta |
| [`4-corrida.png`](portal/4-corrida.png) | `/corridas/c3-interrupcion`: el corte en `run.json` y la alerta F |

## Verificar

```bash
grep -E '"c3-interrupcion-(70|71)"' evidencias/escenarios/c3-interrupcion/eventos.jsonl | cut -c1-240
python -m p6.metricas --db evidencias/escenarios/monitoreo.db --run-id c3-interrupcion --recalcular
```

La prueba `tests/test_interrupcion.py` reproduce el escenario con un reloj simulado: qué se pierde, la cadencia al reanudar, la alerta y la caída de G2.
