"""Genera una liga ficticia para probar la herramienta sin datos reales.

Los resultados se simulan con fuerzas "verdaderas" ocultas y la casa de apuestas
publica cuotas a partir de una estimación algo imprecisa de esas fuerzas, más su
margen. Sirve para comprobar que todo funciona; los beneficios que salgan con
estos datos NO dicen nada sobre apuestas reales.
"""

import math
import random
from datetime import date, timedelta

from .datos import Partido

EQUIPOS = [
    "Atlético Norte", "Real Costa", "Deportivo Sierra", "Unión Valle", "Racing Puerto",
    "Sporting Llano", "CD Ribera", "Club Montaña", "Celta Bahía", "Betis Campiña",
    "Rayo Meseta", "Getafe Río", "Osasuna Monte", "Granada Vega", "Elche Palmeral",
    "Cádiz Faro", "Mallorca Isla", "Alavés Llanura", "Levante Huerta", "Girona Muralla",
]


def _probs(lam: float, mu: float, rho: float = -0.05, n: int = 11):
    def pois(k, l):
        return math.exp(-l) * l ** k / math.factorial(k)

    def tau(i, j):
        return {(0, 0): 1 - lam * mu * rho, (0, 1): 1 + lam * rho,
                (1, 0): 1 + mu * rho, (1, 1): 1 - rho}.get((i, j), 1.0)

    m = [[pois(i, lam) * pois(j, mu) * tau(i, j) for j in range(n)] for i in range(n)]
    t = sum(map(sum, m))
    p1 = sum(m[i][j] for i in range(n) for j in range(n) if i > j) / t
    px = sum(m[i][i] for i in range(n)) / t
    menos = sum(m[i][j] for i in range(n) for j in range(n) if i + j <= 2) / t
    return [p1, px, 1 - p1 - px], [1 - menos, menos]


def _cuotas(probs: list[float], margen: float) -> list[float]:
    return [round(1 / (p * (1 + margen)), 2) for p in probs]


def generar_liga(temporadas: int = 3, semilla: int = 7, inicio: date = date(2023, 8, 12)):
    """Devuelve (histórico jugado, próxima jornada sin jugar con cuotas)."""
    rnd = random.Random(semilla)
    ataque = {t: math.exp(rnd.gauss(0, 0.22)) for t in EQUIPOS}
    defensa = {t: math.exp(rnd.gauss(0, 0.20)) for t in EQUIPOS}
    base, casa = 1.18, 1.22
    jugados, proxima = [], []

    for temporada in range(temporadas):
        # Las fuerzas cambian un poco de una temporada a otra.
        for t in EQUIPOS:
            ataque[t] *= math.exp(rnd.gauss(0, 0.08))
            defensa[t] *= math.exp(rnd.gauss(0, 0.08))
        jornadas = _calendario(EQUIPOS, rnd)
        fecha = inicio + timedelta(days=365 * temporada)
        for num, jornada in enumerate(jornadas):
            ultima = temporada == temporadas - 1 and num == len(jornadas) - 1
            for local, visitante in jornada:
                lam = base * casa * ataque[local] * defensa[visitante]
                mu = base * ataque[visitante] * defensa[local]
                # La casa estima los goles con algo de error.
                lam_c = lam * math.exp(rnd.gauss(0, 0.10))
                mu_c = mu * math.exp(rnd.gauss(0, 0.10))
                p1x2, pgoles = _probs(lam_c, mu_c)
                c1x2, cgoles = _cuotas(p1x2, 0.055), _cuotas(pgoles, 0.06)
                partido = Partido(fecha, local, visitante, None, None, *c1x2, *cgoles)
                if ultima:
                    proxima.append(partido)
                    continue
                partido.goles_local = _poisson_aleatorio(lam, rnd)
                partido.goles_visitante = _poisson_aleatorio(mu, rnd)
                jugados.append(partido)
            fecha += timedelta(days=7)
    return jugados, proxima


def _poisson_aleatorio(lam: float, rnd: random.Random) -> int:
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rnd.random()
        if p <= limite:
            return k
        k += 1


def _calendario(equipos: list[str], rnd: random.Random) -> list[list[tuple[str, str]]]:
    """Liga a doble vuelta (método del círculo)."""
    eq = equipos[:]
    rnd.shuffle(eq)
    n = len(eq)
    ida = []
    for ronda in range(n - 1):
        jornada = []
        for i in range(n // 2):
            a, b = eq[i], eq[n - 1 - i]
            jornada.append((a, b) if (ronda + i) % 2 == 0 else (b, a))
        ida.append(jornada)
        eq = [eq[0]] + [eq[-1]] + eq[1:-1]
    vuelta = [[(b, a) for a, b in jornada] for jornada in ida]
    return ida + vuelta
