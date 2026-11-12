"""Reglas A y B con secuencias sintéticas de ventanas, la referencia real y el portal."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from p6 import portal
from p6.alertas import EvaluadorReglas
from p6.almacen import Almacen, leer_jsonl
from p6.config import cargar_config
from p6.contrato import validar_alerta
from p6.fuente import FuenteCarpeta
from p6.monitorear import correr
from p6.politica import resumir_ventanas

from .conftest import CONFIG, RAIZ
from .test_monitorear import DetectorFalso, carpeta_con

CFG = cargar_config(CONFIG)


def ventana(w: int, baja: int, con: int = 20, cuadros: int = 20):
    """Resumen y eventos de la ventana `w`: `con` cuadros con detecciones, de ellos `baja`
    en zona baja; el resto de los `cuadros` sin detecciones."""
    eventos = []
    for i in range(cuadros):
        frame = (w - 1) * 20 + i + 1
        if i < con:
            zona, status = ("baja" if i < baja else "aceptada"), "ok"
        else:
            zona, status = None, "sin_detecciones"
        eventos.append(
            {
                "event_id": f"r-{frame}",
                "frame_id": frame,
                "status": status,
                "zone": zona,
                "window_id": w,
                "t_capture_utc": f"2026-11-12T06:{frame // 60:02d}:{frame % 60:02d}.000+00:00",
            }
        )
    (resumen,) = resumir_ventanas(eventos, 20, 10)
    return resumen, eventos


def correr_secuencia(proporciones: list):
    """Cada elemento es la cantidad de cuadros bajos de 20, o "insuf" (5 con detecciones)."""
    ev = EvaluadorReglas(CFG, "r")
    cambios = []
    for w, x in enumerate(proporciones, start=1):
        if x == "insuf":
            cambios.append(ev(*ventana(w, baja=5, con=5)))
        else:
            cambios.append(ev(*ventana(w, baja=x)))
    return ev, cambios


def finales(ev: EvaluadorReglas) -> dict:
    """Estado final de cada alerta por id (la última versión publicada)."""
    return {a["alert_id"]: a for a in (ev._publica(x) for x in ev.todas)}


def test_la_configuracion_de_las_reglas():
    ev = EvaluadorReglas(CFG, "r")
    assert CFG.regla_a.proporcion_minima == 0.50 and ev.limite_b == 0.2204
    assert ev.cumple_a(0.50) and not ev.cumple_a(0.4999)  # A: ≥
    assert ev.cumple_b(0.25) and not ev.cumple_b(0.2204) and not ev.cumple_b(0.20)  # B: >


def test_a_se_dispara_en_la_primera_ventana_suficiente_que_cumple():
    ev, cambios = correr_secuencia([2, 10, 12])  # 0.10, 0.50, 0.60
    assert cambios[0] == []
    (a,) = cambios[1]
    assert (a["alert_id"], a["rule_id"], a["status"]) == ("r-A-1", "A", "abierta")
    assert a["opened_window_id"] == 2 and a["window_ids"] == [2]
    assert a["severity"] == "warning" and a["suggested_action"] == CFG.regla_a.accion_sugerida
    assert a["config_sha256"] == CFG.sha256
    assert a["event_ids"] == [f"r-{i}" for i in range(21, 31)]  # los 10 cuadros bajos
    assert "0.50 ≥ 0.50 en la ventana 2" in a["reason"] and "10 de 20" in a["reason"]
    assert a["opened_at"] == "2026-11-12T06:00:40.000+00:00"  # último cuadro de la ventana
    assert validar_alerta(a) == []
    # la ventana 3 sigue cumpliendo: misma alerta extendida, no una nueva
    (a3,) = [x for x in cambios[2] if x["rule_id"] == "A"]
    assert a3["alert_id"] == "r-A-1" and a3["window_ids"] == [2, 3]
    assert "sigue en las ventanas 3 (proporciones 0.60)" in a3["reason"]


def test_a_se_cierra_en_la_primera_ventana_suficiente_que_no_cumple_y_reabre_otra():
    ev, cambios = correr_secuencia([12, 12, 3, 14])
    a = finales(ev)
    assert a["r-A-1"]["status"] == "cerrada" and a["r-A-1"]["window_ids"] == [1, 2]
    assert (a["r-A-1"]["closed_window_id"], a["r-A-1"]["closed_at"][:19]) == (
        3,
        "2026-11-12T06:01:00",
    )
    assert "se cerró en la ventana 3: proporción 0.15 < 0.5" in a["r-A-1"]["reason"]
    assert a["r-A-2"]["status"] == "abierta" and a["r-A-2"]["opened_window_id"] == 4
    assert all(validar_alerta(x) == [] for x in a.values())


def test_las_ventanas_insuficientes_no_abren_ni_cierran_a():
    # una ventana insuficiente con 5 de 5 bajos (100 %) no abre A
    ev, cambios = correr_secuencia(["insuf", 2])
    assert cambios == [[], []]
    # con A abierta, una insuficiente no la cierra ni la extiende
    ev, cambios = correr_secuencia([12, "insuf", 12, 2])
    assert cambios[1] == []
    a = finales(ev)["r-A-1"]
    assert a["window_ids"] == [1, 3] and a["closed_window_id"] == 4


def test_b_necesita_tres_ventanas_seguidas():
    # dos ventanas sobre el límite y luego una debajo: la racha se rompe, B no se abre
    ev, _ = correr_secuencia([6, 6, 2, 6, 6])
    assert [x["rule_id"] for x in ev.todas] == []
    # tres seguidas: se abre en la tercera con las tres ventanas
    ev, cambios = correr_secuencia([6, 6, 6])  # 0.30 > 0.2204, sin llegar a A
    assert cambios[0] == [] and cambios[1] == []
    (b,) = cambios[2]
    assert (b["alert_id"], b["severity"], b["opened_window_id"]) == ("r-B-1", "critical", 3)
    assert b["window_ids"] == [1, 2, 3] and len(b["event_ids"]) == 18
    assert "> 0.2204 (p_ref 0.0204 + margen 0.20) en 3 ventanas" in b["reason"]
    assert "(1–3: 0.30, 0.30, 0.30)" in b["reason"]
    assert validar_alerta(b) == []


def test_el_limite_de_b_es_estricto():
    ev, _ = correr_secuencia([4, 4, 4, 4])  # 0.20 no supera 0.2204
    assert ev.todas == []
    ev, _ = correr_secuencia([5, 5, 5])  # 0.25 sí
    assert [x["alert_id"] for x in ev.todas] == ["r-B-1"]


def test_las_ventanas_insuficientes_no_suman_ni_rompen_la_racha_de_b():
    ev, cambios = correr_secuencia([6, "insuf", 6, "insuf", 6])
    assert cambios[1] == [] and cambios[2] == [] and cambios[3] == []
    (b,) = cambios[4]
    assert b["window_ids"] == [1, 3, 5] and b["opened_window_id"] == 5


def test_b_se_cierra_y_un_episodio_continuo_es_una_sola_alerta():
    ev, _ = correr_secuencia([6, 6, 6, 6, 6, 2, 6])
    b = finales(ev)
    assert list(b) == ["r-B-1"]  # la última ventana empieza una racha nueva, de 1
    assert b["r-B-1"]["window_ids"] == [1, 2, 3, 4, 5] and b["r-B-1"]["closed_window_id"] == 6
    assert "proporción 0.10 ≤ 0.2204" in b["r-B-1"]["reason"]


def test_un_episodio_intenso_abre_a_y_b_por_separado():
    ev, cambios = correr_secuencia([15, 15, 15])
    assert [x["alert_id"] for x in cambios[0]] == ["r-A-1"]
    assert [x["alert_id"] for x in cambios[2]] == ["r-A-1", "r-B-1"]


def test_la_referencia_real_no_dispara_alertas():
    eventos = leer_jsonl(RAIZ / "evidencias" / "referencia" / "eventos.jsonl")
    ev = EvaluadorReglas(CFG, "ref-01")
    for resumen in resumir_ventanas(eventos, 20, 10):
        de_la_ventana = [e for e in eventos if e["window_id"] == resumen["window_id"]]
        assert ev(resumen, de_la_ventana) == []
    assert ev.todas == []


def test_monitorear_guarda_las_alertas_reales_y_captura_la_ventana_que_abre(tmp_path):
    # ventanas 1 y 2 normales (0.95), 3 a 5 con 12 de 20 cuadros bajos (0.40), 6 normal
    valores = [95] * 40
    for _ in range(3):
        valores += [40] * 12 + [95] * 8
    valores += [95] * 20
    fuente = FuenteCarpeta(carpeta_con(tmp_path, valores), 5, sin_pausa=True)
    salida = tmp_path / "res" / "r7"
    lineas: list[str] = []
    run, _ = correr(fuente, DetectorFalso(), CFG, "r7", salida, imprimir=lineas.append)

    alertas = {a["alert_id"]: a for a in leer_jsonl(salida / "alertas.jsonl")}
    assert set(alertas) == {"r7-A-1", "r7-B-1"}
    a, b = alertas["r7-A-1"], alertas["r7-B-1"]
    assert (a["opened_window_id"], a["window_ids"], a["closed_window_id"]) == (3, [3, 4, 5], 6)
    assert (b["opened_window_id"], b["window_ids"], b["closed_window_id"]) == (5, [3, 4, 5], 6)
    assert a["status"] == b["status"] == "cerrada" and len(a["event_ids"]) == 36
    assert all(validar_alerta(x) == [] for x in alertas.values())
    assert any("ALERTA r7-A-1 abierta" in x for x in lineas)
    assert any("ALERTA r7-B-1 cerrada en la ventana 6" in x for x in lineas)
    # los cuadros no bajos de las ventanas que abrieron (3 y 5) se capturan por ventana_alerta
    motivos = {e["frame_id"]: e["image_reason"] for e in leer_jsonl(salida / "eventos.jsonl")}
    assert [motivos[i] for i in range(53, 61)] == ["ventana_alerta"] * 8  # ventana 3
    assert [motivos[i] for i in range(93, 101)] == ["ventana_alerta"] * 8  # ventana 5
    assert motivos[73] is None  # ventana 4 no abrió nada
    assert run["totales"]["alertas"] == 2
    assert run["totales"]["alertas_detalle"]["r7-B-1"]["status"] == "cerrada"
    assert run["politica"]["regla_B"]["limite"] == 0.2204
    with Almacen(tmp_path / "res" / "monitoreo.db", solo_lectura=True) as db:
        assert {x["alert_id"] for x in db.alertas("r7")} == {"r7-A-1", "r7-B-1"}
        assert db.alertas(status="cerrada", rule_id="B")[0]["alert_id"] == "r7-B-1"


@pytest.fixture
def cliente(tmp_path):
    valores = [40] * 12 + [95] * 8 + [95] * 5  # ventana 1 abre A; ventana 2 parcial
    fuente = FuenteCarpeta(carpeta_con(tmp_path, valores), 5, sin_pausa=True)
    correr(fuente, DetectorFalso(), CFG, "pa", tmp_path / "res" / "pa", imprimir=lambda _: None)
    return TestClient(portal.crear_app(tmp_path / "res" / "monitoreo.db"))


def test_portal_de_la_alerta_a_los_cuadros_que_la_causaron(cliente):
    lista = cliente.get("/alertas")
    assert lista.status_code == 200 and 'href="/alertas/pa-A-1"' in lista.text
    assert "warning" in lista.text and "abierta" in lista.text and "0.60 ≥ 0.50" in lista.text
    detalle = cliente.get("/alertas/pa-A-1").text
    for i in range(1, 13):  # los 12 cuadros bajos, con enlace y captura
        assert f'href="/eventos/pa-{i}"' in detalle and f'src="/capturas/pa-{i}"' in detalle
    assert "/eventos?run_id=pa&ventana=1" in detalle
    assert f"/configuracion/{CFG.sha256}" in detalle and "Acción sugerida" in detalle
    assert cliente.get("/capturas/pa-3").status_code == 200
    # el evento enlaza de vuelta a su alerta, y la corrida la lista
    assert 'href="/alertas/pa-A-1"' in cliente.get("/eventos/pa-3").text
    assert 'href="/alertas/pa-A-1"' in cliente.get("/corridas/pa").text


def test_portal_filtros_y_api_de_alertas(cliente):
    assert "pa-A-1" in cliente.get("/alertas?status=abierta&regla=A&run_id=pa").text
    assert "pa-A-1" not in cliente.get("/alertas?status=cerrada").text
    assert "pa-A-1" not in cliente.get("/alertas?regla=B").text
    assert cliente.get("/alertas?status=rara").status_code == 400
    assert cliente.get("/alertas?regla=C").status_code == 400
    assert cliente.get("/alertas/nada").status_code == 404
    api = cliente.get("/api/alertas?run_id=pa").json()
    assert api["total"] == 1 and api["alertas"][0]["event_ids"][0] == "pa-1"
    assert cliente.get("/api/alertas/pa-A-1").json()["alerta"]["rule_id"] == "A"
