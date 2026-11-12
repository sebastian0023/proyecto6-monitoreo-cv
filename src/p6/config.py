"""Lectura y validación de `config/monitoreo.yaml`.

Rechaza claves desconocidas dentro de cada sección y valores fuera de rango. Las secciones
de confianza y de alertas se agregan en #5 y #7. `sha256` es el hash del archivo completo:
es el `config_sha256` que llevan `run.json` y cada evento.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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
class Config:
    ruta: Path
    sha256: str
    modelo: Path
    descriptor: Path
    ritmo_cuadros_s: float
    cuadros_warmup: int
    detector: ConfigDetector


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


def _seccion(data: dict[str, Any], nombre: str, permitidas: set[str], errores: list[str]) -> dict:
    seccion = data.get(nombre)
    if not isinstance(seccion, dict):
        errores.append(f"falta la sección {nombre}")
        return {}
    if extra := set(seccion) - permitidas:
        errores.append(f"{nombre}: claves desconocidas {sorted(extra)}")
    return seccion


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
    m = _seccion(data, "modelo", {"archivo", "descriptor"}, errores)
    f = _seccion(data, "fuente", {"ritmo_cuadros_s", "cuadros_warmup"}, errores)
    d = _seccion(
        data,
        "detector",
        {"tamano_entrada", "relleno", "piso", "nms_iou", "max_detecciones"},
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
    )
