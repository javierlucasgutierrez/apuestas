"""Valor de mercado: comparar casas de apuestas contra el precio justo.

La idea (Kaunitz, Zhong y Kreiner, 2017, "Beating the bookies with their own
numbers"): hay casas muy "finas" (Pinnacle, la bolsa de Betfair) cuyas cuotas,
quitado el margen, son la mejor estimación que existe de la probabilidad real.
Las demás casas a veces se quedan atrás y pagan más de lo justo. Apostar solo en
esos casos da valor a largo plazo.

Para saber si una apuesta tenía valor sin esperar a cientos de resultados se usa
el CLV (closing line value): comparar la cuota que se cogió con el precio justo
justo antes del partido. Si de media coges cuotas mejores que el cierre, ganas a
la larga; es la medida que usan los apostadores profesionales.
"""

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

CASAS = {
    "B365": "Bet365", "BW": "bwin", "WH": "William Hill", "IW": "Interwetten",
    "BFD": "Betfred", "BV": "BetVictor", "BMGM": "BetMGM", "PP": "Paddy Power",
    "SKB": "Sky Bet", "CL": "Coral", "LB": "Ladbrokes", "PS": "Pinnacle",
    "Max": "mejor cuota del mercado",
}
# Referencias del precio justo, de más a menos fiable.
REFERENCIAS = ["PS", "BFE"]
REFERENCIAS_CIERRE = ["PSC", "BFEC", "AvgC"]

MERCADOS = {
    "1X2": [("1", "H"), ("X", "D"), ("2", "A")],
    "Goles 2.5": [("Goles +2.5", ">2.5"), ("Goles -2.5", "<2.5")],
}


def _columna(casa: str, mercado: str, sufijo: str) -> str:
    # En los goles, Pinnacle se llama "P" (P>2.5) y su cierre "PC".
    if mercado != "1X2":
        casa = {"PS": "P", "PSC": "PC"}.get(casa, casa)
    return casa + sufijo


def _cuota(fila: dict, columna: str) -> float | None:
    try:
        v = float((fila.get(columna) or "").replace(",", "."))
    except ValueError:
        return None
    return v if v > 1 else None


def precio_justo(fila: dict, mercado: str, cierre: bool = False) -> tuple[list[float], str] | None:
    """Probabilidades sin margen según la referencia más fiable disponible."""
    for ref in (REFERENCIAS_CIERRE if cierre else REFERENCIAS):
        cuotas = [_cuota(fila, _columna(ref, mercado, s)) for _, s in MERCADOS[mercado]]
        if all(cuotas):
            implicitas = [1 / c for c in cuotas]
            total = sum(implicitas)
            if total < 1.06:  # con más margen ya no es una referencia fina
                return [p / total for p in implicitas], ref
    return None


def probabilidad_consenso(cuotas_si: list[float], cuotas_no: list[float] | None = None,
                          margen_supuesto: float = 0.07) -> float:
    """Probabilidad justa a partir de las cuotas de varias casas (para córners, etc.).

    Con las cuotas de los dos lados (más y menos) de cada casa se quita el margen
    exacto; si solo hay un lado, se supone un margen típico del 7 % repartido a medias.
    """
    if cuotas_no and len(cuotas_no) == len(cuotas_si):
        probs = [(1 / s) / (1 / s + 1 / n) for s, n in zip(cuotas_si, cuotas_no)]
    else:
        probs = [(1 / s) / (1 + margen_supuesto / 2) for s in cuotas_si]
    return sum(probs) / len(probs)


@dataclass
class Oportunidad:
    fecha: date
    liga: str
    local: str
    visitante: str
    mercado: str
    casa: str
    cuota: float
    prob_justa: float
    referencia: str
    resultado: bool | None = None
    clv: float | None = None

    @property
    def cuota_justa(self) -> float:
        return 1 / self.prob_justa

    @property
    def valor(self) -> float:
        return self.cuota * self.prob_justa - 1


def _fecha(texto: str) -> date:
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha no reconocida: {texto!r}")


def _acierto(fila: dict, mercado: str, i: int) -> bool | None:
    try:
        gl, gv = int(fila["FTHG"]), int(fila["FTAG"])
    except (KeyError, ValueError, TypeError):
        return None
    if mercado == "1X2":
        return i == (0 if gl > gv else 1 if gl == gv else 2)
    return (gl + gv > 2) == (i == 0)


def oportunidades(fila: dict, casas: list[str], umbral: float = 0.02, cuota_min: float = 1.50,
                  cuota_max: float = 5.0) -> list[Oportunidad]:
    """Selecciones en las que alguna casa paga al menos `umbral` por encima de lo justo.

    Como mucho una por mercado y partido: la de más valor.
    """
    resultado = []
    for mercado, lados in MERCADOS.items():
        justo = precio_justo(fila, mercado)
        if not justo:
            continue
        probs, ref = justo
        mejor = None
        for i, (nombre, sufijo) in enumerate(lados):
            for casa in casas:
                cuota = _cuota(fila, _columna(casa, mercado, sufijo))
                if not cuota or not cuota_min <= cuota <= cuota_max:
                    continue
                o = Oportunidad(_fecha(fila["Date"]), fila.get("Div", ""), fila["HomeTeam"], fila["AwayTeam"],
                                nombre, casa, cuota, probs[i], ref)
                if o.valor >= umbral and (mejor is None or o.valor > mejor[1].valor):
                    mejor = (i, o)
        if mejor:
            i, o = mejor
            o.resultado = _acierto(fila, mercado, i)
            cierre = precio_justo(fila, mercado, cierre=True)
            if cierre:
                o.clv = o.cuota * cierre[0][i] - 1
            resultado.append(o)
    return resultado


def leer_filas(rutas: list[str]) -> list[dict]:
    archivos = []
    for ruta in rutas:
        if os.path.isdir(ruta):
            archivos += sorted(os.path.join(ruta, f) for f in os.listdir(ruta) if f.lower().endswith(".csv"))
        else:
            archivos.append(ruta)
    filas = []
    for archivo in archivos:
        with open(archivo, encoding="utf-8-sig", errors="replace", newline="") as f:
            for fila in csv.DictReader(f):
                if fila.get("HomeTeam") and fila.get("Date"):
                    fila["_archivo"] = os.path.basename(archivo)
                    filas.append(fila)
    return filas


@dataclass
class ResumenValor:
    n: int = 0
    aciertos: int = 0
    beneficio: float = 0.0
    suma_cuotas: float = 0.0
    suma_clv: float = 0.0
    con_clv: int = 0

    def anotar(self, o: Oportunidad) -> None:
        self.n += 1
        self.aciertos += o.resultado
        self.beneficio += o.cuota - 1 if o.resultado else -1
        self.suma_cuotas += o.cuota
        if o.clv is not None:
            self.suma_clv += o.clv
            self.con_clv += 1

    @property
    def yield_pct(self) -> float:
        return 100 * self.beneficio / self.n if self.n else 0.0

    @property
    def clv_pct(self) -> float:
        return 100 * self.suma_clv / self.con_clv if self.con_clv else 0.0


@dataclass
class InformeValor:
    por_temporada: dict[tuple[str, str], ResumenValor] = field(default_factory=lambda: defaultdict(ResumenValor))
    total: dict[str, ResumenValor] = field(default_factory=lambda: defaultdict(ResumenValor))


def backtest_valor(filas: list[dict], casas: list[str], umbral: float = 0.02, cuota_min: float = 1.50,
                   cuota_max: float = 5.0) -> InformeValor:
    informe = InformeValor()
    for fila in filas:
        if not fila.get("FTHG"):
            continue
        temporada = fila["_archivo"].rsplit("_", 1)[-1][:4]
        temporada = f"20{temporada[:2]}/{temporada[2:]}" if temporada.isdigit() else temporada
        for o in oportunidades(fila, casas, umbral, cuota_min, cuota_max):
            if o.resultado is None:
                continue
            familia = "1X2" if o.mercado in ("1", "X", "2") else "Goles 2.5"
            informe.por_temporada[(familia, temporada)].anotar(o)
            informe.total[familia].anotar(o)
    return informe
