from __future__ import annotations

import copy
from typing import Any

import pytest

from p6.contrato import (
    CAMPOS_ALERTA,
    CAMPOS_EVENTO,
    ETAPAS,
    ValidadorEventos,
    validar_alerta,
    validar_evento,
)

SHA = "a" * 64
CFG = "b" * 64


def evento_ok() -> dict[str, Any]:
    """Evento completo (hasta H4) de un cuadro con una detección."""
    return {
        "event_id": "c1-7",
        "run_id": "c1",
        "frame_id": 7,
        "source_id": "video:normal.mp4",
        "source_kind": "video",
        "origen": "cuadro 19 de normal.mp4",
        "t_capture_utc": "2026-11-12T06:10:00.123+00:00",
        "t_mono_ms": 1200.5,
        "task": "detection",
        "model_version": "0.1.1rc0",
        "model_sha256": SHA,
        "config_sha256": CFG,
        "status": "ok",
        "error_msg": None,
        "detections": [
            {"class_id": 0, "class_name": "person", "score": 0.9, "bbox": [1.0, 2.0, 30.0, 40.0]},
            {"class_id": 56, "class_name": "chair", "score": 0.4, "bbox": [5.0, 6.0, 9.0, 9.5]},
        ],
        "frame_score": 0.9,
        "zone": "aceptada",
        "window_id": 1,
        "t_pre_ms": 1.0,
        "t_infer_ms": 7.0,
        "t_post_ms": 0.5,
        "rss_mb": 210.4,
        "warmup": False,
        "image_ref": None,
        "image_sha256": None,
        "image_reason": None,
    }


def evento_sin_detecciones() -> dict[str, Any]:
    e = evento_ok()
    e.update(status="sin_detecciones", detections=[], frame_score=None, zone=None)
    return e


def evento_error() -> dict[str, Any]:
    e = evento_sin_detecciones()
    e.update(
        status="error",
        error_msg="imagen ilegible",
        t_pre_ms=None,
        t_infer_ms=None,
        t_post_ms=None,
    )
    return e


@pytest.mark.parametrize("etapa", ETAPAS)
@pytest.mark.parametrize("fabrica", [evento_ok, evento_sin_detecciones, evento_error])
def test_los_tres_estados_validos_cumplen_todas_las_etapas(fabrica, etapa):
    assert validar_evento(fabrica(), etapa) == []


def test_una_captura_vinculada_cumple_h4():
    e = evento_ok()
    for motivo in ("baja", "ventana_alerta", "muestra"):
        e.update(image_ref="capturas/c1-7.jpg", image_sha256="c" * 64, image_reason=motivo)
        assert validar_evento(e, "H4") == []


def test_cada_campo_obligatorio_es_necesario():
    for campo in CAMPOS_EVENTO:
        e = evento_ok()
        del e[campo.nombre]
        assert validar_evento(e, campo.desde) == [f"{campo.nombre}: falta"], campo.nombre
    for campo in CAMPOS_ALERTA:
        a = alerta_abierta()
        del a[campo.nombre]
        assert validar_alerta(a) == [f"{campo.nombre}: falta"], campo.nombre


def test_los_campos_de_una_etapa_posterior_no_se_exigen_antes():
    e = evento_ok()
    for campo in ("zone", "window_id", "image_ref", "image_sha256"):
        del e[campo]
    assert validar_evento(e, "H1") == []
    assert {p.split(":")[0] for p in validar_evento(e, "H3")} == {"zone", "window_id"}
    assert len(validar_evento(e, "H4")) == 4


def test_un_valor_null_solo_se_acepta_donde_el_contrato_lo_permite():
    e = evento_ok()
    e["run_id"] = None
    assert validar_evento(e) == ["run_id: no puede ser null"]


@pytest.mark.parametrize(
    ("cambio", "esperado"),
    [
        ({"frame_id": "7"}, "frame_id: debe ser de tipo entero"),
        ({"frame_id": True}, "frame_id: debe ser de tipo entero"),
        ({"t_mono_ms": float("nan")}, "t_mono_ms: debe ser de tipo numero"),
        ({"t_capture_utc": "ayer"}, "t_capture_utc: debe ser de tipo fecha"),
        ({"warmup": 0}, "warmup: debe ser de tipo booleano"),
        ({"detections": "ninguna"}, "detections: debe ser de tipo lista"),
        ({"status": "casi"}, "status: debe ser uno de"),
        ({"source_kind": "radio"}, "source_kind: debe ser uno de"),
        ({"task": "classification"}, "task: debe ser 'detection'"),
        ({"event_id": "otro-7"}, "event_id: debe ser <run_id>-<frame_id>"),
        ({"frame_id": 0, "event_id": "c1-0"}, "frame_id: debe ser ≥ 1"),
        ({"model_sha256": "abc"}, "model_sha256: debe ser SHA-256"),
        ({"config_sha256": "A" * 64}, "config_sha256: debe ser SHA-256"),
        ({"error_msg": "algo"}, "error_msg: debe ser null salvo"),
        ({"frame_score": None}, "frame_score: obligatorio cuando hay detecciones"),
        ({"frame_score": 0.5}, "frame_score: debe ser la puntuación más alta"),
        ({"t_infer_ms": None}, "t_infer_ms: solo puede ser null con status 'error'"),
        ({"t_post_ms": -0.1}, "t_post_ms: no puede ser negativo"),
        ({"rss_mb": 0}, "rss_mb: debe ser positivo"),
        ({"detections": []}, "detections: 'ok' exige al menos una detección"),
    ],
)
def test_cada_regla_rechaza_su_caso(cambio, esperado):
    e = evento_ok()
    e.update(cambio)
    problemas = validar_evento(e)
    assert any(p.startswith(esperado) for p in problemas), problemas


def test_las_detecciones_se_validan_una_por_una():
    e = evento_ok()
    e["detections"][1]["score"] = 1.5
    e["detections"][0]["bbox"] = [1, 2, 3]
    e["detections"].append("no soy un objeto")
    problemas = validar_evento(e)
    assert "detections[1].score: debe estar en [0, 1]" in problemas
    assert "detections[0].bbox: debe ser una lista de 4 números" in problemas
    assert "detections[2]: no es un objeto" in problemas


def test_error_y_sin_detecciones_tienen_sus_propias_reglas():
    e = evento_error()
    e["error_msg"] = None
    assert "error_msg: obligatorio cuando status es 'error'" in validar_evento(e)
    e = evento_error()
    e["detections"] = evento_ok()["detections"]
    assert any("debe estar vacía" in p for p in validar_evento(e))
    e = evento_sin_detecciones()
    e["frame_score"] = 0.3
    assert "frame_score: debe ser null sin detecciones" in validar_evento(e)


def test_reglas_de_la_politica_h3():
    e = evento_ok()
    e["zone"] = "rara"
    assert any(p.startswith("zone: debe ser uno de") for p in validar_evento(e, "H3"))
    e["zone"] = None
    assert "zone: obligatoria cuando hay frame_score" in validar_evento(e, "H3")
    s = evento_sin_detecciones()
    s["zone"] = "baja"
    assert "zone: debe ser null cuando frame_score es null" in validar_evento(s, "H3")
    e = evento_ok()
    e["window_id"] = 0
    assert "window_id: debe ser ≥ 1" in validar_evento(e, "H3")


JUNTOS = "image_ref, image_sha256 e image_reason: deben ir juntos o ser los tres null"


def test_reglas_de_la_captura_h4():
    e = evento_ok()
    e["image_ref"] = "capturas/x.jpg"
    assert JUNTOS in validar_evento(e, "H4")
    e["image_sha256"] = "c" * 64
    assert JUNTOS in validar_evento(e, "H4")  # falta el motivo
    e["image_reason"] = "porque si"
    assert any(p.startswith("image_reason: debe ser uno de") for p in validar_evento(e, "H4"))
    e.update(image_reason="baja", image_sha256="xyz")
    assert "image_sha256: debe ser SHA-256 en hexadecimal minúscula" in validar_evento(e, "H4")
    for ruta in ("../fuera.jpg", "/etc/passwd", "capturas/../../x.jpg"):
        e.update(image_sha256="c" * 64, image_ref=ruta)
        assert "image_ref: debe ser una ruta relativa sin '..'" in validar_evento(e, "H4"), ruta


def test_lo_que_no_es_un_objeto_se_rechaza():
    assert validar_evento(None) == ["el registro no es un objeto"]
    assert validar_evento([1, 2]) == ["el registro no es un objeto"]
    assert validar_alerta("alerta") == ["el registro no es un objeto"]


def test_etapa_desconocida_es_un_error_de_programa():
    with pytest.raises(ValueError, match="etapa"):
        validar_evento(evento_ok(), "H9")
    with pytest.raises(ValueError, match="etapa"):
        ValidadorEventos("H0")


def test_el_validador_cuenta_aceptados_rechazados_y_motivos():
    v = ValidadorEventos("H1")
    malo1, malo2 = evento_ok(), evento_ok()
    del malo1["origen"]
    malo2.update(status="casi", frame_id="x")
    assert v.revisar(evento_ok()) == []
    assert v.revisar(evento_error()) == []
    assert v.revisar(malo1) == ["origen: falta"]
    assert v.revisar(malo2)
    assert (v.aceptados, v.rechazados) == (2, 2)
    assert v.motivos["origen"] == 1 and v.motivos["status"] == 1 and v.motivos["frame_id"] >= 1


def alerta_abierta() -> dict[str, Any]:
    return {
        "alert_id": "c2-A-1",
        "rule_id": "A",
        "run_id": "c2",
        "status": "abierta",
        "opened_at": "2026-11-12T06:20:00+00:00",
        "opened_window_id": 2,
        "closed_at": None,
        "closed_window_id": None,
        "severity": "warning",
        "reason": "proporción baja 0.85 ≥ 0.50 en la ventana 2 (17 de 20 cuadros)",
        "window_ids": [2],
        "event_ids": ["c2-21", "c2-22"],
        "config_sha256": CFG,
        "suggested_action": "Revisar la captura, la iluminación y el enfoque",
    }


def test_alertas_abierta_y_cerrada_cumplen_el_contrato():
    assert validar_alerta(alerta_abierta()) == []
    cerrada = copy.deepcopy(alerta_abierta())
    cerrada.update(status="cerrada", closed_at="2026-11-12T06:21:00+00:00", closed_window_id=5)
    cerrada["window_ids"] = [2, 3, 4]
    assert validar_alerta(cerrada) == []


@pytest.mark.parametrize(
    ("cambio", "esperado"),
    [
        ({"severity": "grave"}, "severity: debe ser uno de"),
        ({"status": "pendiente"}, "status: debe ser uno de"),
        (
            {"closed_at": "2026-11-12T06:21:00+00:00"},
            "closed_at y closed_window_id: deben ser null",
        ),
        ({"status": "cerrada"}, "closed_at y closed_window_id: obligatorios"),
        ({"window_ids": []}, "window_ids: debe ser una lista no vacía"),
        ({"window_ids": [3]}, "opened_window_id: debe estar entre window_ids"),
        ({"event_ids": []}, "event_ids: debe ser una lista no vacía"),
        ({"reason": ""}, "reason: debe ser de tipo texto"),
        ({"config_sha256": "no"}, "config_sha256: debe ser SHA-256"),
    ],
)
def test_cada_regla_de_alerta_rechaza_su_caso(cambio, esperado):
    a = alerta_abierta()
    a.update(cambio)
    problemas = validar_alerta(a)
    assert any(p.startswith(esperado) for p in problemas), problemas
