"""Reglas de alerta A y B evaluadas por ventana (ver `docs/politica.md`, sección 6).

`EvaluadorReglas` se llama al cerrar cada ventana con su resumen (`p6.politica`) y sus
eventos, y devuelve las alertas que esa ventana abrió, extendió o cerró, listas para
guardarse con el contrato de alerta.

- **A · baja confianza:** en una ventana suficiente, proporción baja ≥ `proporcion_minima`.
- **B · cambio sostenido:** proporción baja > `p_ref + margen` en `ventanas_seguidas`
  ventanas suficientes consecutivas.

Ciclo de vida, igual para las dos:

- Se **abre** cuando la condición se cumple (para B, al completar la racha) y no hay otra
  alerta abierta de la misma regla.
- Mientras la condición se siga cumpliendo, la misma alerta se **extiende** con la nueva
  ventana: un episodio continuo es una sola alerta.
- Se **cierra** en la primera ventana suficiente en que la condición deja de cumplirse.
- Una ventana **insuficiente** no abre, no extiende, no cierra y no rompe la racha de B.
- Al terminar la corrida, las alertas que siguen abiertas quedan `abierta`.

Los eventos que explican una alerta (`event_ids`) son los cuadros en zona baja de las
ventanas donde se cumplió la condición; `window_ids` son esas ventanas.
"""

from __future__ import annotations

from typing import Any

from p6.config import Config
from p6.contrato import validar_alerta


class EvaluadorReglas:
    """Estado de las reglas a lo largo de una corrida."""

    def __init__(self, cfg: Config, run_id: str) -> None:
        self.cfg = cfg
        self.run_id = run_id
        self.limite_b = round(cfg.referencia.p_ref + cfg.regla_b.margen_sobre_referencia, 4)
        self.abiertas: dict[str, dict[str, Any]] = {}
        self.contador = {"A": 0, "B": 0}
        # Racha de B: ventanas suficientes seguidas que superan el límite, con sus eventos bajos.
        self.racha: list[tuple[int, float, list[str]]] = []
        self.todas: list[dict[str, Any]] = []

    # ---- condiciones ---------------------------------------------------------------
    def cumple_a(self, proporcion: float) -> bool:
        return proporcion >= self.cfg.regla_a.proporcion_minima

    def cumple_b(self, proporcion: float) -> bool:
        return proporcion > self.limite_b

    # ---- evaluación ----------------------------------------------------------------
    def __call__(self, resumen: dict[str, Any], eventos: list[dict[str, Any]]) -> list[dict]:
        """Evalúa una ventana cerrada; devuelve las alertas que cambiaron en ella."""
        if not resumen["suficiente"]:
            return []  # sin evidencia suficiente no se abre, extiende, cierra ni rompe nada
        w = resumen["window_id"]
        p = resumen["proporcion_baja"]
        bajos = [
            e["event_id"]
            for e in sorted(eventos, key=lambda e: e["frame_id"])
            if e["zone"] == "baja"
        ]
        instante = max(eventos, key=lambda e: e["frame_id"])["t_capture_utc"]  # último cuadro
        detalle = f"{resumen['baja']} de {resumen['con_detecciones']} cuadros con detecciones"
        cambios: list[dict[str, Any]] = []

        # Regla A
        if self.cumple_a(p):
            if "A" in self.abiertas:
                cambios.append(self._extender("A", w, p, bajos))
            else:
                cambios.append(
                    self._abrir(
                        "A",
                        w,
                        instante,
                        [w],
                        bajos,
                        f"proporción de baja confianza {p:.2f} ≥ "
                        f"{self.cfg.regla_a.proporcion_minima:.2f} en la ventana {w} ({detalle})",
                        [p],
                    )
                )
        elif "A" in self.abiertas:
            cambios.append(
                self._cerrar("A", w, instante, p, "<", self.cfg.regla_a.proporcion_minima)
            )

        # Regla B
        if self.cumple_b(p):
            self.racha.append((w, p, bajos))
            n = self.cfg.regla_b.ventanas_seguidas
            if "B" in self.abiertas:
                cambios.append(self._extender("B", w, p, bajos))
            elif len(self.racha) >= n:
                tramo = self.racha[-n:]
                props = ", ".join(f"{q:.2f}" for _, q, _ in tramo)
                cambios.append(
                    self._abrir(
                        "B",
                        w,
                        instante,
                        [v for v, _, _ in tramo],
                        [e for _, _, ids in tramo for e in ids],
                        f"proporción de baja confianza > {self.limite_b:.4f} "
                        f"(p_ref {self.cfg.referencia.p_ref:.4f} + margen "
                        f"{self.cfg.regla_b.margen_sobre_referencia:.2f}) en {n} ventanas "
                        f"suficientes seguidas ({tramo[0][0]}–{w}: {props})",
                        [q for _, q, _ in tramo],
                    )
                )
        else:
            self.racha.clear()
            if "B" in self.abiertas:
                cambios.append(self._cerrar("B", w, instante, p, "≤", self.limite_b))
        return cambios

    # ---- ciclo de vida -------------------------------------------------------------
    def _abrir(
        self,
        regla: str,
        w: int,
        instante: str,
        ventanas: list[int],
        event_ids: list[str],
        motivo: str,
        proporciones: list[float],
    ) -> dict[str, Any]:
        self.contador[regla] += 1
        conf = self.cfg.regla_a if regla == "A" else self.cfg.regla_b
        alerta = {
            "alert_id": f"{self.run_id}-{regla}-{self.contador[regla]}",
            "rule_id": regla,
            "run_id": self.run_id,
            "status": "abierta",
            "opened_at": instante,
            "opened_window_id": w,
            "closed_at": None,
            "closed_window_id": None,
            "severity": conf.severidad,
            "reason": motivo,
            "window_ids": list(ventanas),
            "event_ids": list(event_ids),
            "config_sha256": self.cfg.sha256,
            "suggested_action": conf.accion_sugerida,
        }
        alerta["_inicio"] = motivo
        alerta["_proporciones"] = list(proporciones)
        self.abiertas[regla] = alerta
        self.todas.append(alerta)
        return self._publica(alerta)

    def _extender(self, regla: str, w: int, p: float, event_ids: list[str]) -> dict[str, Any]:
        alerta = self.abiertas[regla]
        alerta["window_ids"].append(w)
        alerta["event_ids"].extend(event_ids)
        alerta["_proporciones"].append(p)
        sigue = alerta["window_ids"][alerta["window_ids"].index(alerta["opened_window_id"]) + 1 :]
        props = alerta["_proporciones"][-len(sigue) :]
        alerta["reason"] = (
            f"{alerta['_inicio']}; sigue en las ventanas {', '.join(map(str, sigue))} "
            f"(proporciones {', '.join(f'{q:.2f}' for q in props)})"
        )
        return self._publica(alerta)

    def _cerrar(
        self, regla: str, w: int, instante: str, p: float, signo: str, limite: float
    ) -> dict[str, Any]:
        alerta = self.abiertas.pop(regla)
        alerta.update(status="cerrada", closed_at=instante, closed_window_id=w)
        alerta["reason"] += f"; se cerró en la ventana {w}: proporción {p:.2f} {signo} {limite:.4g}"
        return self._publica(alerta)

    @staticmethod
    def _publica(alerta: dict[str, Any]) -> dict[str, Any]:
        """Copia sin los campos internos, validada con el contrato de alerta."""
        publica = {
            k: (list(v) if isinstance(v, list) else v)
            for k, v in alerta.items()
            if not k.startswith("_")
        }
        problemas = validar_alerta(publica)
        if problemas:  # sería un error de programa, no de los datos
            raise ValueError(f"alerta {publica['alert_id']} no cumple el contrato: {problemas}")
        return publica
