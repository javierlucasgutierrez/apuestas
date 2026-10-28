"""Prueba histórica (backtest) sin trampas.

Se recorre el histórico en orden: para cada partido el modelo solo conoce los
partidos anteriores a su fecha. Se mide:

1. Calibración: cuando el modelo dice "70 %", ¿pasa de verdad el 70 % de las veces?
   Es lo que permite fiarse de la cuota mínima, también en córners (de los que
   no hay cuotas históricas gratuitas).
2. Dinero: con las cuotas reales del histórico (1X2 y más/menos 2,5 goles), cuánto
   se habría ganado o perdido siguiendo las reglas de selección.
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .calibracion import ajustar_calibradores, grupo_de
from .cuotas import seleccionar
from .datos import Partido
from .mercados import Ajustes, Predictor, acierta, familia

TRAMOS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.0001]


def cuotas_del_partido(p: Partido) -> dict[str, float]:
    """Cuotas que trae el CSV, con el nombre de mercado interno."""
    cuotas = {"1": p.cuota_1, "X": p.cuota_x, "2": p.cuota_2,
              "Goles +2.5": p.cuota_mas25, "Goles -2.5": p.cuota_menos25}
    return {m: c for m, c in cuotas.items() if c and c > 1}


@dataclass
class Apuesta:
    partido: Partido
    mercado: str
    cuota: float
    prob: float
    acertada: bool

    @property
    def beneficio(self) -> float:
        return self.cuota - 1 if self.acertada else -1.0


@dataclass
class Calibracion:
    """Por tramo de probabilidad: nº de casos, suma de probabilidades y aciertos."""
    tramos: dict[int, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0, 0.0, 0]))
    brier: float = 0.0
    casos: int = 0
    aciertos: int = 0

    def anotar(self, prob: float, ok: bool) -> None:
        self.casos += 1
        self.brier += (prob - ok) ** 2
        self.aciertos += ok
        if prob >= TRAMOS[0]:
            i = max(k for k, t in enumerate(TRAMOS) if prob >= t)
            fila = self.tramos[i]
            fila[0] += 1
            fila[1] += prob
            fila[2] += ok

    def mejora_sobre_media(self) -> float:
        """Brier skill: 0 = no mejora nada a "usar el % medio"; cuanto más alto, mejor."""
        if not self.casos:
            return 0.0
        frecuencia = self.aciertos / self.casos
        base = self.casos * frecuencia * (1 - frecuencia)
        return 1 - self.brier / base if base else 0.0

    def filas(self):
        """(desde, hasta, casos, prob media, % acierto real)."""
        for i in sorted(self.tramos):
            n, suma, ok = self.tramos[i]
            yield TRAMOS[i], min(TRAMOS[i + 1], 1.0), int(n), suma / n, ok / n


@dataclass
class InformeBacktest:
    desde: date | None = None
    hasta: date | None = None
    partidos: int = 0
    calibracion: dict[str, Calibracion] = field(default_factory=lambda: defaultdict(Calibracion))
    apuestas: list[Apuesta] = field(default_factory=list)
    calibradores: dict[str, list[float]] = field(default_factory=dict)

    def resumen_apuestas(self, filtro=lambda a: True) -> tuple[int, float, float, float]:
        """(nº, % aciertos, beneficio a 1 € fijo, cuota media)."""
        lista = [a for a in self.apuestas if filtro(a)]
        if not lista:
            return 0, 0.0, 0.0, 0.0
        return (len(lista), 100 * sum(a.acertada for a in lista) / len(lista),
                sum(a.beneficio for a in lista), sum(a.cuota for a in lista) / len(lista))


def backtest(partidos: list[Partido], ajustes: Ajustes | None = None, desde: date | None = None,
             reajuste_dias: int = 7, cuota_min: float = 1.50, umbral: float = 0.05,
             prob_minima: float = 0.50, calibrar: bool = True, aviso=None) -> InformeBacktest:
    """Evalúa los partidos a partir de `desde` (por defecto, tras la primera temporada).

    Con `calibrar`, la corrección de probabilidades se aprende sobre la marcha, solo
    con los partidos ya evaluados. Al final, `informe.calibradores` tiene la corrección
    aprendida con todo el periodo, lista para usar en partidos futuros.
    """
    jugados = sorted((p for p in partidos if p.jugado), key=lambda p: p.fecha)
    if not jugados:
        raise ValueError("No hay partidos jugados.")
    desde = desde or jugados[0].fecha + timedelta(days=330)
    evaluar = [p for p in jugados if p.fecha >= desde]
    if not evaluar:
        raise ValueError("No hay partidos que evaluar: hacen falta más temporadas.")

    informe = InformeBacktest(desde=evaluar[0].fecha, hasta=evaluar[-1].fecha)
    # La calibración guardada se aprendió con estos mismos partidos: aquí se rehace desde cero.
    predictor = Predictor(replace(ajustes or Ajustes(), calibracion={}))
    pares: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    proximo_ajuste = None
    for p in evaluar:
        if proximo_ajuste is None or p.fecha >= proximo_ajuste:
            predictor.ajustar(jugados, hasta=p.fecha)
            if calibrar:
                predictor.ajustes.calibracion = ajustar_calibradores(pares)
            proximo_ajuste = p.fecha + timedelta(days=reajuste_dias)
            if aviso:
                aviso(p.fecha)
        try:
            pred = predictor.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError:
            continue  # equipo recién ascendido sin datos
        if pred.avisos:
            continue
        informe.partidos += 1
        for mercado, prob in pred.probs.items():
            ok = acierta(mercado, p)
            if ok is None:
                continue
            informe.calibracion[familia(mercado)].anotar(prob, ok)
            grupo = grupo_de(mercado)
            if grupo:
                pares[grupo].append((pred.probs_brutas[mercado], ok))

        cuotas = cuotas_del_partido(p)
        elegidas = [s for s in seleccionar(pred.probs, cuotas, cuota_min, umbral, prob_minima)
                    if s.recomendada]
        # Como mucho una apuesta por familia y partido: la de más valor.
        por_familia = {}
        for s in elegidas:
            f = familia(s.mercado)
            if f not in por_familia or s.valor > por_familia[f].valor:
                por_familia[f] = s
        for s in por_familia.values():
            informe.apuestas.append(Apuesta(p, s.mercado, s.cuota, s.prob, acierta(s.mercado, p)))
    informe.calibradores = ajustar_calibradores(pares)
    return informe
