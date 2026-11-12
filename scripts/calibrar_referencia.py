"""Calcula, con la corrida sobre `referencia.mp4`, lo que justifica los umbrales y las reglas.

    python scripts/calibrar_referencia.py --run resultados/ref-00 --salida evidencias/referencia

Lee solo `eventos.jsonl` de la corrida de referencia (nunca los videos de C1 ni C2) y escribe:

- `calibracion.json`: cuadros, cuadros sin detecciones, percentiles de `frame_score`, la
  propuesta de umbrales (percentil 10 y 50 redondeados a 0.05) y, si la configuración ya tiene
  la sección `confianza`, la comprobación de que sus valores salen de esa propuesta, el
  `p_ref` y la proporción de baja confianza de cada ventana con los umbrales vigentes.
- `histograma.csv` y `histograma.svg`: distribución de `frame_score` en cajas de 0.01, con el
  piso del detector y los umbrales marcados.

Con `--verificar` termina con código 1 si la configuración no coincide con la propuesta.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from p6.monitorear import percentil
from p6.politica import resumir_ventanas, zona

RAIZ = Path(__file__).resolve().parents[1]
CAJA = 0.01


def redondear_05(x: float) -> float:
    """Múltiplo de 0.05 más cercano."""
    return round(round(x * 20) / 20, 2)


def leer_eventos(carpeta: Path) -> list[dict[str, Any]]:
    ruta = carpeta / "eventos.jsonl"
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def histograma(scores: list[float], piso: float) -> list[tuple[float, float, int]]:
    """Cajas de 0.01 desde el piso hasta 1.00: (desde, hasta, cuadros)."""
    n_cajas = round((1.0 - piso) / CAJA)
    cuentas = [0] * n_cajas
    for s in scores:
        i = min(int((s - piso) / CAJA + 1e-9), n_cajas - 1)
        cuentas[i] += 1
    return [
        (round(piso + i * CAJA, 2), round(piso + (i + 1) * CAJA, 2), c)
        for i, c in enumerate(cuentas)
    ]


def svg(
    caja: list[tuple[float, float, int]], piso: float, inf: float | None, sup: float | None
) -> str:
    ancho, alto, m = 760, 300, 50
    maximo = max((c for _, _, c in caja), default=1) or 1
    w = (ancho - 2 * m) / len(caja)
    x = lambda v: m + (v - piso) / (1.0 - piso) * (ancho - 2 * m)  # noqa: E731
    barras = "".join(
        f'<rect x="{m + i * w:.2f}" y="{alto - m - c / maximo * (alto - 2 * m):.2f}" '
        f'width="{max(w - 0.6, 0.5):.2f}" height="{c / maximo * (alto - 2 * m):.2f}" fill="#4a7fb5"/>'
        for i, (_, _, c) in enumerate(caja)
        if c
    )
    marcas = []
    for valor, etiqueta, color in (
        (piso, "piso", "#888"),
        (inf, "inferior", "#c0392b"),
        (sup, "superior", "#2e8b57"),
    ):
        if valor is None:
            continue
        marcas.append(
            f'<line x1="{x(valor):.2f}" x2="{x(valor):.2f}" y1="{m - 10}" y2="{alto - m}" stroke="{color}" stroke-dasharray="4 3"/>'
            f'<text x="{x(valor) + 3:.2f}" y="{m - 12}" font-size="11" fill="{color}">{etiqueta} {valor:.2f}</text>'
        )
    ticks = "".join(
        f'<text x="{x(v):.2f}" y="{alto - m + 16}" font-size="11" text-anchor="middle" fill="#555">{v:.1f}</text>'
        for v in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}" width="{ancho}" height="{alto}" '
        'font-family="sans-serif"><rect width="100%" height="100%" fill="#fff"/>'
        f'<text x="{m}" y="18" font-size="13" fill="#222">frame_score de la referencia (cajas de 0.01; máximo {maximo} cuadros)</text>'
        f'<line x1="{m}" x2="{ancho - m}" y1="{alto - m}" y2="{alto - m}" stroke="#555"/>'
        f"{barras}{''.join(marcas)}{ticks}"
        f'<text x="{ancho / 2}" y="{alto - 8}" font-size="12" text-anchor="middle" fill="#555">frame_score</text></svg>\n'
    )


def calcular(eventos: list[dict[str, Any]], cfg: dict[str, Any] | None) -> dict[str, Any]:
    piso = cfg["detector"]["piso"] if cfg else 0.10
    scores = [e["frame_score"] for e in eventos if e["frame_score"] is not None]
    sin = sum(e["status"] == "sin_detecciones" for e in eventos)
    err = sum(e["status"] == "error" for e in eventos)
    p = {f"p{k}": percentil(scores, k) for k in (1, 5, 10, 25, 50, 75, 90, 95, 99)}
    prop = {
        "umbral_inferior": redondear_05(percentil(scores, 10)),
        "umbral_superior": redondear_05(percentil(scores, 50)),
        "regla": "inferior = percentil 10 y superior = percentil 50 de frame_score, al múltiplo de 0.05 más cercano",
    }
    res: dict[str, Any] = {
        "cuadros": len(eventos),
        "con_detecciones": len(scores),
        "sin_detecciones": sin,
        "error": err,
        "frame_score": {"min": min(scores), "max": max(scores), **p},
        "propuesta": prop,
        "piso_detector": piso,
        "restriccion": "piso < inferior < superior <= 1",
        "restriccion_cumple": piso < prop["umbral_inferior"] < prop["umbral_superior"] <= 1,
    }
    conf = (cfg or {}).get("confianza")
    if conf:
        inf, sup = conf["umbral_inferior"], conf["umbral_superior"]
        baja = sum(1 for s in scores if zona(s, inf, sup) == "baja")
        resumen = resumir_ventanas(
            [
                {
                    **e,
                    "zone": zona(e["frame_score"], inf, sup),
                    "window_id": (e["frame_id"] - 1) // conf["ventana_cuadros"] + 1,
                }
                for e in eventos
            ],
            conf["ventana_cuadros"],
            conf["minimo_con_detecciones"],
        )
        res["configuracion"] = {
            "umbral_inferior": inf,
            "umbral_superior": sup,
            "coincide_con_la_propuesta": (inf, sup)
            == (prop["umbral_inferior"], prop["umbral_superior"]),
            "cuadros_baja": baja,
            "cuadros_duda": sum(1 for s in scores if zona(s, inf, sup) == "duda"),
            "cuadros_aceptada": sum(1 for s in scores if zona(s, inf, sup) == "aceptada"),
            "p_ref_calculado": round(baja / len(scores), 4) if scores else None,
            "p_ref_en_config": cfg.get("referencia", {}).get("p_ref"),
            "ventanas": resumen,
        }
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, required=True, help="carpeta de la corrida de referencia")
    ap.add_argument("--salida", type=Path, required=True, help="carpeta de evidencias")
    ap.add_argument("--config", type=Path, default=RAIZ / "config" / "monitoreo.yaml")
    ap.add_argument(
        "--sin-config",
        action="store_true",
        help="solo la propuesta, sin comparar con la configuración",
    )
    ap.add_argument(
        "--verificar", action="store_true", help="código 1 si la configuración no coincide"
    )
    args = ap.parse_args(argv)

    eventos = leer_eventos(args.run)
    cfg = None if args.sin_config else yaml.safe_load(args.config.read_text(encoding="utf-8"))
    res = calcular(eventos, cfg)
    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "calibracion.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    scores = [e["frame_score"] for e in eventos if e["frame_score"] is not None]
    caja = histograma(scores, res["piso_detector"])
    with (args.salida / "histograma.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["desde", "hasta", "cuadros"])
        w.writerows(caja)
    c = res.get("configuracion")
    (args.salida / "histograma.svg").write_text(
        svg(caja, res["piso_detector"], c and c["umbral_inferior"], c and c["umbral_superior"]),
        encoding="utf-8",
    )

    fs = res["frame_score"]
    print(
        f"{res['cuadros']} cuadros: {res['con_detecciones']} con detecciones, {res['sin_detecciones']} sin, {res['error']} con error"
    )
    print(
        f"frame_score: min {fs['min']} | p10 {fs['p10']} | p50 {fs['p50']} | p90 {fs['p90']} | max {fs['max']}"
    )
    p = res["propuesta"]
    print(
        f"propuesta: inferior {p['umbral_inferior']:.2f} | superior {p['umbral_superior']:.2f} (piso < inferior < superior <= 1: {res['restriccion_cumple']})"
    )
    if c:
        print(
            f"configuración: inferior {c['umbral_inferior']:.2f} | superior {c['umbral_superior']:.2f} | coincide: {c['coincide_con_la_propuesta']}"
        )
        print(
            f"zonas: baja {c['cuadros_baja']} | duda {c['cuadros_duda']} | aceptada {c['cuadros_aceptada']} | p_ref calculado {c['p_ref_calculado']} (config: {c['p_ref_en_config']})"
        )
        print("ventanas (proporción baja):", [v["proporcion_baja"] for v in c["ventanas"]])
        if args.verificar:
            ok = c["coincide_con_la_propuesta"] and c["p_ref_calculado"] == c["p_ref_en_config"]
            return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
