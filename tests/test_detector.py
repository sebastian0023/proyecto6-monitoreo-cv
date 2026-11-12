from __future__ import annotations

import math

import cv2
import numpy as np
import pytest
import yaml

from p6.config import ConfigDetector, cargar_config
from p6.detector import (
    DetectorError,
    DetectorONNX,
    ModeloInvalidoError,
    decodificar,
    letterbox,
    nms,
)

from .conftest import CONFIG, DESCRIPTOR, PESOS, VIDEO_NORMAL, requiere_modelo

CFG = ConfigDetector(tamano_entrada=416, relleno=114, piso=0.10, nms_iou=0.45, max_detecciones=100)
ANCLAS = 52**2 + 26**2 + 13**2  # 3549
CUP = 41


def salida_vacia(clases: list[str]) -> np.ndarray:
    s = np.zeros((1, ANCLAS, 5 + len(clases)), dtype=np.float32)
    s[:, :, 4] = -0.0  # objectness 0: ninguna ancla supera el piso
    return s


def poner(s: np.ndarray, ancla: int, obj: float, clase: int, prob: float, lado: float = 4.0):
    """Ancla con centro en el centro de su celda y lados `lado` * stride."""
    s[0, ancla, :2] = 0.5
    s[0, ancla, 2:4] = math.log(lado)
    s[0, ancla, 4] = obj
    s[0, ancla, 5 + clase] = prob


def test_decodifica_una_caja_conocida(clases):
    # Ancla de stride 8 en la celda (x=10, y=20): centro (10.5*8, 20.5*8) = (84, 164),
    # lados 4*8 = 32 -> caja (68, 148, 100, 180). Puntuación 0.9 * 0.8 = 0.72.
    s = salida_vacia(clases)
    poner(s, 20 * 52 + 10, obj=0.9, clase=CUP, prob=0.8)
    (d,) = decodificar(s, 1.0, 416, 416, CFG, clases)
    assert (d.class_id, d.class_name) == (CUP, "cup")
    assert d.score == pytest.approx(0.72)
    assert d.bbox == (68.0, 148.0, 100.0, 180.0)


def test_la_caja_vuelve_a_pixeles_del_cuadro_original(clases):
    # Una imagen de 832x832 se reduce a la mitad (r = 0.5): la caja se duplica.
    s = salida_vacia(clases)
    poner(s, 20 * 52 + 10, obj=0.9, clase=CUP, prob=0.8)
    (d,) = decodificar(s, 0.5, 832, 832, CFG, clases)
    assert d.bbox == (136.0, 296.0, 200.0, 360.0)


def test_el_piso_decide_que_se_entrega_y_no_altera_puntuaciones(clases):
    s = salida_vacia(clases)
    poner(s, 100, obj=0.5, clase=0, prob=0.22)  # 0.11: sobre el piso
    poner(s, 300, obj=0.5, clase=0, prob=0.18)  # 0.09: bajo el piso de 0.10
    poner(s, 500, obj=0.5, clase=0, prob=0.5)  # 0.25
    bajo = decodificar(s, 1.0, 416, 416, CFG, clases)
    assert sorted(round(d.score, 2) for d in bajo) == [0.11, 0.25]  # 0.09 queda fuera
    sin_piso = ConfigDetector(416, 114, 0.01, 0.45, 100)
    todas = decodificar(s, 1.0, 416, 416, sin_piso, clases)
    assert sorted(round(d.score, 2) for d in todas) == [0.09, 0.11, 0.25]


def test_nms_une_cajas_que_se_solapan_en_la_misma_clase(clases):
    s = salida_vacia(clases)
    poner(s, 20 * 52 + 10, obj=0.9, clase=CUP, prob=0.8)
    poner(s, 20 * 52 + 11, obj=0.8, clase=CUP, prob=0.8)  # vecina, casi la misma caja
    assert len(decodificar(s, 1.0, 416, 416, CFG, clases)) == 1
    otra = salida_vacia(clases)
    poner(otra, 20 * 52 + 10, obj=0.9, clase=CUP, prob=0.8)
    poner(otra, 20 * 52 + 11, obj=0.8, clase=56, prob=0.8)  # misma zona, otra clase
    assert len(decodificar(otra, 1.0, 416, 416, CFG, clases)) == 2


def test_nms_directo():
    cajas = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=float)
    assert nms(cajas, np.array([0.9, 0.8, 0.7]), 0.45) == [0, 2]


def test_salida_malformada_o_no_finita_es_error(clases):
    with pytest.raises(DetectorError, match="malformada"):
        decodificar(np.zeros((1, 10, 85), dtype=np.float32), 1.0, 416, 416, CFG, clases)
    s = salida_vacia(clases)
    s[0, 0, 0] = np.nan
    with pytest.raises(DetectorError, match="no finita"):
        decodificar(s, 1.0, 416, 416, CFG, clases)


def test_letterbox_forma_orden_de_canales_y_relleno():
    rgb = np.zeros((480, 640, 3), dtype=np.uint8)
    rgb[:, :] = (255, 0, 0)  # rojo en RGB
    tensor, r = letterbox(rgb, 416, 114)
    assert tensor.shape == (1, 3, 416, 416) and tensor.dtype == np.float32
    assert r == pytest.approx(416 / 640)
    assert tensor[0, :, 10, 10].tolist() == [0.0, 0.0, 255.0]  # BGR: B=0, G=0, R=255
    assert tensor[0, :, 400, 10].tolist() == [114.0, 114.0, 114.0]  # relleno abajo (alto 312)


class SesionFalsa:
    def __init__(self, salida: np.ndarray) -> None:
        self.salida = salida

    def run(self, nombres, entrada):
        assert entrada["images"].shape == (1, 3, 416, 416)
        return [self.salida]


def detector_falso(salida: np.ndarray, clases: list[str]) -> DetectorONNX:
    return DetectorONNX(SesionFalsa(salida), CFG, clases, "a" * 64, "0.1.1rc0")


def test_detectar_mide_los_tiempos_y_calcula_el_frame_score(clases):
    s = salida_vacia(clases)
    poner(s, 100, obj=0.9, clase=0, prob=0.9)  # 0.81
    poner(s, 2000, obj=0.5, clase=CUP, prob=0.6)  # 0.30
    res = detector_falso(s, clases).detectar(np.zeros((480, 640, 3), dtype=np.uint8))
    assert res.frame_score == pytest.approx(0.81)
    assert all(t >= 0 for t in (res.t_pre_ms, res.t_infer_ms, res.t_post_ms))
    assert (res.ancho, res.alto) == (640, 480)


def test_un_cuadro_sin_detecciones_no_tiene_frame_score(clases):
    res = detector_falso(salida_vacia(clases), clases).detectar(np.zeros((48, 64, 3), np.uint8))
    assert res.detecciones == [] and res.frame_score is None


@pytest.mark.parametrize(
    "cuadro",
    [
        np.zeros((10, 10), np.uint8),
        np.zeros((10, 10, 3), np.float32),
        np.zeros((0, 10, 3), np.uint8),
    ],
)
def test_un_cuadro_invalido_es_error(clases, cuadro):
    with pytest.raises(DetectorError):
        detector_falso(salida_vacia(clases), clases).detectar(cuadro)


def test_pesos_con_otro_sha256_se_rechazan(tmp_path):
    pesos = tmp_path / "pesos.onnx"
    pesos.write_bytes(b"no son los pesos")
    base = cargar_config(CONFIG)
    cfg = cargar_config(CONFIG, modelo=pesos)
    assert cfg.modelo != base.modelo
    with pytest.raises(ModeloInvalidoError, match="SHA-256"):
        DetectorONNX.desde_config(cfg)


def test_pesos_inexistentes_dicen_como_descargarlos(tmp_path):
    cfg = cargar_config(CONFIG, modelo=tmp_path / "no_existe.onnx")
    with pytest.raises(ModeloInvalidoError, match="descargar_modelo"):
        DetectorONNX.desde_config(cfg)


@requiere_modelo
def test_modelo_real_detecta_a_la_persona_de_un_cuadro_conocido():
    if not VIDEO_NORMAL.is_file():
        pytest.skip("falta datos/videos/normal.mp4")
    cap = cv2.VideoCapture(str(VIDEO_NORMAL))
    ok, cuadro = cap.read()
    cap.release()
    assert ok
    det = DetectorONNX.desde_config(cargar_config(CONFIG))
    esperado = yaml.safe_load(DESCRIPTOR.read_text(encoding="utf-8"))["sha256"]
    assert det.model_sha256 == esperado and PESOS.is_file()
    res = det.detectar(cuadro)
    mejor = res.detecciones[0]
    assert mejor.class_name == "person" and mejor.score > 0.5
    x1, y1, x2, y2 = mejor.bbox
    assert 0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 480
    assert all(0.10 <= d.score <= 1 for d in res.detecciones)  # nada bajo el piso
