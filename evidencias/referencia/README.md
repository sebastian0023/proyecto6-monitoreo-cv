# Evidencia de la referencia (#5)

Con qué se eligieron los umbrales y las reglas de [`docs/politica.md`](../../docs/politica.md): solo con `datos/videos/referencia.mp4` (SHA-256 `ac2d62846cc0d020d753ae48b50d6c0972ec9df5b32c5f0c3cb1cc14db2c0d84`). Los videos de C1 y C2 no intervienen.

## Archivos

| Archivo | Contenido |
|---|---|
| `run.json` | Corrida `ref-01`: fuente, ritmo 5 cuadros/s y muestreo 1 de cada 3, modelo (SHA-256 `c789161e…`), `config_sha256`, umbrales, conteo por zona y resumen por ventana |
| `eventos.jsonl` | Los 147 eventos de `ref-01` (contrato etapa H3), con detecciones, `frame_score`, `zone` y `window_id` |
| `config-monitoreo.yaml` | Copia de `config/monitoreo.yaml` usada en `ref-01` (SHA-256 `11b062533007…`) |
| `calibracion.json` | Cuadros, sin detecciones, percentiles de `frame_score`, propuesta de umbrales, comprobación contra la configuración, `p_ref` y proporción de baja confianza por ventana |
| `histograma.csv`, `histograma.svg` | Distribución de `frame_score` en cajas de 0.01, con el piso y los umbrales |
| `calibracion-previa/` | La calibración original: corrida `ref-00` con la configuración anterior (sin umbrales) y la propuesta que salió de ella |

## Dos corridas, dos revisiones de Git

1. **`ref-00` (calibración previa).** Se ejecutó con el código del commit `8414427` y una configuración sin umbrales (`config_sha256` `515cbb0a002d…`). De ahí salió la propuesta 0.85 y 0.90. Su `run.json` marca el árbol con cambios sin confirmar porque en ese momento `scripts/calibrar_referencia.py`, un archivo nuevo sin seguimiento, se estaba escribiendo; el código de `src/p6` es el del commit.
2. **`ref-01` (referencia con la configuración congelada).** Se ejecutó con el commit `ff2fcb9`, que contiene la configuración congelada, con el árbol limpio (`git_arbol_con_cambios: false`). Tiene el mismo `config_sha256` que usarán C1 y C2.

Las puntuaciones de las dos corridas son idénticas (diferencia máxima 0.0), de modo que los umbrales calculados con `ref-00` valen para `ref-01`. Esta carpeta se agregó después del código probado: el código es `ff2fcb9` y las evidencias se incorporan en el commit siguiente.

## Reproducir

```bash
export PYTHONPATH=src
python -m p6.monitorear --fuente datos/videos/referencia.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id ref-01
python scripts/calibrar_referencia.py --run resultados/ref-01 \
    --salida evidencias/referencia --verificar     # código 0: la configuración sale de la referencia
```

Resultado esperado: 147 cuadros, 0 sin detecciones; percentiles 10 y 50 de 0.8657 y 0.8956; umbrales 0.85 y 0.90; `p_ref` 0.0204; proporción baja por ventana 0.10, 0.05, 0, 0, 0, 0, 0 y `insuficiente` en la ventana parcial.
