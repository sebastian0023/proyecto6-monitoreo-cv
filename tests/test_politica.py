from __future__ import annotations

import pytest

from p6.config import ConfigError, cargar_config
from p6.politica import INSUFICIENTE, resumir_ventanas, window_id, zona

from .conftest import CONFIG


@pytest.mark.parametrize(
    ("score", "esperada"),
    [
        (0.99, "aceptada"),
        (0.90, "aceptada"),  # igualdad con el superior: aceptada
        (0.8999, "duda"),
        (0.85, "duda"),  # igualdad con el inferior: duda
        (0.8499, "baja"),
        (0.10, "baja"),
        (None, None),  # sin puntuación: sin zona, no es baja
    ],
)
def test_zonas_e_igualdades(score, esperada):
    assert zona(score, 0.85, 0.90) == esperada


def test_ventana_de_cada_cuadro():
    assert [window_id(i, 20) for i in (1, 20, 21, 40, 41)] == [1, 1, 2, 2, 3]


def evento(frame_id, status="ok", zone="aceptada", tamano=20):
    return {
        "event_id": f"r-{frame_id}",
        "frame_id": frame_id,
        "status": status,
        "zone": None if status != "ok" else zone,
        "window_id": window_id(frame_id, tamano),
    }


def test_resumen_de_ventanas_con_suficiente_e_insuficiente():
    # ventana 1: 20 cuadros, 12 ok (4 baja, 3 duda, 5 aceptada) y 8 sin detecciones
    v1 = [
        evento(i, zone=z) for i, z in enumerate(["baja"] * 4 + ["duda"] * 3 + ["aceptada"] * 5, 1)
    ]
    v1 += [evento(i, status="sin_detecciones") for i in range(13, 21)]
    # ventana 2: 20 cuadros pero solo 9 con detecciones -> insuficiente aunque 9 sean bajas
    v2 = [evento(i, zone="baja") for i in range(21, 30)]
    v2 += [evento(i, status="sin_detecciones") for i in range(30, 40)]
    v2 += [evento(40, status="error")]
    # ventana 3 parcial: 5 cuadros
    v3 = [evento(i) for i in range(41, 46)]
    r1, r2, r3 = resumir_ventanas(v1 + v2 + v3, tamano=20, minimo=10)

    assert (r1["window_id"], r1["cuadros"], r1["completa"], r1["suficiente"]) == (1, 20, True, True)
    assert (r1["con_detecciones"], r1["sin_detecciones"]) == (12, 8)
    assert (r1["baja"], r1["duda"], r1["aceptada"]) == (4, 3, 5)
    assert r1["proporcion_baja"] == pytest.approx(4 / 12, abs=1e-4)  # denominador: con detecciones
    assert (r1["event_id_desde"], r1["event_id_hasta"]) == ("r-1", "r-20")

    assert r2["suficiente"] is False and r2["proporcion_baja"] == INSUFICIENTE
    assert (r2["con_detecciones"], r2["baja"], r2["error"]) == (9, 9, 1)  # no es "100 % baja"

    assert r3["completa"] is False and r3["proporcion_baja"] == INSUFICIENTE


def test_el_resumen_ordena_por_ventana_y_acepta_eventos_desordenados():
    evs = [evento(25), evento(3), evento(1)]
    assert [r["window_id"] for r in resumir_ventanas(evs, 20, 1)] == [1, 2]
    assert resumir_ventanas(evs, 20, 1)[0]["event_id_desde"] == "r-1"


def test_la_configuracion_congelada_cumple_las_restricciones():
    c = cargar_config(CONFIG)
    assert c.detector.piso < c.confianza.umbral_inferior < c.confianza.umbral_superior <= 1
    assert c.confianza.minimo_con_detecciones <= c.confianza.ventana_cuadros
    assert c.referencia.p_ref + c.regla_b.margen_sobre_referencia < 1
    assert c.regla_a.severidad == "warning" and c.regla_b.severidad == "critical"
    assert c.referencia.video.name == "referencia.mp4"


@pytest.mark.parametrize(
    ("original", "cambio"),
    [
        ("umbral_inferior: 0.85", "umbral_inferior: 0.05"),  # no supera el piso
        ("umbral_inferior: 0.85", "umbral_inferior: 0.95"),  # pasa al superior
        ("umbral_superior: 0.90", "umbral_superior: 1.5"),
        ("minimo_con_detecciones: 10", "minimo_con_detecciones: 25"),
        ("ventana_cuadros: 20", "ventana_cuadros: 0"),
        ("proporcion_minima: 0.50", "proporcion_minima: 0"),
        ("ventanas_seguidas: 3", "ventanas_seguidas: 1"),
        ("margen_sobre_referencia: 0.20", "margen_sobre_referencia: 0.99"),
        ("severidad: warning", "severidad: grave"),
        ("video_sha256: ", "video_sha256: x"),
        ("p_ref: 0.0204", "p_ref: 1.5"),
    ],
)
def test_la_configuracion_rechaza_valores_invalidos(tmp_path, original, cambio):
    texto = CONFIG.read_text(encoding="utf-8")
    assert original in texto
    ruta = tmp_path / "c.yaml"
    ruta.write_text(texto.replace(original, cambio, 1), encoding="utf-8")
    with pytest.raises(ConfigError):
        cargar_config(ruta)


def test_la_configuracion_exige_las_secciones_nuevas(tmp_path):
    ruta = tmp_path / "c.yaml"
    ruta.write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="falta la sección confianza"):
        cargar_config(ruta)
