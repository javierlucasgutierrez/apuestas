"""Prueba histórica (backtest) sin trampas.

Se recorre el histórico en orden: para cada partido el modelo solo conoce los
partidos anteriores a su fecha, se decide la apuesta con las cuotas de ese día
y después se mira el resultado real. Es la única forma honesta de saber si la
estrategia habría ganado dinero.
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta

from .cuotas import analizar, probabilidades_mercado
from .datos import Partido
from .modelo import ModeloPoisson


@dataclass
class Apuesta:
    partido: Partido
    mercado: str
    cuota: float
    prob: float
    valor: float
    stake_kelly: float
    acertada: bool

    @property
    def beneficio_plano(self) -> float:
        return self.cuota - 1 if self.acertada else -1.0


@dataclass
class InformeBacktest:
    apuestas: list[Apuesta] = field(default_factory=list)
    partidos_evaluados: int = 0
    logloss_modelo: float = 0.0
    logloss_mercado: float = 0.0
    brier_modelo: float = 0.0
    brier_mercado: float = 0.0
    partidos_con_cuotas: int = 0
    bank_inicial: float = 100.0
    bank_final: float = 100.0
    caida_maxima: float = 0.0

    @property
    def beneficio(self) -> float:
        return sum(a.beneficio_plano for a in self.apuestas)

    @property
    def yield_pct(self) -> float:
        return 100 * self.beneficio / len(self.apuestas) if self.apuestas else 0.0

    @property
    def aciertos_pct(self) -> float:
        return 100 * sum(a.acertada for a in self.apuestas) / len(self.apuestas) if self.apuestas else 0.0

    @property
    def cuota_media(self) -> float:
        return sum(a.cuota for a in self.apuestas) / len(self.apuestas) if self.apuestas else 0.0

    def por_mercado(self) -> dict[str, tuple[int, float]]:
        """mercado -> (nº apuestas, beneficio en unidades)."""
        resumen: dict[str, tuple[int, float]] = {}
        for a in self.apuestas:
            n, b = resumen.get(a.mercado, (0, 0.0))
            resumen[a.mercado] = (n + 1, b + a.beneficio_plano)
        return resumen


def _acierta(mercado: str, p: Partido) -> bool:
    goles = p.goles_local + p.goles_visitante
    return {
        "1": p.resultado == "1", "X": p.resultado == "X", "2": p.resultado == "2",
        "+2.5": goles > 2, "-2.5": goles <= 2,
    }[mercado]


def backtest(partidos: list[Partido], crear_modelo=ModeloPoisson, partidos_entrenamiento: int = 150,
             reajuste_dias: int = 7, umbral: float = 0.05, prob_minima: float = 0.20,
             cuota_maxima: float = 6.0, fraccion_kelly: float = 0.25, tope_kelly: float = 0.03,
             bank_inicial: float = 100.0) -> InformeBacktest:
    jugados = sorted((p for p in partidos if p.jugado), key=lambda p: p.fecha)
    if len(jugados) <= partidos_entrenamiento:
        raise ValueError(f"Hacen falta más de {partidos_entrenamiento} partidos para el backtest.")

    informe = InformeBacktest(bank_inicial=bank_inicial, bank_final=bank_inicial)
    bank = maximo = bank_inicial
    modelo = None
    proximo_ajuste = None

    for p in jugados[partidos_entrenamiento:]:
        if modelo is None or p.fecha >= proximo_ajuste:
            modelo = crear_modelo().ajustar(jugados, hasta=p.fecha)
            proximo_ajuste = p.fecha + timedelta(days=reajuste_dias)
        try:
            pred = modelo.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError:
            continue  # equipo recién llegado: todavía no hay datos
        if pred.avisos:
            continue
        informe.partidos_evaluados += 1

        cuotas_1x2 = [p.cuota_1, p.cuota_x, p.cuota_2]
        if all(cuotas_1x2):
            informe.partidos_con_cuotas += 1
            real = {"1": 0, "X": 1, "2": 2}[p.resultado]
            modelo_p = [pred.prob_1, pred.prob_x, pred.prob_2]
            mercado_p = probabilidades_mercado(cuotas_1x2)
            informe.logloss_modelo -= math.log(max(modelo_p[real], 1e-12))
            informe.logloss_mercado -= math.log(max(mercado_p[real], 1e-12))
            informe.brier_modelo += sum((q - (i == real)) ** 2 for i, q in enumerate(modelo_p))
            informe.brier_mercado += sum((q - (i == real)) ** 2 for i, q in enumerate(mercado_p))

        selecciones = analizar(pred, cuotas_1x2, [p.cuota_mas25, p.cuota_menos25], umbral=umbral,
                               prob_minima=prob_minima, cuota_maxima=cuota_maxima,
                               fraccion_kelly=fraccion_kelly, tope_kelly=tope_kelly)
        # Como mucho una apuesta por mercado y partido: la de más valor.
        for grupo in (("1", "X", "2"), ("+2.5", "-2.5")):
            candidatas = [o for o, es_valor in selecciones if es_valor and o.mercado in grupo]
            if not candidatas:
                continue
            o = max(candidatas, key=lambda o: o.valor)
            acertada = _acierta(o.mercado, p)
            informe.apuestas.append(Apuesta(p, o.mercado, o.cuota, o.prob_modelo, o.valor, o.stake, acertada))
            importe = bank * o.stake
            bank += importe * (o.cuota - 1) if acertada else -importe
            maximo = max(maximo, bank)
            informe.caida_maxima = max(informe.caida_maxima, (maximo - bank) / maximo)

    if informe.partidos_con_cuotas:
        informe.logloss_modelo /= informe.partidos_con_cuotas
        informe.logloss_mercado /= informe.partidos_con_cuotas
        informe.brier_modelo /= informe.partidos_con_cuotas
        informe.brier_mercado /= informe.partidos_con_cuotas
    informe.bank_final = bank
    return informe
