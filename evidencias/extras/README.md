# Extras reclamados

Inventario de los adicionales, separados de la base. Cada uno es distinto de los requisitos base y de los demás extras. Se pide el nivel indicado; si la evidencia solo acredita uno menor, corresponde ese.

Todo se generó con el commit `3dc1c44` (árbol limpio) y la misma configuración de la base (SHA-256 `11b06253…`). Los issues correspondientes son #11 a #14.

| ID | Tipo | Elemento | Nivel pedido | Evidencia | Cómo verificar |
|---|---|---|---|---|---|
| X1 | Funcionalidad | **Exportar a CSV los eventos filtrados** desde el portal (#12) | 10 | `src/p6/portal.py` (`/eventos.csv`), botón en `/eventos`; [`csv/`](csv/) | Ver abajo |
| X2 | Funcionalidad | **Fotos del carrito de P5 como segunda fuente** de tipo carpeta (#13) | 5 | `datos/carrito/` (78 fotos, manifiesto con SHA-256, origen y crédito); corrida [`carrito-p5`](../escenarios/carrito-p5/) consultable en el portal | `python scripts/descargar_fotos_carrito.py`; `/corridas/carrito-p5` |
| X3 | Métrica | **E1 · proporción de cuadros sin detecciones** (G4), por ventana y por corrida (#11) | 5 | `docs/metricas.md` §6; `metricas.json` → `extras.E1` | `--recalcular`; `tests/test_metricas.py::test_e1_ejemplo_del_documento` |
| X4 | Métrica | **E2 · detecciones por cuadro** (G4), distribución por ventana y por corrida (#11) | 5 | `docs/metricas.md` §6; `metricas.json` → `extras.E2` | `--recalcular`; `test_e2_ejemplo_del_documento` |
| X5 | Métrica | **E3 · predicciones por clase** (G4), distribución por ventana y por corrida (#11) | 5 | `docs/metricas.md` §6; `metricas.json` → `extras.E3` | `--recalcular`; `test_e3_ejemplo_del_documento` |
| X6 | Escenario | **C3 · interrupción del stream y recuperación** (#14) | 10 | [`escenarios/c3-interrupcion/`](../escenarios/c3-interrupcion/); regla F en `src/p6/alertas.py`; `docs/politica.md` §9 | `tests/test_interrupcion.py`; `/alertas/c3-interrupcion-F-1` |

## X1 · Exportar eventos a CSV

- **Flujo:** en `/eventos` se eligen los filtros (corrida, estado, zona, ventana, captura) y el enlace «Descargar CSV (N eventos)» baja **todos** los eventos que los cumplen, sin paginar, en `/eventos.csv?…`.
- **Persistencia:** el CSV se lee de la base de datos. Incluye los campos del contrato, un resumen de las detecciones y el estado de la captura verificado en ese momento, así que una captura borrada sale como `no_existe`.
- **Por qué nivel 10:**
  - Consulta parametrizada sobre datos persistidos.
  - Resultados verificados contra la base (`tests/test_portal.py::test_csv_exporta_los_eventos_filtrados_igual_que_la_base`).
  - Estado vacío, que devuelve el encabezado solo.
  - Estado erróneo: un filtro inválido devuelve 400 (`test_csv_respeta_los_filtros_y_el_caso_sin_resultados`).
- **Evidencia de uso con datos reales** (`csv/`):
  - `eventos_c2-baja-confianza_zona-baja.csv`: 128 filas, los cuadros bajos de C2.
  - `eventos_c1-normal_zona-baja_vacio.csv`: el caso sin resultados, con solo el encabezado.
  - `eventos_carrito-p5.csv`: los 78 eventos del carrito.
  - `portal-boton-descargar-csv.png`: el enlace en la lista filtrada.

## X2 · Segunda fuente: fotos del carrito

- **Datos reales del proyecto:** son las capturas del carrito del Proyecto 5. El origen está fijado por commit y se verifica por SHA-256.
- **Flujo:** se eligen con `--fuente datos/carrito`, se procesan como stream a 5 cuadros/s y sus eventos, alertas y capturas se consultan en el portal junto a las demás corridas.
- **Evidencia:** [`escenarios/carrito-p5/README.md`](../escenarios/carrito-p5/README.md) y sus pantallas.

## X3–X5 · Métricas adicionales de G4

Las tres son distintas de la métrica base de G4 (proporción de baja confianza) y entre sí: E1 cuenta cuadros sin salida, E2 mide cuántas detecciones hay por cuadro y E3 mide qué clases aparecen.

Cada una es por ventana, con población, exclusiones (`error`), «sin datos» y trazabilidad (`n`, `window_ids`, rango de `event_id`), y se recalcula desde la base de datos ([`../metricas/`](../metricas/)). Valores:

| | C1 | C2 | C3 | Carrito |
|---|---|---|---|---|
| E1 sin detecciones | 0.0 | 0.0 | 0.0 | 0.2051 (16 de 78) |
| E2 detecciones por cuadro (media / p90 / máx.) | 1.03 / 1 / 2 | 1.14 / 2 / 3 | 1.03 / 1 / 2 | 2.13 / 5 / 7 |
| E3 clases distintas (las más frecuentes) | 3 (person, chair, bottle) | 5 (person, kite, frisbee, cat, donut) | 2 (person, chair) | 25 (person, dog, cat, …) |

E3 muestra algo que la base no ve. En C2, con la persona solo en parte dentro del cuadro y poca luz, el modelo empieza a predecir clases que no están en la escena (kite, frisbee, cat, donut). En C1 eso no ocurre.

## X6 · Escenario de interrupción (C3)

Secuencia temporal con fallo, diagnóstico, recuperación y verificación posterior, con evidencia de cada etapa:
- **Fallo:** 6 s sin cuadros, simulados con `--simular-corte 70:6`, registrados en `run.json`.
- **Diagnóstico:** la alerta F `c3-interrupcion-F-1`, con la duración del hueco, los dos cuadros que lo delimitan y una acción sugerida.
- **Recuperación:** la alerta se cierra con el cuadro 71 y la cadencia vuelve a 5 cuadros/s.
- **Verificación:** G2 de la ventana 4 cae a 1.94 y el resto queda en ~5.0; se procesaron 117 cuadros en lugar de 147; zonas y puntuaciones iguales a C1.

Detalle por etapa: [`escenarios/c3-interrupcion/README.md`](../escenarios/c3-interrupcion/README.md). Es distinto de C1 y C2: cambia la condición probada (la fuente, no la confianza) y el comportamiento verificado (la regla F).

## Lo que no se reclama

- Las funciones del portal que forman parte de la base: consulta de eventos y alertas y vista de capturas.
- La regla sostenida B y su demostración en C2: ya cuentan para R3.3 y R6.2.
- La corrida del carrito como escenario: se reclama solo como funcionalidad (X2), no dos veces.
