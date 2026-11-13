# Política de confianza y reglas de alerta

Cómo se decide si un cuadro tiene confianza aceptada, dudosa o baja, y cuándo un conjunto de cuadros dispara una alerta. Cada valor sale de la corrida sobre `referencia.mp4` y está en [`config/monitoreo.yaml`](../config/monitoreo.yaml), que queda **congelada**. Los eventos que la usan siguen [`contrato.md`](contrato.md) (zona y ventana desde la etapa H3); las evidencias están en [`evidencias/referencia/`](../evidencias/referencia/).

La confianza es la puntuación que entrega el detector. No es la probabilidad de acertar y esta política no afirma que una detección sea correcta ni que haya drift: solo describe y vigila las salidas del modelo.

## 1. Valores elegidos

| Parámetro | Valor | De dónde sale |
|---|---|---|
| Piso del detector | 0.10 | Debe quedar por debajo del umbral inferior para que se vean las zonas de duda y baja (sección 2) |
| NMS | IoU 0.45 por clase, máximo 100 detecciones | Valor por defecto de YOLOX |
| Umbral inferior | **0.85** | Percentil 10 de la referencia (0.8657), al múltiplo de 0.05 más cercano |
| Umbral superior | **0.90** | Percentil 50 de la referencia (0.8956), al múltiplo de 0.05 más cercano |
| Ventana | 20 cuadros (4 s a 5 cuadros/s) | Sección 5 |
| Mínimo con detecciones | 10 de 20 | Sección 5 |
| Regla A | proporción baja ≥ 0.50 en una ventana suficiente | Sección 6 |
| Regla B | proporción baja > p_ref + 0.20 = 0.2204 en 3 ventanas suficientes seguidas | Sección 6 |
| p_ref | 0.0204 (3 de 147 cuadros) | Cuadros bajos entre cuadros con detecciones de la referencia |

Cumple 0 ≤ piso (0.10) < inferior (0.85) < superior (0.90) ≤ 1. La configuración rechaza cualquier valor que lo viole.

## 2. Unidad, piso y estados aparte

- **Unidad: el cuadro.** Su confianza (`frame_score`) es la puntuación más alta entre sus detecciones. El denominador de toda proporción son los **cuadros con detecciones**.
- **Piso 0.10 en lugar del 0.30 de P5.** El detector entrega todo lo que puntúa 0.10 o más. Con un piso igual o mayor que el umbral inferior, las puntuaciones bajas nunca llegarían a la política y no se podrían observar la zona de duda ni la de baja confianza. Con 0.10, cada cuadro conserva la puntuación de su mejor candidata y también las de las demás detecciones (`detections` en el evento).
- **NMS** por clase con IoU 0.45: de varias cajas muy solapadas de la misma clase se conserva la de mayor puntuación. No modifica ninguna puntuación.
- **Las puntuaciones nunca se modifican.** Ni el piso, ni el NMS, ni las zonas cambian un valor del modelo.
- **Estados aparte.** Un cuadro `sin_detecciones` (nada supera el piso) o con `error` (no se pudo leer o el detector falló) no tiene confianza: su `zone` es nula. No cuentan como baja confianza ni como confianza cero, y no entran en el denominador. Se cuentan por separado.

## 3. Zonas

Con `frame_score` = *s*, el umbral inferior *u*<sub>inf</sub> = 0.85 y el superior *u*<sub>sup</sub> = 0.90:

| Zona | Condición | Significa |
|---|---|---|
| `aceptada` | *s* ≥ 0.90 | Aceptada por la política |
| `duda` | 0.85 ≤ *s* < 0.90 | Confianza intermedia |
| `baja` | *s* < 0.85 | Baja confianza |

**Igualdades:** *s* = 0.85 cuenta como `duda` y *s* = 0.90 como `aceptada`. La zona se calcula con el `frame_score` guardado en el evento (redondeado a 6 decimales), de modo que se puede recalcular desde los datos guardados.

## 4. La referencia y por qué estos umbrales

**Referencia:** `datos/videos/referencia.mp4` (SHA-256 `ac2d6284…0d84`), procesada como stream a 5 cuadros/s con el modelo YOLOX-Nano 0.1.1rc0 (SHA-256 `c789161e…0b7d`) y el piso en 0.10. Corrida `ref-01`; evidencias en `evidencias/referencia/`.

| | |
|---|---|
| Cuadros | 147 |
| Con detecciones | 147 |
| Sin detecciones / con error | 0 / 0 |
| `frame_score` mínimo, máximo | 0.8333, 0.9507 |
| Percentiles 10, 25, 50, 75, 90 | 0.8657, 0.8813, 0.8956, 0.9059, 0.9249 |

Histograma (cajas de 0.01; el gráfico completo es [`histograma.svg`](../evidencias/referencia/histograma.svg)):

| 0.83 | 0.84 | 0.85 | 0.86 | 0.87 | 0.88 | 0.89 | 0.90 | 0.91 | 0.92 | 0.93 | 0.94 | 0.95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 5 | 12 | 15 | 27 | 34 | 22 | 9 | 11 | 8 | 0 | 1 |

**Regla de elección.** Umbral inferior = percentil 10 y superior = percentil 50 de `frame_score` de la referencia, cada uno al múltiplo de 0.05 más cercano (0.8657 → 0.85; 0.8956 → 0.90). La idea: el inferior marca la cola baja de la operación normal y el superior separa la mitad más confiable.

Lo que implican estos valores sobre la propia referencia: 3 cuadros en `baja` (2 %), 93 en `duda` (63 %) y 51 en `aceptada` (35 %). La zona `aceptada` queda por debajo del 50 % esperado porque 0.8956 se redondea hacia arriba, a 0.90.

**Qué sugiere la referencia y qué limitaciones tiene:**

- La referencia es estrecha: todos sus cuadros están entre 0.83 y 0.95, porque la persona domina la imagen y el detector la puntúa de forma muy estable. Por eso las dos zonas intermedias están a solo 0.05 de distancia y los umbrales son **relativos a esta escena**: «baja» significa que la puntuación cayó por debajo de lo que esta escena produce en operación normal, no que 0.85 sea baja en términos absolutos.
- No hay una razón en la referencia para apartarse de la regla del plan (percentiles 10 y 50), de modo que no se ajustó ningún valor a mano.
- Una escena distinta o un cambio de cámara exigiría una referencia nueva y repetir esta calibración.

**Qué datos se usaron.** Los umbrales se calcularon con una corrida previa, `ref-00`, sobre `referencia.mp4` con la configuración anterior (sin umbrales); el script `scripts/calibrar_referencia.py` produjo la propuesta 0.85 y 0.90 solo a partir de ese archivo (`evidencias/referencia/calibracion-previa/`). Luego se congeló la configuración y se repitió la corrida como `ref-01` con ella, para que la referencia comparta el `config_sha256` con C1 y C2; las puntuaciones son idénticas y el script lo verifica (`--verificar`).

**Transparencia sobre C2.** Antes de fijar los umbrales se grabó `baja_confianza.mp4` y se comprobó que sus puntuaciones sí bajaban (la primera toma no bajaba, con p50 0.93, y se volvió a grabar). Esa comprobación decidió regrabar el video y no movió ningún umbral. También se calcularon de forma preliminar las zonas de C1 y C2 con la regla del plan para confirmar que el montaje era viable; salieron los mismos umbrales (0.85 y 0.90) que da la referencia sola, y no se ajustó ningún valor después de ver C1 ni C2.

## 5. Ventana y evidencia suficiente

- **Ventana:** 20 cuadros procesados consecutivos, sin solapamiento, contados desde el primero de la corrida: `window_id = (frame_id − 1) // 20 + 1`. A 5 cuadros/s son 4 s, suficientes para promediar un movimiento breve y lo bastante cortas para que 3 seguidas (regla B) sean 12 s. La referencia (147 cuadros) da 7 ventanas completas y una parcial de 7 cuadros, suficiente para aplicar la regla sostenida.
- **Mínimo:** una ventana tiene **evidencia suficiente** si al menos 10 de sus 20 cuadros tienen detecciones (la mitad). Si no, es `insuficiente`. Que casi nada se detecte en una ventana indica que la fuente no muestra objetos, no que el modelo tenga baja confianza, así que `insuficiente` **no equivale a normal** ni a baja confianza: su proporción no se calcula (`"insuficiente"`, nunca 0).
- **Última ventana parcial:** se calcula con los cuadros que tenga; con menos de 10 cuadros es siempre `insuficiente`. En la referencia, la ventana 8 (7 cuadros) lo es.

Proporción de cuadros en zona baja por ventana de la referencia (`evidencias/referencia/calibracion.json`):

| Ventana | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Cuadros | 20 | 20 | 20 | 20 | 20 | 20 | 20 | 7 |
| Baja | 2 | 1 | 0 | 0 | 0 | 0 | 0 | — |
| Proporción baja | 0.10 | 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | insuficiente |

## 6. Reglas de alerta

| Regla | Condición | Severidad | Acción sugerida |
|---|---|---|---|
| A · baja confianza | En una ventana **suficiente**, la proporción de cuadros en zona baja es ≥ 0.50 | `warning` | Revisar la captura, la iluminación y el enfoque |
| B · cambio sostenido | La proporción baja supera p_ref + 0.20 = 0.2204 en 3 ventanas **suficientes** seguidas | `critical` | Investigar un cambio de escena o de cámara; comparar con la referencia |

La regla C del plan (evidencia insuficiente sostenida) es opcional y no se implementa.

**Ciclo de vida** (cada alerta guarda su regla, ventanas y eventos, ver [`contrato.md`](contrato.md)):

- Una alerta se **abre** al cumplirse la condición y se **cierra** en la primera ventana suficiente en que deja de cumplirse. Un episodio continuo produce **una** alerta, no una por ventana.
- Las ventanas `insuficiente` **no suman ni rompen la racha** de la regla B y **no cierran** una alerta abierta: sin evidencia no se puede afirmar que el problema terminó.
- El `reason` de cada alerta lleva los valores medidos y los límites, y se completa si la alerta sigue o se cierra. Por ejemplo: «proporción de baja confianza 0.70 ≥ 0.50 en la ventana 1 (14 de 20 cuadros con detecciones); sigue en las ventanas 2, 3 (proporciones 0.85, 0.80); se cerró en la ventana 4: proporción 0.10 < 0.5».
- `opened_at` y `closed_at` son el `t_capture_utc` del último cuadro de la ventana en que se abrió o se cerró, que es cuando la condición se pudo evaluar.
- Los eventos que explican una alerta (`event_ids`) son los cuadros en zona baja de las ventanas donde se cumplió la condición; `window_ids` son esas ventanas. Para B, al abrirse incluye las 3 ventanas de la racha.
- Si la corrida termina con una alerta abierta (por ejemplo, porque la última ventana es parcial e insuficiente), queda `abierta`: no se cierra sin evidencia.

**Implementación:** [`src/p6/alertas.py`](../src/p6/alertas.py) (`EvaluadorReglas`). `monitorear` la llama al cerrar cada ventana, guarda las alertas que cambian y, si una alerta se abrió en esa ventana, conserva la captura de todos sus cuadros ([`capturas.md`](capturas.md)). Las pruebas con secuencias sintéticas están en `tests/test_alertas.py`: A se dispara con ≥ 0.50, B necesita 3 ventanas seguidas con > 0.2204, las ventanas insuficientes no cuentan, un episodio es una sola alerta y la referencia real no dispara ninguna.

**Por qué estos valores, con la referencia:**

- **A = 0.50.** La peor ventana de la referencia tiene proporción 0.10 (2 de 20), cinco veces menos. Una ventana donde la mitad de los cuadros con detecciones cae bajo un umbral que solo el 2 % de la referencia cruzó es un cambio claro. Es una alerta de severidad `warning` que se evalúa ventana por ventana.
- **B = p_ref + 0.20.** Con p_ref = 0.0204 el límite es 0.2204, es decir, 5 o más cuadros bajos de 20 (5/20 = 0.25 supera el límite; 4/20 = 0.20 no). Es más de dos veces la peor ventana de la referencia (0.10), de modo que la referencia no la dispara, pero es mucho más sensible que A: detecta un deterioro moderado. Se mide contra p_ref y no contra un valor fijo porque la regla busca un cambio **respecto de la referencia**.
- **3 ventanas seguidas = 12 s.** Un movimiento puntual (inclinarse, una mano frente a la cámara) dura segundos y afecta una ventana; un cambio de escena o de cámara persiste. Exigir 3 separa ambos casos. Es la regla `critical` porque indica un cambio sostenido y no un episodio.
- **A y B son alertas distintas:** una ventana con proporción ≥ 0.50 también supera 0.2204, así que un episodio intenso puede abrir A en la primera ventana y B en la tercera; son alertas distintas con acciones distintas.

## 7. Congelamiento

`config/monitoreo.yaml` no se cambia después de esta calibración. Su SHA-256 va en `run.json`, en cada evento y en cada alerta. Las tres corridas de evidencia (referencia, C1 y C2) deben mostrar el mismo `config_sha256`; si cambia, la comparación se separa en series distintas y hay que repetir la referencia y los dos escenarios.

## 8. Reproducir

```bash
export PYTHONPATH=src
python -m p6.monitorear --fuente datos/videos/referencia.mp4 --ritmo 5 \
    --config config/monitoreo.yaml --run-id ref-01
python scripts/calibrar_referencia.py --run resultados/ref-01 \
    --salida evidencias/referencia --verificar     # código 0: la configuración sale de la referencia
```

`calibrar_referencia.py` lee solo la corrida de referencia, recalcula percentiles, umbrales, `p_ref` y la proporción por ventana, y falla si la configuración no coincide.

## 9. Regla F · interrupción de la fuente (extra #14)

Además de A y B, el monitoreo vigila que la fuente siga entregando cuadros.

- **Condición:** el hueco entre dos cuadros seguidos (por su reloj monotónico, `t_mono_ms`) supera **5 intervalos esperados**, es decir, 1 s a 5 cuadros/s.
- **Alerta:** se registra una alerta `F` de severidad `critical`.
  - `opened_at` es el momento en que el hueco pasó el umbral: el último cuadro antes del corte más 1 s.
  - `closed_at` es el primer cuadro que llega después, es decir, la recuperación.
  - `event_ids` son esos dos cuadros.
  - `reason` dice la duración del hueco, el umbral y los cuadros de origen.
- **Dónde está:** `src/p6/alertas.py` (`DetectorInterrupciones`). No está en `config/monitoreo.yaml`, que quedó congelada en #5: es una constante del código y cada `run.json` la registra en `politica.regla_F`. Con un ritmo normal no se dispara (ni en la referencia, ni en C1, ni en C2).
- **Simulación para el escenario:** `python -m p6.monitorear … --simular-corte N:S` hace que la fuente de video o de carpeta deje de entregar cuadros durante S segundos después del cuadro N. Luego sigue donde estaría un stream en vivo: los cuadros de ese lapso se pierden y la cadencia se reanuda sin ponerse al día. `run.json` → `fuente.simulacion_corte` registra lo que ocurrió.
- **Límite:** la interrupción se detecta y se registra cuando la fuente se recupera. Un corte definitivo termina la corrida: el video se acaba o la cámara da error.
