"""Extra #14: corte simulado de la fuente y regla F (interrupción y recuperación)."""

from __future__ import annotations

import pytest

from p6.alertas import DetectorInterrupciones, umbral_sin_cuadros_s
from p6.almacen import Almacen, leer_jsonl
from p6.config import cargar_config
from p6.contrato import validar_alerta
from p6.fuente import FuenteCarpeta, FuenteError, FuenteVideo, abrir_fuente
from p6.monitorear import correr, main

from .conftest import CONFIG
from .test_fuente import RelojFalso, escribir_imagen, hacer_video
from .test_monitorear import DetectorFalso, carpeta_con

CFG = cargar_config(CONFIG)


def carpeta_de(tmp_path, n):
    c = tmp_path / "fotos"
    c.mkdir()
    for i in range(n):
        escribir_imagen(c / f"{i:03d}.png", 10 + i)
    return c


def test_el_corte_en_una_carpeta_pierde_lo_que_no_llego_y_sigue_al_ritmo(tmp_path):
    reloj = RelojFalso()
    fuente = FuenteCarpeta(
        carpeta_de(tmp_path, 20), 5, reloj=reloj, dormir=reloj.dormir, corte=(3, 2.0)
    )
    cuadros = list(fuente.cuadros())
    # 2 s a 5 imágenes/s = 10 imágenes que no se entregan: 3 + (20 - 3 - 10) = 10 cuadros
    assert [c.frame_id for c in cuadros] == list(range(1, 11))
    assert [c.origen for c in cuadros[2:4]] == ["002.png", "013.png"]
    t = [c.t_mono_ms for c in cuadros]
    assert t[3] - t[2] == pytest.approx(2200)  # 2 s de corte + el intervalo normal
    assert t[4] - t[3] == pytest.approx(200)  # después sigue al ritmo, sin ponerse al día
    assert 2.0 in reloj.pausas
    d = fuente.descripcion()["simulacion_corte"]
    assert (d["despues_del_cuadro"], d["segundos"]) == (3, 2.0)
    assert d["ocurrio"]["elementos_omitidos"] == 10
    assert d["ocurrio"]["t_mono_fin_ms"] - d["ocurrio"]["t_mono_inicio_ms"] == pytest.approx(2000)


def test_el_corte_en_un_video_salta_los_cuadros_del_lapso(tmp_path):
    ruta = tmp_path / "v.mp4"
    hacer_video(ruta, cuadros=30, fps=15)
    reloj = RelojFalso()
    with FuenteVideo(
        ruta, 5, sin_pausa=True, reloj=reloj, dormir=reloj.dormir, corte=(2, 1.0)
    ) as fuente:
        cuadros = list(fuente.cuadros())
        d = fuente.descripcion()["simulacion_corte"]
    # cuadros 1 y 4 del video; 1 s a 15 fps = 15 cuadros omitidos; sigue en el 22
    assert [c.origen for c in cuadros[:3]] == [
        "cuadro 1 de v.mp4",
        "cuadro 4 de v.mp4",
        "cuadro 22 de v.mp4",
    ]
    assert len(cuadros) == 5 and reloj.pausas == [1.0]  # 1, 4, 22, 25, 28
    assert d["ocurrio"]["elementos_omitidos"] == 15


def test_corte_invalido_o_en_webcam():
    with pytest.raises(ValueError, match="corte"):
        FuenteCarpeta(".", 5, corte=(0, 1.0))
    with pytest.raises(FuenteError, match="video o a una carpeta"):
        abrir_fuente("webcam:0", 5, corte=(3, 1.0))


def evento(frame, t_mono_ms, w=1):
    return {
        "event_id": f"r-{frame}",
        "frame_id": frame,
        "window_id": w,
        "origen": f"cuadro {frame}",
        "t_mono_ms": t_mono_ms,
        "t_capture_utc": f"2026-11-12T06:00:{frame:02d}.000+00:00",
    }


def test_el_detector_de_huecos():
    det = DetectorInterrupciones(CFG, "r", ritmo=5)
    assert umbral_sin_cuadros_s(5) == 1.0 and det.umbral_s == 1.0
    assert det(evento(1, 0.0)) is None
    assert det(evento(2, 200.0)) is None
    assert det(evento(3, 1199.0)) is None  # 0.999 s: no supera el umbral
    a = det(evento(4, 3400.0, w=2))  # 2.2 s sin cuadros
    assert a is not None and validar_alerta(a) == []
    assert (a["alert_id"], a["rule_id"], a["severity"], a["status"]) == (
        "r-F-1",
        "F",
        "critical",
        "cerrada",
    )
    assert a["event_ids"] == ["r-3", "r-4"] and a["window_ids"] == [1, 2]
    assert (a["opened_window_id"], a["closed_window_id"]) == (1, 2)
    assert a["opened_at"] == "2026-11-12T06:00:04.000+00:00"  # cuadro 3 + 1 s de umbral
    assert a["closed_at"] == "2026-11-12T06:00:04.000+00:00"  # el cuadro 4, la recuperación
    assert "durante 2.20 s" in a["reason"] and "se recuperó con r-4" in a["reason"]
    assert a["config_sha256"] == CFG.sha256
    assert det(evento(5, 3600.0, w=2)) is None


def test_monitorear_registra_la_interrupcion_y_su_recuperacion(tmp_path):
    reloj = RelojFalso()
    fuente = FuenteCarpeta(
        carpeta_con(tmp_path, [95] * 30), 5, reloj=reloj, dormir=reloj.dormir, corte=(12, 3.0)
    )
    salida = tmp_path / "res" / "corte"
    lineas: list[str] = []
    run, t = correr(fuente, DetectorFalso(), CFG, "corte", salida, imprimir=lineas.append)
    # 3 s a 5 imágenes/s = 15 imágenes perdidas: 12 + 3 = 15 cuadros
    assert t.cuadros == 15
    (alerta,) = leer_jsonl(salida / "alertas.jsonl")
    assert alerta["rule_id"] == "F" and alerta["event_ids"] == ["corte-12", "corte-13"]
    assert "durante 3.20 s" in alerta["reason"]
    assert any("ALERTA corte-F-1" in x for x in lineas)
    assert run["fuente"]["simulacion_corte"]["ocurrio"]["elementos_omitidos"] == 15
    assert run["politica"]["regla_F"]["umbral_s"] == 1.0
    assert run["totales"]["alertas_detalle"]["corte-F-1"]["status"] == "cerrada"
    with Almacen(tmp_path / "res" / "monitoreo.db", solo_lectura=True) as db:
        assert db.alerta("corte-F-1") == alerta
    # la caída de ritmo se ve en G2 de la ventana del corte (cuadros 1 a 15, una sola ventana)
    g2 = t.metricas["ventanas"][0]["G2"]
    assert g2["valor"] == pytest.approx(14 / (14 * 0.2 + 3.0), abs=1e-3)


def test_sin_huecos_no_hay_alerta_f(tmp_path):
    reloj = RelojFalso()
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [95] * 8), 5, reloj=reloj, dormir=reloj.dormir)
    salida = tmp_path / "res" / "sin"
    correr(fuente, DetectorFalso(), CFG, "sin", salida, imprimir=lambda _: None)
    assert leer_jsonl(salida / "alertas.jsonl") == []


def test_la_cli_valida_el_corte(tmp_path):
    base = ["--fuente", str(tmp_path), "--salida", str(tmp_path / "res")]
    assert main([*base, "--simular-corte", "x"]) == 2
    assert main([*base, "--simular-corte", "0:5"]) == 2
