# Fotos del carrito como segunda fuente (`carrito-p5`, extra #13)

Una corrida con otra fuente visual: las 78 fotos de evaluación del carrito del Proyecto 5, leídas como **carpeta de imágenes**. El origen y el crédito están en [`datos/carrito/README.md`](../../../datos/carrito/README.md): son capturas de Bryan (@BryanRomoG) del commit `b63ddbc` del repositorio de P5. Las anotaciones de P5 no se usan.

## Entrada y comando

- **Entrada:** `datos/carrito/` (78 JPEG de 400×296, verificados contra `datos/carrito/manifiesto.csv` con `python scripts/descargar_fotos_carrito.py`).
- **Comando exacto** (commit `3dc1c44`, árbol limpio, 2026-11-13 00:26:24 UTC):

  ```bash
  export PYTHONPATH=src
  python -m p6.monitorear --fuente datos/carrito --ritmo 5 \
      --config config/monitoreo.yaml --run-id carrito-p5
  ```

- **Fuente:** `carpeta:carrito`, una imagen por cuadro en orden alfabético (secuencias S1 → S6) a 5 cuadros/s. Medido: 5.036 cuadros/s; G2 4.998.
- **Configuración:** la misma de todas las corridas (SHA-256 `11b06253…500a3f`).

## Observado

| | |
|---|---|
| Cuadros | 78: **62 con detecciones y 16 sin detecciones**, 0 errores |
| Zonas | aceptada 1, duda 13, baja 48 (G4 = 0.7742) |
| Ventanas | 1: **insuficiente** (9 de 20 cuadros con detecciones); 2: 0.89; 3: 0.75; 4 (parcial, 18 cuadros): 0.67 |
| Alertas | `carrito-p5-A-1` (ventana 2) y `carrito-p5-B-1` (ventana 4, tras las ventanas suficientes 2, 3 y 4); la ventana 1 insuficiente no abre ninguna regla |
| Capturas | 62 (48 baja, 12 de ventanas con alerta, 2 de muestra) |
| Métricas adicionales | E1 0.2051 (16 de 78 sin detecciones) · E2 media 2.13 detecciones por cuadro, p90 5, máx. 7 · E3 25 clases distintas (person 31, dog 20, cat 18, refrigerator 13, teddy bear 13…) |

Esta corrida ejercita estados que C1 y C2 no tienen:
- Cuadros `sin_detecciones`: sin zona y fuera del denominador de G4.
- Una ventana `insuficiente`, que no se trata como normal ni abre alertas.

**Los umbrales no están calibrados para esta escena.** Son los de la escena de la webcam (`referencia.mp4`). El carrito muestra cuartos, piso, un gato y un peluche, y el detector los puntúa mucho más bajo. Que se abran A y B es lo que esas reglas deben hacer ante un cambio de escena respecto de la referencia. Para monitorear el carrito como fuente principal habría que calibrar su propia referencia.

## Archivos y portal

`salida.txt`, `run.json`, `eventos.jsonl`, `alertas.jsonl`, `metricas.json` y `capturas/`.

| Pantalla | Ruta |
|---|---|
| [`1-eventos-lista.png`](portal/1-eventos-lista.png) | `/eventos?run_id=carrito-p5` |
| [`2-evento-sin-detecciones.png`](portal/2-evento-sin-detecciones.png) | `/eventos/carrito-p5-1`: sin detecciones, sin zona y sin captura |
| [`3-evento-detalle-con-captura.png`](portal/3-evento-detalle-con-captura.png) | `/eventos/carrito-p5-58`: 7 detecciones sobre la foto del carrito |
| [`4-alertas.png`](portal/4-alertas.png) | `/alertas?run_id=carrito-p5` |
| [`5-corrida.png`](portal/5-corrida.png) | `/corridas/carrito-p5`: la fuente de carpeta, la ventana insuficiente y las alertas |
