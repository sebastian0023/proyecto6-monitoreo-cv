"""Detector real: YOLOX-Nano en ONNX Runtime (CPU) sobre cuadros completos.

Origen: adaptado de `Proyecto5/src/p5/detector_onnx.py` del repositorio
sebastian0023/Proyecto-3-Clasificador-de-imagenes, tag `p5-entrega` (b63ddbc), escrito por
Edith (@edithflor) para el equipo de P5. Se conservan el letterbox, la decodificación de la
rejilla y el NMS. Cambios para P6: el piso de puntuación es configurable (0.10), recibe cuadros
BGR en memoria (video o webcam) en lugar de rutas de archivo, mide `t_pre_ms`, `t_infer_ms` y
`t_post_ms`, y ya no depende del contrato de P5.

Preprocesamiento (letterbox de YOLOX): el cuadro RGB se escala por `r = min(S/H, S/W)` con
Pillow BILINEAR, se pega arriba a la izquierda en un lienzo SxS gris `relleno` y se pasa a BGR,
NCHW, float32 0-255 sin normalizar.

Posprocesamiento: se decodifica la rejilla (strides 8/16/32), `score = objectness x
prob_clase` con la mejor clase por ancla, se descarta lo menor al piso, NMS por clase con
`nms_iou`, cajas `xyxy` en píxeles del cuadro original, recortadas a sus bordes. Las
puntuaciones no se modifican nunca.

Fallos: un cuadro inválido, una salida con forma inesperada o valores no finitos levantan
`DetectorError` (el monitoreo lo registra como `status=error`). Pesos con otro SHA-256 que el
del descriptor levantan `ModeloInvalidoError` al cargar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import yaml
from PIL import Image

from p6.config import Config, ConfigDetector, sha256_archivo

STRIDES = (8, 16, 32)


class DetectorError(RuntimeError):
    """Un cuadro no se pudo procesar; el monitoreo lo registra como `status=error`."""


class ModeloInvalidoError(ValueError):
    """Pesos o descriptor rechazados al cargar el detector."""


class Sesion(Protocol):
    """Lo que se usa de `onnxruntime.InferenceSession` (inyectable en pruebas)."""

    def run(self, output_names: Any, input_feed: dict[str, np.ndarray]) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class Deteccion:
    class_id: int
    class_name: str
    score: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 en píxeles del cuadro

    def como_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "score": round(self.score, 6),
            "bbox": list(self.bbox),
        }


@dataclass
class Resultado:
    """Lo que devuelve el detector por cuadro: detecciones y tiempos por etapa."""

    detecciones: list[Deteccion]
    t_pre_ms: float
    t_infer_ms: float
    t_post_ms: float
    ancho: int = 0
    alto: int = 0

    @property
    def frame_score(self) -> float | None:
        """Puntuación más alta del cuadro; `None` si no hay detecciones."""
        return max((d.score for d in self.detecciones), default=None)


def letterbox(rgb: np.ndarray, tamano: int, relleno: int) -> tuple[np.ndarray, float]:
    """Tensor NCHW BGR float32 y la escala `r` para regresar al cuadro original."""
    alto, ancho = rgb.shape[:2]
    r = min(tamano / alto, tamano / ancho)
    nuevo_ancho, nuevo_alto = int(ancho * r), int(alto * r)
    escalada = Image.fromarray(np.ascontiguousarray(rgb)).resize(
        (nuevo_ancho, nuevo_alto), Image.BILINEAR
    )
    lienzo = np.full((tamano, tamano, 3), relleno, dtype=np.uint8)
    lienzo[:nuevo_alto, :nuevo_ancho] = np.asarray(escalada)
    bgr = lienzo[:, :, ::-1]
    return np.ascontiguousarray(bgr.transpose(2, 0, 1)[None], dtype=np.float32), r


def _rejilla(tamano: int) -> tuple[np.ndarray, np.ndarray]:
    rejillas, strides = [], []
    for stride in STRIDES:
        lado = tamano // stride
        yv, xv = np.meshgrid(np.arange(lado), np.arange(lado), indexing="ij")
        rejillas.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((lado * lado, 1), stride))
    return np.concatenate(rejillas).astype(np.float32), np.concatenate(strides).astype(np.float32)


def nms(cajas: np.ndarray, scores: np.ndarray, iou_max: float) -> list[int]:
    """Índices que sobreviven al NMS, en orden de confianza descendente."""
    orden = scores.argsort()[::-1]
    areas = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
    quedan: list[int] = []
    while orden.size:
        i = int(orden[0])
        quedan.append(i)
        resto = orden[1:]
        x1 = np.maximum(cajas[i, 0], cajas[resto, 0])
        y1 = np.maximum(cajas[i, 1], cajas[resto, 1])
        x2 = np.minimum(cajas[i, 2], cajas[resto, 2])
        y2 = np.minimum(cajas[i, 3], cajas[resto, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou = inter / np.maximum(areas[i] + areas[resto] - inter, 1e-9)
        orden = resto[iou <= iou_max]
    return quedan


def decodificar(
    salida: np.ndarray,
    r: float,
    ancho: int,
    alto: int,
    config: ConfigDetector,
    clases: list[str],
) -> list[Deteccion]:
    """Salida cruda `[1, N, 5 + C]` de YOLOX a detecciones en píxeles del cuadro original."""
    anclas = sum((config.tamano_entrada // s) ** 2 for s in STRIDES)
    esperada = (1, anclas, 5 + len(clases))
    if salida.shape != esperada:
        raise DetectorError(f"salida malformada: forma {salida.shape}, se esperaba {esperada}")
    if not np.isfinite(salida).all():
        raise DetectorError("salida no finita del modelo (NaN o infinito)")
    o = salida[0].astype(np.float64)
    rejilla, strides = _rejilla(config.tamano_entrada)
    centro = (o[:, :2] + rejilla) * strides
    with np.errstate(over="ignore"):
        lados = np.exp(o[:, 2:4]) * strides
    cajas = np.concatenate((centro - lados / 2, centro + lados / 2), axis=1) / r
    por_clase = o[:, 4:5] * o[:, 5:]
    clase = por_clase.argmax(1)
    score = por_clase.max(1)
    sel = score >= config.piso
    cajas, clase, score = cajas[sel], clase[sel], score[sel]
    if not np.isfinite(cajas).all() or not np.isfinite(score).all():
        raise DetectorError("salida no finita al decodificar las cajas")
    cajas[:, [0, 2]] = cajas[:, [0, 2]].clip(0, ancho)
    cajas[:, [1, 3]] = cajas[:, [1, 3]].clip(0, alto)
    detecciones: list[Deteccion] = []
    for c in np.unique(clase):
        idx = np.flatnonzero(clase == c)
        for k in nms(cajas[idx], score[idx], config.nms_iou):
            x1, y1, x2, y2 = (round(float(v), 2) for v in cajas[idx[k]])
            if x1 < x2 and y1 < y2:
                conf = min(max(float(score[idx[k]]), 0.0), 1.0)
                detecciones.append(Deteccion(int(c), clases[int(c)], conf, (x1, y1, x2, y2)))
    detecciones.sort(key=lambda d: d.score, reverse=True)
    return detecciones[: config.max_detecciones]


class DetectorONNX:
    """Detector YOLOX-Nano; `desde_config` verifica el SHA-256 y abre la sesión de CPU."""

    task = "detection"

    def __init__(
        self,
        sesion: Sesion,
        config: ConfigDetector,
        clases: list[str],
        model_sha256: str,
        model_version: str,
        model_name: str = "yolox_nano",
        nombre_entrada: str = "images",
    ) -> None:
        self._sesion = sesion
        self.config = config
        self.clases = clases
        self.model_sha256 = model_sha256
        self.model_version = model_version
        self.model_name = model_name
        self._entrada = nombre_entrada

    @classmethod
    def desde_config(cls, cfg: Config) -> DetectorONNX:
        try:
            descriptor = yaml.safe_load(cfg.descriptor.read_text(encoding="utf-8"))
            esperado, clases = str(descriptor["sha256"]), list(descriptor["clases"])
            version, nombre = str(descriptor["version"]), str(descriptor["nombre"])
        except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
            raise ModeloInvalidoError(f"descriptor {cfg.descriptor}: {exc}") from exc
        if not cfg.modelo.is_file():
            raise ModeloInvalidoError(
                f"no existe {cfg.modelo}; descárgalo con "
                "`python scripts/descargar_modelo.py --destino modelo/`"
            )
        obtenido = sha256_archivo(cfg.modelo)
        if obtenido != esperado:
            raise ModeloInvalidoError(
                f"SHA-256 de {cfg.modelo} es {obtenido}; el descriptor espera {esperado}"
            )
        import onnxruntime as ort  # solo al cargar pesos reales: las pruebas inyectan sesión

        try:
            sesion = ort.InferenceSession(str(cfg.modelo), providers=["CPUExecutionProvider"])
        except Exception as exc:  # ONNX Runtime no expone una jerarquía de errores estable
            raise ModeloInvalidoError(f"onnxruntime no pudo cargar {cfg.modelo}: {exc}") from exc
        entrada = sesion.get_inputs()[0]
        lado = cfg.detector.tamano_entrada
        if list(entrada.shape) != [1, 3, lado, lado]:
            raise ModeloInvalidoError(f"entrada del modelo {entrada.shape}, config pide {lado}")
        return cls(sesion, cfg.detector, clases, obtenido, version, nombre, entrada.name)

    def detectar(self, bgr: np.ndarray) -> Resultado:
        """Detecciones de un cuadro BGR uint8 HxWx3, con el tiempo de cada etapa."""
        if not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise DetectorError("el cuadro debe ser un arreglo HxWx3")
        if bgr.dtype != np.uint8 or bgr.shape[0] == 0 or bgr.shape[1] == 0:
            raise DetectorError("el cuadro debe ser uint8 y no estar vacío")
        alto, ancho = bgr.shape[:2]

        t0 = time.perf_counter()
        tensor, r = letterbox(bgr[:, :, ::-1], self.config.tamano_entrada, self.config.relleno)
        t1 = time.perf_counter()
        try:
            salida = self._sesion.run(None, {self._entrada: tensor})[0]
        except Exception as exc:  # cualquier fallo del runtime es un fallo del detector
            raise DetectorError(f"onnxruntime: {type(exc).__name__}: {exc}") from exc
        t2 = time.perf_counter()
        detecciones = decodificar(np.asarray(salida), r, ancho, alto, self.config, self.clases)
        t3 = time.perf_counter()
        return Resultado(
            detecciones,
            t_pre_ms=(t1 - t0) * 1000,
            t_infer_ms=(t2 - t1) * 1000,
            t_post_ms=(t3 - t2) * 1000,
            ancho=ancho,
            alto=alto,
        )
