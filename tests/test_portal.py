from __future__ import annotations

import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from p6 import portal
from p6.almacen import Almacen
from p6.config import cargar_config
from p6.fuente import FuenteCarpeta
from p6.monitorear import correr

from .conftest import CONFIG
from .test_monitorear import DetectorFalso, carpeta_con


@pytest.fixture
def entorno(tmp_path):
    """Corrida `p1` de 5 cuadros: 1 aceptado (muestra), 2 sin detecciones, 3 error,
    4 baja (capturado), 5 duda (sin captura)."""
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [90, 0, 255, 40, 87]), 5, sin_pausa=True)
    salida = tmp_path / "res" / "p1"
    correr(fuente, DetectorFalso(), cfg, "p1", salida, imprimir=lambda _: None)
    cliente = TestClient(portal.crear_app(tmp_path / "res" / "monitoreo.db"))
    return cliente, salida, cfg


def test_de_un_evento_se_llega_a_su_imagen_y_a_su_configuracion(entorno):
    cliente, salida, cfg = entorno
    lista = cliente.get("/eventos")
    assert lista.status_code == 200
    assert "/eventos/p1-4" in lista.text  # la lista enlaza al detalle

    detalle = cliente.get("/eventos/p1-4")
    assert detalle.status_code == 200
    assert "SHA-256 verificado" in detalle.text and "baja" in detalle.text
    assert 'href="/capturas/p1-4"' in detalle.text
    assert f'href="/configuracion/{cfg.sha256}"' in detalle.text

    imagen = cliente.get("/capturas/p1-4")
    assert imagen.status_code == 200 and imagen.headers["content-type"] == "image/jpeg"
    assert imagen.content == (salida / "capturas" / "p1-4.jpg").read_bytes()

    conf = cliente.get(f"/configuracion/{cfg.sha256}")
    assert conf.status_code == 200 and "SHA-256 verificado" in conf.text
    assert "umbral_inferior: 0.85" in conf.text and "/corridas/p1" in conf.text
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest() == cfg.sha256


def test_un_evento_sin_captura_lo_dice(entorno):
    cliente, _, _ = entorno
    detalle = cliente.get("/eventos/p1-5")
    assert "no tiene captura" in detalle.text and "/capturas/p1-5" not in detalle.text
    r = cliente.get("/capturas/p1-5")
    assert r.status_code == 404 and "no tiene captura" in r.json()["error"]
    assert "sin detecciones" in cliente.get("/eventos/p1-2").text.lower()
    assert "fallo simulado" in cliente.get("/eventos/p1-3").text


def test_una_captura_borrada_se_muestra_como_rota(entorno):
    cliente, salida, _ = entorno
    (salida / "capturas" / "p1-4.jpg").unlink()
    detalle = cliente.get("/eventos/p1-4")
    assert "rota: el archivo no existe" in detalle.text
    assert "SHA-256 verificado" not in detalle.text and "<image" not in detalle.text
    assert cliente.get("/capturas/p1-4").status_code == 409
    fila = re.search(r"p1-4</a>.*?</tr>", cliente.get("/eventos").text, re.S).group(0)
    assert "rota" in fila


def test_una_captura_alterada_no_se_muestra_como_valida(entorno):
    cliente, salida, _ = entorno
    (salida / "capturas" / "p1-4.jpg").write_bytes(b"no es la imagen original")
    detalle = cliente.get("/eventos/p1-4")
    assert "rota: el SHA-256 no coincide" in detalle.text and "<image" not in detalle.text
    assert cliente.get("/capturas/p1-4").status_code == 409


def test_filtros_de_la_lista(entorno):
    cliente, _, _ = entorno
    enlaces = lambda url: re.findall(r'href="/eventos/(p1-\d+)"', cliente.get(url).text)  # noqa: E731
    assert enlaces("/eventos?run_id=p1") == ["p1-1", "p1-2", "p1-3", "p1-4", "p1-5"]
    assert enlaces("/eventos?zone=baja") == ["p1-4"]
    assert enlaces("/eventos?zone=ninguna") == ["p1-2", "p1-3"]
    assert enlaces("/eventos?status=error") == ["p1-3"]
    assert enlaces("/eventos?captura=si") == ["p1-1", "p1-4"]
    assert enlaces("/eventos?ventana=1&zone=duda") == ["p1-5"]
    assert enlaces("/eventos?run_id=otra") == []
    for malo in (
        "status=raro",
        "zone=media",
        "ventana=0",
        "ventana=x",
        "captura=quizas",
        "pagina=0",
    ):
        assert cliente.get(f"/eventos?{malo}").status_code == 400, malo


def test_paginacion(entorno, monkeypatch):
    cliente, _, _ = entorno
    monkeypatch.setattr(portal, "POR_PAGINA", 2)
    p2 = cliente.get("/eventos?run_id=p1&pagina=2").text
    assert re.findall(r'href="/eventos/(p1-\d+)"', p2) == ["p1-3", "p1-4"]
    assert "página 2 de 3" in p2 and "pagina=1" in p2 and "pagina=3" in p2


def test_corridas_y_api(entorno):
    cliente, salida, cfg = entorno
    assert "/corridas/p1" in cliente.get("/corridas").text
    corrida = cliente.get("/corridas/p1").text
    assert cfg.sha256 in corrida and "Ventanas" in corrida
    api = cliente.get("/api/eventos/p1-4").json()
    assert api["captura"] == "ok"
    with Almacen(salida.parent / "monitoreo.db", solo_lectura=True) as db:
        assert api["evento"] == db.evento("p1-4")
    lista = cliente.get("/api/eventos?zone=baja").json()
    assert lista["total"] == 1 and lista["eventos"][0]["event_id"] == "p1-4"


def test_lo_que_no_existe_da_404(entorno):
    cliente, _, _ = entorno
    for url in ("/eventos/nada", "/capturas/nada", "/corridas/nada", "/configuracion/" + "0" * 64):
        assert cliente.get(url).status_code == 404, url
    assert cliente.get("/", follow_redirects=False).headers["location"] == "/eventos"


def test_sin_base_de_datos_responde_503(tmp_path):
    cliente = TestClient(portal.crear_app(tmp_path / "no.db"))
    assert cliente.get("/eventos").status_code == 503


def _csv(respuesta):
    import csv
    import io

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    texto = respuesta.content.decode("utf-8")
    assert texto.startswith("﻿")  # BOM para Excel
    return list(csv.DictReader(io.StringIO(texto[1:])))


def test_csv_exporta_los_eventos_filtrados_igual_que_la_base(entorno):
    cliente, salida, _ = entorno
    filas = _csv(cliente.get("/eventos.csv?run_id=p1"))
    with Almacen(salida.parent / "monitoreo.db", solo_lectura=True) as db:
        eventos = db.eventos(run_id="p1")
    assert [f["event_id"] for f in filas] == [e["event_id"] for e in eventos]
    for f, e in zip(filas, eventos, strict=True):
        assert f["status"] == e["status"] and f["zone"] == (e["zone"] or "")
        assert f["frame_score"] == ("" if e["frame_score"] is None else str(e["frame_score"]))
        assert json.loads(f["detections"]) == e["detections"]
        assert f["n_detecciones"] == str(len(e["detections"]))
        assert f["image_sha256"] == (e["image_sha256"] or "")
        assert f["config_sha256"] == e["config_sha256"]
    assert [f["captura"] for f in filas] == [
        "ok",
        "sin_captura",
        "sin_captura",
        "ok",
        "sin_captura",
    ]
    assert filas[0]["mejor_clase"] == "person" and filas[1]["mejor_clase"] == ""


def test_csv_respeta_los_filtros_y_el_caso_sin_resultados(entorno):
    cliente, salida, _ = entorno
    r = cliente.get("/eventos.csv?run_id=p1&zone=baja")
    assert [f["event_id"] for f in _csv(r)] == ["p1-4"]
    assert r.headers["x-total-eventos"] == "1"
    assert 'filename="eventos_p1_zona-baja.csv"' in r.headers["content-disposition"]
    vacio = cliente.get("/eventos.csv?run_id=otra")
    assert _csv(vacio) == [] and vacio.headers["x-total-eventos"] == "0"
    assert vacio.content.decode("utf-8").strip("﻿").startswith("event_id,run_id,frame_id")
    assert cliente.get("/eventos.csv?zone=rara").status_code == 400
    # la lista ofrece la descarga con los mismos filtros
    assert (
        'href="/eventos.csv?run_id=p1&amp;zone=baja"'
        in cliente.get("/eventos?run_id=p1&zone=baja").text
    )
    # una captura rota se informa en el CSV
    (salida / "capturas" / "p1-4.jpg").unlink()
    assert _csv(cliente.get("/eventos.csv?zone=baja"))[0]["captura"] == "no_existe"
