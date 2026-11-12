"""Política de confianza: zonas por cuadro y resumen por ventana (ver `docs/politica.md`).

- **Unidad:** el cuadro. Su confianza es `frame_score`, la puntuación más alta de sus
  detecciones. Un cuadro sin detecciones (`sin_detecciones`) o con `error` no tiene confianza:
  su zona es `None`, no `baja`.
- **Zonas** con el umbral inferior `u_inf` y el superior `u_sup`: `aceptada` si s ≥ `u_sup`;
  `duda` si `u_inf` ≤ s < `u_sup`; `baja` si s < `u_inf`.
- **Ventana:** `tamano` cuadros procesados consecutivos, sin solapamiento. Tiene evidencia
  suficiente si al menos `minimo` de sus cuadros tienen detecciones; si no, es `insuficiente`,
  que no equivale a normal.

Las reglas de alerta que usan estos resúmenes se evalúan en #7.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

ZONAS = ("aceptada", "duda", "baja")
INSUFICIENTE = "insuficiente"


def zona(score: float | None, inferior: float, superior: float) -> str | None:
    """Zona de un `frame_score`; `None` si el cuadro no tiene puntuación."""
    if score is None:
        return None
    if score >= superior:
        return "aceptada"
    if score >= inferior:
        return "duda"
    return "baja"


def window_id(frame_id: int, tamano: int) -> int:
    """Ventana (desde 1) a la que pertenece el cuadro `frame_id` (desde 1)."""
    return (frame_id - 1) // tamano + 1


def resumir_ventanas(
    eventos: Iterable[dict[str, Any]], tamano: int, minimo: int
) -> list[dict[str, Any]]:
    """Resumen por ventana a partir de eventos con `zone` y `window_id` (etapa H3).

    `proporcion_baja` es cuadros en zona baja entre cuadros con detecciones, o la cadena
    `"insuficiente"` si la ventana tiene menos de `minimo` cuadros con detecciones.
    """
    por_ventana: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in eventos:
        por_ventana[e["window_id"]].append(e)
    resumen = []
    for wid in sorted(por_ventana):
        evs = sorted(por_ventana[wid], key=lambda e: e["frame_id"])
        con = [e for e in evs if e["status"] == "ok"]
        baja = sum(e["zone"] == "baja" for e in con)
        suficiente = len(con) >= minimo
        resumen.append(
            {
                "window_id": wid,
                "cuadros": len(evs),
                "completa": len(evs) == tamano,
                "con_detecciones": len(con),
                "sin_detecciones": sum(e["status"] == "sin_detecciones" for e in evs),
                "error": sum(e["status"] == "error" for e in evs),
                "aceptada": sum(e["zone"] == "aceptada" for e in con),
                "duda": sum(e["zone"] == "duda" for e in con),
                "baja": baja,
                "suficiente": suficiente,
                "proporcion_baja": round(baja / len(con), 4) if suficiente else INSUFICIENTE,
                "event_id_desde": evs[0]["event_id"],
                "event_id_hasta": evs[-1]["event_id"],
            }
        )
    return resumen
