"""Lectura y validación de `config/monitoreo.yaml`.

Rechaza claves desconocidas dentro de cada sección y valores fuera de rango. `sha256` es el
hash del archivo completo: es el `config_sha256` que llevan `run.json`, cada evento y cada
alerta. Los umbrales, la ventana y las reglas se justifican en `docs/politica.md`.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SEVERIDADES = ("info", "warning", "critical")
HEX64 = re.compile(r"[0-9a-f]{64}")


class ConfigError(ValueError):
    """El archivo de configuración no se puede leer o tiene valores inválidos."""


@dataclass(frozen=True)
class ConfigDetector:
    tamano_entrada: int
    relleno: int
    piso: float
    nms_iou: float
    max_detecciones: int


@dataclass(frozen=True)
class ConfigConfianza:
    umbral_inferior: float
    umbral_superior: float
    ventana_cuadros: int
    minimo_con_detecciones: int


@dataclass(frozen=True)
class ConfigReferencia:
    run_id: str
    video: Path
    video_sha256: str
    p_ref: float  # proporción de baja confianza de la referencia


@dataclass(frozen=True)
class ReglaA:
    """Baja confianza: proporción baja ≥ `proporcion_minima` en una ventana suficiente."""

    nombre: str
    proporcion_minima: float
    severidad: str
    accion_sugerida: str


@dataclass(frozen=True)
class ReglaB:
    """Cambio sostenido: proporción baja > p_ref + `margen_sobre_referencia` en
    `ventanas_seguidas` ventanas suficientes consecutivas."""

    nombre: str
    margen_sobre_referencia: float
    ventanas_seguidas: int
    severidad: str
    accion_sugerida: str


@dataclass(frozen=True)
class Config:
    ruta: Path
    sha256: str
    modelo: Path
    descriptor: Path
    ritmo_cuadros_s: float
    cuadros_warmup: int
    detector: ConfigDetector
    confianza: ConfigConfianza
    referencia: ConfigReferencia
    regla_a: ReglaA
    regla_b: ReglaB


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with Path(ruta).open("rb") as f:
        while bloque := f.read(1 << 20):
            h.update(bloque)
    return h.hexdigest()


def _numero(
    seccion: dict[str, Any], clave: str, tipo: type, errores: list[str], nombre: str
) -> Any:
    valor = seccion.get(clave)
    if tipo is int:
        if isinstance(valor, bool) or not isinstance(valor, int):
            errores.append(f"{nombre}.{clave} debe ser entero")
            return None
    elif isinstance(valor, bool) or not isinstance(valor, int | float) or not math.isfinite(valor):
        errores.append(f"{nombre}.{clave} debe ser un número finito")
        return None
    return valor


def _texto(seccion: dict[str, Any], clave: str, errores: list[str], nombre: str) -> str | None:
    valor = seccion.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        errores.append(f"{nombre}.{clave} debe ser un texto no vacío")
        return None
    return valor


def _seccion(
    data: dict[str, Any], nombre: str, permitidas: set[str], errores: list[str]
) -> dict[str, Any]:
    seccion = data.get(nombre)
    if not isinstance(seccion, dict):
        errores.append(f"falta la sección {nombre}")
        return {}
    if extra := set(seccion) - permitidas:
        errores.append(f"{nombre}: claves desconocidas {sorted(extra)}")
    return seccion


def _regla(
    alertas: dict[str, Any], clave: str, permitidas: set[str], errores: list[str]
) -> dict[str, Any]:
    regla = alertas.get(clave)
    if not isinstance(regla, dict):
        errores.append(f"alertas: falta la regla {clave}")
        return {}
    if extra := set(regla) - permitidas:
        errores.append(f"alertas.{clave}: claves desconocidas {sorted(extra)}")
    return regla


def cargar_config(ruta: Path | str, modelo: Path | None = None) -> Config:
    """Lee la configuración. `modelo` reemplaza la ruta de los pesos (por ejemplo en pruebas)."""
    ruta = Path(ruta)
    try:
        data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{ruta}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{ruta}: se esperaba un mapa")

    errores: list[str] = []
    if data.get("version") != 1:
        errores.append("version debe ser 1")
    if extra := set(data) - {
        "version",
        "modelo",
        "fuente",
        "detector",
        "confianza",
        "referencia",
        "alertas",
    }:
        errores.append(f"claves desconocidas {sorted(extra)}")
    m = _seccion(data, "modelo", {"archivo", "descriptor"}, errores)
    f = _seccion(data, "fuente", {"ritmo_cuadros_s", "cuadros_warmup"}, errores)
    d = _seccion(
        data,
        "detector",
        {"tamano_entrada", "relleno", "piso", "nms_iou", "max_detecciones"},
        errores,
    )
    c = _seccion(
        data,
        "confianza",
        {"umbral_inferior", "umbral_superior", "ventana_cuadros", "minimo_con_detecciones"},
        errores,
    )
    r = _seccion(data, "referencia", {"run_id", "video", "video_sha256", "p_ref"}, errores)
    al = _seccion(data, "alertas", {"A", "B"}, errores)
    ra = _regla(al, "A", {"nombre", "proporcion_minima", "severidad", "accion_sugerida"}, errores)
    rb = _regla(
        al,
        "B",
        {"nombre", "margen_sobre_referencia", "ventanas_seguidas", "severidad", "accion_sugerida"},
        errores,
    )
    for clave in ("archivo", "descriptor"):
        if not isinstance(m.get(clave), str) or not m[clave]:
            errores.append(f"modelo.{clave} debe ser una ruta")

    ritmo = _numero(f, "ritmo_cuadros_s", float, errores, "fuente")
    warmup = _numero(f, "cuadros_warmup", int, errores, "fuente")
    tamano = _numero(d, "tamano_entrada", int, errores, "detector")
    relleno = _numero(d, "relleno", int, errores, "detector")
    piso = _numero(d, "piso", float, errores, "detector")
    iou = _numero(d, "nms_iou", float, errores, "detector")
    maximo = _numero(d, "max_detecciones", int, errores, "detector")
    inferior = _numero(c, "umbral_inferior", float, errores, "confianza")
    superior = _numero(c, "umbral_superior", float, errores, "confianza")
    ventana = _numero(c, "ventana_cuadros", int, errores, "confianza")
    minimo = _numero(c, "minimo_con_detecciones", int, errores, "confianza")
    run_ref = _texto(r, "run_id", errores, "referencia")
    video_ref = _texto(r, "video", errores, "referencia")
    sha_ref = _texto(r, "video_sha256", errores, "referencia")
    p_ref = _numero(r, "p_ref", float, errores, "referencia")
    nombre_a = _texto(ra, "nombre", errores, "alertas.A")
    prop_a = _numero(ra, "proporcion_minima", float, errores, "alertas.A")
    sev_a = _texto(ra, "severidad", errores, "alertas.A")
    acc_a = _texto(ra, "accion_sugerida", errores, "alertas.A")
    nombre_b = _texto(rb, "nombre", errores, "alertas.B")
    margen = _numero(rb, "margen_sobre_referencia", float, errores, "alertas.B")
    seguidas = _numero(rb, "ventanas_seguidas", int, errores, "alertas.B")
    sev_b = _texto(rb, "severidad", errores, "alertas.B")
    acc_b = _texto(rb, "accion_sugerida", errores, "alertas.B")

    if ritmo is not None and ritmo <= 0:
        errores.append("fuente.ritmo_cuadros_s debe ser positivo")
    if warmup is not None and warmup < 0:
        errores.append("fuente.cuadros_warmup no puede ser negativo")
    if tamano is not None and (tamano <= 0 or tamano % 32):
        errores.append("detector.tamano_entrada debe ser positivo y múltiplo de 32")
    if relleno is not None and not 0 <= relleno <= 255:
        errores.append("detector.relleno debe estar en [0, 255]")
    if piso is not None and not 0 < piso <= 1:
        errores.append("detector.piso debe estar en (0, 1]")
    if iou is not None and not 0 < iou <= 1:
        errores.append("detector.nms_iou debe estar en (0, 1]")
    if maximo is not None and maximo <= 0:
        errores.append("detector.max_detecciones debe ser positivo")
    if None not in (piso, inferior, superior) and not piso < inferior < superior <= 1:
        errores.append(
            "se exige detector.piso < confianza.umbral_inferior < confianza.umbral_superior ≤ 1"
        )
    if ventana is not None and ventana < 1:
        errores.append("confianza.ventana_cuadros debe ser al menos 1")
    if minimo is not None and ventana is not None and not 1 <= minimo <= ventana:
        errores.append("confianza.minimo_con_detecciones debe estar entre 1 y ventana_cuadros")
    if sha_ref is not None and not HEX64.fullmatch(sha_ref):
        errores.append("referencia.video_sha256 debe ser SHA-256 en hexadecimal minúscula")
    if p_ref is not None and not 0 <= p_ref <= 1:
        errores.append("referencia.p_ref debe estar en [0, 1]")
    if prop_a is not None and not 0 < prop_a <= 1:
        errores.append("alertas.A.proporcion_minima debe estar en (0, 1]")
    if margen is not None and not 0 < margen < 1:
        errores.append("alertas.B.margen_sobre_referencia debe estar en (0, 1)")
    if seguidas is not None and seguidas < 2:
        errores.append("alertas.B.ventanas_seguidas debe ser al menos 2 (es una regla sostenida)")
    if p_ref is not None and margen is not None and p_ref + margen >= 1:
        errores.append("alertas.B: referencia.p_ref + margen_sobre_referencia debe ser menor que 1")
    for nombre, sev in (("A", sev_a), ("B", sev_b)):
        if sev is not None and sev not in SEVERIDADES:
            errores.append(f"alertas.{nombre}.severidad debe ser una de {SEVERIDADES}")
    if errores:
        raise ConfigError(f"{ruta}: " + "; ".join(errores))

    base = ruta.resolve().parent
    return Config(
        ruta=ruta,
        sha256=sha256_archivo(ruta),
        modelo=Path(modelo) if modelo is not None else base / m["archivo"],
        descriptor=base / m["descriptor"],
        ritmo_cuadros_s=float(ritmo),
        cuadros_warmup=warmup,
        detector=ConfigDetector(tamano, relleno, float(piso), float(iou), maximo),
        confianza=ConfigConfianza(float(inferior), float(superior), ventana, minimo),
        referencia=ConfigReferencia(run_ref, base / video_ref, sha_ref, float(p_ref)),
        regla_a=ReglaA(nombre_a, float(prop_a), sev_a, acc_a),
        regla_b=ReglaB(nombre_b, float(margen), seguidas, sev_b, acc_b),
    )
