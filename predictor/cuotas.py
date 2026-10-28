"""Cuotas, margen de la casa, valor esperado y tamaño de la apuesta (Kelly)."""

from dataclasses import dataclass


def margen(cuotas: list[float]) -> float:
    """Margen de la casa: cuánto suman las probabilidades implícitas por encima del 100 %."""
    return sum(1 / c for c in cuotas) - 1


def probabilidades_mercado(cuotas: list[float]) -> list[float]:
    """Probabilidades que da la casa, quitando su margen (método proporcional)."""
    implicitas = [1 / c for c in cuotas]
    total = sum(implicitas)
    return [p / total for p in implicitas]


def valor_esperado(prob: float, cuota: float) -> float:
    """Beneficio medio por cada euro apostado. 0,05 = +5 %."""
    return prob * cuota - 1


def kelly(prob: float, cuota: float, fraccion: float = 0.25, tope: float = 0.03) -> float:
    """Parte del bank a apostar según el criterio de Kelly fraccionado.

    Kelly completo es demasiado agresivo cuando la probabilidad es una estimación,
    por eso se usa una fracción (1/4 por defecto) y un tope por apuesta.
    """
    if cuota <= 1:
        return 0.0
    completo = (prob * cuota - 1) / (cuota - 1)
    return max(0.0, min(completo * fraccion, tope))


@dataclass
class Oportunidad:
    mercado: str
    cuota: float
    prob_modelo: float
    prob_mercado: float
    valor: float
    stake: float

    @property
    def cuota_justa(self) -> float:
        return 1 / self.prob_modelo if self.prob_modelo > 0 else float("inf")


def analizar(prediccion, cuotas_1x2: list[float] | None = None,
             cuotas_goles: list[float] | None = None, umbral: float = 0.05,
             prob_minima: float = 0.20, cuota_maxima: float = 6.0,
             fraccion_kelly: float = 0.25, tope_kelly: float = 0.03) -> list[tuple[Oportunidad, bool]]:
    """Compara el modelo con la casa. Devuelve cada selección y si es apuesta de valor.

    Se descartan probabilidades muy bajas y cuotas muy altas: es donde el modelo
    se equivoca más y donde un error pequeño parece un valor enorme.
    """
    grupos = []
    if cuotas_1x2 and all(cuotas_1x2):
        grupos.append((["1", "X", "2"], cuotas_1x2,
                       [prediccion.prob_1, prediccion.prob_x, prediccion.prob_2]))
    if cuotas_goles and all(cuotas_goles):
        grupos.append((["+2.5", "-2.5"], cuotas_goles,
                       [prediccion.prob_mas25, prediccion.prob_menos25]))

    resultado = []
    for nombres, cuotas, probs in grupos:
        mercado = probabilidades_mercado(cuotas)
        for nombre, cuota, p, pm in zip(nombres, cuotas, probs, mercado):
            v = valor_esperado(p, cuota)
            es_valor = v >= umbral and p >= prob_minima and cuota <= cuota_maxima
            stake = kelly(p, cuota, fraccion_kelly, tope_kelly) if es_valor else 0.0
            resultado.append((Oportunidad(nombre, cuota, p, pm, v, stake), es_valor))
    return resultado
