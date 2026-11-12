"""Persistencia: SQLite con corridas, eventos y alertas, y exportación a JSONL.

    python -m p6.almacen exportar --db resultados/monitoreo.db --run-id c1-normal \\
        --salida resultados/c1-normal

Las columnas de `eventos` y `alertas` salen de los campos del contrato
(`p6.contrato.CAMPOS_EVENTO` y `CAMPOS_ALERTA`), en el mismo orden. Un evento se guarda y se
lee como el mismo diccionario: las listas van como JSON, los booleanos como 0/1 y los
números como REAL. `eventos.jsonl` y `alertas.jsonl` de cada corrida se exportan desde aquí,
de modo que la base de datos es la fuente y los JSONL son su copia legible.

La tabla `corridas` guarda, además de `run.json`, el texto completo de la configuración
usada: el portal puede mostrar la configuración que produjo cada evento y comprobar su
SHA-256.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from p6.contrato import CAMPOS_ALERTA, CAMPOS_EVENTO, Campo

TIPO_SQL = {
    "texto": "TEXT",
    "fecha": "TEXT",
    "entero": "INTEGER",
    "numero": "REAL",
    "booleano": "INTEGER",
    "lista": "TEXT",
}


def _columnas(campos: tuple[Campo, ...], clave: str) -> str:
    cols = []
    for c in campos:
        nulo = "" if c.nulable or c.desde != "H1" else " NOT NULL"
        pk = " PRIMARY KEY" if c.nombre == clave else ""
        cols.append(f"{c.nombre} {TIPO_SQL[c.tipo]}{pk}{nulo}")
    return ", ".join(cols)


ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS corridas (
    run_id TEXT PRIMARY KEY,
    carpeta TEXT NOT NULL,
    inicio_utc TEXT NOT NULL,
    fin_utc TEXT,
    source_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    config_texto TEXT NOT NULL,
    etapa_contrato TEXT NOT NULL,
    run_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos ({_columnas(CAMPOS_EVENTO, "event_id")});
CREATE INDEX IF NOT EXISTS eventos_run ON eventos (run_id, frame_id);
CREATE INDEX IF NOT EXISTS eventos_filtros ON eventos (run_id, status, zone, window_id);
CREATE TABLE IF NOT EXISTS alertas ({_columnas(CAMPOS_ALERTA, "alert_id")});
CREATE INDEX IF NOT EXISTS alertas_run ON alertas (run_id, opened_window_id);
"""


def _a_sql(campo: Campo, valor: Any) -> Any:
    if valor is None:
        return None
    if campo.tipo == "lista":
        return json.dumps(valor, ensure_ascii=False)
    if campo.tipo == "booleano":
        return int(valor)
    if campo.tipo == "numero":
        return float(valor)
    return valor


def _de_sql(campo: Campo, valor: Any) -> Any:
    if valor is None:
        return None
    if campo.tipo == "lista":
        return json.loads(valor)
    if campo.tipo == "booleano":
        return bool(valor)
    if campo.tipo == "numero":
        return float(valor)
    return valor


def _fila_a_dict(campos: tuple[Campo, ...], fila: sqlite3.Row) -> dict[str, Any]:
    return {c.nombre: _de_sql(c, fila[c.nombre]) for c in campos}


class AlmacenError(RuntimeError):
    """La base de datos no se puede abrir o la operación no es válida."""


class Almacen:
    """Acceso a `monitoreo.db`. Con `solo_lectura=True` (el portal) no escribe nada."""

    def __init__(self, ruta: Path | str, solo_lectura: bool = False) -> None:
        self.ruta = Path(ruta)
        try:
            if solo_lectura:
                if not self.ruta.is_file():
                    raise AlmacenError(f"no existe la base de datos {self.ruta}")
                uri = f"file:{self.ruta.resolve()}?mode=ro"
                self._con = sqlite3.connect(uri, uri=True, check_same_thread=False)
            else:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                self._con = sqlite3.connect(self.ruta, check_same_thread=False)
                self._con.execute("PRAGMA journal_mode=WAL")  # el portal lee mientras se escribe
                self._con.executescript(ESQUEMA)
        except sqlite3.Error as exc:
            raise AlmacenError(f"{self.ruta}: {exc}") from exc
        self._con.row_factory = sqlite3.Row

    def cerrar(self) -> None:
        self._con.close()

    def __enter__(self) -> Almacen:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cerrar()

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        with self._con:
            yield

    # ---- corridas -------------------------------------------------------------------
    def existe_corrida(self, run_id: str) -> bool:
        fila = self._con.execute("SELECT 1 FROM corridas WHERE run_id = ?", (run_id,)).fetchone()
        return fila is not None

    def borrar_corrida(self, run_id: str) -> None:
        """Quita la corrida y sus eventos y alertas (solo con `--sobrescribir`)."""
        with self._con:
            for tabla in ("eventos", "alertas", "corridas"):
                self._con.execute(f"DELETE FROM {tabla} WHERE run_id = ?", (run_id,))

    def guardar_corrida(self, run: dict[str, Any], carpeta: str, config_texto: str) -> None:
        """Inserta o actualiza la corrida con el contenido actual de `run.json`."""
        with self._con:
            self._con.execute(
                """INSERT INTO corridas (run_id, carpeta, inicio_utc, fin_utc, source_id,
                       model_version, model_sha256, config_sha256, config_texto,
                       etapa_contrato, run_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET fin_utc = excluded.fin_utc,
                       run_json = excluded.run_json""",
                (
                    run["run_id"],
                    carpeta,
                    run["inicio_utc"],
                    run["fin_utc"],
                    run["fuente"]["source_id"],
                    run["modelo"]["version"],
                    run["modelo"]["sha256"],
                    run["configuracion"]["sha256"],
                    config_texto,
                    run["contrato"]["etapa"],
                    json.dumps(run, ensure_ascii=False),
                ),
            )

    def corridas(self) -> list[dict[str, Any]]:
        filas = self._con.execute(
            """SELECT c.run_id, c.carpeta, c.inicio_utc, c.fin_utc, c.source_id,
                      c.model_version, c.model_sha256, c.config_sha256, c.etapa_contrato,
                      (SELECT COUNT(*) FROM eventos e WHERE e.run_id = c.run_id) AS eventos,
                      (SELECT COUNT(*) FROM alertas a WHERE a.run_id = c.run_id) AS alertas
               FROM corridas c ORDER BY c.inicio_utc DESC"""
        ).fetchall()
        return [dict(f) for f in filas]

    def corrida(self, run_id: str) -> dict[str, Any] | None:
        fila = self._con.execute("SELECT * FROM corridas WHERE run_id = ?", (run_id,)).fetchone()
        if fila is None:
            return None
        d = dict(fila)
        d["run"] = json.loads(d.pop("run_json"))
        return d

    def configuracion(self, sha256: str) -> dict[str, Any] | None:
        """Texto de la configuración con ese SHA-256 y las corridas que la usaron."""
        filas = self._con.execute(
            "SELECT run_id, config_texto FROM corridas WHERE config_sha256 = ? ORDER BY run_id",
            (sha256,),
        ).fetchall()
        if not filas:
            return None
        return {"texto": filas[0]["config_texto"], "corridas": [f["run_id"] for f in filas]}

    # ---- eventos --------------------------------------------------------------------
    def insertar_eventos(self, eventos: Iterable[dict[str, Any]]) -> int:
        nombres = [c.nombre for c in CAMPOS_EVENTO]
        sql = (
            f"INSERT INTO eventos ({', '.join(nombres)}) VALUES ({', '.join('?' for _ in nombres)})"
        )
        filas = [tuple(_a_sql(c, e.get(c.nombre)) for c in CAMPOS_EVENTO) for e in eventos]
        with self._con:
            self._con.executemany(sql, filas)
        return len(filas)

    def evento(self, event_id: str) -> dict[str, Any] | None:
        fila = self._con.execute("SELECT * FROM eventos WHERE event_id = ?", (event_id,)).fetchone()
        return None if fila is None else _fila_a_dict(CAMPOS_EVENTO, fila)

    @staticmethod
    def _filtro(
        run_id: str | None,
        status: str | None,
        zone: str | None,
        window_id: int | None,
        con_captura: bool | None,
    ) -> tuple[str, list[Any]]:
        condiciones, args = [], []
        if run_id:
            condiciones.append("run_id = ?")
            args.append(run_id)
        if status:
            condiciones.append("status = ?")
            args.append(status)
        if zone == "ninguna":
            condiciones.append("zone IS NULL")
        elif zone:
            condiciones.append("zone = ?")
            args.append(zone)
        if window_id is not None:
            condiciones.append("window_id = ?")
            args.append(window_id)
        if con_captura is True:
            condiciones.append("image_ref IS NOT NULL")
        elif con_captura is False:
            condiciones.append("image_ref IS NULL")
        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        return where, args

    def eventos(
        self,
        run_id: str | None = None,
        status: str | None = None,
        zone: str | None = None,
        window_id: int | None = None,
        con_captura: bool | None = None,
        limite: int | None = None,
        desde: int = 0,
    ) -> list[dict[str, Any]]:
        where, args = self._filtro(run_id, status, zone, window_id, con_captura)
        sql = f"SELECT * FROM eventos {where} ORDER BY run_id, frame_id"
        if limite is not None:
            sql += " LIMIT ? OFFSET ?"
            args += [limite, desde]
        return [_fila_a_dict(CAMPOS_EVENTO, f) for f in self._con.execute(sql, args)]

    def contar_eventos(
        self,
        run_id: str | None = None,
        status: str | None = None,
        zone: str | None = None,
        window_id: int | None = None,
        con_captura: bool | None = None,
    ) -> int:
        where, args = self._filtro(run_id, status, zone, window_id, con_captura)
        return self._con.execute(f"SELECT COUNT(*) FROM eventos {where}", args).fetchone()[0]

    def vecinos(self, evento: dict[str, Any]) -> tuple[str | None, str | None]:
        """`event_id` del cuadro anterior y del siguiente de la misma corrida."""
        ant = self._con.execute(
            "SELECT event_id FROM eventos WHERE run_id = ? AND frame_id < ? "
            "ORDER BY frame_id DESC LIMIT 1",
            (evento["run_id"], evento["frame_id"]),
        ).fetchone()
        sig = self._con.execute(
            "SELECT event_id FROM eventos WHERE run_id = ? AND frame_id > ? "
            "ORDER BY frame_id LIMIT 1",
            (evento["run_id"], evento["frame_id"]),
        ).fetchone()
        return (ant[0] if ant else None, sig[0] if sig else None)

    # ---- alertas --------------------------------------------------------------------
    def guardar_alertas(self, alertas: Iterable[dict[str, Any]]) -> int:
        """Inserta o reemplaza alertas (una alerta abierta se actualiza al cerrarse)."""
        nombres = [c.nombre for c in CAMPOS_ALERTA]
        sql = (
            f"INSERT OR REPLACE INTO alertas ({', '.join(nombres)}) "
            f"VALUES ({', '.join('?' for _ in nombres)})"
        )
        filas = [tuple(_a_sql(c, a.get(c.nombre)) for c in CAMPOS_ALERTA) for a in alertas]
        with self._con:
            self._con.executemany(sql, filas)
        return len(filas)

    def alertas(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id:
            filas = self._con.execute(
                "SELECT * FROM alertas WHERE run_id = ? ORDER BY opened_window_id, alert_id",
                (run_id,),
            )
        else:
            filas = self._con.execute("SELECT * FROM alertas ORDER BY run_id, opened_window_id")
        return [_fila_a_dict(CAMPOS_ALERTA, f) for f in filas]

    def alerta(self, alert_id: str) -> dict[str, Any] | None:
        fila = self._con.execute("SELECT * FROM alertas WHERE alert_id = ?", (alert_id,)).fetchone()
        return None if fila is None else _fila_a_dict(CAMPOS_ALERTA, fila)

    # ---- exportación ----------------------------------------------------------------
    def exportar(self, run_id: str, carpeta: Path) -> dict[str, int]:
        """Escribe `eventos.jsonl` y `alertas.jsonl` de la corrida desde la base de datos."""
        carpeta.mkdir(parents=True, exist_ok=True)
        eventos = self.eventos(run_id=run_id)
        alertas = self.alertas(run_id=run_id)
        for nombre, registros in (("eventos.jsonl", eventos), ("alertas.jsonl", alertas)):
            with (carpeta / nombre).open("w", encoding="utf-8") as f:
                for r in registros:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return {"eventos": len(eventos), "alertas": len(alertas)}


def leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(ruta).read_text(encoding="utf-8").splitlines() if x]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m p6.almacen", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    ex = sub.add_parser("exportar", help="escribe eventos.jsonl y alertas.jsonl de una corrida")
    ex.add_argument("--db", type=Path, default=Path("resultados/monitoreo.db"))
    ex.add_argument("--run-id", required=True)
    ex.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        with Almacen(args.db, solo_lectura=True) as db:
            if not db.existe_corrida(args.run_id):
                print(f"ERROR: la corrida {args.run_id} no está en {args.db}", file=sys.stderr)
                return 2
            n = db.exportar(args.run_id, args.salida)
    except (AlmacenError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"{n['eventos']} eventos y {n['alertas']} alertas -> {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
