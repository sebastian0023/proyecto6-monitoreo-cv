"""Contrato del evento y de la alerta (ver `docs/contrato.md`) y su validación.

`validar_evento` y `validar_alerta` devuelven la lista de problemas de un registro; vacía
significa que cumple el contrato. `ValidadorEventos` cuenta los aceptados y los rechazados,
con el motivo de cada rechazo.

El contrato se completa por etapas. Cada campo declara desde qué etapa es obligatorio, y
una etapa exige también todo lo de las anteriores:

- `H1` (#3): lo que produce el detector sobre cada cuadro.
- `H3` (#5): la zona de confianza y la ventana.
- `H4` (#6): la captura vinculada (`image_ref`, `image_sha256`, `image_reason`).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ETAPAS = ("H1", "H3", "H4")
ESTADOS = ("ok", "sin_detecciones", "error")
ZONAS = ("aceptada", "duda", "baja")
TIPOS_FUENTE = ("video", "carpeta", "webcam")
ESTADOS_ALERTA = ("abierta", "cerrada")
SEVERIDADES = ("info", "warning", "critical")
# Por qué se conservó la captura de un cuadro (ver docs/capturas.md).
MOTIVOS_CAPTURA = ("baja", "ventana_alerta", "muestra")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _texto(v: Any) -> bool:
    return isinstance(v, str) and v != ""


def _entero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _numero(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _fecha(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return False
    return True


COMPROBACIONES: dict[str, Callable[[Any], bool]] = {
    "texto": _texto,
    "entero": _entero,
    "numero": _numero,
    "booleano": lambda v: isinstance(v, bool),
    "lista": lambda v: isinstance(v, list),
    "fecha": _fecha,
}


@dataclass(frozen=True)
class Campo:
    nombre: str
    tipo: str  # clave de COMPROBACIONES
    desde: str = "H1"  # etapa desde la que es obligatorio
    nulable: bool = False  # la clave debe existir; el valor puede ser null (con su condición)


CAMPOS_EVENTO: tuple[Campo, ...] = (
    Campo("event_id", "texto"),
    Campo("run_id", "texto"),
    Campo("frame_id", "entero"),
    Campo("source_id", "texto"),
    Campo("source_kind", "texto"),
    Campo("origen", "texto"),
    Campo("t_capture_utc", "fecha"),
    Campo("t_mono_ms", "numero"),
    Campo("task", "texto"),
    Campo("model_version", "texto"),
    Campo("model_sha256", "texto"),
    Campo("config_sha256", "texto"),
    Campo("status", "texto"),
    Campo("error_msg", "texto", nulable=True),
    Campo("detections", "lista"),
    Campo("frame_score", "numero", nulable=True),
    Campo("zone", "texto", desde="H3", nulable=True),
    Campo("window_id", "entero", desde="H3"),
    Campo("t_pre_ms", "numero", nulable=True),
    Campo("t_infer_ms", "numero", nulable=True),
    Campo("t_post_ms", "numero", nulable=True),
    Campo("rss_mb", "numero"),
    Campo("warmup", "booleano"),
    Campo("image_ref", "texto", desde="H4", nulable=True),
    Campo("image_sha256", "texto", desde="H4", nulable=True),
    Campo("image_reason", "texto", desde="H4", nulable=True),
)

CAMPOS_ALERTA: tuple[Campo, ...] = (
    Campo("alert_id", "texto"),
    Campo("rule_id", "texto"),
    Campo("run_id", "texto"),
    Campo("status", "texto"),
    Campo("opened_at", "fecha"),
    Campo("opened_window_id", "entero"),
    Campo("closed_at", "fecha", nulable=True),
    Campo("closed_window_id", "entero", nulable=True),
    Campo("severity", "texto"),
    Campo("reason", "texto"),
    Campo("window_ids", "lista"),
    Campo("event_ids", "lista"),
    Campo("config_sha256", "texto"),
    Campo("suggested_action", "texto"),
)


def _etapa_valida(etapa: str) -> int:
    if etapa not in ETAPAS:
        raise ValueError(f"etapa desconocida {etapa!r}; usa una de {ETAPAS}")
    return ETAPAS.index(etapa)


def _campos(registro: Any, campos: tuple[Campo, ...], etapa: str) -> list[str]:
    """Presencia y tipo de cada campo exigido en `etapa`."""
    tope = _etapa_valida(etapa)
    if not isinstance(registro, dict):
        return ["el registro no es un objeto"]
    problemas: list[str] = []
    for c in campos:
        if ETAPAS.index(c.desde) > tope:
            continue
        if c.nombre not in registro:
            problemas.append(f"{c.nombre}: falta")
        elif registro[c.nombre] is None:
            if not c.nulable:
                problemas.append(f"{c.nombre}: no puede ser null")
        elif not COMPROBACIONES[c.tipo](registro[c.nombre]):
            problemas.append(f"{c.nombre}: debe ser de tipo {c.tipo}")
    return problemas


def _deteccion(d: Any, n: int) -> list[str]:
    if not isinstance(d, dict):
        return [f"detections[{n}]: no es un objeto"]
    p: list[str] = []
    if not _entero(d.get("class_id")):
        p.append(f"detections[{n}].class_id: debe ser entero")
    if not _texto(d.get("class_name")):
        p.append(f"detections[{n}].class_name: debe ser texto")
    if not _numero(d.get("score")) or not 0 <= d["score"] <= 1:
        p.append(f"detections[{n}].score: debe estar en [0, 1]")
    bbox = d.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and all(_numero(v) for v in bbox)):
        p.append(f"detections[{n}].bbox: debe ser una lista de 4 números")
    return p


def validar_evento(evento: Any, etapa: str = "H1") -> list[str]:
    """Problemas del evento respecto al contrato hasta `etapa`; vacío si lo cumple."""
    problemas = _campos(evento, CAMPOS_EVENTO, etapa)
    if problemas and not isinstance(evento, dict):
        return problemas
    tope = _etapa_valida(etapa)
    e = evento
    # Las reglas entre campos solo se revisan sobre campos presentes y bien tipados.
    malos = {p.split(":")[0] for p in problemas}
    bien = lambda *ns: not malos.intersection(ns)  # noqa: E731

    if bien("status"):
        if e["status"] not in ESTADOS:
            problemas.append(f"status: debe ser uno de {ESTADOS}")
    if bien("source_kind") and e["source_kind"] not in TIPOS_FUENTE:
        problemas.append(f"source_kind: debe ser uno de {TIPOS_FUENTE}")
    if bien("task") and e["task"] != "detection":
        problemas.append("task: debe ser 'detection'")
    if bien("event_id", "run_id", "frame_id"):
        if e["frame_id"] < 1:
            problemas.append("frame_id: debe ser ≥ 1")
        if e["event_id"] != f"{e['run_id']}-{e['frame_id']}":
            problemas.append("event_id: debe ser <run_id>-<frame_id>")
    for campo in ("model_sha256", "config_sha256"):
        if bien(campo) and not HEX64.fullmatch(e[campo]):
            problemas.append(f"{campo}: debe ser SHA-256 en hexadecimal minúscula (64 caracteres)")

    estado = e.get("status") if bien("status") else None
    if estado == "error":
        if bien("error_msg") and e["error_msg"] is None:
            problemas.append("error_msg: obligatorio cuando status es 'error'")
    elif estado is not None and bien("error_msg") and e["error_msg"] is not None:
        problemas.append("error_msg: debe ser null salvo cuando status es 'error'")

    if bien("detections"):
        for n, d in enumerate(e["detections"]):
            problemas += _deteccion(d, n)
        if estado == "ok" and not e["detections"]:
            problemas.append("detections: 'ok' exige al menos una detección")
        if estado in ("sin_detecciones", "error") and e["detections"]:
            problemas.append(f"detections: debe estar vacía con status {estado!r}")
    if bien("detections", "frame_score", "status") and not any(
        p.startswith("detections[") for p in problemas
    ):
        scores = [d["score"] for d in e["detections"]]
        if scores:
            if e["frame_score"] is None:
                problemas.append("frame_score: obligatorio cuando hay detecciones")
            elif abs(e["frame_score"] - max(scores)) > 1e-6:
                problemas.append("frame_score: debe ser la puntuación más alta del cuadro")
        elif e["frame_score"] is not None:
            problemas.append("frame_score: debe ser null sin detecciones")
        if e["frame_score"] is not None and not 0 <= e["frame_score"] <= 1:
            problemas.append("frame_score: debe estar en [0, 1]")

    for campo in ("t_pre_ms", "t_infer_ms", "t_post_ms"):
        if not bien(campo):
            continue
        if e[campo] is None and estado not in ("error", None):
            problemas.append(f"{campo}: solo puede ser null con status 'error'")
        elif e[campo] is not None and e[campo] < 0:
            problemas.append(f"{campo}: no puede ser negativo")
    if bien("rss_mb") and e["rss_mb"] <= 0:
        problemas.append("rss_mb: debe ser positivo")

    if tope >= ETAPAS.index("H3"):
        if bien("zone", "frame_score"):
            if e["zone"] is not None and e["zone"] not in ZONAS:
                problemas.append(f"zone: debe ser uno de {ZONAS} o null")
            if e["frame_score"] is None and e["zone"] is not None:
                problemas.append("zone: debe ser null cuando frame_score es null")
            if e["frame_score"] is not None and e["zone"] is None:
                problemas.append("zone: obligatoria cuando hay frame_score")
        if bien("window_id") and e["window_id"] < 1:
            problemas.append("window_id: debe ser ≥ 1")
    if tope >= ETAPAS.index("H4") and bien("image_ref", "image_sha256", "image_reason"):
        nulos = {e[c] is None for c in ("image_ref", "image_sha256", "image_reason")}
        if len(nulos) > 1:
            problemas.append(
                "image_ref, image_sha256 e image_reason: deben ir juntos o ser los tres null"
            )
        elif e["image_ref"] is not None:
            if not HEX64.fullmatch(e["image_sha256"]):
                problemas.append("image_sha256: debe ser SHA-256 en hexadecimal minúscula")
            if e["image_reason"] not in MOTIVOS_CAPTURA:
                problemas.append(f"image_reason: debe ser uno de {MOTIVOS_CAPTURA}")
            ref = e["image_ref"]
            if ref.startswith(("/", "\\")) or ".." in ref.replace("\\", "/").split("/"):
                problemas.append("image_ref: debe ser una ruta relativa sin '..'")
    return problemas


def validar_alerta(alerta: Any, etapa: str = "H1") -> list[str]:
    """Problemas de la alerta respecto al contrato; vacío si lo cumple."""
    problemas = _campos(alerta, CAMPOS_ALERTA, etapa)
    if not isinstance(alerta, dict):
        return problemas
    a = alerta
    malos = {p.split(":")[0] for p in problemas}
    bien = lambda *ns: not malos.intersection(ns)  # noqa: E731

    if bien("severity") and a["severity"] not in SEVERIDADES:
        problemas.append(f"severity: debe ser uno de {SEVERIDADES}")
    if bien("config_sha256") and not HEX64.fullmatch(a["config_sha256"]):
        problemas.append("config_sha256: debe ser SHA-256 en hexadecimal minúscula")
    if bien("status") and a["status"] not in ESTADOS_ALERTA:
        problemas.append(f"status: debe ser uno de {ESTADOS_ALERTA}")
    elif bien("status", "closed_at", "closed_window_id"):
        cierre = (a["closed_at"], a["closed_window_id"])
        if a["status"] == "abierta" and any(v is not None for v in cierre):
            problemas.append("closed_at y closed_window_id: deben ser null en una alerta abierta")
        if a["status"] == "cerrada" and any(v is None for v in cierre):
            problemas.append("closed_at y closed_window_id: obligatorios en una alerta cerrada")
    if bien("window_ids"):
        if not a["window_ids"] or not all(_entero(w) and w >= 1 for w in a["window_ids"]):
            problemas.append("window_ids: debe ser una lista no vacía de enteros ≥ 1")
        elif bien("opened_window_id") and a["opened_window_id"] not in a["window_ids"]:
            problemas.append("opened_window_id: debe estar entre window_ids")
    if bien("event_ids") and (not a["event_ids"] or not all(_texto(x) for x in a["event_ids"])):
        problemas.append("event_ids: debe ser una lista no vacía de textos")
    return problemas


class ValidadorEventos:
    """Valida cada evento de una corrida y cuenta aceptados, rechazados y motivos."""

    def __init__(self, etapa: str = "H1") -> None:
        _etapa_valida(etapa)
        self.etapa = etapa
        self.aceptados = 0
        self.rechazados = 0
        self.motivos: Counter[str] = Counter()

    def revisar(self, evento: Any) -> list[str]:
        """Valida y cuenta. Devuelve los problemas (vacío si el evento se acepta)."""
        problemas = validar_evento(evento, self.etapa)
        if problemas:
            self.rechazados += 1
            self.motivos.update(p.split(":")[0] for p in problemas)
        else:
            self.aceptados += 1
        return problemas
