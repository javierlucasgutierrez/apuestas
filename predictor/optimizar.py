"""Búsqueda de los ajustes que mejor predicen (cuánto pesa el pasado y cuánto se regulariza).

Para cada combinación se hace una prueba histórica sin trampas y se mide lo bien
que el modelo predijo lo que pasó (log-verosimilitud: cuánta probabilidad dio a
lo que ocurrió de verdad). Se elige la combinación que mejor predice, no la que
más dinero habría ganado: el dinero del pasado depende mucho de la suerte y
optimizarlo lleva a estrategias que luego fallan.
"""

import math
from datetime import date, timedelta

from .datos import Partido
from .modelo import ModeloFuerzas

VIDAS_MEDIAS = [90, 180, 365, 540, 730, 1000]
REGULARIZACIONES = [2.0, 4.0, 8.0, 16.0, 32.0]


def evaluar(partidos: list[Partido], variable: str, vida_media: float, regularizacion: float,
            desde: date, reajuste_dias: int = 14) -> tuple[float, int]:
    """Log-verosimilitud media por partido (más alta = mejor) y nº de partidos evaluados."""
    por_liga: dict[str, list[Partido]] = {}
    for p in partidos:
        por_liga.setdefault(p.liga, []).append(p)
    total, casos = 0.0, 0
    for lista in por_liga.values():
        modelo, proximo = None, None
        for p in lista:
            if p.fecha < desde:
                continue
            valores = ModeloFuerzas(variable).valores(p)
            if valores is None:
                continue
            if proximo is None or p.fecha >= proximo:
                try:
                    modelo = ModeloFuerzas(variable, vida_media, regularizacion).ajustar(
                        lista, hasta=p.fecha, previo=modelo)
                except ValueError:
                    continue
                proximo = p.fecha + timedelta(days=reajuste_dias)
            if not (modelo.conoce(p.local) and modelo.conoce(p.visitante)):
                continue
            if min(modelo.partidos_equipo[p.local], modelo.partidos_equipo[p.visitante]) < modelo.min_partidos:
                continue
            lam, mu = modelo.esperados(p.local, p.visitante)
            x, y = valores
            if variable == "goles":
                m = modelo.matriz_goles(lam, mu)
                prob = m[x][y] if x < len(m) and y < len(m) else 1e-9
            else:
                dist = modelo.distribucion_total(lam + mu, maximo=40)
                prob = dist[x + y] if x + y < len(dist) else 1e-9
            total += math.log(max(prob, 1e-12))
            casos += 1
    return (total / casos if casos else -math.inf), casos


def optimizar(partidos: list[Partido], desde: date | None = None, aviso=print) -> dict:
    jugados = sorted((p for p in partidos if p.jugado), key=lambda p: p.fecha)
    desde = desde or jugados[0].fecha + timedelta(days=330)
    resultado = {}
    for variable in ("goles", "corners"):
        mejor = None
        aviso(f"\n{variable.capitalize()}:")
        for vida in VIDAS_MEDIAS:
            for reg in REGULARIZACIONES:
                ll, casos = evaluar(jugados, variable, vida, reg, desde)
                if not casos:
                    continue
                aviso(f"  vida media {vida:>3} días · regularización {reg:<3} → {ll:.4f}  ({casos} partidos)")
                if mejor is None or ll > mejor[0]:
                    mejor = (ll, vida, reg)
        if mejor:
            resultado[variable] = {"vida_media": mejor[1], "regularizacion": mejor[2], "log_verosimilitud": mejor[0]}
    return resultado
