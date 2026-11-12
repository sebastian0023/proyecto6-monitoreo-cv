"""Las 7 métricas base (G1–G7), por ventana y por corrida (ver `docs/metricas.md`).

    python -m p6.metricas --db resultados/monitoreo.db --run-id c1-normal   # calcula y guarda
    python -m p6.metricas --db resultados/monitoreo.db --run-id c1-normal --recalcular

Se calculan solo con datos primarios: las filas de `eventos` y `alertas` de la base de datos y
los archivos de captura. Nada sale de `run.json` ni de otro resultado ya agregado.

Cada resultado declara su `estado`: `ok`, `sin datos` (no hubo observaciones; nunca se
reporta 0) o `insuficiente` (hubo menos observaciones que el mínimo). G7 es la excepción:
0 alertas activas es un valor válido. Cada resultado lleva su población: cuántas
observaciones usó (`n`), de qué ventanas (`window_ids`) y el rango de `event_id`.

Al calcular, el documento se guarda en la tabla `metricas` y en
`resultados/<run_id>/metricas.json`. `--recalcular` lo vuelve a calcular desde los datos
primarios y lo compara campo por campo con lo guardado: código 0 si coincide, 1 si no.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from p6 import capturas
from p6.almacen import Almacen, AlmacenError
from p6.contrato import validar_evento

RAIZ = Path(__file__).resolve().parents[2]
DESCRIPTOR = RAIZ / "modelo" / "descriptor.yaml"
SIN_DATOS = "sin datos"
INSUFICIENTE = "insuficiente"
MINIMO_G4 = 10  # cuadros con detecciones; igual a confianza.minimo_con_detecciones
COMPLETADOS = ("ok", "sin_detecciones")  # la inferencia se completó


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil por rango más cercano; `None` si no hay valores."""
    if not valores:
        return None
    orden = sorted(valores)
    rango = max(1, math.ceil(p / 100 * len(orden)))
    return orden[rango - 1]


def _poblacion(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """Trazabilidad de un resultado: cuántos eventos, de qué ventanas y su rango de ids."""
    orden = sorted(eventos, key=lambda e: e["frame_id"])
    return {
        "n": len(orden),
        "window_ids": sorted({e["window_id"] for e in orden}),
        "event_id_desde": orden[0]["event_id"] if orden else None,
        "event_id_hasta": orden[-1]["event_id"] if orden else None,
    }


# ---- una función por métrica ---------------------------------------------------------
def g1_latencia(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """Latencia de inferencia p50 y p95: t_infer_ms + t_post_ms, sin warmup ni error."""
    pob = [e for e in eventos if e["status"] in COMPLETADOS and not e["warmup"]]
    x = [round(e["t_infer_ms"] + e["t_post_ms"], 3) for e in pob]
    return {
        "metrica": "latencia_inferencia_ms",
        "estado": "ok" if x else SIN_DATOS,
        "p50": percentil(x, 50),
        "p95": percentil(x, 95),
        "excluidos": {
            "warmup": sum(1 for e in eventos if e["warmup"] and e["status"] in COMPLETADOS),
            "error": sum(1 for e in eventos if e["status"] == "error"),
        },
        **_poblacion(pob),
    }


def g2_cuadros_por_s(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuadros con inferencia completada por segundo: (n − 1) / intervalo monotónico."""
    pob = sorted((e for e in eventos if e["status"] in COMPLETADOS), key=lambda e: e["frame_id"])
    intervalo = (pob[-1]["t_mono_ms"] - pob[0]["t_mono_ms"]) / 1000 if len(pob) >= 2 else 0.0
    ok = len(pob) >= 2 and intervalo > 0
    return {
        "metrica": "cuadros_procesados_por_s",
        "estado": "ok" if ok else SIN_DATOS,
        "valor": round((len(pob) - 1) / intervalo, 3) if ok else None,
        "intervalo_s": round(intervalo, 3) if ok else None,
        "excluidos": {"error": sum(1 for e in eventos if e["status"] == "error")},
        **_poblacion(pob),
    }


def g3_ram(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """RAM (RSS) del proceso en MiB: máximo y último valor; todos los eventos."""
    pob = sorted(eventos, key=lambda e: e["frame_id"])
    mayor = max(pob, key=lambda e: e["rss_mb"]) if pob else None
    return {
        "metrica": "ram_proceso_mib",
        "estado": "ok" if pob else SIN_DATOS,
        "max": mayor["rss_mb"] if mayor else None,
        "ultimo": pob[-1]["rss_mb"] if pob else None,
        "event_id_max": mayor["event_id"] if mayor else None,
        **_poblacion(pob),
    }


def g4_baja_confianza(eventos: list[dict[str, Any]], minimo: int = MINIMO_G4) -> dict[str, Any]:
    """Cuadros en zona baja entre cuadros con detecciones; insuficiente bajo el mínimo."""
    pob = [e for e in eventos if e["status"] == "ok"]
    baja = sum(1 for e in pob if e["zone"] == "baja")
    if not eventos:
        estado = SIN_DATOS
    elif len(pob) < minimo:
        estado = INSUFICIENTE
    else:
        estado = "ok"
    return {
        "metrica": "proporcion_baja_confianza",
        "estado": estado,
        "valor": round(baja / len(pob), 4) if estado == "ok" else None,
        "baja": baja,
        "con_detecciones": len(pob),
        "minimo": minimo,
        "excluidos": {
            "sin_detecciones": sum(1 for e in eventos if e["status"] == "sin_detecciones"),
            "error": sum(1 for e in eventos if e["status"] == "error"),
        },
        **_poblacion(pob),
    }


def g5_trazabilidad(eventos: list[dict[str, Any]], carpeta: Path) -> dict[str, Any]:
    """Eventos con el contrato completo y, si tienen captura, archivo verificado."""
    incumplen = []
    for e in sorted(eventos, key=lambda e: e["frame_id"]):
        motivos = validar_evento(e, "H4")
        estado_captura = capturas.verificar(carpeta, e.get("image_ref"), e.get("image_sha256"))
        if estado_captura not in ("ok", "sin_captura"):
            motivos.append(f"captura: {estado_captura}")
        if motivos:
            incumplen.append({"event_id": e["event_id"], "motivos": motivos})
    total = len(eventos)
    return {
        "metrica": "cobertura_trazabilidad",
        "estado": "ok" if total else SIN_DATOS,
        "valor": round((total - len(incumplen)) / total, 4) if total else None,
        "cumplen": total - len(incumplen),
        "total": total,
        "incumplen": incumplen,
        **_poblacion(eventos),
    }


def g6_version(eventos: list[dict[str, Any]], sha_esperado: str) -> dict[str, Any]:
    """Eventos producidos por el modelo del descriptor, y versiones que aparecen."""
    versiones: dict[tuple[str, str], int] = {}
    for e in eventos:
        clave = (e["model_version"], e["model_sha256"])
        versiones[clave] = versiones.get(clave, 0) + 1
    coinciden = sum(1 for e in eventos if e["model_sha256"] == sha_esperado)
    total = len(eventos)
    return {
        "metrica": "coincidencia_version_modelo",
        "estado": "ok" if total else SIN_DATOS,
        "valor": round(coinciden / total, 4) if total else None,
        "coinciden": coinciden,
        "total": total,
        "sha256_esperado": sha_esperado,
        "versiones": [
            {"model_version": v, "model_sha256": s, "eventos": n}
            for (v, s), n in sorted(versiones.items())
        ],
        **_poblacion(eventos),
    }


def activas_al_cierre(alertas: list[dict[str, Any]], w: int) -> list[str]:
    """Alertas activas al cerrarse la ventana `w`: abiertas en `w` o antes, y no cerradas aún."""
    return sorted(
        a["alert_id"]
        for a in alertas
        if a["opened_window_id"] <= w
        and (a["closed_window_id"] is None or a["closed_window_id"] > w)
    )


def g7_alertas_ventana(alertas: list[dict[str, Any]], w: int) -> dict[str, Any]:
    activas = activas_al_cierre(alertas, w)
    return {
        "metrica": "alertas_activas",
        "estado": "ok",  # 0 es un valor válido
        "valor": len(activas),
        "alert_ids": activas,
        "window_ids": [w],
    }


def g7_alertas_corrida(alertas: list[dict[str, Any]], ventanas: list[int]) -> dict[str, Any]:
    serie = [len(activas_al_cierre(alertas, w)) for w in ventanas]
    return {
        "metrica": "alertas_activas",
        "estado": "ok",
        "serie": serie,
        "max_simultaneas": max(serie, default=0),
        "abiertas_al_final": serie[-1] if serie else 0,
        "alert_ids": sorted(a["alert_id"] for a in alertas),
        "window_ids": ventanas,
    }


# ---- documento completo --------------------------------------------------------------
def calcular(
    run_id: str,
    eventos: list[dict[str, Any]],
    alertas: list[dict[str, Any]],
    carpeta: Path,
    sha_esperado: str,
    minimo_g4: int = MINIMO_G4,
) -> dict[str, Any]:
    """Las 7 métricas de una corrida, para la corrida entera y para cada ventana."""
    ventanas = sorted({e["window_id"] for e in eventos})
    por_ventana = []
    for w in ventanas:
        evs = [e for e in eventos if e["window_id"] == w]
        por_ventana.append(
            {
                "window_id": w,
                "cuadros": len(evs),
                **{k: v for k, v in _poblacion(evs).items() if k.startswith("event_id")},
                "G1": g1_latencia(evs),
                "G2": g2_cuadros_por_s(evs),
                "G3": g3_ram(evs),
                "G4": g4_baja_confianza(evs, minimo_g4),
                "G5": g5_trazabilidad(evs, carpeta),
                "G6": g6_version(evs, sha_esperado),
                "G7": g7_alertas_ventana(alertas, w),
            }
        )
    return {
        "run_id": run_id,
        "documento": "docs/metricas.md",
        "corrida": {
            "cuadros": len(eventos),
            **{k: v for k, v in _poblacion(eventos).items() if k != "n"},
            "G1": g1_latencia(eventos),
            "G2": g2_cuadros_por_s(eventos),
            "G3": g3_ram(eventos),
            "G4": g4_baja_confianza(eventos, minimo_g4),
            "G5": g5_trazabilidad(eventos, carpeta),
            "G6": g6_version(eventos, sha_esperado),
            "G7": g7_alertas_corrida(alertas, ventanas),
        },
        "ventanas": por_ventana,
    }


def sha_del_descriptor(ruta: Path = DESCRIPTOR) -> str:
    return str(yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))["sha256"])


def _minimo_de(db: Almacen, run_id: str) -> int:
    corrida = db.corrida(run_id)
    conf = yaml.safe_load(corrida["config_texto"]) if corrida else {}
    return int(((conf or {}).get("confianza") or {}).get("minimo_con_detecciones", MINIMO_G4))


def calcular_desde_db(db: Almacen, run_id: str, descriptor: Path = DESCRIPTOR) -> dict[str, Any]:
    corrida = db.corrida(run_id)
    if corrida is None:
        raise AlmacenError(f"la corrida {run_id} no está en {db.ruta}")
    carpeta = db.ruta.resolve().parent / corrida["carpeta"]
    return calcular(
        run_id,
        db.eventos(run_id=run_id),
        db.alertas(run_id=run_id),
        carpeta,
        sha_del_descriptor(descriptor),
        _minimo_de(db, run_id),
    )


def guardar(db: Almacen, run_id: str, documento: dict[str, Any]) -> Path:
    """Guarda en la base de datos y en `<carpeta de la corrida>/metricas.json`."""
    documento = {**documento, "calculado_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    db.guardar_metricas(run_id, documento)
    carpeta = db.ruta.resolve().parent / db.corrida(run_id)["carpeta"]
    ruta = carpeta / "metricas.json"
    ruta.write_text(json.dumps(documento, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ruta


def diferencias(a: Any, b: Any, ruta: str = "") -> list[str]:
    """Campos que difieren entre dos documentos (números con tolerancia 1e-9)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k == "calculado_utc":
                continue
            if k not in a or k not in b:
                out.append(f"{ruta}{k}: solo en uno de los dos")
            else:
                out += diferencias(a[k], b[k], f"{ruta}{k}.")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{ruta.rstrip('.')}: largo {len(a)} ≠ {len(b)}"]
        return [
            d
            for i, (x, y) in enumerate(zip(a, b, strict=True))
            for d in diferencias(x, y, f"{ruta}{i}.")
        ]
    numeros = (int, float)
    if isinstance(a, numeros) and isinstance(b, numeros) and not isinstance(a, bool):
        return (
            []
            if math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
            else [f"{ruta.rstrip('.')}: {a} ≠ {b}"]
        )
    return [] if a == b else [f"{ruta.rstrip('.')}: {a!r} ≠ {b!r}"]


def resumen(documento: dict[str, Any]) -> list[str]:
    """Una línea por métrica de la corrida, para la terminal."""
    c = documento["corrida"]
    f = lambda r, k, fmt="{}": fmt.format(r[k]) if r[k] is not None else r["estado"]  # noqa: E731
    g = c["G7"]
    return [
        f"G1 latencia de inferencia: p50 {f(c['G1'], 'p50')} ms, p95 {f(c['G1'], 'p95')} ms "
        f"(n={c['G1']['n']})",
        f"G2 cuadros procesados por segundo: {f(c['G2'], 'valor')} (n={c['G2']['n']})",
        f"G3 RAM del proceso: máximo {f(c['G3'], 'max')} MiB, último {f(c['G3'], 'ultimo')} MiB",
        f"G4 proporción de baja confianza: {f(c['G4'], 'valor')} "
        f"({c['G4']['baja']} de {c['G4']['con_detecciones']} con detecciones)",
        f"G5 cobertura de trazabilidad: {f(c['G5'], 'valor')} "
        f"({c['G5']['cumplen']} de {c['G5']['total']})",
        f"G6 coincidencia de versión del modelo: {f(c['G6'], 'valor')} "
        f"({c['G6']['coinciden']} de {c['G6']['total']}; {len(c['G6']['versiones'])} versión(es))",
        f"G7 alertas activas por ventana: {g['serie']} "
        f"(máximo {g['max_simultaneas']}, abiertas al final {g['abiertas_al_final']})",
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m p6.metricas", description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=RAIZ / "resultados" / "monitoreo.db")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--descriptor", type=Path, default=DESCRIPTOR, help="SHA-256 esperado (G6)")
    ap.add_argument("--recalcular", action="store_true", help="recalcula y compara con lo guardado")
    ap.add_argument("--salida", type=Path, default=None, help="guardar el informe del recálculo")
    args = ap.parse_args(argv)
    try:
        with Almacen(args.db, solo_lectura=args.recalcular) as db:
            nuevo = calcular_desde_db(db, args.run_id, args.descriptor)
            if not args.recalcular:
                ruta = guardar(db, args.run_id, nuevo)
                print("\n".join(resumen(nuevo)))
                print(f"guardado en la base de datos y en {ruta}")
                return 0
            guardado = db.metricas(args.run_id)
    except (AlmacenError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if guardado is None:
        print(f"ERROR: la corrida {args.run_id} no tiene métricas guardadas", file=sys.stderr)
        return 2
    difs = diferencias(guardado, nuevo)
    lineas = [
        f"recálculo de las métricas de {args.run_id} desde {args.db} "
        f"(guardadas el {guardado.get('calculado_utc')})",
        *resumen(nuevo),
    ]
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        propias = [d for d in difs if f".{g}." in f".{d}"]
        lineas.append(
            f"{g}: {'coincide' if not propias else 'NO coincide'} (corrida y "
            f"{len(nuevo['ventanas'])} ventanas)"
        )
    lineas += [f"  diferencia: {d}" for d in difs[:50]]
    lineas.append("resultado: " + ("todo coincide" if not difs else f"{len(difs)} diferencias"))
    texto = "\n".join(lineas)
    print(texto)
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(texto + "\n", encoding="utf-8")
    return 0 if not difs else 1


if __name__ == "__main__":
    sys.exit(main())
