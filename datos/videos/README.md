# Videos de entrada

Tres grabaciones propias con la cámara de la MacBook Pro, de unos 30 s cada una. Se convierten a 640×480 y 15 cuadros/s, y se reproducen como stream a 5 cuadros/s (ver `docs/PLAN.md`, secciones 6 y 10).

| Archivo | Para qué | Cómo grabarlo |
|---|---|---|
| `referencia.mp4` | Elegir los umbrales (#5). No se usa en los escenarios | Escena de siempre con buena luz. Con unas 2 o 3 salidas breves del cuadro (ver abajo) |
| `normal.mp4` | Escenario C1 | La misma escena y la misma luz, en otra toma, con el mismo tipo de salidas breves |
| `baja_confianza.mp4` | Escenario C2 | La misma escena, con la persona **a medias en el cuadro** casi todo el tiempo (ver abajo) |

## Qué baja la confianza de este detector (medido)

Se probó sobre cuadros reales de `normal.mp4` con YOLOX-Nano. La puntuación de un cuadro es la de su mejor detección, y `person` domina:

| Cambio al cuadro | Puntuación de `person` |
|---|---|
| Original, buena luz | 0.91 |
| Oscurecido (hasta ×0.15) | 0.90 – 0.91 |
| Desenfocado | 0.89 – 0.90 |
| Persona lejos (hasta 20 % del tamaño) | 0.84 – 0.88 |
| Persona asomando por el borde, 30 % visible | 0.34 |
| Solo se ve el 40 % superior de la persona | 0.56 |
| Persona empujada 70 % hacia abajo (solo asoma la frente) | 0.19 |
| Casi nada de la persona visible | sin detecciones |

Conclusión: **la poca luz, el desenfoque y la distancia no alcanzan**. Lo que baja la puntuación es que la persona esté **solo en parte dentro del cuadro**, con algo de ella todavía visible. Si no se ve nada, el cuadro sale `sin_detecciones` y no cuenta como baja confianza. El primer intento de `baja_confianza.mp4` (oscuro, con la cara entera) dio un `frame_score` con p50 de 0.93.

## Cómo grabar

- **`baja_confianza.mp4`:** con poca luz, desplázate hacia un borde del cuadro hasta que se vea solo un tercio de tu cara y cuerpo, o baja hasta que asome solo de la frente hacia arriba. Muévete despacio dentro de esa zona y mantén algo tuyo visible todo el tiempo. Debe durar al menos 20 s así.
- **`referencia.mp4` y `normal.mp4`:** siéntate normal y, 2 o 3 veces, inclínate hacia un lado durante 1 o 2 s hasta que se vea solo parte de ti, y vuelve. Salidas breves: una ventana de 20 cuadros (4 s) no debe quedar con la mitad en baja confianza.

## Cómo comprobar un video antes de usarlo

```bash
export PYTHONPATH=src
python scripts/preparar_video.py datos/videos/originales/baja_confianza.mov datos/videos/baja_confianza.mp4
python -m p6.monitorear --fuente datos/videos/baja_confianza.mp4 --sin-pausa --run-id prueba --sobrescribir | tail -3
```

La última línea muestra la distribución de `frame_score` (min, p10, p50, p90, max) y las anteriores cuántos cuadros salieron sin detecciones. Para `baja_confianza` se busca un p50 claramente bajo y menos de la mitad de los cuadros sin detecciones; para `referencia` y `normal`, un p10 claramente distinto del p50.

## Cómo grabar con QuickTime

1. Abre QuickTime Player, elige Archivo → Nueva grabación de película y selecciona la cámara de la MacBook Pro.
2. Guarda el `.mov` en `datos/videos/originales/` con el nombre de la tabla. Esa carpeta no va a Git.
3. Convierte cada video con `scripts/preparar_video.py` (comando de arriba). Recorta el centro de 16:9 a 4:3 sin deformar, deja 640×480 a 15 cuadros/s y no toca brillo ni nitidez. El `.mp4` se guarda aquí.
