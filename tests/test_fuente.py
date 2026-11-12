from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from p6.fuente import FuenteCarpeta, FuenteError, FuenteVideo, abrir_fuente


class RelojFalso:
    def __init__(self) -> None:
        self.t = 100.0
        self.pausas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.pausas.append(s)
        self.t += s


def escribir_imagen(ruta: Path, valor: int) -> None:
    assert cv2.imwrite(str(ruta), np.full((48, 64, 3), valor, dtype=np.uint8))


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    for nombre, valor in (("b.png", 20), ("a.png", 10), ("c.png", 30)):
        escribir_imagen(tmp_path / nombre, valor)
    (tmp_path / "notas.txt").write_text("no es imagen")
    return tmp_path


def test_la_carpeta_se_lee_en_orden_alfabetico_y_ignora_lo_que_no_es_imagen(carpeta):
    fuente = FuenteCarpeta(carpeta, ritmo=5, sin_pausa=True)
    cuadros = list(fuente.cuadros())
    assert [c.origen for c in cuadros] == ["a.png", "b.png", "c.png"]
    assert [c.frame_id for c in cuadros] == [1, 2, 3]
    assert [int(c.imagen[0, 0, 0]) for c in cuadros] == [10, 20, 30]
    assert cuadros[0].imagen.shape == (48, 64, 3)
    assert all(c.error is None for c in cuadros)
    d = fuente.descripcion()
    assert d["source_id"] == f"carpeta:{carpeta.name}" and d["imagenes"] == 3


def test_una_imagen_ilegible_se_entrega_como_error_y_la_lectura_sigue(carpeta):
    (carpeta / "b.png").write_bytes(b"esto no es un png")
    cuadros = list(FuenteCarpeta(carpeta, ritmo=5, sin_pausa=True).cuadros())
    assert len(cuadros) == 3
    assert cuadros[1].imagen is None and "ilegible" in cuadros[1].error
    assert cuadros[2].imagen is not None


def test_carpeta_vacia_o_inexistente(tmp_path):
    with pytest.raises(FuenteError, match="no tiene imágenes"):
        FuenteCarpeta(tmp_path, ritmo=5)
    with pytest.raises(FuenteError):
        abrir_fuente(str(tmp_path / "no_existe"), ritmo=5)


def test_el_ritmo_declarado_espacia_las_entregas(carpeta):
    reloj = RelojFalso()
    fuente = FuenteCarpeta(carpeta, ritmo=5, reloj=reloj, dormir=reloj.dormir)
    cuadros = list(fuente.cuadros())
    t = [c.t_mono_ms for c in cuadros]
    assert t[1] - t[0] == pytest.approx(200) and t[2] - t[1] == pytest.approx(200)
    assert reloj.pausas == [pytest.approx(0.2), pytest.approx(0.2)]


def test_el_procesamiento_lento_no_acumula_retraso(carpeta):
    # Si cada cuadro tarda 150 ms de procesamiento, solo se espera lo que falta hasta los 200.
    reloj = RelojFalso()
    fuente = FuenteCarpeta(carpeta, ritmo=5, reloj=reloj, dormir=reloj.dormir)
    for _ in fuente.cuadros():
        reloj.t += 0.15
    assert reloj.pausas == [pytest.approx(0.05), pytest.approx(0.05)]


def test_sin_pausa_no_espera(carpeta):
    reloj = RelojFalso()
    list(
        FuenteCarpeta(carpeta, ritmo=5, sin_pausa=True, reloj=reloj, dormir=reloj.dormir).cuadros()
    )
    assert reloj.pausas == []


def hacer_video(ruta: Path, cuadros: int, fps: float) -> None:
    """Video de cuadros planos: el cuadro i vale 8*i (distinguibles pese a la compresión)."""
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for i in range(cuadros):
        w.write(np.full((48, 64, 3), 8 * i, dtype=np.uint8))
    w.release()


def test_el_video_se_muestrea_1_de_cada_k(tmp_path):
    ruta = tmp_path / "v.mp4"
    hacer_video(ruta, cuadros=30, fps=15)
    with FuenteVideo(ruta, ritmo=5, sin_pausa=True) as fuente:
        assert fuente.k == 3
        cuadros = list(fuente.cuadros())
        d = fuente.descripcion()
    assert len(cuadros) == 10
    assert [c.frame_id for c in cuadros] == list(range(1, 11))
    valores = [int(c.imagen.mean()) for c in cuadros]
    assert all(abs(v - 8 * 3 * i) <= 6 for i, v in enumerate(valores))  # cuadros 0, 3, 6, ...
    assert cuadros[0].origen == "cuadro 1 de v.mp4" and cuadros[1].origen == "cuadro 4 de v.mp4"
    assert d["ritmo_declarado_cuadros_s"] == 5
    assert d["muestreo"]["k"] == 3 and d["muestreo"]["fps_video"] == 15
    assert d["muestreo"]["ritmo_equivalente_cuadros_s"] == 5


def test_un_video_mas_lento_que_el_ritmo_entrega_todos_los_cuadros(tmp_path):
    ruta = tmp_path / "lento.mp4"
    hacer_video(ruta, cuadros=6, fps=2)
    with FuenteVideo(ruta, ritmo=5, sin_pausa=True) as fuente:
        assert fuente.k == 1
        assert len(list(fuente.cuadros())) == 6


def test_fuentes_invalidas(tmp_path):
    corrupto = tmp_path / "x.mp4"
    corrupto.write_bytes(b"no es un video")
    with pytest.raises(FuenteError):
        abrir_fuente(str(corrupto), ritmo=5)
    with pytest.raises(FuenteError, match="índice de cámara"):
        abrir_fuente("webcam:uno", ritmo=5)
    with pytest.raises(ValueError, match="ritmo"):
        FuenteCarpeta(tmp_path, ritmo=0)
