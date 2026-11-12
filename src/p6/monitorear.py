"""Recorre una fuente, corre el detector en cada cuadro y guarda lo que pasó.

    python -m p6.monitorear --fuente datos/videos/normal.mp4 --ritmo 5 \\
        --config config/monitoreo.yaml --run-id c1-normal

Por corrida escribe en `resultados/<run_id>/`:

- `run.json`: fuente, ritmo y muestreo, modelo (versión y SHA-256), configuración (SHA-256),
  entorno, código (commit de Git) y totales.
- `eventos.jsonl`: un evento por cuadro procesado, con sus detecciones reales, la
  puntuación más alta del cuadro y los tiempos por etapa. La política de confianza (#5), las
  capturas y la base de datos (#6) se agregan sobre estos mismos eventos.

Ctrl+C detiene la corrida y deja `run.json` cerrado con lo procesado hasta ese momento.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import psutil

from p6.config import Config, ConfigError, cargar_config
from p6.detector import DetectorError, DetectorONNX, ModeloInvalidoError
from p6.fuente import FuenteBase, FuenteError, abrir_fuente

RAIZ = Path(__file__).resolve().parents[2]
RUN_ID_VALIDO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass
class Totales:
    cuadros: int = 0
    ok: int = 0
    sin_detecciones: int = 0
    error: int = 0
    interrumpida: bool = False
    scores: list[float] = field(default_factory=list)


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil por rango más cercano; `None` si no hay valores."""
    if not valores:
        return None
    orden = sorted(valores)
    rango = max(1, math.ceil(p / 100 * len(orden)))
    return orden[rango - 1]


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
        "frame_score": None if score is None else round(score, 6),
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
        f"{mejor['class_name']} {mejor['score']:.3f} | infer {e['t_infer_ms']:.1f} ms"
    )


def correr(
    fuente: FuenteBase,
    detector: DetectorONNX,
    cfg: Config,
    run_id: str,
    carpeta: Path,
    max_cuadros: int | None = None,
    imprimir: Callable[[str], None] = print,
) -> tuple[dict[str, Any], Totales]:
    """Procesa la fuente y devuelve el contenido de run.json y los totales."""
    carpeta.mkdir(parents=True, exist_ok=True)
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
        "archivos": {"eventos": "eventos.jsonl"},
        "totales": None,
    }
    escribir_run(carpeta, run)  # queda constancia aunque la corrida se corte

    with (carpeta / "eventos.jsonl").open("w", encoding="utf-8") as f:
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
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
                f.flush()
                totales.cuadros += 1
                setattr(totales, evento["status"], getattr(totales, evento["status"]) + 1)
                if evento["frame_score"] is not None:
                    totales.scores.append(evento["frame_score"])
                imprimir(_linea(evento))
        except KeyboardInterrupt:
            totales.interrumpida = True
            imprimir("interrumpido: se cierra run.json con lo procesado")
    fin = datetime.now(UTC)
    duracion = (fin - inicio).total_seconds()
    run["fin_utc"] = fin.isoformat(timespec="seconds")
    run["totales"] = {
        "cuadros": totales.cuadros,
        "ok": totales.ok,
        "sin_detecciones": totales.sin_detecciones,
        "error": totales.error,
        "interrumpida": totales.interrumpida,
        "frame_score": resumen_scores(totales.scores),
        "duracion_s": round(duracion, 3),
        "cuadros_por_s_medido": round(totales.cuadros / duracion, 3) if duracion > 0 else None,
    }
    escribir_run(carpeta, run)
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
        if (carpeta / "run.json").exists() and not args.sobrescribir:
            raise ConfigError(f"{carpeta} ya existe; usa otro --run-id o --sobrescribir")
        detector = DetectorONNX.desde_config(cfg)
        fuente = abrir_fuente(args.fuente, ritmo, sin_pausa=args.sin_pausa)
    except (ConfigError, ModeloInvalidoError, FuenteError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"run {run_id} | fuente {fuente.source_id} | ritmo {ritmo:g} cuadros/s | "
        f"modelo {detector.model_name} {detector.model_version} "
        f"sha256 {detector.model_sha256[:12]}… | piso {cfg.detector.piso}"
    )
    try:
        run, t = correr(fuente, detector, cfg, run_id, carpeta, args.max_cuadros)
    except FuenteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        fuente.cerrar()
    print(
        f"listo: {t.cuadros} cuadros ({t.ok} con detecciones, {t.sin_detecciones} sin, "
        f"{t.error} con error) en {run['totales']['duracion_s']} s -> {carpeta}"
    )
    s = run["totales"]["frame_score"]
    if s["n"]:
        print(
            f"frame_score ({s['n']} cuadros con detecciones): min {s['min']} | p10 {s['p10']} "
            f"| p50 {s['p50']} | p90 {s['p90']} | max {s['max']}"
        )
    return 1 if t.error else 0


if __name__ == "__main__":
    sys.exit(main())
