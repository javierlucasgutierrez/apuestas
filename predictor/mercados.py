"""Predicción completa de un partido: goles, córners y la probabilidad de cada mercado."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date

from .calibracion import aplicar
from .datos import Partido, cara_a_cara
from .modelo import ModeloFuerzas, buscar_equipo

LINEAS_GOLES = [1.5, 2.5, 3.5]
LINEAS_CORNERS = [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]


def familia(mercado: str) -> str:
    """Agrupa los mercados para los informes."""
    if mercado in ("1", "X", "2"):
        return "1X2"
    if mercado in ("1X", "X2", "12"):
        return "Doble oportunidad"
    if mercado.startswith("Ambos"):
        return "Ambos marcan"
    if mercado.startswith("Goles"):
        return "Goles más/menos"
    return "Córners más/menos"


def acierta(mercado: str, p: Partido) -> bool | None:
    """¿Se cumplió el mercado en el partido? None si falta el dato."""
    if mercado.startswith("Córners"):
        if not p.con_corners:
            return None
        total, linea = p.corners_local + p.corners_visitante, float(mercado.split()[1][1:])
        return total > linea if "+" in mercado else total < linea
    if not p.jugado:
        return None
    goles = p.goles_local + p.goles_visitante
    if mercado.startswith("Goles"):
        linea = float(mercado.split()[1][1:])
        return goles > linea if "+" in mercado else goles < linea
    if mercado == "Ambos marcan: sí":
        return p.goles_local > 0 and p.goles_visitante > 0
    if mercado == "Ambos marcan: no":
        return not (p.goles_local > 0 and p.goles_visitante > 0)
    return p.resultado in mercado


@dataclass
class Ajustes:
    vida_media_goles: float = 180.0
    vida_media_corners: float = 180.0
    regularizacion_goles: float = 2.0
    regularizacion_corners: float = 2.0
    peso_h2h: float = 0.0
    # Corrección aprendida de los aciertos/fallos pasados (la calcula `optimizar`).
    calibracion: dict[str, list[float]] = field(default_factory=dict)

    @classmethod
    def cargar(cls, ruta: str) -> "Ajustes":
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                return cls(**{k: v for k, v in json.load(f).items() if k in cls.__dataclass_fields__})
        return cls()

    def guardar(self, ruta: str) -> None:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


@dataclass
class PrediccionPartido:
    local: str
    visitante: str
    liga: str
    goles_local: float
    goles_visitante: float
    corners_local: float | None
    corners_visitante: float | None
    probs: dict[str, float]
    probs_brutas: dict[str, float]
    marcadores: list[tuple[str, float]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


class Predictor:
    """Un modelo de goles y otro de córners por liga."""

    def __init__(self, ajustes: Ajustes | None = None, min_partidos: int = 6):
        self.ajustes = ajustes or Ajustes()
        self.min_partidos = min_partidos
        self.goles: dict[str, ModeloFuerzas] = {}
        self.corners: dict[str, ModeloFuerzas] = {}
        self.historial: list[Partido] = []

    def ajustar(self, partidos: list[Partido], hasta: date | None = None) -> "Predictor":
        """Ajusta cada liga. Si ya estaba ajustado, parte de lo anterior (mucho más rápido)."""
        por_liga: dict[str, list[Partido]] = {}
        for p in partidos:
            if hasta is None or p.fecha < hasta:
                por_liga.setdefault(p.liga, []).append(p)
        for liga, lista in por_liga.items():
            a = self.ajustes
            for variable, modelos, vida, reg in (
                    ("goles", self.goles, a.vida_media_goles, a.regularizacion_goles),
                    ("corners", self.corners, a.vida_media_corners, a.regularizacion_corners)):
                modelo = ModeloFuerzas(variable, vida, reg, self.min_partidos)
                try:
                    modelos[liga] = modelo.ajustar(lista, hasta, previo=modelos.get(liga))
                except ValueError:
                    modelos.pop(liga, None)  # sin datos suficientes (p. ej. sin córners)
        if not self.goles:
            raise ValueError("No hay partidos suficientes para ajustar ninguna liga.")
        self.historial = [p for p in partidos if p.jugado and (hasta is None or p.fecha < hasta)]
        return self

    @property
    def equipos(self) -> list[str]:
        return sorted({t for m in self.goles.values() for t in m.equipos})

    def liga_de(self, equipo: str) -> str:
        # Si un equipo aparece en varias ligas (ascensos), vale la más reciente.
        for p in reversed(self.historial):
            if equipo in (p.local, p.visitante) and p.liga in self.goles:
                return p.liga
        raise KeyError(f"Sin datos de {equipo}")

    def predecir(self, local: str, visitante: str, fecha: date | None = None) -> PrediccionPartido:
        local, visitante = buscar_equipo(local, self.equipos), buscar_equipo(visitante, self.equipos)
        liga = self.liga_de(local)
        mg = self.goles[liga]
        if not mg.conoce(visitante):
            raise KeyError(f"{local} y {visitante} no están en la misma liga en los datos.")
        avisos = [f"{t} solo tiene {mg.partidos_equipo.get(t, 0)} partidos recientes en los datos: poco fiable."
                  for t in (local, visitante) if mg.partidos_equipo.get(t, 0) < self.min_partidos]

        lam, mu = mg.esperados(local, visitante)
        if self.ajustes.peso_h2h > 0:
            h2h = cara_a_cara(self.historial, local, visitante, hasta=fecha)
            if h2h.n:
                s = self.ajustes.peso_h2h * h2h.n / (h2h.n + 5)
                lam = (1 - s) * lam + s * max(h2h.goles_a, 0.1)
                mu = (1 - s) * mu + s * max(h2h.goles_b, 0.1)

        m = mg.matriz_goles(lam, mu)
        n = len(m)
        p1 = sum(m[i][j] for i in range(n) for j in range(i))
        px = sum(m[i][i] for i in range(n))
        p2 = 1 - p1 - px
        probs = {"1": p1, "X": px, "2": p2, "1X": p1 + px, "X2": px + p2, "12": p1 + p2}
        total_goles = [0.0] * (2 * n)
        for i in range(n):
            for j in range(n):
                total_goles[i + j] += m[i][j]
        for linea in LINEAS_GOLES:
            menos = sum(total_goles[:int(linea) + 1])
            probs[f"Goles +{linea}"] = 1 - menos
            probs[f"Goles -{linea}"] = menos
        ambos_no = sum(m[0]) + sum(m[i][0] for i in range(1, n))
        probs["Ambos marcan: sí"] = 1 - ambos_no
        probs["Ambos marcan: no"] = ambos_no

        c_local = c_visitante = None
        mc = self.corners.get(liga)
        if mc and mc.conoce(local) and mc.conoce(visitante):
            c_local, c_visitante = mc.esperados(local, visitante)
            dist = mc.distribucion_total(c_local + c_visitante)
            for linea in LINEAS_CORNERS:
                menos = sum(dist[:int(linea) + 1])
                probs[f"Córners +{linea}"] = 1 - menos
                probs[f"Córners -{linea}"] = menos

        marcadores = sorted(((f"{i}-{j}", m[i][j]) for i in range(n) for j in range(n)),
                            key=lambda x: -x[1])[:5]
        return PrediccionPartido(local, visitante, liga, lam, mu, c_local, c_visitante,
                                 aplicar(probs, self.ajustes.calibracion), probs, marcadores, avisos)
