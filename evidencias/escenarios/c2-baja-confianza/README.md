# C2 · Baja confianza (`c2-baja-confianza`)

## Entrada y comando

- **Entrada:** `datos/videos/baja_confianza.mp4` (SHA-256 `9393e680716f14652a69f9d66b927a8853658b59553fb6c53c0115ef029876bb`). La misma escena con poca luz y la persona solo en parte dentro del cuadro: 640×480, 15 cuadros/s, 29.3 s. Ver en `datos/videos/README.md` por qué así: oscurecer o desenfocar no bajaba las puntuaciones de este detector.
- **Comando exacto** (commit `9a4ba47`, árbol limpio, 2026-11-12 07:16:14 UTC):

  ```bash
  export PYTHONPATH=src
  python -m p6.monitorear --fuente datos/videos/baja_confianza.mp4 --ritmo 5 \
      --config config/monitoreo.yaml --run-id c2-baja-confianza
  ```

- **Configuración:** SHA-256 `11b06253…500a3f`, la misma que la referencia y C1. Los umbrales (0.85 y 0.90) se fijaron solo con la referencia, antes de esta corrida.
- **Stream:** 1 de cada 3 cuadros, a 5 cuadros/s con espera real (medido: 5.021 cuadros/s; G2: 4.999).

## Esperado y observado

| Esperado (`docs/PLAN.md`, sección 10) | Observado |
|---|---|
| Inferencias reales; las puntuaciones no se modifican | 147 cuadros, los 147 con detecciones del modelo (SHA-256 `c789161e…`). `frame_score` de 0.4284 a 0.8985 (p50 0.8061), tal como salen del modelo |
| Cuadros en zona baja | **128 de 147 en zona baja** (G4 = 0.8707), 19 en duda, 0 aceptados |
| Capturas conservadas | 139 capturas, todas con SHA-256 verificado: los 128 cuadros bajos, 10 cuadros no bajos de las ventanas que abrieron alerta (1 y 3) y 1 de muestra |
| Alerta A abierta según su regla | **`c2-baja-confianza-A-1`** (warning) se abre en la **ventana 1**: proporción baja 0.70 ≥ 0.50 (14 de 20 cuadros con detecciones). Sigue en las ventanas 2 a 7 (0.85, 0.80, 0.80, 1.00, 0.90, 1.00) |
| (regla sostenida, R3.3) | **`c2-baja-confianza-B-1`** (critical) se abre en la **ventana 3**: proporción baja > 0.2204 en 3 ventanas suficientes seguidas (0.70, 0.85, 0.80) |
| Métricas | G1 p50 18.5 ms / p95 22.5 ms · G2 5.0 cuadros/s · G3 máx. 182 MiB · G4 0.8707 · G5 1.0 · G6 1.0 · G7 por ventana 1, 1, 2, 2, 2, 2, 2, 2 |

Las dos alertas **siguen abiertas** al terminar. La última ventana (8) tiene 7 cuadros y es insuficiente, y una ventana insuficiente no cierra una alerta: sin evidencia no se afirma que el problema terminó. Cada alerta lleva sus 7 ventanas y los 121 cuadros bajos que la explican.

## Seguir la alerta hasta los cuadros

1. `/alertas?run_id=c2-baja-confianza` muestra las dos alertas, con momento, motivo y severidad.
2. `/alertas/c2-baja-confianza-A-1` muestra la regla con sus límites, las ventanas con su proporción y los 121 cuadros bajos, cada uno con su miniatura.
3. Un clic en un cuadro, por ejemplo `/eventos/c2-baja-confianza-26` (`frame_score` 0.4284), abre su detalle: la captura con su SHA-256 verificado, las detecciones con sus cajas, la ventana, las alertas que lo incluyen y la configuración.

## Archivos

| Archivo | Contenido |
|---|---|
| `salida.txt` | Salida completa del comando, con las dos líneas `ALERTA … abierta` |
| `run.json` | Identidad de la corrida, política, reglas, totales por zona y por ventana y resumen de alertas |
| `eventos.jsonl` | Los 147 eventos |
| `alertas.jsonl` | Las 2 alertas con regla, severidad, motivo, ventanas, eventos, `config_sha256` y acción sugerida |
| `metricas.json` | G1–G7 por corrida y por ventana (también en [`evidencias/metricas/`](../../metricas/)) |
| `capturas/` | Las 139 capturas JPEG, nombradas con su `event_id` |
| `portal/` | Capturas de pantalla del portal (abajo) |

## Portal

| Pantalla | Ruta |
|---|---|
| [`1-eventos-lista-zona-baja.png`](portal/1-eventos-lista-zona-baja.png) | `/eventos?run_id=c2-baja-confianza&zone=baja` |
| [`2-evento-detalle-con-captura.png`](portal/2-evento-detalle-con-captura.png) | `/eventos/c2-baja-confianza-26`: cuadro bajo con su captura, sus detecciones y sus alertas |
| [`3-alertas.png`](portal/3-alertas.png) | `/alertas?run_id=c2-baja-confianza` |
| [`4-alerta-A-detalle.png`](portal/4-alerta-A-detalle.png) | `/alertas/c2-baja-confianza-A-1` |
| [`5-alerta-B-detalle.png`](portal/5-alerta-B-detalle.png) | `/alertas/c2-baja-confianza-B-1` |
| [`6-corrida.png`](portal/6-corrida.png) | `/corridas/c2-baja-confianza`: zonas, ventanas y alertas |
