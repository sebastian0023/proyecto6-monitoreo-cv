"""Descarga (o verifica) las 78 fotos del carrito del Proyecto 5, la segunda fuente (#13).

    python scripts/descargar_fotos_carrito.py              # verifica las fotos de datos/carrito/
    python scripts/descargar_fotos_carrito.py --descargar  # las baja del repositorio de P5

Las fotos son las capturas de evaluación del Proyecto 5 (`Proyecto5/datos/evaluacion/S1…S6`)
del repositorio público sebastian0023/Proyecto-3-Clasificador-de-imagenes, en el commit
`b63ddbc` (tag `p5-entrega`). `datos/carrito/manifiesto.csv` lista cada archivo con el
SHA-256 que registró P5. Solo se copian las imágenes: las anotaciones de P5 no se usan.

Con `--descargar`, cada archivo se escribe solo si su SHA-256 coincide con el del
manifiesto. Sin la opción, se comprueba que cada foto exista y coincida.
Códigos de salida: 0 todo coincide; 1 falta o no coincide alguna foto; 2 error de red o disco.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "datos" / "carrito"
MANIFIESTO = CARPETA / "manifiesto.csv"
COMMIT_P5 = "b63ddbc91a45db90d857c635def6a344ce895b09"
URL_BASE = (
    "https://raw.githubusercontent.com/sebastian0023/Proyecto-3-Clasificador-de-imagenes/"
    f"{COMMIT_P5}/"
)


def leer_manifiesto(ruta: Path = MANIFIESTO) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--descargar", action="store_true", help="bajar las fotos del repo de P5")
    ap.add_argument("--carpeta", type=Path, default=CARPETA)
    args = ap.parse_args(argv)
    filas = leer_manifiesto()
    contexto = ssl.create_default_context(cafile=certifi.where())
    malas = 0
    for fila in filas:
        destino = args.carpeta / fila["archivo"]
        if args.descargar:
            try:
                peticion = urllib.request.Request(
                    URL_BASE + fila["origen"], headers={"User-Agent": "p6-fotos-carrito/1.0"}
                )
                with urllib.request.urlopen(peticion, timeout=60, context=contexto) as r:
                    datos = r.read()
            except OSError as exc:
                print(f"ERROR: {fila['origen']}: {exc}", file=sys.stderr)
                return 2
            if sha256(datos) != fila["sha256"]:
                print(f"NO COINCIDE: {fila['archivo']}", file=sys.stderr)
                malas += 1
                continue
            args.carpeta.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(datos)
        elif not destino.is_file() or sha256(destino.read_bytes()) != fila["sha256"]:
            print(f"{'NO COINCIDE' if destino.is_file() else 'FALTA'}: {fila['archivo']}")
            malas += 1
    accion = "descargadas" if args.descargar else "verificadas"
    print(f"{len(filas) - malas} de {len(filas)} fotos {accion} contra {MANIFIESTO.name}")
    return 1 if malas else 0


if __name__ == "__main__":
    sys.exit(main())
