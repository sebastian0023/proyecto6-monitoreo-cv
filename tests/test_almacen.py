from __future__ import annotations

import sqlite3

import pytest

from p6.almacen import Almacen, AlmacenError, leer_jsonl
from p6.config import cargar_config
from p6.contrato import CAMPOS_ALERTA, CAMPOS_EVENTO
from p6.fuente import FuenteCarpeta
from p6.monitorear import correr

from .conftest import CONFIG
from .test_contrato import alerta_abierta, evento_error, evento_ok, evento_sin_detecciones
from .test_monitorear import DetectorFalso, carpeta_con


def run_minimo(run_id: str = "c1") -> dict:
    return {
        "run_id": run_id,
        "inicio_utc": "2026-11-12T06:00:00+00:00",
        "fin_utc": None,
        "fuente": {"source_id": "video:normal.mp4"},
        "modelo": {"version": "0.1.1rc0", "sha256": "a" * 64},
        "configuracion": {"sha256": "b" * 64},
        "contrato": {"etapa": "H4"},
    }


def eventos_de_prueba() -> list[dict]:
    ok = evento_ok()
    ok.update(image_ref="capturas/c1-7.jpg", image_sha256="c" * 64, image_reason="muestra")
    sin = evento_sin_detecciones()
    sin.update(event_id="c1-8", frame_id=8, warmup=True)
    err = evento_error()
    err.update(event_id="c1-21", frame_id=21, window_id=2)
    baja = evento_ok()
    baja.update(event_id="c1-22", frame_id=22, window_id=2, frame_score=0.9, zone="baja")
    return [ok, sin, err, baja]


@pytest.fixture
def db(tmp_path):
    with Almacen(tmp_path / "monitoreo.db") as a:
        a.guardar_corrida(run_minimo(), "c1", "version: 1\n")
        a.insertar_eventos(eventos_de_prueba())
        yield a


def test_un_evento_se_lee_igual_que_se_guardo(db):
    for original in eventos_de_prueba():
        leido = db.evento(original["event_id"])
        assert leido == original
        assert list(leido) == [c.nombre for c in CAMPOS_EVENTO]  # mismo orden que el contrato
        assert isinstance(leido["warmup"], bool) and isinstance(leido["detections"], list)


def test_la_exportacion_jsonl_es_igual_a_la_base_de_datos(db, tmp_path):
    n = db.exportar("c1", tmp_path / "c1")
    assert n == {"eventos": 4, "alertas": 0}
    assert leer_jsonl(tmp_path / "c1" / "eventos.jsonl") == db.eventos(run_id="c1")
    assert leer_jsonl(tmp_path / "c1" / "eventos.jsonl") == sorted(
        eventos_de_prueba(), key=lambda e: e["frame_id"]
    )
    assert (tmp_path / "c1" / "alertas.jsonl").read_text() == ""


def test_filtros_y_conteos(db):
    ids = lambda **f: [e["event_id"] for e in db.eventos(**f)]  # noqa: E731
    assert ids(run_id="c1") == ["c1-7", "c1-8", "c1-21", "c1-22"]  # orden por cuadro
    assert ids(status="error") == ["c1-21"]
    assert ids(zone="baja") == ["c1-22"]
    assert ids(zone="ninguna") == ["c1-8", "c1-21"]
    assert ids(window_id=2) == ["c1-21", "c1-22"]
    assert ids(con_captura=True) == ["c1-7"]
    assert ids(con_captura=False) == ["c1-8", "c1-21", "c1-22"]
    assert ids(run_id="otra") == []
    assert db.contar_eventos(window_id=2) == 2
    assert ids(limite=2, desde=1) == ["c1-8", "c1-21"]
    assert db.vecinos(db.evento("c1-8")) == ("c1-7", "c1-21")
    assert db.vecinos(db.evento("c1-7")) == (None, "c1-8")


def test_corridas_y_configuracion(db):
    run = run_minimo()
    run["fin_utc"] = "2026-11-12T06:01:00+00:00"
    db.guardar_corrida(run, "c1", "version: 1\n")  # actualiza al terminar
    (c,) = db.corridas()
    assert (c["run_id"], c["eventos"], c["alertas"], c["fin_utc"]) == ("c1", 4, 0, run["fin_utc"])
    assert db.corrida("c1")["run"]["fin_utc"] == run["fin_utc"]
    assert db.configuracion("b" * 64) == {"texto": "version: 1\n", "corridas": ["c1"]}
    assert db.configuracion("0" * 64) is None
    assert db.corrida("no") is None and db.evento("no") is None


def test_las_alertas_se_guardan_y_se_actualizan(db):
    a = alerta_abierta()
    a["run_id"] = "c1"
    db.guardar_alertas([a])
    assert db.alertas("c1") == [a]
    cerrada = {**a, "status": "cerrada", "closed_at": "2026-11-12T06:21:00+00:00"}
    cerrada["closed_window_id"] = 5
    db.guardar_alertas([cerrada])  # misma alert_id: se reemplaza, no se duplica
    assert db.alertas("c1") == [cerrada] and db.alerta(a["alert_id"]) == cerrada
    assert list(cerrada) == [c.nombre for c in CAMPOS_ALERTA]


def test_borrar_una_corrida_quita_todo_lo_suyo(db):
    db.guardar_alertas([{**alerta_abierta(), "run_id": "c1"}])
    db.borrar_corrida("c1")
    assert not db.existe_corrida("c1") and db.eventos() == [] and db.alertas() == []


def test_solo_lectura_no_escribe(db, tmp_path):
    with Almacen(tmp_path / "monitoreo.db", solo_lectura=True) as ro:
        assert ro.contar_eventos() == 4
        with pytest.raises(sqlite3.OperationalError):
            ro.insertar_eventos([evento_ok()])
    with pytest.raises(AlmacenError, match="no existe"):
        Almacen(tmp_path / "no.db", solo_lectura=True)


def test_un_evento_guardado_por_monitorear_se_lee_igual_desde_db_y_jsonl(tmp_path):
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [90, 0, 255, 40, 87]), 5, sin_pausa=True)
    salida = tmp_path / "res" / "r1"
    correr(fuente, DetectorFalso(), cfg, "r1", salida, imprimir=lambda _: None)
    with Almacen(tmp_path / "res" / "monitoreo.db", solo_lectura=True) as db:
        desde_db = db.eventos(run_id="r1")
        corrida = db.corrida("r1")
    desde_jsonl = leer_jsonl(salida / "eventos.jsonl")
    assert desde_db == desde_jsonl and len(desde_db) == 5
    assert [e["status"] for e in desde_db] == ["ok", "sin_detecciones", "error", "ok", "ok"]
    assert [e["zone"] for e in desde_db] == ["aceptada", None, None, "baja", "duda"]
    # la corrida guarda la configuración exacta y su run.json final
    assert corrida["carpeta"] == "r1" and corrida["config_texto"] == CONFIG.read_text()
    assert corrida["run"]["totales"]["cuadros"] == 5
