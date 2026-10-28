"""Cuotas, margen de la casa, valor esperado, cuota mínima y tamaño de la apuesta."""

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


def normalizar_mercado(texto: str) -> str:
    """'corners +9.5', 'Córners+9,5', 'goles -2.5', 'btts si'... → nombre interno."""
    t = texto.strip().lower().replace(" ", "").replace(",", ".").replace("ó", "o")
    for prefijo, nombre in (("corners", "Córners"), ("corner", "Córners"), ("c", "Córners"),
                            ("goles", "Goles"), ("g", "Goles")):
        if t.startswith(prefijo) and len(t) > len(prefijo) and t[len(prefijo)] in "+-":
            signo, linea = t[len(prefijo)], float(t[len(prefijo) + 1:])
            return f"{nombre} {signo}{linea}"
    if t in ("ambossi", "ambosmarcan", "ambosmarcan:si", "btts", "bttssi"):
        return "Ambos marcan: sí"
    if t in ("ambosno", "ambosmarcan:no", "bttsno"):
        return "Ambos marcan: no"
    if t.upper() in ("1", "X", "2", "1X", "X2", "12"):
        return t.upper()
    raise ValueError(f"Mercado no reconocido: {texto!r} (ejemplos: 1, X2, goles+2.5, corners-10.5, ambos si)")


@dataclass
class Seleccion:
    mercado: str
    prob: float
    cuota_minima: float
    cuota: float | None = None
    stake: float = 0.0

    @property
    def cuota_justa(self) -> float:
        return 1 / self.prob

    @property
    def valor(self) -> float | None:
        return None if self.cuota is None else valor_esperado(self.prob, self.cuota)

    @property
    def recomendada(self) -> bool:
        return self.cuota is not None and self.cuota >= self.cuota_minima


def seleccionar(probs: dict[str, float], cuotas: dict[str, float] | None = None,
                cuota_min: float = 1.50, umbral: float = 0.05, prob_minima: float = 0.50,
                fraccion_kelly: float = 0.25, tope_kelly: float = 0.03) -> list[Seleccion]:
    """Las selecciones con probabilidad suficiente y la cuota mínima a la que merecen la pena.

    Cuota mínima = la mayor entre la que pides (1,50) y la que da un valor esperado
    de al menos `umbral` según el modelo. Si se conoce la cuota, se dice si llega.
    """
    cuotas = cuotas or {}
    resultado = []
    for mercado, p in probs.items():
        if p < prob_minima or p <= 0:
            continue
        s = Seleccion(mercado, p, max(cuota_min, (1 + umbral) / p), cuotas.get(mercado))
        if s.recomendada:
            s.stake = kelly(p, s.cuota, fraccion_kelly, tope_kelly)
        resultado.append(s)
    return sorted(resultado, key=lambda s: -s.prob)
