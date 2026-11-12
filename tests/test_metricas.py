"""Cada métrica con el ejemplo calculado a mano de docs/metricas.md, y el recálculo."""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest

from p6 import capturas, metricas
from p6.almacen import Almacen
from p6.config import cargar_config
from p6.fuente import FuenteCarpeta
from p6.metricas import (
    INSUFICIENTE,
    SIN_DATOS,
    calcular,
    diferencias,
    g1_latencia,
    g2_cuadros_por_s,
    g3_ram,
    g4_baja_confianza,
    g5_trazabilidad,
    g6_version,
    g7_alertas_corrida,
    g7_alertas_ventana,
    percentil,
)
from p6.monitorear import correr

from .conftest import CONFIG
from .test_contrato import alerta_abierta, evento_ok
from .test_monitorear import DetectorFalso, carpeta_con

SHA = "a" * 64


def ev(frame: int, **cambios) -> dict:
    """Evento válido (H4) del cuadro `frame`, en la ventana que le toca."""
    e = evento_ok()
    e.update(
        event_id=f"r-{frame}",
        run_id="r",
        frame_id=frame,
        window_id=(frame - 1) // 20 + 1,
        warmup=False,
        model_sha256=SHA,
    )
    e.update(cambios)
    return e


def sin_det(frame: int, **cambios) -> dict:
    return ev(
        frame, status="sin_detecciones", detections=[], frame_score=None, zone=None, **cambios
    )


def error(frame: int, **cambios) -> dict:
    return ev(
        frame,
        status="error",
        error_msg="falla",
        detections=[],
        frame_score=None,
        zone=None,
        t_pre_ms=None,
        t_infer_ms=None,
        t_post_ms=None,
        **cambios,
    )


def test_percentil_por_rango_mas_cercano():
    assert percentil([6, 7, 8, 9, 40], 50) == 8 and percentil([6, 7, 8, 9, 40], 95) == 40
    assert percentil([5], 95) == 5 and percentil([], 50) is None


def test_g1_ejemplo_del_documento():
    # x = t_infer + t_post = 6, 7, 8, 9, 40 ms -> p50 8, p95 40
    evs = [ev(i + 10, t_infer_ms=x - 0.5, t_post_ms=0.5) for i, x in enumerate([6, 7, 8, 9, 40])]
    evs += [ev(1, warmup=True, t_infer_ms=500.0), error(2)]  # excluidos
    r = g1_latencia(evs)
    assert (r["estado"], r["p50"], r["p95"], r["n"]) == ("ok", 8.0, 40.0, 5)
    assert r["excluidos"] == {"warmup": 1, "error": 1}
    assert (r["event_id_desde"], r["event_id_hasta"], r["window_ids"]) == ("r-10", "r-14", [1])
    # t_pre_ms no cuenta
    assert g1_latencia([ev(9, t_pre_ms=99.0, t_infer_ms=7.0, t_post_ms=1.0)])["p50"] == 8.0
    vacio = g1_latencia([ev(1, warmup=True), error(2)])
    assert vacio["estado"] == SIN_DATOS and vacio["p50"] is None and vacio["n"] == 0


def test_g2_ejemplo_del_documento():
    evs = [ev(i + 1, t_mono_ms=t) for i, t in enumerate([0.0, 200.0, 400.0, 600.0, 800.0])]
    r = g2_cuadros_por_s(evs)
    assert (r["estado"], r["valor"], r["intervalo_s"], r["n"]) == ("ok", 5.0, 0.8, 5)
    # un cuadro con error no cuenta como procesado
    r = g2_cuadros_por_s([*evs, error(6, t_mono_ms=1000.0)])
    assert r["valor"] == 5.0 and r["excluidos"] == {"error": 1}
    # sin_detecciones sí completó la inferencia
    assert g2_cuadros_por_s([ev(1, t_mono_ms=0.0), sin_det(2, t_mono_ms=500.0)])["valor"] == 2.0
    assert g2_cuadros_por_s([ev(1)])["estado"] == SIN_DATOS  # n < 2
    assert g2_cuadros_por_s([])["valor"] is None


def test_g3_ejemplo_del_documento():
    evs = [ev(1, rss_mb=200.0), ev(2, rss_mb=210.5), error(3, rss_mb=209.8)]
    r = g3_ram(evs)
    assert (r["max"], r["ultimo"], r["event_id_max"], r["n"]) == (210.5, 209.8, "r-2", 3)
    assert g3_ram([])["estado"] == SIN_DATOS


def test_g4_ejemplo_del_documento():
    evs = [ev(i, zone="baja", frame_score=0.5) for i in range(1, 7)]  # 6 bajas
    evs += [ev(i) for i in range(7, 17)]  # 10 aceptadas
    evs += [sin_det(i) for i in range(17, 21)]  # 4 sin detecciones
    r = g4_baja_confianza(evs)
    assert (r["estado"], r["valor"], r["baja"], r["con_detecciones"]) == ("ok", 0.375, 6, 16)
    assert r["excluidos"] == {"sin_detecciones": 4, "error": 0}
    pocos = g4_baja_confianza([ev(i, zone="baja", frame_score=0.5) for i in range(1, 9)])
    assert (pocos["estado"], pocos["valor"], pocos["baja"]) == (INSUFICIENTE, None, 8)  # no 0
    assert g4_baja_confianza([])["estado"] == SIN_DATOS
    assert g4_baja_confianza([sin_det(i) for i in range(1, 21)])["estado"] == INSUFICIENTE


def test_g5_ejemplo_del_documento(tmp_path):
    evs = [ev(i) for i in range(1, 11)]
    evs[3]["origen"] = None  # le falta un campo obligatorio
    ref, sha = capturas.guardar(tmp_path, "r-5", np.zeros((8, 8, 3), np.uint8))
    evs[4].update(image_ref=ref, image_sha256=sha, image_reason="baja")  # captura verificada
    evs[6].update(
        image_ref="capturas/r-7.jpg", image_sha256="b" * 64, image_reason="baja"
    )  # no existe
    r = g5_trazabilidad(evs, tmp_path)
    assert (r["valor"], r["cumplen"], r["total"]) == (0.8, 8, 10)
    assert [x["event_id"] for x in r["incumplen"]] == ["r-4", "r-7"]
    assert r["incumplen"][0]["motivos"] == ["origen: no puede ser null"]
    assert r["incumplen"][1]["motivos"] == ["captura: no_existe"]
    assert g5_trazabilidad([], tmp_path)["estado"] == SIN_DATOS


def test_g6_ejemplo_del_documento():
    evs = [ev(i) for i in range(1, 10)] + [ev(10, model_sha256="c" * 64, model_version="otra")]
    r = g6_version(evs, SHA)
    assert (r["valor"], r["coinciden"], r["total"]) == (0.9, 9, 10)
    assert r["versiones"] == [
        {"model_version": "0.1.1rc0", "model_sha256": SHA, "eventos": 9},
        {"model_version": "otra", "model_sha256": "c" * 64, "eventos": 1},
    ]
    assert g6_version([], SHA)["estado"] == SIN_DATOS


def test_g7_ejemplo_del_documento():
    a = {**alerta_abierta(), "alert_id": "A", "opened_window_id": 2, "closed_window_id": 5}
    b = {**alerta_abierta(), "alert_id": "B", "opened_window_id": 4, "closed_window_id": None}
    r = g7_alertas_corrida([a, b], [1, 2, 3, 4, 5, 6])
    assert r["serie"] == [0, 1, 1, 2, 1, 1]
    assert (r["max_simultaneas"], r["abiertas_al_final"]) == (2, 1)
    assert g7_alertas_ventana([a, b], 4)["alert_ids"] == ["A", "B"]
    assert g7_alertas_ventana([a, b], 5)["alert_ids"] == ["B"]  # A ya cerró en la 5
    # 0 es un valor válido, no "sin datos"
    cero = g7_alertas_corrida([], [1, 2])
    assert (cero["estado"], cero["serie"], cero["abiertas_al_final"]) == ("ok", [0, 0], 0)


def test_documento_por_corrida_y_por_ventana_con_trazabilidad(tmp_path):
    evs = [ev(i) for i in range(1, 26)]  # ventana 1 completa y 5 cuadros de la 2
    doc = calcular("r", evs, [], tmp_path, SHA)
    c = doc["corrida"]
    assert (c["cuadros"], c["window_ids"], c["event_id_desde"], c["event_id_hasta"]) == (
        25,
        [1, 2],
        "r-1",
        "r-25",
    )
    assert [v["window_id"] for v in doc["ventanas"]] == [1, 2]
    v2 = doc["ventanas"][1]
    assert (v2["cuadros"], v2["event_id_desde"], v2["event_id_hasta"]) == (5, "r-21", "r-25")
    assert v2["G4"]["estado"] == INSUFICIENTE  # 5 < 10 con detecciones
    for alcance in [c, *doc["ventanas"]]:
        for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
            assert {"metrica", "estado", "window_ids"} <= set(alcance[g]), g


def test_diferencias():
    assert (
        diferencias({"a": 1.0, "calculado_utc": "x"}, {"a": 1.0 + 1e-12, "calculado_utc": "y"})
        == []
    )
    assert diferencias({"a": [1, 2]}, {"a": [1, 3]}) == ["a.1: 2 ≠ 3"]
    assert diferencias({"a": None}, {"a": 0}) == ["a: None ≠ 0"]
    assert diferencias({"a": 1}, {}) == ["a: solo en uno de los dos"]


@pytest.fixture
def corrida(tmp_path):
    """Corrida real de monitorear (detector simulado) con métricas guardadas."""
    cfg = cargar_config(CONFIG)
    valores = [40] * 12 + [95] * 8 + [0] * 3 + [95] * 7  # ventana 1 abre A; ventana 2 parcial
    fuente = FuenteCarpeta(carpeta_con(tmp_path, valores), 5, sin_pausa=True)
    salida = tmp_path / "res" / "m1"
    _, t = correr(fuente, DetectorFalso(), cfg, "m1", salida, imprimir=lambda _: None)
    return tmp_path / "res" / "monitoreo.db", salida, t


def test_monitorear_guarda_las_metricas_en_la_base_y_en_json(corrida):
    db_ruta, salida, t = corrida
    guardado = json.loads((salida / "metricas.json").read_text())
    with Almacen(db_ruta, solo_lectura=True) as db:
        assert db.metricas("m1") == guardado
    c = guardado["corrida"]
    assert c["G4"]["valor"] == 0.4444 and (c["G4"]["baja"], c["G4"]["con_detecciones"]) == (12, 27)
    assert (
        c["G5"]["valor"] == 1.0 and c["G6"]["valor"] == 0.0
    )  # el detector simulado no es el del descriptor
    assert c["G7"]["serie"] == [1, 1] and c["G1"]["excluidos"]["warmup"] == 5
    assert guardado["ventanas"][1]["G4"]["estado"] == INSUFICIENTE  # 7 con detecciones
    assert t.metricas["corrida"] == c


def test_recalcular_coincide_y_detecta_cambios(corrida, capsys):
    db_ruta, salida, _ = corrida
    assert metricas.main(["--db", str(db_ruta), "--run-id", "m1", "--recalcular"]) == 0
    assert "resultado: todo coincide" in capsys.readouterr().out
    # se altera un dato primario: el recálculo ya no coincide con lo guardado
    con = sqlite3.connect(db_ruta)
    con.execute("UPDATE eventos SET rss_mb = 999.0 WHERE event_id = 'm1-7'")
    con.commit()
    con.close()
    informe = salida / "recalculo.txt"
    codigo = metricas.main(
        ["--db", str(db_ruta), "--run-id", "m1", "--recalcular", "--salida", str(informe)]
    )
    texto = informe.read_text()
    assert codigo == 1 and "G3: NO coincide" in texto and "G1: coincide" in texto
    assert "corrida.G3.max: " in texto and "999.0" in texto


def test_calcular_y_guardar_desde_la_cli(corrida, capsys):
    db_ruta, salida, _ = corrida
    (salida / "metricas.json").unlink()
    assert metricas.main(["--db", str(db_ruta), "--run-id", "m1"]) == 0
    assert (salida / "metricas.json").exists()
    assert "G4 proporción de baja confianza: 0.4444" in capsys.readouterr().out
    assert metricas.main(["--db", str(db_ruta), "--run-id", "nada"]) == 2
