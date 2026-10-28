"""Sistema de apuestas: qué apostar, cuánto, y qué cabe esperar (incluido el riesgo).

Reúne las estrategias que han aguantado la prueba con temporadas que no se usaron
para elegirlas (ver `comparar_perfiles`):

- Hándicap asiático y 1X2 con cuota hasta 5, cuando una casa paga por encima del
  precio justo de Pinnacle o la bolsa de Betfair.
- Goles 2,5 queda fuera: ganaba en las temporadas de entrenamiento y perdía en las
  de prueba.

Cada perfil cambia volumen por margen: exigir menos valor da más apuestas, pero
cada una deja menos y es más sensible a que la cuota se mueva antes de apostar.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field

from .valor import Oportunidad, oportunidades

# perfil -> mercado -> (valor mínimo, cuota máxima)
PERFILES = {
    # La estrategia principal: la más sólida del backtest (positiva en cada temporada completa).
    "principal": {"Hándicap asiático": (0.02, 2.50), "1X2": (0.02, 2.50)},
    "conservador": {"Hándicap asiático": (0.03, 5.0), "1X2": (0.03, 5.0)},
    "equilibrado": {"Hándicap asiático": (0.02, 5.0), "1X2": (0.02, 5.0)},
    "volumen": {"Hándicap asiático": (0.01, 5.0), "1X2": (0.02, 5.0)},
    # Cuotas de 1,60 a 2,10: menos apuestas, pero se gana la mitad y las rachas son más cortas.
    "cuotas_cortas": {"Hándicap asiático": (0.02, 2.10), "1X2": (0.02, 2.10)},
    # Solo más/menos 2,5 goles (los córners van aparte, con el modelo). Margen pequeño:
    # en las pruebas, alrededor de +2 % con CLV positivo pero poco.
    # El asiático de goles solo llega con cuotas en vivo y aún no tiene backtest: se le exige más valor.
    "goles": {"Goles 2.5": (0.01, 2.10), "Goles asiático": (0.02, 2.10)},
}
CUOTA_MIN_PERFIL = {"principal": 1.50, "cuotas_cortas": 1.60, "goles": 1.60}
TEMPORADAS_ENTRENO = {"2324", "2425"}


def temporada(fila: dict) -> str:
    return fila.get("_archivo", "").rsplit("_", 1)[-1][:4]


def apuestas_del_sistema(filas: list[dict], perfil: str, casas: list[str],
                         cuota_min: float = 1.50) -> list[tuple[dict, Oportunidad]]:
    reglas = PERFILES[perfil]
    cuota_min = max(cuota_min, CUOTA_MIN_PERFIL.get(perfil, cuota_min))
    resultado = []
    for fila in filas:
        try:
            ops = oportunidades(fila, casas, umbral=min(u for u, _ in reglas.values()),
                                cuota_min=cuota_min, cuota_max=max(c for _, c in reglas.values()))
        except ValueError:
            continue
        for o in ops:
            if o.familia in reglas:
                umbral, cuota_max = reglas[o.familia]
                if o.valor >= umbral and o.cuota <= cuota_max:
                    resultado.append((fila, o))
    resultado.sort(key=lambda x: x[1].fecha)
    return resultado


def stake(o: Oportunidad, metodo: str, fraccion_kelly: float = 0.5, tope: float = 0.03,
          plano: float = 0.01) -> float:
    """Parte del bank para una apuesta."""
    if metodo == "plano":
        return plano
    completo = (o.prob_justa * o.cuota - 1) / (o.cuota - 1)
    return max(0.0, min(completo * fraccion_kelly, tope))


@dataclass
class Simulacion:
    bank_inicial: float
    bank_final: float = 0.0
    apostado: float = 0.0
    caida_maxima: float = 0.0
    apuestas: int = 0
    por_mes: dict[str, float] = field(default_factory=dict)

    @property
    def rentabilidad_bank(self) -> float:
        return 100 * (self.bank_final / self.bank_inicial - 1)


def simular_bank(ops: list[Oportunidad], bank: float = 1000.0, metodo: str = "kelly", **kw) -> Simulacion:
    """Recorre las apuestas en orden. Las del mismo día se calculan con el bank de ese día."""
    sim = Simulacion(bank_inicial=bank)
    maximo = bank
    por_dia: dict = defaultdict(list)
    for o in ops:
        por_dia[o.fecha].append(o)
    for dia in sorted(por_dia):
        base = bank
        for o in por_dia[dia]:
            importe = base * stake(o, metodo, **kw)
            bank += importe * o.beneficio
            sim.apostado += importe
            sim.apuestas += 1
        maximo = max(maximo, bank)
        sim.caida_maxima = max(sim.caida_maxima, (maximo - bank) / maximo)
        sim.por_mes[f"{dia:%Y-%m}"] = bank
    sim.bank_final = bank
    return sim


def montecarlo(ops: list[Oportunidad], apuestas_por_temporada: int, simulaciones: int = 2000,
               metodo: str = "kelly", semilla: int = 1, **kw) -> dict[str, float]:
    """Repite una temporada al azar miles de veces con las apuestas del histórico.

    Devuelve los percentiles del resultado del bank y la probabilidad de acabar perdiendo.
    """
    rnd = random.Random(semilla)
    resultados, caidas = [], []
    for _ in range(simulaciones):
        bank = maximo = 1.0
        caida = 0.0
        for o in rnd.choices(ops, k=apuestas_por_temporada):
            bank += bank * stake(o, metodo, **kw) * o.beneficio
            maximo = max(maximo, bank)
            caida = max(caida, (maximo - bank) / maximo)
        resultados.append(100 * (bank - 1))
        caidas.append(100 * caida)
    resultados.sort()
    caidas.sort()

    def percentil(lista, p):
        return lista[min(len(lista) - 1, int(p * len(lista)))]

    return {
        "peor_5": percentil(resultados, 0.05), "mediana": percentil(resultados, 0.5),
        "mejor_5": percentil(resultados, 0.95),
        "prob_perder": 100 * sum(r < 0 for r in resultados) / len(resultados),
        "caida_mediana": percentil(caidas, 0.5), "caida_peor_5": percentil(caidas, 0.95),
    }


@dataclass
class ResultadoPerfil:
    perfil: str
    entreno: list[Oportunidad]
    prueba: list[Oportunidad]


def comparar_perfiles(filas: list[dict], casas: list[str], cuota_min: float = 1.50) -> list[ResultadoPerfil]:
    """Cada perfil, separado en temporadas de entrenamiento (2023-25) y de prueba (2025-27)."""
    jugadas = [f for f in filas if f.get("FTHG")]
    resultado = []
    for perfil in PERFILES:
        entreno, prueba = [], []
        for fila, o in apuestas_del_sistema(jugadas, perfil, casas, cuota_min):
            if o.beneficio is None:
                continue
            (entreno if temporada(fila) in TEMPORADAS_ENTRENO else prueba).append(o)
        resultado.append(ResultadoPerfil(perfil, entreno, prueba))
    return resultado
