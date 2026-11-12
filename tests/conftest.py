from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = RAIZ / "config" / "monitoreo.yaml"
DESCRIPTOR = RAIZ / "modelo" / "descriptor.yaml"
PESOS = RAIZ / "modelo" / "yolox_nano.onnx"
VIDEO_NORMAL = RAIZ / "datos" / "videos" / "normal.mp4"

requiere_modelo = pytest.mark.skipif(
    not PESOS.is_file(),
    reason="faltan los pesos: python scripts/descargar_modelo.py --destino modelo/",
)


@pytest.fixture(scope="session")
def clases() -> list[str]:
    return list(yaml.safe_load(DESCRIPTOR.read_text(encoding="utf-8"))["clases"])
