# Eventos persistentes, capturas y portal

Cómo se guardan los eventos, qué imágenes se conservan y cómo se consultan. Cubre R4.2 (eventos persistentes y consultables) y R4.3 (imágenes vinculadas sin caducidad). Los campos están en [`contrato.md`](contrato.md) (etapa H4).

## 1. Persistencia

`python -m p6.monitorear` guarda todo en una base de datos SQLite, `resultados/monitoreo.db` (opción `--db`), con tres tablas ([`src/p6/almacen.py`](../src/p6/almacen.py)):

| Tabla | Una fila por | Contenido |
|---|---|---|
| `corridas` | corrida | `run_id`, carpeta de la corrida, fechas, fuente, modelo, `config_sha256`, **el texto completo de la configuración** y el `run.json` |
| `eventos` | cuadro procesado | una columna por campo del contrato, en el mismo orden; `detections` como JSON |
| `alertas` | alerta | una columna por campo del contrato de alerta; `window_ids` y `event_ids` como JSON |

- Las columnas salen de `CAMPOS_EVENTO` y `CAMPOS_ALERTA` de [`contrato.py`](../src/p6/contrato.py), así que la base y el contrato no se pueden desalinear.
- Un evento se guarda y se lee como el mismo diccionario (`tests/test_almacen.py` lo comprueba con los tres estados).
- `eventos.jsonl` y `alertas.jsonl` de cada corrida se **exportan desde la base de datos** al terminar. La base es la fuente y los JSONL son su copia legible. Se pueden volver a exportar con:

  ```bash
  python -m p6.almacen exportar --db resultados/monitoreo.db --run-id c1-normal --salida resultados/c1-normal
  ```

- Los eventos se guardan al cerrar cada ventana (cada 20 cuadros, 4 s). Con Ctrl+C se guarda la ventana en curso antes de cerrar `run.json`.
- Un evento que no cumple el contrato no entra en la base: va a `rechazados.jsonl` con sus motivos y `run.json` lo cuenta.

## 2. Política de capturas

No se guardan todos los cuadros. Se conserva la imagen de un cuadro por uno de estos motivos (`image_reason`), en este orden de prioridad:

| Motivo | Qué cuadros | Para qué |
|---|---|---|
| `baja` | Todo cuadro en zona baja | Poder revisar cada caso de baja confianza |
| `ventana_alerta` | Todos los cuadros de una ventana que **abrió** una alerta | Ver el contexto completo que disparó la alerta |
| `muestra` | 1 de cada 20 cuadros (`frame_id` 1, 21, 41, …) | Una muestra de la operación normal para comparar |

- **Formato y lugar.** JPEG de calidad 90 en `resultados/<run_id>/capturas/<event_id>.jpg`. El nombre lleva el `event_id`, de modo que el archivo se identifica aunque se separe de la base.
- **Vínculo con el evento.** Cada evento guarda `image_ref` (ruta relativa a la carpeta de la corrida), `image_sha256` (SHA-256 de los bytes escritos) e `image_reason`. Los tres van juntos: o los tres tienen valor o los tres son nulos.
- **Sin captura.** Si un cuadro no cumple ningún motivo, los tres campos son nulos y el portal lo dice explícitamente. Un cuadro que no se pudo leer (sin imagen) tampoco puede tener captura.
- **Escritura segura.** Se escribe a un archivo temporal y se renombra, así que nunca queda un JPEG a medias con el nombre final.
- **Sin caducidad.** Ningún código del proyecto borra capturas ni tiene un plazo de expiración. Solo se reemplazan al repetir una corrida con el mismo `run_id` y `--sobrescribir`, que vuelve a crearla desde cero. Para la entrega se copian a `evidencias/`.
- **Parámetros en el código.** El plan preveía poner esta política en `config/monitoreo.yaml`. Quedó como constantes en [`capturas.py`](../src/p6/capturas.py) (`MUESTRA_CADA = 20`, `CALIDAD_JPEG = 90`) porque la configuración ya estaba congelada en #5 con su SHA-256, y la política de capturas no cambia ninguna puntuación, zona ni alerta. Cada `run.json` la registra en `politica_capturas`.

**Verificación.** Una captura está bien solo si el archivo existe dentro de la carpeta de su corrida y su SHA-256 coincide con `image_sha256`. `capturas.verificar` devuelve uno de estos estados:

| Estado | Significa | Qué muestra el portal |
|---|---|---|
| `ok` | Existe y el SHA-256 coincide | La imagen con sus cajas y «SHA-256 verificado» |
| `sin_captura` | La política no guardó este cuadro | «Este evento no tiene captura» |
| `no_existe` | El evento apunta a un archivo que no está | «Captura rota: el archivo no existe»; no muestra imagen |
| `alterada` | El archivo existe pero su SHA-256 no coincide | «Captura rota: el SHA-256 no coincide»; no muestra imagen |
| `ruta_invalida` | La ruta sale de la carpeta de la corrida | «Captura rota»; no muestra imagen |

Una captura rota nunca se sirve ni se muestra como válida: `/capturas/{event_id}` responde 409.

## 3. Portal

```bash
export PYTHONPATH=src
python -m p6.portal --db resultados/monitoreo.db      # http://127.0.0.1:8000
```

Solo lee: abre la base en modo de solo lectura y no modifica archivos.

| Ruta | Qué muestra |
|---|---|
| `/eventos` | Lista paginada (50 por página) con filtros por corrida, estado, zona (incluida «sin zona»), ventana y captura. Cada fila enlaza al detalle, a la corrida y a su ventana, e indica si la captura está verificada, falta o está rota |
| `/eventos/{event_id}` | Estado, zona, `frame_score`, ventana, la captura con las cajas de las detecciones (si está verificada), la tabla de detecciones, las alertas que incluyen el evento y la trazabilidad: fuente, momento, modelo, **enlace a la configuración**, tiempos y RAM. Enlaces al cuadro anterior y siguiente |
| `/capturas/{event_id}` | El JPEG, solo si existe y su SHA-256 coincide |
| `/configuracion/{sha256}` | El texto completo de la configuración que produjo los eventos, con su SHA-256 recalculado y comprobado, y las corridas que la usaron |
| `/corridas`, `/corridas/{run_id}` | Corridas con su fuente, modelo y configuración; por corrida, el conteo por zona, las capturas, el resumen por ventana con enlaces y el `run.json` completo |
| `/alertas` | Alertas con filtros por corrida, estado y regla: regla, severidad, estado, momento y ventana de apertura y de cierre, motivo con los valores medidos y número de eventos |
| `/alertas/{alert_id}` | La alerta completa: condición de la regla con sus límites, acción sugerida, enlace a la configuración, sus ventanas (con enlace a todos sus cuadros) y los eventos que la explican, cada uno con enlace y miniatura de su captura |
| `/api/eventos`, `/api/eventos/{event_id}`, `/api/alertas`, `/api/alertas/{alert_id}` | Lo mismo en JSON (los eventos, con el estado de su captura) |

Recorrido de un evento a su imagen y su configuración: `/eventos` → clic en un `event_id` → la imagen está en la sección «Captura» (con su SHA-256 verificado) y la configuración en «Trazabilidad → Configuración».

Recorrido de una alerta a los cuadros que la causaron: `/alertas` → clic en un `alert_id` → «Eventos que la explican» lista cada cuadro con su miniatura; cada uno abre su detalle. El detalle de un evento enlaza de vuelta a las alertas que lo incluyen.

## 4. Pruebas

- `tests/test_almacen.py`: un evento se lee igual que se guardó, la exportación JSONL es igual a la base, filtros, alertas que se actualizan, solo lectura, y que un evento de `monitorear` se lee igual desde la base y desde JSONL.
- `tests/test_capturas.py`: motivos y prioridades, JPEG con su SHA-256, los cinco estados de verificación, todos los cuadros de una ventana que abre una alerta y el reemplazo al repetir una corrida.
- `tests/test_portal.py`: de un evento a su imagen y su configuración, eventos sin captura, capturas borradas o alteradas, filtros, paginación, API y 404.
