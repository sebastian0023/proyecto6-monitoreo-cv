from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from p6.config import ConfigError, cargar_config, sha256_archivo
from p6.contrato import validar_evento
from p6.detector import Deteccion, DetectorError, Resultado
from p6.fuente import FuenteCarpeta
from p6.monitorear import correr, main, percentil, resumen_scores

from .conftest import CONFIG, DESCRIPTOR, VIDEO_NORMAL, requiere_modelo


class DetectorFalso:
    """Devuelve una puntuación según el valor del cuadro (0 -> sin detecciones, 255 -> error)."""

    task = "detection"
    model_name = "yolox_nano"
    model_version = "0.1.1rc0"
    model_sha256 = "f" * 64

    def detectar(self, bgr: np.ndarray) -> Resultado:
        v = int(bgr[0, 0, 0])
        if v == 255:
            raise DetectorError("fallo simulado")
        dets = [] if v == 0 else [Deteccion(0, "person", v / 100, (1.0, 2.0, 30.0, 40.0))]
        return Resultado(dets, 1.0, 2.0, 0.5, ancho=64, alto=48)


def carpeta_con(tmp_path: Path, valores: list[int]) -> Path:
    c = tmp_path / "fotos"
    c.mkdir()
    for i, v in enumerate(valores):
        cv2.imwrite(str(c / f"{i:03d}.png"), np.full((48, 64, 3), v, dtype=np.uint8))
    return c


def test_correr_guarda_un_evento_por_cuadro_y_el_run_json(tmp_path):
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [90, 0, 255, 40, 70, 60]), 5, sin_pausa=True)
    salida = tmp_path / "res" / "r1"
    lineas: list[str] = []
    run, t = correr(fuente, DetectorFalso(), cfg, "r1", salida, imprimir=lineas.append)

    assert (t.cuadros, t.ok, t.sin_detecciones, t.error) == (6, 4, 1, 1)
    eventos = [json.loads(x) for x in (salida / "eventos.jsonl").read_text().splitlines()]
    assert [e["event_id"] for e in eventos] == [f"r1-{i}" for i in range(1, 7)]
    assert [e["status"] for e in eventos] == ["ok", "sin_detecciones", "error", "ok", "ok", "ok"]
    ok = eventos[0]
    assert ok["frame_score"] == 0.9 and ok["detections"][0]["class_name"] == "person"
    assert ok["model_sha256"] == "f" * 64 and ok["config_sha256"] == cfg.sha256
    assert ok["task"] == "detection" and ok["source_kind"] == "carpeta"
    assert (ok["t_pre_ms"], ok["t_infer_ms"], ok["t_post_ms"]) == (1.0, 2.0, 0.5)
    assert ok["rss_mb"] > 0
    # sin detecciones: ni puntuación ni detecciones; error: sin tiempos y con mensaje
    assert eventos[1]["frame_score"] is None and eventos[1]["detections"] == []
    assert eventos[2]["error_msg"] == "fallo simulado" and eventos[2]["t_infer_ms"] is None
    assert [e["warmup"] for e in eventos] == [True] * 5 + [False]
    assert len(lineas) == 6 and "ERROR" in lineas[2] and "sin detecciones" in lineas[1]

    guardado = json.loads((salida / "run.json").read_text())
    assert guardado == run
    assert guardado["run_id"] == "r1" and guardado["fin_utc"] is not None
    assert guardado["fuente"]["ritmo_declarado_cuadros_s"] == 5
    assert (
        guardado["modelo"]["sha256"] == "f" * 64 and guardado["modelo"]["piso_puntuacion"] == 0.10
    )
    assert guardado["configuracion"]["sha256"] == sha256_archivo(CONFIG)
    assert {"so", "python", "onnxruntime"} <= set(guardado["entorno"])
    assert guardado["totales"]["cuadros"] == 6
    assert guardado["totales"]["frame_score"]["n"] == 4


def test_los_eventos_de_la_corrida_cumplen_el_contrato(tmp_path):
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [90, 0, 255, 40]), 5, sin_pausa=True)
    salida = tmp_path / "res"
    run, t = correr(fuente, DetectorFalso(), cfg, "r3", salida, imprimir=lambda _: None)
    eventos = [json.loads(x) for x in (salida / "eventos.jsonl").read_text().splitlines()]
    assert all(validar_evento(e, "H1") == [] for e in eventos)  # incluye el de error
    assert run["contrato"] == {"documento": "docs/contrato.md", "etapa": "H1"}
    assert run["totales"]["eventos_aceptados"] == 4 and run["totales"]["eventos_rechazados"] == 0
    assert not (salida / "rechazados.jsonl").exists() and "rechazados" not in run["archivos"]


def test_un_evento_incompleto_se_rechaza_se_guarda_aparte_y_se_cuenta(tmp_path):
    class DetectorRoto(DetectorFalso):
        def detectar(self, bgr):
            if int(bgr[0, 0, 0]) == 20:  # tiempo negativo: viola el contrato
                return Resultado([], 1.0, -5.0, 0.5, ancho=64, alto=48)
            return super().detectar(bgr)

    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [90, 20, 70]), 5, sin_pausa=True)
    salida = tmp_path / "res"
    lineas: list[str] = []
    run, t = correr(fuente, DetectorRoto(), cfg, "r4", salida, imprimir=lineas.append)

    assert t.cuadros == 3 and (t.ok, t.sin_detecciones, t.error) == (2, 0, 0)
    eventos = [json.loads(x) for x in (salida / "eventos.jsonl").read_text().splitlines()]
    assert [e["frame_id"] for e in eventos] == [1, 3]  # el rechazado no entra
    (rechazado,) = [json.loads(x) for x in (salida / "rechazados.jsonl").read_text().splitlines()]
    assert rechazado["evento"]["frame_id"] == 2
    assert rechazado["motivos"] == ["t_infer_ms: no puede ser negativo"]
    tot = run["totales"]
    assert (tot["eventos_aceptados"], tot["eventos_rechazados"]) == (2, 1)
    assert tot["motivos_rechazo"] == {"t_infer_ms": 1}
    assert run["archivos"]["rechazados"] == "rechazados.jsonl"
    assert any("RECHAZADO" in x and "t_infer_ms" in x for x in lineas)

    # una corrida nueva con el mismo run_id no hereda los rechazados de la anterior
    (tmp_path / "otra").mkdir()
    fuente = FuenteCarpeta(carpeta_con(tmp_path / "otra", [90]), 5, sin_pausa=True)
    correr(fuente, DetectorFalso(), cfg, "r4", salida, imprimir=lambda _: None)
    assert not (salida / "rechazados.jsonl").exists()


def test_max_cuadros_detiene_la_corrida(tmp_path):
    cfg = cargar_config(CONFIG)
    fuente = FuenteCarpeta(carpeta_con(tmp_path, [50] * 6), 5, sin_pausa=True)
    _, t = correr(fuente, DetectorFalso(), cfg, "r2", tmp_path / "r2", max_cuadros=2)
    assert t.cuadros == 2


def test_percentil_por_rango_mas_cercano():
    v = [0.9, 0.1, 0.5, 0.3, 0.7]
    assert percentil(v, 10) == 0.1 and percentil(v, 50) == 0.5 and percentil(v, 90) == 0.9
    assert percentil([], 50) is None
    assert resumen_scores([]) == {
        "n": 0,
        "min": None,
        "p10": None,
        "p50": None,
        "p90": None,
        "max": None,
    }


def test_config_rechaza_valores_invalidos(tmp_path):
    base = CONFIG.read_text(encoding="utf-8")
    malos = {
        "piso: 0.10": "piso: 0",
        "ritmo_cuadros_s: 5 ": "ritmo_cuadros_s: -1 ",
        "tamano_entrada: 416": "tamano_entrada: 400",
        "max_detecciones: 100": "max_detecciones: 100\n  inventada: 1",
    }
    for original, cambio in malos.items():
        assert original in base
        ruta = tmp_path / "c.yaml"
        ruta.write_text(base.replace(original, cambio), encoding="utf-8")
        with pytest.raises(ConfigError):
            cargar_config(ruta)
    with pytest.raises(ConfigError):
        cargar_config(tmp_path / "no_existe.yaml")


def test_main_rechaza_una_fuente_inexistente(capsys, tmp_path):
    codigo = main(["--fuente", str(tmp_path / "no.mp4"), "--salida", str(tmp_path / "res")])
    assert codigo == 2


@requiere_modelo
def test_corrida_real_de_punta_a_punta(tmp_path, capsys):
    if not VIDEO_NORMAL.is_file():
        pytest.skip("falta datos/videos/normal.mp4")
    salida = tmp_path / "res"
    args = ["--fuente", str(VIDEO_NORMAL), "--run-id", "real", "--salida", str(salida)]
    assert main([*args, "--sin-pausa", "--max-cuadros", "4"]) == 0
    out = capsys.readouterr().out
    assert "sha256 c789161ed43c" in out and "cuadro    1" in out
    run = json.loads((salida / "real" / "run.json").read_text())
    esperado = yaml.safe_load(DESCRIPTOR.read_text(encoding="utf-8"))["sha256"]
    assert run["modelo"]["sha256"] == esperado
    assert run["fuente"]["muestreo"]["k"] == 3 and run["totales"]["cuadros"] == 4
    eventos = [json.loads(x) for x in (salida / "real" / "eventos.jsonl").read_text().splitlines()]
    assert all(e["model_sha256"] == esperado for e in eventos)
    assert any(e["detections"] for e in eventos)  # inferencias reales
    # una corrida existente no se pisa sin permiso
    assert main([*args, "--sin-pausa", "--max-cuadros", "1"]) == 2
