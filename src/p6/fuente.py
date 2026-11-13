"""Fuentes de cuadros con ritmo declarado: video, carpeta de imágenes o webcam.

    abrir_fuente("datos/videos/normal.mp4", ritmo=5)    # video
    abrir_fuente("datos/otros/fotos", ritmo=5)          # carpeta de imágenes
    abrir_fuente("webcam:0", ritmo=5)                   # cámara en vivo

Todas entregan `Cuadro` a `ritmo` cuadros por segundo:

- **Video:** se muestrea 1 de cada `k = round(fps_video / ritmo)` cuadros del archivo y se
  espera entre entregas para que el stream salga al ritmo declarado. Con un video de 15 fps
  y ritmo 5, k = 3.
- **Carpeta:** cada imagen es un cuadro, en orden alfabético, con la misma espera.
- **Webcam:** se leen cuadros y se entrega el primero que llega después de cada 1/ritmo s.

`sin_pausa=True` omite la espera (pruebas y recorridos rápidos). El ritmo declarado y el
muestreo quedan en `descripcion()`, que se guarda en `run.json`.

**Corte simulado (extra #14).** Con `corte=(N, S)`, una fuente de video o de carpeta deja de
entregar cuadros durante S segundos después del cuadro N, como una cámara que se cuelga, y
luego sigue donde estaría un stream en vivo: los cuadros de ese lapso se pierden (en un video
se saltan S × fps cuadros del archivo; en una carpeta, S × ritmo imágenes). `descripcion()`
registra lo que ocurrió. El monitoreo detecta el hueco por los relojes de los cuadros.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class FuenteError(RuntimeError):
    """La fuente no se puede abrir o dejó de entregar cuadros."""


@dataclass(frozen=True)
class Cuadro:
    frame_id: int  # correlativo dentro de la corrida, desde 1
    imagen: np.ndarray | None  # BGR uint8; None si no se pudo leer (se registra como error)
    t_mono_ms: float  # reloj monotónico al entregarlo
    t_capture_utc: str  # reloj de pared, ISO 8601
    origen: str  # de dónde salió, por ejemplo "cuadro 30 de normal.mp4"
    error: str | None = None


class Marcapasos:
    """Reparte las entregas a `ritmo` por segundo contando desde la primera."""

    def __init__(
        self,
        ritmo: float,
        sin_pausa: bool,
        reloj: Callable[[], float],
        dormir: Callable[[float], None],
    ) -> None:
        self._intervalo = 1.0 / ritmo
        self._sin_pausa = sin_pausa
        self._reloj = reloj
        self._dormir = dormir
        self._t0: float | None = None
        self._n = 0

    def desplazar(self, segundos: float) -> None:
        """Corre el calendario de entregas: tras un corte se sigue al ritmo, sin ponerse al día."""
        if self._t0 is not None:
            self._t0 += segundos

    def esperar(self) -> None:
        """Bloquea hasta el instante de la próxima entrega."""
        ahora = self._reloj()
        if self._t0 is None:
            self._t0 = ahora
        elif not self._sin_pausa:
            falta = self._t0 + self._n * self._intervalo - ahora
            if falta > 0:
                self._dormir(falta)
        self._n += 1


def _ahora_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class FuenteBase:
    source_kind = ""
    source_id = ""

    def __init__(
        self,
        ritmo: float,
        sin_pausa: bool = False,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        corte: tuple[int, float] | None = None,
    ) -> None:
        if ritmo <= 0:
            raise ValueError("el ritmo debe ser positivo")
        if corte is not None and (corte[0] < 1 or corte[1] <= 0):
            raise ValueError("el corte necesita un cuadro ≥ 1 y una duración positiva")
        self.ritmo = ritmo
        self.sin_pausa = sin_pausa
        self._reloj = reloj
        self._dormir = dormir
        self._pasos = Marcapasos(ritmo, sin_pausa, reloj, dormir)
        self.corte = corte
        self.corte_ocurrido: dict[str, Any] | None = None

    def _cortar_si_toca(self, entregados: int, por_segundo: float) -> int:
        """Si el cuadro `entregados` es el del corte, espera la duración del corte y devuelve
        cuántos elementos de la fuente hay que saltar (`por_segundo` × segundos)."""
        if self.corte is None or entregados != self.corte[0]:
            return 0
        segundos = self.corte[1]
        inicio = self._reloj()
        self._dormir(segundos)
        self._pasos.desplazar(segundos)
        saltar = round(segundos * por_segundo)
        self.corte_ocurrido = {
            "despues_del_cuadro": entregados,
            "segundos": segundos,
            "elementos_omitidos": saltar,
            "t_mono_inicio_ms": round(inicio * 1000, 3),
            "t_mono_fin_ms": round(self._reloj() * 1000, 3),
        }
        return saltar

    def _descripcion_corte(self) -> dict[str, Any]:
        if self.corte is None:
            return {}
        return {
            "simulacion_corte": {
                "despues_del_cuadro": self.corte[0],
                "segundos": self.corte[1],
                "ocurrio": self.corte_ocurrido,
            }
        }

    def _cuadro(
        self, frame_id: int, imagen: np.ndarray | None, origen: str, error: str | None = None
    ) -> Cuadro:
        return Cuadro(frame_id, imagen, self._reloj() * 1000.0, _ahora_utc(), origen, error)

    def cuadros(self) -> Iterator[Cuadro]:
        raise NotImplementedError

    def descripcion(self) -> dict[str, Any]:
        raise NotImplementedError

    def cerrar(self) -> None:
        pass

    def __enter__(self) -> FuenteBase:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cerrar()


class FuenteVideo(FuenteBase):
    source_kind = "video"

    def __init__(self, ruta: Path, ritmo: float, **kw: Any) -> None:
        super().__init__(ritmo, **kw)
        self.ruta = Path(ruta)
        self.source_id = f"video:{self.ruta.name}"
        self._cap = cv2.VideoCapture(str(self.ruta))
        if not self._cap.isOpened():
            raise FuenteError(f"no se pudo abrir el video {self.ruta}")
        self.fps_video = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.cuadros_video = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if self.fps_video <= 0:
            raise FuenteError(f"{self.ruta} no declara sus cuadros por segundo")
        # Si el video tiene menos cuadros por segundo que el ritmo pedido no hay de dónde
        # muestrear: se entregan todos (k = 1) y el ritmo efectivo es el del video.
        self.k = max(1, round(self.fps_video / ritmo))

    def cuadros(self) -> Iterator[Cuadro]:
        entregados = indice = 0
        while True:
            ok, imagen = self._cap.read()
            if not ok:
                return
            indice += 1
            if (indice - 1) % self.k:
                continue
            self._pasos.esperar()
            entregados += 1
            yield self._cuadro(entregados, imagen, f"cuadro {indice} de {self.ruta.name}")
            for _ in range(self._cortar_si_toca(entregados, self.fps_video)):
                if not self._cap.grab():  # lo que la cámara «no vio» durante el corte
                    return
                indice += 1

    def descripcion(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "ruta": str(self.ruta),
            "ritmo_declarado_cuadros_s": self.ritmo,
            "sin_pausa": self.sin_pausa,
            "muestreo": {
                "metodo": "1 de cada k cuadros del video",
                "k": self.k,
                "fps_video": round(self.fps_video, 3),
                "cuadros_video": self.cuadros_video,
                "ritmo_equivalente_cuadros_s": round(self.fps_video / self.k, 3),
            },
            **self._descripcion_corte(),
        }

    def cerrar(self) -> None:
        self._cap.release()


class FuenteCarpeta(FuenteBase):
    source_kind = "carpeta"

    def __init__(self, ruta: Path, ritmo: float, **kw: Any) -> None:
        super().__init__(ritmo, **kw)
        self.ruta = Path(ruta)
        self.source_id = f"carpeta:{self.ruta.name}"
        if not self.ruta.is_dir():
            raise FuenteError(f"{self.ruta} no es una carpeta")
        self.archivos = sorted(
            p for p in self.ruta.iterdir() if p.suffix.lower() in EXTENSIONES_IMAGEN
        )
        if not self.archivos:
            raise FuenteError(f"{self.ruta} no tiene imágenes ({sorted(EXTENSIONES_IMAGEN)})")

    def cuadros(self) -> Iterator[Cuadro]:
        entregados = saltar = 0
        for archivo in self.archivos:
            if saltar:
                saltar -= 1
                continue
            self._pasos.esperar()
            entregados += 1
            imagen = cv2.imread(str(archivo), cv2.IMREAD_COLOR)
            if imagen is None:
                yield self._cuadro(
                    entregados, None, archivo.name, f"imagen ilegible: {archivo.name}"
                )
            else:
                yield self._cuadro(entregados, imagen, archivo.name)
            saltar = self._cortar_si_toca(entregados, self.ritmo)

    def descripcion(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "ruta": str(self.ruta),
            "ritmo_declarado_cuadros_s": self.ritmo,
            "sin_pausa": self.sin_pausa,
            "muestreo": {"metodo": "una imagen por cuadro, en orden alfabético", "k": 1},
            "imagenes": len(self.archivos),
            **self._descripcion_corte(),
        }


class FuenteWebcam(FuenteBase):
    source_kind = "webcam"

    def __init__(self, indice: int, ritmo: float, **kw: Any) -> None:
        super().__init__(ritmo, **kw)
        self.indice = indice
        self.source_id = f"webcam:{indice}"
        self._cap = cv2.VideoCapture(indice)
        if not self._cap.isOpened():
            raise FuenteError(
                f"no se pudo abrir la cámara {indice}. En macOS dale permiso a la terminal "
                "o a VS Code en Configuración del Sistema → Privacidad y seguridad → Cámara"
            )
        self.fps_camara = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)

    def cuadros(self) -> Iterator[Cuadro]:
        entregados = 0
        proximo = self._reloj()
        while True:
            ok, imagen = self._cap.read()
            if not ok:
                raise FuenteError(f"la cámara {self.indice} dejó de entregar cuadros")
            # Se leen todos para vaciar el búfer de la cámara; se entrega uno por intervalo.
            if not self.sin_pausa and self._reloj() < proximo:
                continue
            proximo = self._reloj() + 1.0 / self.ritmo
            entregados += 1
            yield self._cuadro(entregados, imagen, f"webcam {self.indice}")

    def descripcion(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "ritmo_declarado_cuadros_s": self.ritmo,
            "sin_pausa": self.sin_pausa,
            "muestreo": {
                "metodo": "primer cuadro de la cámara tras cada 1/ritmo s",
                "fps_camara": round(self.fps_camara, 3),
            },
        }

    def cerrar(self) -> None:
        self._cap.release()


def abrir_fuente(spec: str, ritmo: float, **kw: Any) -> FuenteBase:
    """`webcam` o `webcam:N` abre la cámara; una carpeta, sus imágenes; si no, un video."""
    if spec == "webcam" or spec.startswith("webcam:"):
        _, _, n = spec.partition(":")
        if n and not n.isdigit():
            raise FuenteError(f"índice de cámara inválido en {spec!r}")
        if kw.get("corte") is not None:
            raise FuenteError("el corte simulado solo aplica a un video o a una carpeta")
        return FuenteWebcam(int(n) if n else 0, ritmo, **kw)
    ruta = Path(spec)
    if ruta.is_dir():
        return FuenteCarpeta(ruta, ritmo, **kw)
    if not ruta.exists():
        raise FuenteError(f"no existe la fuente {spec}")
    return FuenteVideo(ruta, ritmo, **kw)
