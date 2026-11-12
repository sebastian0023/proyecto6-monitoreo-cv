from __future__ import annotations

import hashlib

import cv2
import numpy as np
import pytest

from p6 import capturas
from p6.almacen import Almacen, leer_jsonl
from p6.config import cargar_config
from p6.fuente import FuenteCarpeta
from p6.monitorear import correr

from .conftest import CONFIG
from .test_contrato import alerta_abierta
from .test_monitorear import DetectorFalso, carpeta_con


@pytest.mark.parametrize(
    ("zona", "frame_id", "alerta", "esperado"),
    [
        ("baja", 7, False, "baja"),
        ("baja", 21, True, "baja"),  # baja tiene prioridad
        ("aceptada", 7, True, "ventana_alerta"),
        ("aceptada", 21, True, "ventana_alerta"),  # ventana_alerta antes que muestra
        ("duda", 21, False, "muestra"),
        (None, 41, False, "muestra"),  # sin detecciones también se muestrea
        ("aceptada", 7, False, None),
        (None, 8, False, None),
    ],
)
def test_motivo_de_captura(zona, frame_id, alerta, esperado):
    assert capturas.motivo({"zone": zona, "frame_id": frame_id}, alerta) == esperado


def test_guardar_escribe_un_jpeg_con_el_event_id_y_su_sha(tmp_path):
    imagen = np.full((48, 64, 3), 120, dtype=np.uint8)
    ref, sha = capturas.guardar(tmp_path, "c2-21", imagen)
    assert ref == "capturas/c2-21.jpg"
    archivo = tmp_path / ref
    assert hashlib.sha256(archivo.read_bytes()).hexdigest() == sha
    assert cv2.imread(str(archivo)).shape == (48, 64, 3)
    assert list((tmp_path / "capturas").iterdir()) == [archivo]  # sin temporales


def test_verificar_distingue_cada_estado(tmp_path):
    ref, sha = capturas.guardar(tmp_path, "e-1", np.zeros((8, 8, 3), np.uint8))
    assert capturas.verificar(tmp_path, ref, sha) == "ok"
    assert capturas.verificar(tmp_path, None, None) == "sin_captura"
    assert capturas.verificar(tmp_path, "capturas/otra.jpg", sha) == "no_existe"
    assert capturas.verificar(tmp_path, ref, "0" * 64) == "alterada"
    assert capturas.verificar(tmp_path / "sub", "../capturas/e-1.jpg", sha) == "ruta_invalida"
    (tmp_path / ref).write_bytes(b"otra cosa")
    assert capturas.verificar(tmp_path, ref, sha) == "alterada"


def test_una_ventana_que_abre_una_alerta_conserva_todos_sus_cuadros(tmp_path):
    # 45 cuadros aceptados (0.95), salvo el 30 en zona baja (0.40)
    valores = [95] * 45
    valores[29] = 40
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, valores), 5, sin_pausa=True)
    salida = tmp_path / "res" / "r5"
    vistas = []

    def evaluador(resumen, eventos):
        vistas.append((resumen["window_id"], len(eventos)))
        if resumen["window_id"] != 2:
            return []
        alerta = alerta_abierta()
        alerta.update(
            alert_id="r5-A-1",
            run_id="r5",
            opened_window_id=2,
            window_ids=[2],
            event_ids=[e["event_id"] for e in eventos],
            config_sha256=cfg.sha256,
        )
        return [alerta]

    run, _ = correr(
        fuente, DetectorFalso(), cfg, "r5", salida, imprimir=lambda _: None, evaluador=evaluador
    )
    assert vistas == [(1, 20), (2, 20), (3, 5)]  # una llamada por ventana, con sus eventos
    eventos = leer_jsonl(salida / "eventos.jsonl")
    motivos = {e["frame_id"]: e["image_reason"] for e in eventos}
    assert motivos[1] == "muestra" and motivos[41] == "muestra"
    assert motivos[30] == "baja"
    assert all(motivos[i] == "ventana_alerta" for i in range(21, 41) if i != 30)
    assert all(motivos[i] is None for i in [*range(2, 21), *range(42, 46)])
    assert run["totales"]["capturas"] == {
        "baja": 1,
        "ventana_alerta": 19,
        "muestra": 2,
        "total": 22,
    }
    assert run["totales"]["alertas"] == 1
    # cada captura existe y coincide con su SHA-256
    assert all(
        capturas.verificar(salida, e["image_ref"], e["image_sha256"]) in ("ok", "sin_captura")
        for e in eventos
    )
    # la alerta queda en la base de datos y en alertas.jsonl
    with Almacen(tmp_path / "res" / "monitoreo.db", solo_lectura=True) as db:
        assert [a["alert_id"] for a in db.alertas("r5")] == ["r5-A-1"]
    assert [a["alert_id"] for a in leer_jsonl(salida / "alertas.jsonl")] == ["r5-A-1"]


def test_repetir_una_corrida_reemplaza_sus_capturas(tmp_path):
    cfg = cargar_config(CONFIG)
    salida = tmp_path / "res" / "r6"
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [40, 40, 40]), 5, sin_pausa=True)
    correr(fuente, DetectorFalso(), cfg, "r6", salida, imprimir=lambda _: None)
    assert len(list((salida / "capturas").iterdir())) == 3
    (tmp_path / "otra").mkdir()
    fuente = FuenteCarpeta(carpeta_con(tmp_path / "otra", [95]), 5, sin_pausa=True)
    correr(fuente, DetectorFalso(), cfg, "r6", salida, imprimir=lambda _: None)
    assert [p.name for p in (salida / "capturas").iterdir()] == ["r6-1.jpg"]
    with Almacen(tmp_path / "res" / "monitoreo.db", solo_lectura=True) as db:
        assert db.contar_eventos(run_id="r6") == 1
