"""Modelo de goles de Poisson con corrección de Dixon-Coles.

Cada equipo tiene una fuerza de ataque y otra de defensa. Los goles esperados de
un partido son:

    goles local     = base * ventaja_campo * ataque_local     * defensa_visitante
    goles visitante = base *                 ataque_visitante * defensa_local

Los parámetros se estiman por máxima verosimilitud, dando más peso a los
partidos recientes (vida media configurable) y con una regularización que
acerca a la media a los equipos con pocos partidos. Con los goles esperados se
calcula la probabilidad de cada marcador y, de ahí, la de cada mercado
(1X2, más/menos de 2,5 goles, ambos marcan).
"""

import difflib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .datos import Partido, cara_a_cara


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Corrección de Dixon-Coles para los marcadores bajos (0-0, 1-0, 0-1, 1-1)."""
    if i == 0 and j == 0:
        return 1 - lam * mu * rho
    if i == 0 and j == 1:
        return 1 + lam * rho
    if i == 1 and j == 0:
        return 1 + mu * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


@dataclass
class Prediccion:
    local: str
    visitante: str
    goles_local: float
    goles_visitante: float
    prob_1: float
    prob_x: float
    prob_2: float
    prob_mas25: float
    prob_menos25: float
    prob_ambos_si: float
    prob_ambos_no: float
    marcadores: list[tuple[str, float]] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def mercados(self) -> dict[str, float]:
        return {
            "1": self.prob_1, "X": self.prob_x, "2": self.prob_2,
            "+2.5": self.prob_mas25, "-2.5": self.prob_menos25,
            "Ambos sí": self.prob_ambos_si, "Ambos no": self.prob_ambos_no,
        }


class ModeloPoisson:
    def __init__(self, vida_media_dias: float = 180.0, regularizacion: float = 3.0,
                 peso_h2h: float = 0.0, max_goles: int = 10, min_partidos: int = 6):
        self.vida_media_dias = vida_media_dias
        self.regularizacion = regularizacion
        self.peso_h2h = peso_h2h
        self.max_goles = max_goles
        self.min_partidos = min_partidos
        self.ataque: dict[str, float] = {}
        self.defensa: dict[str, float] = {}
        self.partidos_equipo: dict[str, int] = {}
        self.base = 1.3
        self.ventaja_campo = 1.2
        self.rho = 0.0
        self.historial: list[Partido] = []
        self.fecha_ajuste: date | None = None

    # ------------------------------------------------------------------ ajuste
    def _pesos(self, jugados: list[Partido], referencia: date) -> list[float]:
        if not self.vida_media_dias:
            return [1.0] * len(jugados)
        k = math.log(2) / self.vida_media_dias
        return [math.exp(-k * max(0, (referencia - p.fecha).days)) for p in jugados]

    def ajustar(self, partidos: list[Partido], hasta: date | None = None) -> "ModeloPoisson":
        """Estima las fuerzas con los partidos jugados antes de `hasta` (o todos)."""
        jugados = [p for p in partidos if p.jugado and (hasta is None or p.fecha < hasta)]
        if len(jugados) < 20:
            raise ValueError("Hacen falta al menos 20 partidos jugados para ajustar el modelo.")
        referencia = hasta or max(p.fecha for p in jugados)
        pesos = self._pesos(jugados, referencia)
        equipos = sorted({p.local for p in jugados} | {p.visitante for p in jugados})
        r = self.regularizacion

        a = {t: 1.0 for t in equipos}
        d = {t: 1.0 for t in equipos}
        total_w = sum(pesos)
        c = sum(w * (p.goles_local + p.goles_visitante) for p, w in zip(jugados, pesos)) / (2 * total_w)
        h = 1.2

        for _ in range(500):
            anterior = (dict(a), dict(d), c, h)

            num, den = defaultdict(float), defaultdict(float)
            for p, w in zip(jugados, pesos):
                num[p.local] += w * p.goles_local
                den[p.local] += w * c * h * d[p.visitante]
                num[p.visitante] += w * p.goles_visitante
                den[p.visitante] += w * c * d[p.local]
            a = {t: (num[t] + r) / (den[t] + r) for t in equipos}

            num, den = defaultdict(float), defaultdict(float)
            for p, w in zip(jugados, pesos):
                num[p.visitante] += w * p.goles_local
                den[p.visitante] += w * c * h * a[p.local]
                num[p.local] += w * p.goles_visitante
                den[p.local] += w * c * a[p.visitante]
            d = {t: (num[t] + r) / (den[t] + r) for t in equipos}

            media_a = sum(a.values()) / len(a)
            media_d = sum(d.values()) / len(d)
            a = {t: v / media_a for t, v in a.items()}
            d = {t: v / media_d for t, v in d.items()}

            goles_casa = sum(w * p.goles_local for p, w in zip(jugados, pesos))
            h = goles_casa / sum(w * c * a[p.local] * d[p.visitante] for p, w in zip(jugados, pesos))
            goles = sum(w * (p.goles_local + p.goles_visitante) for p, w in zip(jugados, pesos))
            c = goles / sum(w * (h * a[p.local] * d[p.visitante] + a[p.visitante] * d[p.local])
                            for p, w in zip(jugados, pesos))

            cambio = max(
                max(abs(a[t] - anterior[0][t]) for t in equipos),
                max(abs(d[t] - anterior[1][t]) for t in equipos),
                abs(c - anterior[2]), abs(h - anterior[3]),
            )
            if cambio < 1e-7:
                break

        self.ataque, self.defensa, self.base, self.ventaja_campo = a, d, c, h
        self.rho = self._estimar_rho(jugados, pesos)
        self.partidos_equipo = defaultdict(int)
        for p in jugados:
            self.partidos_equipo[p.local] += 1
            self.partidos_equipo[p.visitante] += 1
        self.historial = jugados
        self.fecha_ajuste = referencia
        return self

    def _estimar_rho(self, jugados: list[Partido], pesos: list[float]) -> float:
        bajos = [(p, w) for p, w in zip(jugados, pesos) if p.goles_local <= 1 and p.goles_visitante <= 1]
        mejor, mejor_ll = 0.0, -math.inf
        for paso in range(-25, 16):
            rho = paso / 100
            ll = 0.0
            for p, w in bajos:
                lam, mu = self._lambdas(p.local, p.visitante)
                t = _tau(p.goles_local, p.goles_visitante, lam, mu, rho)
                if t <= 0:
                    ll = -math.inf
                    break
                ll += w * math.log(t)
            if ll > mejor_ll:
                mejor, mejor_ll = rho, ll
        return mejor

    # -------------------------------------------------------------- predicción
    @property
    def equipos(self) -> list[str]:
        return sorted(self.ataque)

    def buscar_equipo(self, nombre: str) -> str:
        """Devuelve el nombre exacto del equipo (sin distinguir mayúsculas)."""
        for t in self.ataque:
            if t.lower() == nombre.strip().lower():
                return t
        parecidos = difflib.get_close_matches(nombre, self.equipos, n=3, cutoff=0.5)
        sugerencia = f" ¿Quizás: {', '.join(parecidos)}?" if parecidos else ""
        raise KeyError(f"Equipo desconocido: {nombre!r}.{sugerencia}")

    def _lambdas(self, local: str, visitante: str) -> tuple[float, float]:
        lam = self.base * self.ventaja_campo * self.ataque[local] * self.defensa[visitante]
        mu = self.base * self.ataque[visitante] * self.defensa[local]
        return lam, mu

    def matriz(self, lam: float, mu: float) -> list[list[float]]:
        n = self.max_goles + 1
        pl = [_poisson(i, lam) for i in range(n)]
        pv = [_poisson(j, mu) for j in range(n)]
        m = [[pl[i] * pv[j] * _tau(i, j, lam, mu, self.rho) for j in range(n)] for i in range(n)]
        total = sum(map(sum, m))
        return [[x / total for x in fila] for fila in m]

    def predecir(self, local: str, visitante: str, fecha: date | None = None) -> Prediccion:
        local, visitante = self.buscar_equipo(local), self.buscar_equipo(visitante)
        lam, mu = self._lambdas(local, visitante)
        avisos = []
        for t in (local, visitante):
            if self.partidos_equipo.get(t, 0) < self.min_partidos:
                avisos.append(f"{t} solo tiene {self.partidos_equipo.get(t, 0)} partidos en los datos: predicción poco fiable.")

        if self.peso_h2h > 0:
            h2h = cara_a_cara(self.historial, local, visitante, hasta=fecha)
            if h2h.n:
                # Cuantos más enfrentamientos, más se tienen en cuenta (sin pasar de peso_h2h).
                s = self.peso_h2h * h2h.n / (h2h.n + 5)
                lam = (1 - s) * lam + s * max(h2h.goles_a, 0.1)
                mu = (1 - s) * mu + s * max(h2h.goles_b, 0.1)

        m = self.matriz(lam, mu)
        n = len(m)
        p1 = sum(m[i][j] for i in range(n) for j in range(n) if i > j)
        px = sum(m[i][i] for i in range(n))
        p2 = 1 - p1 - px
        menos25 = sum(m[i][j] for i in range(n) for j in range(n) if i + j <= 2)
        ambos_no = sum(m[0]) + sum(m[i][0] for i in range(1, n))
        marcadores = sorted(((f"{i}-{j}", m[i][j]) for i in range(n) for j in range(n)),
                            key=lambda x: -x[1])[:6]
        return Prediccion(local, visitante, lam, mu, p1, px, p2, 1 - menos25, menos25,
                          1 - ambos_no, ambos_no, marcadores, avisos)

    def clasificacion_fuerzas(self) -> list[tuple[str, float, float, float]]:
        """(equipo, ataque, defensa, índice) ordenado de mejor a peor.

        El índice es la diferencia de goles esperada por partido contra un rival medio
        en campo neutral.
        """
        filas = []
        for t in self.equipos:
            indice = self.base * (self.ataque[t] - self.defensa[t])
            filas.append((t, self.ataque[t], self.defensa[t], indice))
        return sorted(filas, key=lambda x: -x[3])
