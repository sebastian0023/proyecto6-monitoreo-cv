# Videos de entrada

Tres grabaciones propias con la cámara de la MacBook Pro. Se reproducen como stream a 5 cuadros/s (ver `docs/PLAN.md`, secciones 6 y 10).

| Archivo | Para qué | Cómo grabarlo |
|---|---|---|
| `referencia.mp4` | Elegir los umbrales (#5). No se usa en los escenarios | Escena de siempre con buena luz: tú, una taza, una silla y el celular a la vista. Muévete un poco |
| `normal.mp4` | Escenario C1 | La misma escena y la misma luz, en otra toma |
| `baja_confianza.mp4` | Escenario C2 | La misma escena con poca luz, desenfocada, con los objetos lejos o tapados a medias. No tapes la cámara por completo: esos cuadros salen sin detecciones y no cuentan como baja confianza |

Cada video dura unos 60 segundos.

## Cómo grabar

1. Abre QuickTime Player, elige Archivo → Nueva grabación de película y selecciona la cámara de la MacBook Pro.
2. Guarda el `.mov` en `datos/videos/originales/`. Esa carpeta no va a Git.
3. Convierte cada video a 640×480 con `scripts/preparar_video.py` (se crea en #3). El resultado se guarda aquí con el nombre de la tabla.
