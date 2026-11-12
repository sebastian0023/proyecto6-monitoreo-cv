"""Convierte una grabación (.mov de QuickTime) en el .mp4 que usa el monitoreo.

    python scripts/preparar_video.py datos/videos/originales/normal.mov datos/videos/normal.mp4

- Tamaño de salida 640x480 (`--ancho`, `--alto`).
- Ritmo constante de `--fps` cuadros/s (15 por defecto). Las cámaras graban a ritmo variable
  (23.5 fps de promedio con buena luz, 15 con poca); se remuestrea por marca de tiempo para
  que los tres videos tengan el mismo ritmo y el muestreo a 5 cuadros/s sea siempre 1 de cada 3.
- `--ajuste` decide cómo pasar de 16:9 a 4:3: `recortar` (centro, sin deformar; por defecto),
  `barras` (la imagen completa con franjas negras) o `estirar` (deforma).

Solo cambia el formato: no modifica brillo, contraste ni nitidez.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def ajustar(cuadro: np.ndarray, ancho: int, alto: int, modo: str) -> np.ndarray:
    """Lleva un cuadro BGR a `ancho`x`alto` según `modo`."""
    h, w = cuadro.shape[:2]
    if modo == "estirar":
        return cv2.resize(cuadro, (ancho, alto), interpolation=cv2.INTER_AREA)
    if modo == "recortar":
        objetivo = ancho / alto
        if w / h > objetivo:  # más ancho que el destino: se recortan los lados
            nuevo_w = round(h * objetivo)
            x0 = (w - nuevo_w) // 2
            cuadro = cuadro[:, x0 : x0 + nuevo_w]
        else:  # más alto: se recortan arriba y abajo
            nuevo_h = round(w / objetivo)
            y0 = (h - nuevo_h) // 2
            cuadro = cuadro[y0 : y0 + nuevo_h]
        return cv2.resize(cuadro, (ancho, alto), interpolation=cv2.INTER_AREA)
    if modo == "barras":
        escala = min(ancho / w, alto / h)
        nuevo = cv2.resize(
            cuadro, (round(w * escala), round(h * escala)), interpolation=cv2.INTER_AREA
        )
        lienzo = np.zeros((alto, ancho, 3), dtype=np.uint8)
        y0, x0 = (alto - nuevo.shape[0]) // 2, (ancho - nuevo.shape[1]) // 2
        lienzo[y0 : y0 + nuevo.shape[0], x0 : x0 + nuevo.shape[1]] = nuevo
        return lienzo
    raise ValueError(f"ajuste desconocido: {modo}")


def convertir(
    entrada: Path, salida: Path, ancho: int, alto: int, fps: float, modo: str
) -> dict[str, float]:
    """Escribe `salida` y devuelve un resumen. Levanta OSError si no puede leer o escribir."""
    cap = cv2.VideoCapture(str(entrada))
    if not cap.isOpened():
        raise OSError(f"no se pudo abrir {entrada}")
    fps_origen = cap.get(cv2.CAP_PROP_FPS) or 0.0
    salida.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(
        str(salida), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ancho, alto), isColor=True
    )
    if not escritor.isOpened():
        cap.release()
        raise OSError(f"no se pudo escribir {salida}")

    leidos = escritos = 0
    paso_ms = 1000.0 / fps
    anterior: np.ndarray | None = None
    t_anterior = 0.0
    try:
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC)
            if not t and fps_origen:  # sin marcas de tiempo: se usa el índice y el ritmo medio
                t = leidos * 1000.0 / fps_origen
            leidos += 1
            # Cada instante de salida toma el cuadro de origen más cercano en el tiempo.
            while escritos * paso_ms <= t:
                t_salida = escritos * paso_ms
                elegido = cuadro
                if anterior is not None and (t_salida - t_anterior) < (t - t_salida):
                    elegido = anterior
                escritor.write(ajustar(elegido, ancho, alto, modo))
                escritos += 1
            anterior, t_anterior = cuadro, t
    finally:
        cap.release()
        escritor.release()
    if escritos == 0:
        raise OSError(f"{entrada} no tiene cuadros legibles")
    return {
        "fps_origen": round(fps_origen, 2),
        "cuadros_leidos": leidos,
        "cuadros_escritos": escritos,
        "duracion_s": round(escritos / fps, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("entrada", type=Path, help="grabación original (.mov, .mp4...)")
    parser.add_argument("salida", type=Path, help="archivo .mp4 de salida")
    parser.add_argument("--ancho", type=int, default=640)
    parser.add_argument("--alto", type=int, default=480)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--ajuste", choices=["recortar", "barras", "estirar"], default="recortar")
    args = parser.parse_args(argv)
    try:
        r = convertir(args.entrada, args.salida, args.ancho, args.alto, args.fps, args.ajuste)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(
        f"{args.entrada.name} -> {args.salida} ({args.ancho}x{args.alto}, {args.fps:g} fps, "
        f"ajuste {args.ajuste}): {r['cuadros_escritos']} cuadros, {r['duracion_s']} s "
        f"(origen {r['fps_origen']} fps, {r['cuadros_leidos']} cuadros)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
