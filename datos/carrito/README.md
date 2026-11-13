# Fotos del carrito del Proyecto 5 (segunda fuente, extra #13)

Las 78 fotos de evaluación del carrito del Proyecto 5, usadas como una segunda fuente visual de tipo **carpeta de imágenes**.

## Origen

| | |
|---|---|
| Repositorio | [sebastian0023/Proyecto-3-Clasificador-de-imagenes](https://github.com/sebastian0023/Proyecto-3-Clasificador-de-imagenes) (público) |
| Revisión | commit `b63ddbc91a45db90d857c635def6a344ce895b09`, tag `p5-entrega` |
| Ruta | `Proyecto5/datos/evaluacion/S1` … `S6` (6 secuencias, 12 a 17 fotos cada una) |
| Autoría de las capturas | Bryan (@BryanRomoG), con la cámara del carrito, para el equipo del Proyecto 5 |
| Formato | JPEG de 400×296 |

**Las anotaciones de P5 no se usan.** De su manifiesto (`capturas.csv`) solo se copiaron la ruta, el SHA-256 y el tamaño de cada foto, a [`manifiesto.csv`](manifiesto.csv). Las etiquetas de escena y de riesgo no se copian ni se leen: el monitoreo no evalúa aciertos.

## Verificar o volver a descargar

```bash
python scripts/descargar_fotos_carrito.py              # verifica las 78 fotos contra manifiesto.csv
python scripts/descargar_fotos_carrito.py --descargar  # las baja del commit b63ddbc y verifica cada una
```

## Usarlas como fuente

```bash
export PYTHONPATH=src
python -m p6.monitorear --fuente datos/carrito --ritmo 5 \
    --config config/monitoreo.yaml --run-id carrito-p5
```

La fuente de carpeta entrega una imagen por cuadro, en orden alfabético, al ritmo declarado. Los nombres empiezan por la secuencia y el tiempo de captura, de modo que ese orden es S1 → S6 en el orden en que se tomaron. En el portal la corrida aparece en `/corridas` y se puede filtrar en `/eventos?run_id=carrito-p5`.

**Los umbrales no están calibrados para esta escena.** La configuración congelada se eligió con la escena de la webcam (`referencia.mp4`). En el carrito la escena es otra (cuartos, piso, un gato, un peluche), el detector puntúa mucho más bajo, y por eso se abren las reglas A y B. Eso es lo que esas reglas deben hacer ante un cambio de escena respecto de la referencia. Para monitorear el carrito como fuente principal habría que grabar su propia referencia y calibrar sus umbrales.
