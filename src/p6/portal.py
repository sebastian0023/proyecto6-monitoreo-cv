"""Portal de consulta: eventos, sus capturas y la configuración que los produjo.

    python -m p6.portal --db resultados/monitoreo.db      # http://127.0.0.1:8000

Solo lee la base de datos (modo de solo lectura) y los archivos de captura; no modifica nada.

Páginas:

- `/eventos`: lista con filtros por corrida, estado, zona, ventana y captura.
- `/eventos.csv`: los eventos filtrados (todos, sin paginar) en CSV.
- `/eventos/{event_id}`: detecciones, zona, ventana, captura (verificada por SHA-256) y
  enlaces a la configuración y a la corrida.
- `/capturas/{event_id}`: el JPEG, solo si existe y su SHA-256 coincide con el del evento.
- `/configuracion/{sha256}`: el texto de la configuración, con su SHA-256 comprobado.
- `/alertas`: lista con filtros por corrida, estado y regla (momento, motivo, severidad).
- `/alertas/{alert_id}`: regla, ventanas y los eventos que la explican, con sus capturas.
- `/corridas` y `/corridas/{run_id}`: corridas, su `run.json`, el resumen por ventana y sus
  alertas.
- `/api/eventos`, `/api/eventos/{event_id}`, `/api/alertas` y `/api/alertas/{alert_id}`: lo
  mismo en JSON.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from PIL import Image

from p6 import capturas
from p6.almacen import Almacen, AlmacenError
from p6.contrato import ESTADOS, ESTADOS_ALERTA, ZONAS

POR_PAGINA = 50
# Columnas del CSV de eventos: los campos del contrato, en lista plana, más un resumen de las
# detecciones y el estado verificado de la captura.
COLUMNAS_CSV = (
    "event_id",
    "run_id",
    "frame_id",
    "t_capture_utc",
    "source_id",
    "origen",
    "status",
    "error_msg",
    "frame_score",
    "zone",
    "window_id",
    "n_detecciones",
    "mejor_clase",
    "mejor_score",
    "detections",
    "t_pre_ms",
    "t_infer_ms",
    "t_post_ms",
    "rss_mb",
    "warmup",
    "model_version",
    "model_sha256",
    "config_sha256",
    "image_ref",
    "image_sha256",
    "image_reason",
    "captura",
)


def eventos_a_csv(eventos: list[dict[str, Any]]) -> str:
    """CSV con encabezado; una fila por evento. Sin eventos, solo el encabezado."""
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    w.writerow(COLUMNAS_CSV)
    for e in eventos:
        mejor = e["detections"][0] if e["detections"] else None
        fila = {
            **e,
            "n_detecciones": len(e["detections"]),
            "mejor_clase": mejor["class_name"] if mejor else None,
            "mejor_score": mejor["score"] if mejor else None,
            "detections": json.dumps(e["detections"], ensure_ascii=False),
            "warmup": "true" if e["warmup"] else "false",
            "captura": e.get("_captura"),
        }
        w.writerow(["" if fila.get(c) is None else fila[c] for c in COLUMNAS_CSV])
    return salida.getvalue()


PLANTILLAS = Path(__file__).resolve().parent / "plantillas"

ESTADO_CAPTURA = {
    "ok": "verificada",
    "sin_captura": "sin captura",
    "no_existe": "rota: el archivo no existe",
    "alterada": "rota: el SHA-256 no coincide",
    "ruta_invalida": "rota: la ruta sale de la carpeta de la corrida",
}


class FiltroInvalido(ValueError):
    pass


def _texto_o_none(valor: str | None) -> str | None:
    return valor if valor not in (None, "") else None


def _leer_filtros(
    run_id: str | None,
    status: str | None,
    zone: str | None,
    ventana: str | None,
    captura: str | None,
    pagina: str | None,
) -> dict[str, Any]:
    f = {
        "run_id": _texto_o_none(run_id),
        "status": _texto_o_none(status),
        "zone": _texto_o_none(zone),
        "window_id": None,
        "con_captura": None,
    }
    if f["status"] is not None and f["status"] not in ESTADOS:
        raise FiltroInvalido(f"estado desconocido {status!r}; usa uno de {ESTADOS}")
    if f["zone"] is not None and f["zone"] not in (*ZONAS, "ninguna"):
        raise FiltroInvalido(f"zona desconocida {zone!r}; usa una de {(*ZONAS, 'ninguna')}")
    if _texto_o_none(ventana) is not None:
        if not ventana.isdigit() or int(ventana) < 1:
            raise FiltroInvalido(f"ventana inválida {ventana!r}; debe ser un entero ≥ 1")
        f["window_id"] = int(ventana)
    if _texto_o_none(captura) is not None:
        if captura not in ("si", "no"):
            raise FiltroInvalido(f"captura inválida {captura!r}; usa 'si' o 'no'")
        f["con_captura"] = captura == "si"
    p = _texto_o_none(pagina) or "1"
    if not p.isdigit() or int(p) < 1:
        raise FiltroInvalido(f"página inválida {pagina!r}")
    f["pagina"] = int(p)
    return f


def crear_app(ruta_db: Path | str) -> FastAPI:
    ruta_db = Path(ruta_db)
    base_resultados = ruta_db.resolve().parent
    app = FastAPI(title="Monitoreo CV · Proyecto 6", docs_url=None, redoc_url=None)
    plantillas = Jinja2Templates(directory=str(PLANTILLAS))

    def abrir() -> Almacen:
        try:
            return Almacen(ruta_db, solo_lectura=True)
        except AlmacenError as exc:
            raise HTTPException(503, str(exc)) from exc

    def carpeta_de(db: Almacen, run_id: str) -> Path:
        corrida = db.corrida(run_id)
        if corrida is None:  # un evento siempre tiene su corrida; por si la base está dañada
            raise HTTPException(500, f"la corrida {run_id} no está registrada")
        return base_resultados / corrida["carpeta"]

    def estado_captura(db: Almacen, evento: dict[str, Any], carpetas: dict[str, Path]) -> str:
        if evento["run_id"] not in carpetas:
            carpetas[evento["run_id"]] = carpeta_de(db, evento["run_id"])
        return capturas.verificar(
            carpetas[evento["run_id"]], evento["image_ref"], evento["image_sha256"]
        )

    def render(request: Request, nombre: str, contexto: dict[str, Any], codigo: int = 200):
        return plantillas.TemplateResponse(
            request, nombre, {"estado_captura_texto": ESTADO_CAPTURA, **contexto}, codigo
        )

    @app.exception_handler(HTTPException)
    async def _error(request: Request, exc: HTTPException):
        if request.url.path.startswith(("/api/", "/capturas/")):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        return render(
            request,
            "error.html",
            {"codigo": exc.status_code, "mensaje": exc.detail},
            exc.status_code,
        )

    @app.get("/", include_in_schema=False)
    def inicio() -> RedirectResponse:
        return RedirectResponse("/eventos")

    def _consultar(filtros: dict[str, Any]) -> tuple[list[dict[str, Any]], int, list[dict]]:
        with abrir() as db:
            args = {k: filtros[k] for k in ("run_id", "status", "zone", "window_id", "con_captura")}
            total = db.contar_eventos(**args)
            eventos = db.eventos(
                **args, limite=POR_PAGINA, desde=(filtros["pagina"] - 1) * POR_PAGINA
            )
            carpetas: dict[str, Path] = {}
            for e in eventos:
                e["_captura"] = estado_captura(db, e, carpetas)
            return eventos, total, db.corridas()

    @app.get("/eventos", response_class=HTMLResponse)
    def lista_eventos(
        request: Request,
        run_id: str | None = None,
        status: str | None = None,
        zone: str | None = None,
        ventana: str | None = None,
        captura: str | None = None,
        pagina: str | None = None,
    ):
        try:
            filtros = _leer_filtros(run_id, status, zone, ventana, captura, pagina)
        except FiltroInvalido as exc:
            raise HTTPException(400, str(exc)) from exc
        eventos, total, corridas = _consultar(filtros)
        paginas = max(1, -(-total // POR_PAGINA))
        consulta = {
            k: v
            for k, v in {
                "run_id": run_id,
                "status": status,
                "zone": zone,
                "ventana": ventana,
                "captura": captura,
            }.items()
            if v
        }
        enlace = lambda n: "/eventos?" + urlencode({**consulta, "pagina": n})  # noqa: E731
        csv_url = "/eventos.csv" + ("?" + urlencode(consulta) if consulta else "")
        return render(
            request,
            "eventos.html",
            {
                "eventos": eventos,
                "total": total,
                "filtros": filtros,
                "corridas": corridas,
                "estados": ESTADOS,
                "zonas": ZONAS,
                "csv_url": csv_url,
                "pagina_actual": filtros["pagina"],
                "paginas": paginas,
                "anterior": enlace(filtros["pagina"] - 1) if filtros["pagina"] > 1 else None,
                "siguiente": enlace(filtros["pagina"] + 1) if filtros["pagina"] < paginas else None,
            },
        )

    @app.get("/eventos.csv")
    def eventos_csv(
        run_id: str | None = None,
        status: str | None = None,
        zone: str | None = None,
        ventana: str | None = None,
        captura: str | None = None,
    ) -> Response:
        """Todos los eventos que cumplen los filtros (sin paginar), en CSV."""
        try:
            filtros = _leer_filtros(run_id, status, zone, ventana, captura, None)
        except FiltroInvalido as exc:
            raise HTTPException(400, str(exc)) from exc
        with abrir() as db:
            args = {k: filtros[k] for k in ("run_id", "status", "zone", "window_id", "con_captura")}
            eventos = db.eventos(**args)
            carpetas: dict[str, Path] = {}
            for e in eventos:
                e["_captura"] = estado_captura(db, e, carpetas)
        partes = [run_id or "todas"] + [
            f"{k}-{v}"
            for k, v in (
                ("status", status),
                ("zona", zone),
                ("ventana", ventana),
                ("captura", captura),
            )
            if v
        ]
        nombre = "eventos_" + "_".join(partes) + ".csv"
        return Response(
            "\ufeff" + eventos_a_csv(eventos),  # BOM: Excel reconoce el UTF-8
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre}"',
                "X-Total-Eventos": str(len(eventos)),
            },
        )

    @app.get("/eventos/{event_id}", response_class=HTMLResponse)
    def detalle_evento(request: Request, event_id: str):
        with abrir() as db:
            evento = db.evento(event_id)
            if evento is None:
                raise HTTPException(404, f"no existe el evento {event_id}")
            carpeta = carpeta_de(db, evento["run_id"])
            estado = capturas.verificar(carpeta, evento["image_ref"], evento["image_sha256"])
            tamano = None
            if estado == "ok":
                with Image.open(capturas.ruta(carpeta, evento["image_ref"])) as im:
                    tamano = im.size
            anterior, siguiente = db.vecinos(evento)
            alertas = [a for a in db.alertas(evento["run_id"]) if event_id in a["event_ids"]]
        return render(
            request,
            "evento.html",
            {
                "e": evento,
                "captura": estado,
                "tamano": tamano,
                "anterior": anterior,
                "siguiente": siguiente,
                "alertas": alertas,
            },
        )

    @app.get("/capturas/{event_id}")
    def captura(event_id: str) -> FileResponse:
        with abrir() as db:
            evento = db.evento(event_id)
            if evento is None:
                raise HTTPException(404, f"no existe el evento {event_id}")
            carpeta = carpeta_de(db, evento["run_id"])
        estado = capturas.verificar(carpeta, evento["image_ref"], evento["image_sha256"])
        if estado == "sin_captura":
            raise HTTPException(404, f"el evento {event_id} no tiene captura")
        if estado != "ok":
            raise HTTPException(409, f"captura {ESTADO_CAPTURA[estado]}")
        return FileResponse(capturas.ruta(carpeta, evento["image_ref"]), media_type="image/jpeg")

    @app.get("/configuracion/{sha256}", response_class=HTMLResponse)
    def configuracion(request: Request, sha256: str):
        with abrir() as db:
            conf = db.configuracion(sha256)
        if conf is None:
            raise HTTPException(404, f"no hay ninguna corrida con la configuración {sha256}")
        calculado = hashlib.sha256(conf["texto"].encode("utf-8")).hexdigest()
        return render(
            request,
            "configuracion.html",
            {
                "sha": sha256,
                "calculado": calculado,
                "texto": conf["texto"],
                "corridas": conf["corridas"],
            },
        )

    @app.get("/corridas", response_class=HTMLResponse)
    def lista_corridas(request: Request):
        with abrir() as db:
            corridas = db.corridas()
        return render(request, "corridas.html", {"corridas": corridas})

    @app.get("/corridas/{run_id}", response_class=HTMLResponse)
    def detalle_corrida(request: Request, run_id: str):
        with abrir() as db:
            corrida = db.corrida(run_id)
            alertas = db.alertas(run_id=run_id)
        if corrida is None:
            raise HTTPException(404, f"no existe la corrida {run_id}")
        return render(
            request, "corrida.html", {"c": corrida, "run": corrida["run"], "alertas": alertas}
        )

    def _filtros_alertas(
        run_id: str | None, status: str | None, regla: str | None
    ) -> dict[str, str | None]:
        f = {
            "run_id": _texto_o_none(run_id),
            "status": _texto_o_none(status),
            "rule_id": _texto_o_none(regla),
        }
        if f["status"] is not None and f["status"] not in ESTADOS_ALERTA:
            raise HTTPException(
                400, f"estado de alerta desconocido {status!r}; usa {ESTADOS_ALERTA}"
            )
        if f["rule_id"] is not None and f["rule_id"] not in ("A", "B", "F"):
            raise HTTPException(400, f"regla desconocida {regla!r}; usa A, B o F")
        return f

    def _reglas(db: Almacen, run_id: str) -> dict[str, dict[str, Any]]:
        """Definición de las reglas tal como estaba en la configuración de la corrida."""
        corrida = db.corrida(run_id)
        if corrida is None:
            return {}
        return (yaml.safe_load(corrida["config_texto"]) or {}).get("alertas", {})

    @app.get("/alertas", response_class=HTMLResponse)
    def lista_alertas(
        request: Request,
        run_id: str | None = None,
        status: str | None = None,
        regla: str | None = None,
    ):
        filtros = _filtros_alertas(run_id, status, regla)
        with abrir() as db:
            alertas = db.alertas(**filtros)
            corridas = db.corridas()
            reglas = {c["run_id"]: _reglas(db, c["run_id"]) for c in corridas}
        return render(
            request,
            "alertas.html",
            {
                "alertas": alertas,
                "corridas": corridas,
                "filtros": filtros,
                "reglas": reglas,
                "estados": ESTADOS_ALERTA,
            },
        )

    @app.get("/alertas/{alert_id}", response_class=HTMLResponse)
    def detalle_alerta(request: Request, alert_id: str):
        with abrir() as db:
            alerta = db.alerta(alert_id)
            if alerta is None:
                raise HTTPException(404, f"no existe la alerta {alert_id}")
            regla = _reglas(db, alerta["run_id"]).get(alerta["rule_id"], {})
            corrida = db.corrida(alerta["run_id"])
            carpeta = carpeta_de(db, alerta["run_id"])
            eventos = []
            for event_id in alerta["event_ids"]:
                e = db.evento(event_id)
                if e is None:  # un evento referido que no está: se muestra como faltante
                    eventos.append({"event_id": event_id, "_falta": True})
                    continue
                e["_captura"] = capturas.verificar(carpeta, e["image_ref"], e["image_sha256"])
                eventos.append(e)
        ventanas = {
            v["window_id"]: v
            for v in ((corrida or {}).get("run", {}).get("totales") or {}).get("ventanas", [])
        }
        return render(
            request,
            "alerta.html",
            {
                "a": alerta,
                "regla": regla,
                "eventos": eventos,
                "ventanas": [ventanas.get(w, {"window_id": w}) for w in alerta["window_ids"]],
                "politica": ((corrida or {}).get("run") or {}).get("politica", {}),
            },
        )

    @app.get("/api/alertas")
    def api_alertas(
        run_id: str | None = None, status: str | None = None, regla: str | None = None
    ) -> JSONResponse:
        filtros = _filtros_alertas(run_id, status, regla)
        with abrir() as db:
            alertas = db.alertas(**filtros)
        return JSONResponse({"total": len(alertas), "alertas": alertas})

    @app.get("/api/alertas/{alert_id}")
    def api_alerta(alert_id: str) -> JSONResponse:
        with abrir() as db:
            alerta = db.alerta(alert_id)
        if alerta is None:
            raise HTTPException(404, f"no existe la alerta {alert_id}")
        return JSONResponse({"alerta": alerta})

    @app.get("/api/eventos")
    def api_eventos(
        run_id: str | None = None,
        status: str | None = None,
        zone: str | None = None,
        ventana: str | None = None,
        captura: str | None = None,
        pagina: str | None = None,
    ) -> JSONResponse:
        try:
            filtros = _leer_filtros(run_id, status, zone, ventana, captura, pagina)
        except FiltroInvalido as exc:
            raise HTTPException(400, str(exc)) from exc
        eventos, total, _ = _consultar(filtros)
        for e in eventos:
            e["captura"] = e.pop("_captura")
        return JSONResponse({"total": total, "pagina": filtros["pagina"], "eventos": eventos})

    @app.get("/api/eventos/{event_id}")
    def api_evento(event_id: str) -> JSONResponse:
        with abrir() as db:
            evento = db.evento(event_id)
            if evento is None:
                raise HTTPException(404, f"no existe el evento {event_id}")
            carpeta = carpeta_de(db, evento["run_id"])
        estado = capturas.verificar(carpeta, evento["image_ref"], evento["image_sha256"])
        return JSONResponse({"evento": evento, "captura": estado})

    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m p6.portal", description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=Path("resultados/monitoreo.db"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=8000)
    args = ap.parse_args(argv)
    if not args.db.is_file():
        print(f"ERROR: no existe {args.db}; corre primero python -m p6.monitorear", file=sys.stderr)
        return 2
    import uvicorn

    print(f"portal en http://{args.host}:{args.puerto} (base de datos {args.db})")
    uvicorn.run(crear_app(args.db), host=args.host, port=args.puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
