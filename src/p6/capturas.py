"""Política de capturas: qué cuadros se conservan como imagen y cómo (ver `docs/capturas.md`).

Se conservan, sin caducidad:

1. `baja`: todo cuadro en zona baja.
2. `ventana_alerta`: todos los cuadros de una ventana que abrió una alerta.
3. `muestra`: 1 de cada `MUESTRA_CADA` cuadros (`frame_id` 1, 21, 41, ...), como muestra de
   la operación normal.

Si un cuadro cumple varios motivos se registra el primero de la lista. Los cuadros sin
imagen (no se pudieron leer) no se pueden conservar.

Cada captura es un JPEG en `<carpeta de la corrida>/capturas/<event_id>.jpg`. El evento
guarda la ruta relativa a la carpeta de la corrida (`image_ref`), el SHA-256 de los bytes
escritos (`image_sha256`) y el motivo (`image_reason`). Nada en el proyecto borra capturas:
solo se reemplazan al repetir una corrida con el mismo `run_id` y `--sobrescribir`.

Los parámetros son constantes del código, no de `config/monitoreo.yaml`: no cambian ninguna
puntuación, zona ni alerta, y la configuración quedó congelada en #5. Se registran en el
`run.json` de cada corrida.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

MUESTRA_CADA = 20
CALIDAD_JPEG = 90
CARPETA = "capturas"


def descripcion() -> dict[str, Any]:
    """Parámetros de la política, para `run.json`."""
    return {
        "documento": "docs/capturas.md",
        "motivos": {
            "baja": "todo cuadro en zona baja",
            "ventana_alerta": "todos los cuadros de una ventana que abrió una alerta",
            "muestra": f"1 de cada {MUESTRA_CADA} cuadros (frame_id % {MUESTRA_CADA} == 1)",
        },
        "formato": f"JPEG calidad {CALIDAD_JPEG}",
        "carpeta": f"{CARPETA}/<event_id>.jpg",
        "caducidad": "ninguna",
    }


def motivo(evento: dict[str, Any], ventana_abrio_alerta: bool) -> str | None:
    """Por qué conservar este cuadro, o `None` si la política no lo guarda."""
    if evento.get("zone") == "baja":
        return "baja"
    if ventana_abrio_alerta:
        return "ventana_alerta"
    if evento["frame_id"] % MUESTRA_CADA == 1:
        return "muestra"
    return None


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def guardar(carpeta_corrida: Path, event_id: str, imagen: np.ndarray) -> tuple[str, str]:
    """Escribe el JPEG y devuelve (`image_ref` relativa a la corrida, SHA-256 del archivo)."""
    ok, buf = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG])
    if not ok:
        raise OSError(f"no se pudo codificar la captura de {event_id}")
    datos = buf.tobytes()
    ref = f"{CARPETA}/{event_id}.jpg"
    destino = carpeta_corrida / ref
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".parcial")
    tmp.write_bytes(datos)
    os.replace(tmp, destino)  # nunca queda un JPEG a medias con el nombre final
    return ref, sha256_bytes(datos)


def verificar(carpeta_corrida: Path, image_ref: str | None, image_sha256: str | None) -> str:
    """Estado de la captura de un evento: `sin_captura`, `ok`, `no_existe`, `alterada` o
    `ruta_invalida` (la referencia sale de la carpeta de la corrida)."""
    if image_ref is None:
        return "sin_captura"
    base = carpeta_corrida.resolve()
    ruta = (base / image_ref).resolve()
    if not ruta.is_relative_to(base):
        return "ruta_invalida"
    if not ruta.is_file():
        return "no_existe"
    if sha256_bytes(ruta.read_bytes()) != image_sha256:
        return "alterada"
    return "ok"


def ruta(carpeta_corrida: Path, image_ref: str) -> Path:
    return (carpeta_corrida.resolve() / image_ref).resolve()
