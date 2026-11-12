"""Recorre una fuente, corre el detector en cada cuadro y guarda lo que pasó.

    python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \\
        --config config/monitoreo.yaml --run-id c1-normal

Los cuadros se acumulan por ventana. Al cerrarse una ventana se evalúan las reglas de alerta
(`p6.alertas`), se decide qué cuadros conservar como imagen (`p6.capturas`), se valida
cada evento con el contrato y se guardan en la base de datos. Por corrida queda:

- `resultados/monitoreo.db` (`--db`): corridas, eventos y alertas (ver `p6.almacen`).
- `resultados/<run_id>/run.json`: fuente, ritmo y muestreo, modelo (versión y SHA-256),
  configuración (SHA-256), política de confianza y de capturas, entorno, código (commit de
  Git) y totales, con el resumen por ventana.
- `resultados/<run_id>/eventos.jsonl` y `alertas.jsonl`: exportados desde la base de datos.
- `resultados/<run_id>/capturas/<event_id>.jpg`: las imágenes conservadas.
- `resultados/<run_id>/rechazados.jsonl` (solo si hubo): los eventos que no cumplen
  `docs/contrato.md`, con sus motivos. No entran en la base de datos; `run.json` los cuenta.

Ctrl+C detiene la corrida: se guarda la ventana en curso y se cierra `run.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import cv2
import numpy as np
import psutil

from p6 import capturas
from p6.alertas import EvaluadorReglas
from p6.almacen import Almacen, AlmacenError
from p6.config import Config, ConfigError, cargar_config
from p6.contrato import ValidadorEventos
from p6.detector import DetectorError, DetectorONNX, ModeloInvalidoError
from p6.fuente import FuenteBase, FuenteError, abrir_fuente
from p6.metricas import (
    calcular,
    guardar,
    percentil,  # noqa: F401  (también la usan scripts y pruebas)
    resumen,
    sha_del_descriptor,
)
from p6.politica import resumir_ventanas, window_id, zona

RAIZ = Path(__file__).resolve().parents[2]
# Etapa del contrato que cumplen los eventos: H1 es lo que produce el detector, H3 agrega la
# zona y la ventana (#5) y H4 la captura vinculada (#6).
ETAPA_CONTRATO = "H4"
# Recibe el resumen de una ventana recién cerrada y sus eventos; devuelve las alertas que
# esa ventana abrió, extendió o cerró (por defecto, las reglas A y B de p6.alertas).
EvaluadorVentanas = Callable[[dict[str, Any], list[dict[str, Any]]], list[dict[str, Any]]]
RUN_ID_VALIDO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass
class Totales:
    cuadros: int = 0
    ok: int = 0
    sin_detecciones: int = 0
    error: int = 0
    interrumpida: bool = False
    scores: list[float] = field(default_factory=list)
    zonas: dict[str, int] = field(default_factory=lambda: {"aceptada": 0, "duda": 0, "baja": 0})
    resumen_eventos: list[dict[str, Any]] = field(default_factory=list)
    capturas: dict[str, int] = field(
        default_factory=lambda: {m: 0 for m in ("baja", "ventana_alerta", "muestra")}
    )
    alertas: dict[str, dict[str, Any]] = field(default_factory=dict)
    metricas: dict[str, Any] | None = None


def resumen_scores(valores: list[float]) -> dict[str, float | None]:
    """Distribución del `frame_score` de la corrida (solo cuadros con detecciones)."""
    r = lambda x: None if x is None else round(x, 4)  # noqa: E731
    return {
        "n": len(valores),
        "min": r(min(valores, default=None)),
        "p10": r(percentil(valores, 10)),
        "p50": r(percentil(valores, 50)),
        "p90": r(percentil(valores, 90)),
        "max": r(max(valores, default=None)),
    }


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip()


def entorno() -> dict[str, Any]:
    import onnxruntime

    commit = _git("rev-parse", "HEAD")
    sucio = _git("status", "--porcelain")
    return {
        "so": platform.platform(),
        "python": platform.python_version(),
        "onnxruntime": onnxruntime.__version__,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "git_commit": commit,
        "git_arbol_con_cambios": None if sucio is None else bool(sucio),
    }


def _evento(
    run_id: str,
    cuadro: Any,
    fuente: FuenteBase,
    detector: DetectorONNX,
    cfg: Config,
    proceso: psutil.Process,
    resultado: Any,
    error: str | None,
) -> dict[str, Any]:
    if error is not None:
        status, detecciones, score = "error", [], None
    else:
        detecciones = [d.como_dict() for d in resultado.detecciones]
        score = resultado.frame_score
        status = "ok" if detecciones else "sin_detecciones"
    frame_score = None if score is None else round(score, 6)
    conf = cfg.confianza
    return {
        "event_id": f"{run_id}-{cuadro.frame_id}",
        "run_id": run_id,
        "frame_id": cuadro.frame_id,
        "source_id": fuente.source_id,
        "source_kind": fuente.source_kind,
        "origen": cuadro.origen,
        "t_capture_utc": cuadro.t_capture_utc,
        "t_mono_ms": round(cuadro.t_mono_ms, 3),
        "task": detector.task,
        "model_version": detector.model_version,
        "model_sha256": detector.model_sha256,
        "config_sha256": cfg.sha256,
        "status": status,
        "error_msg": error,
        "detections": detecciones,
        "frame_score": frame_score,
        "zone": zona(frame_score, conf.umbral_inferior, conf.umbral_superior),
        "window_id": window_id(cuadro.frame_id, conf.ventana_cuadros),
        "t_pre_ms": None if resultado is None else round(resultado.t_pre_ms, 3),
        "t_infer_ms": None if resultado is None else round(resultado.t_infer_ms, 3),
        "t_post_ms": None if resultado is None else round(resultado.t_post_ms, 3),
        "rss_mb": round(proceso.memory_info().rss / (1 << 20), 2),
        "warmup": cuadro.frame_id <= cfg.cuadros_warmup,
    }


def _linea(e: dict[str, Any]) -> str:
    if e["status"] == "error":
        return f"cuadro {e['frame_id']:>4} | ERROR {e['error_msg']}"
    if e["status"] == "sin_detecciones":
        return f"cuadro {e['frame_id']:>4} | sin detecciones | infer {e['t_infer_ms']:.1f} ms"
    mejor = e["detections"][0]
    return (
        f"cuadro {e['frame_id']:>4} | {len(e['detections']):>2} det | mejor "
        f"{mejor['class_name']} {mejor['score']:.3f} [{e['zone']}] | infer {e['t_infer_ms']:.1f} ms"
    )


def correr(
    fuente: FuenteBase,
    detector: DetectorONNX,
    cfg: Config,
    run_id: str,
    carpeta: Path,
    max_cuadros: int | None = None,
    imprimir: Callable[[str], None] = print,
    almacen: Almacen | None = None,
    evaluador: EvaluadorVentanas | None = None,
) -> tuple[dict[str, Any], Totales]:
    """Procesa la fuente y devuelve el contenido de run.json y los totales.

    Reemplaza cualquier dato previo de `run_id` (la CLI solo lo permite con `--sobrescribir`).
    Sin `almacen` usa `<carpeta>/../monitoreo.db`. Sin `evaluador` aplica las reglas A y B de
    la configuración (`p6.alertas.EvaluadorReglas`).
    """
    propio = almacen is None
    if evaluador is None:
        evaluador = EvaluadorReglas(cfg, run_id)
    db = almacen if almacen is not None else Almacen(carpeta.parent / "monitoreo.db")
    try:
        return _correr(fuente, detector, cfg, run_id, carpeta, max_cuadros, imprimir, db, evaluador)
    finally:
        if propio:
            db.cerrar()


def _correr(
    fuente: FuenteBase,
    detector: DetectorONNX,
    cfg: Config,
    run_id: str,
    carpeta: Path,
    max_cuadros: int | None,
    imprimir: Callable[[str], None],
    db: Almacen,
    evaluador: EvaluadorVentanas | None,
) -> tuple[dict[str, Any], Totales]:
    config_bytes = cfg.ruta.read_bytes()
    if capturas.sha256_bytes(config_bytes) != cfg.sha256:
        raise ConfigError(f"{cfg.ruta} cambió después de cargarse")
    # Una corrida repetida con el mismo run_id empieza de cero.
    db.borrar_corrida(run_id)
    shutil.rmtree(carpeta / capturas.CARPETA, ignore_errors=True)
    (carpeta / "rechazados.jsonl").unlink(missing_ok=True)
    carpeta.mkdir(parents=True, exist_ok=True)
    carpeta_rel = os.path.relpath(carpeta.resolve(), db.ruta.resolve().parent)

    proceso = psutil.Process()
    totales = Totales()
    inicio = datetime.now(UTC)
    run: dict[str, Any] = {
        "run_id": run_id,
        "inicio_utc": inicio.isoformat(timespec="seconds"),
        "fin_utc": None,
        "fuente": fuente.descripcion(),
        "modelo": {
            "nombre": detector.model_name,
            "version": detector.model_version,
            "sha256": detector.model_sha256,
            "tarea": detector.task,
            "archivo": str(cfg.modelo),
            "descriptor": str(cfg.descriptor),
            "piso_puntuacion": cfg.detector.piso,
        },
        "configuracion": {"archivo": str(cfg.ruta), "sha256": cfg.sha256},
        "entorno": entorno(),
        "cuadros_warmup": cfg.cuadros_warmup,
        "contrato": {"documento": "docs/contrato.md", "etapa": ETAPA_CONTRATO},
        "politica": {
            "documento": "docs/politica.md",
            "umbral_inferior": cfg.confianza.umbral_inferior,
            "umbral_superior": cfg.confianza.umbral_superior,
            "ventana_cuadros": cfg.confianza.ventana_cuadros,
            "minimo_con_detecciones": cfg.confianza.minimo_con_detecciones,
            "referencia_run_id": cfg.referencia.run_id,
            "p_ref": cfg.referencia.p_ref,
            "regla_A": {
                "condicion": "proporción baja >= proporcion_minima en una ventana suficiente",
                "proporcion_minima": cfg.regla_a.proporcion_minima,
                "severidad": cfg.regla_a.severidad,
            },
            "regla_B": {
                "condicion": "proporción baja > p_ref + margen en N ventanas suficientes seguidas",
                "limite": round(cfg.referencia.p_ref + cfg.regla_b.margen_sobre_referencia, 4),
                "ventanas_seguidas": cfg.regla_b.ventanas_seguidas,
                "severidad": cfg.regla_b.severidad,
            },
        },
        "politica_capturas": capturas.descripcion(),
        "archivos": {
            "eventos": "eventos.jsonl",
            "alertas": "alertas.jsonl",
            "capturas": f"{capturas.CARPETA}/",
            "base_de_datos": os.path.relpath(db.ruta.resolve(), carpeta.resolve()),
            "metricas": "metricas.json",
        },
        "totales": None,
    }
    escribir_run(carpeta, run)  # queda constancia aunque la corrida se corte
    db.guardar_corrida(run, carpeta_rel, config_bytes.decode("utf-8"))

    validador = ValidadorEventos(ETAPA_CONTRATO)
    rechazados: TextIO | None = None
    pendientes: list[tuple[dict[str, Any], np.ndarray | None]] = []

    def cerrar_ventana() -> None:
        nonlocal rechazados
        if not pendientes:
            return
        eventos = [e for e, _ in pendientes]
        wid = eventos[0]["window_id"]
        (resumen,) = resumir_ventanas(
            eventos, cfg.confianza.ventana_cuadros, cfg.confianza.minimo_con_detecciones
        )
        alertas = evaluador(resumen, eventos) if evaluador is not None else []
        abrio = any(a["opened_window_id"] == wid for a in alertas)
        for a in alertas:
            if a["opened_window_id"] == wid:
                imprimir(f"ALERTA {a['alert_id']} abierta ({a['severity']}): {a['reason']}")
            elif a["closed_window_id"] == wid:
                imprimir(f"ALERTA {a['alert_id']} cerrada en la ventana {wid}")
        aceptados = []
        for evento, imagen in pendientes:
            razon = capturas.motivo(evento, abrio)
            ref = sha = None
            if razon is not None and imagen is not None:
                ref, sha = capturas.guardar(carpeta, evento["event_id"], imagen)
            else:
                razon = None
            evento.update(image_ref=ref, image_sha256=sha, image_reason=razon)
            problemas = validador.revisar(evento)
            if problemas:
                # Un evento que no cumple el contrato no se guarda: va aparte con sus motivos.
                if ref is not None:
                    (carpeta / ref).unlink(missing_ok=True)
                if rechazados is None:
                    rechazados = (carpeta / "rechazados.jsonl").open("w", encoding="utf-8")
                linea = {"evento": evento, "motivos": problemas}
                rechazados.write(json.dumps(linea, ensure_ascii=False) + "\n")
                rechazados.flush()
                imprimir(f"cuadro {evento['frame_id']:>4} | RECHAZADO: {'; '.join(problemas)}")
                continue
            aceptados.append(evento)
            setattr(totales, evento["status"], getattr(totales, evento["status"]) + 1)
            if evento["frame_score"] is not None:
                totales.scores.append(evento["frame_score"])
                totales.zonas[evento["zone"]] += 1
            if razon is not None:
                totales.capturas[razon] += 1
            totales.resumen_eventos.append(
                {k: evento[k] for k in ("event_id", "frame_id", "status", "zone", "window_id")}
            )
        db.insertar_eventos(aceptados)
        if alertas:
            db.guardar_alertas(alertas)
            for a in alertas:
                totales.alertas[a["alert_id"]] = {
                    k: a[k]
                    for k in (
                        "rule_id",
                        "severity",
                        "status",
                        "opened_window_id",
                        "closed_window_id",
                    )
                }
        pendientes.clear()

    error_fuente: FuenteError | None = None
    try:
        for cuadro in fuente.cuadros():
            if max_cuadros is not None and totales.cuadros >= max_cuadros:
                break
            resultado, error = None, cuadro.error
            if error is None:
                try:
                    resultado = detector.detectar(cuadro.imagen)
                except DetectorError as exc:
                    error = str(exc)
            evento = _evento(run_id, cuadro, fuente, detector, cfg, proceso, resultado, error)
            totales.cuadros += 1
            imprimir(_linea(evento))
            if pendientes and pendientes[0][0]["window_id"] != evento["window_id"]:
                cerrar_ventana()
            pendientes.append((evento, cuadro.imagen))
    except KeyboardInterrupt:
        totales.interrumpida = True
        imprimir("interrumpido: se guarda la ventana en curso y se cierra run.json")
    except FuenteError as exc:
        totales.interrumpida = True
        error_fuente = exc
    finally:
        try:
            cerrar_ventana()
        finally:
            if rechazados is not None:
                rechazados.close()

    if validador.rechazados:
        run["archivos"]["rechazados"] = "rechazados.jsonl"
    fin = datetime.now(UTC)
    duracion = (fin - inicio).total_seconds()
    run["fin_utc"] = fin.isoformat(timespec="seconds")
    run["totales"] = {
        "cuadros": totales.cuadros,
        "ok": totales.ok,
        "sin_detecciones": totales.sin_detecciones,
        "error": totales.error,
        "interrumpida": totales.interrumpida,
        "eventos_aceptados": validador.aceptados,
        "eventos_rechazados": validador.rechazados,
        "motivos_rechazo": dict(validador.motivos),
        "frame_score": resumen_scores(totales.scores),
        "zonas": totales.zonas,
        "capturas": {**totales.capturas, "total": sum(totales.capturas.values())},
        "alertas": len(totales.alertas),
        "alertas_detalle": totales.alertas,
        "ventanas": resumir_ventanas(
            totales.resumen_eventos,
            cfg.confianza.ventana_cuadros,
            cfg.confianza.minimo_con_detecciones,
        ),
        "duracion_s": round(duracion, 3),
        "cuadros_por_s_medido": round(totales.cuadros / duracion, 3) if duracion > 0 else None,
    }
    escribir_run(carpeta, run)
    db.guardar_corrida(run, carpeta_rel, config_bytes.decode("utf-8"))
    db.exportar(run_id, carpeta)
    # Métricas G1–G7 desde lo que quedó guardado (eventos, alertas y capturas).
    metricas = calcular(
        run_id,
        db.eventos(run_id=run_id),
        db.alertas(run_id=run_id),
        carpeta,
        sha_del_descriptor(cfg.descriptor),
        cfg.confianza.minimo_con_detecciones,
    )
    guardar(db, run_id, metricas)
    totales.metricas = metricas
    if error_fuente is not None:
        raise error_fuente
    return run, totales


def escribir_run(carpeta: Path, run: dict[str, Any]) -> None:
    (carpeta / "run.json").write_text(
        json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m p6.monitorear", description=__doc__.split("\n")[0])
    p.add_argument(
        "--fuente", required=True, help="video, carpeta de imágenes, `webcam` o `webcam:N`"
    )
    p.add_argument(
        "--ritmo", type=float, default=None, help="cuadros/s (por defecto, el de la config)"
    )
    p.add_argument("--config", type=Path, default=RAIZ / "config" / "monitoreo.yaml")
    p.add_argument("--run-id", default=None, help="identificador de la corrida")
    p.add_argument("--salida", type=Path, default=RAIZ / "resultados", help="carpeta de corridas")
    p.add_argument(
        "--db", type=Path, default=None, help="base de datos (por defecto <salida>/monitoreo.db)"
    )
    p.add_argument("--sin-pausa", action="store_true", help="no esperar entre cuadros (pruebas)")
    p.add_argument("--max-cuadros", type=int, default=None, help="detenerse tras N cuadros")
    p.add_argument("--sobrescribir", action="store_true", help="reemplazar una corrida existente")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cfg = cargar_config(args.config)
        ritmo = args.ritmo if args.ritmo is not None else cfg.ritmo_cuadros_s
        if ritmo <= 0:
            raise ConfigError("--ritmo debe ser positivo")
        run_id = args.run_id or (
            f"{Path(args.fuente).stem.replace(':', '')}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
        )
        if not RUN_ID_VALIDO.fullmatch(run_id):
            raise ConfigError(f"run_id inválido {run_id!r}: usa letras, números, punto, _ o -")
        carpeta = args.salida / run_id
        almacen = Almacen(args.db or args.salida / "monitoreo.db")
        existe = (carpeta / "run.json").exists() or almacen.existe_corrida(run_id)
        if existe and not args.sobrescribir:
            almacen.cerrar()
            raise ConfigError(f"la corrida {run_id} ya existe; usa otro --run-id o --sobrescribir")
        detector = DetectorONNX.desde_config(cfg)
        fuente = abrir_fuente(args.fuente, ritmo, sin_pausa=args.sin_pausa)
    except (ConfigError, ModeloInvalidoError, FuenteError, AlmacenError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if "almacen" in locals():
            almacen.cerrar()
        return 2

    print(
        f"run {run_id} | fuente {fuente.source_id} | ritmo {ritmo:g} cuadros/s | "
        f"modelo {detector.model_name} {detector.model_version} "
        f"sha256 {detector.model_sha256[:12]}… | piso {cfg.detector.piso}"
    )
    try:
        run, t = correr(fuente, detector, cfg, run_id, carpeta, args.max_cuadros, almacen=almacen)
    except FuenteError as exc:
        print(f"ERROR: {exc} (lo procesado quedó guardado)", file=sys.stderr)
        return 2
    finally:
        fuente.cerrar()
        almacen.cerrar()
    tot = run["totales"]
    print(
        f"listo: {t.cuadros} cuadros ({t.ok} con detecciones, {t.sin_detecciones} sin, "
        f"{t.error} con error) en {tot['duracion_s']} s -> {carpeta}"
    )
    print(
        f"contrato (etapa {ETAPA_CONTRATO}): {tot['eventos_aceptados']} eventos aceptados, "
        f"{tot['eventos_rechazados']} rechazados"
    )
    s = tot["frame_score"]
    if s["n"]:
        print(
            f"frame_score ({s['n']} cuadros con detecciones): min {s['min']} | p10 {s['p10']} "
            f"| p50 {s['p50']} | p90 {s['p90']} | max {s['max']}"
        )
        z = tot["zonas"]
        print(f"zonas: aceptada {z['aceptada']} | duda {z['duda']} | baja {z['baja']}")
        print(
            "proporción baja por ventana:",
            [v["proporcion_baja"] for v in tot["ventanas"]],
        )
    c = tot["capturas"]
    print(
        f"capturas: {c['total']} (baja {c['baja']}, ventana_alerta {c['ventana_alerta']}, "
        f"muestra {c['muestra']}) | alertas: {tot['alertas']} | base de datos: {almacen.ruta}"
    )
    if t.metricas is not None:
        print("métricas (metricas.json):")
        for linea in resumen(t.metricas):
            print(f"  {linea}")
    return 1 if t.error or tot["eventos_rechazados"] else 0


if __name__ == "__main__":
    sys.exit(main())
