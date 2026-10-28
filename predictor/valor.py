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

# Las casas que no tienen columnas de hándicap asiático simplemente no se tienen en cuenta ahí.
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
    familia: str = ""
    resultado: bool | None = None
    beneficio: float | None = None  # por euro apostado (en hándicap asiático puede ser medio o nulo)
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


def beneficio_handicap(diferencia: int, linea: float, cuota: float) -> float:
    """Beneficio por euro de una apuesta de hándicap asiático.

    `diferencia` son los goles a favor menos en contra del equipo apostado y `linea`
    su hándicap. Las líneas de cuarto (-0.25, +0.75...) son media apuesta a cada
    línea vecina: por eso se puede ganar o perder solo la mitad.
    """
    partes = [linea - 0.25, linea + 0.25] if abs(linea * 4) % 2 == 1 else [linea]
    total = 0.0
    for l in partes:
        margen = diferencia + l
        total += cuota - 1 if margen > 0 else 0.0 if margen == 0 else -1.0
    return total / len(partes)


def _justo_dos_lados(fila: dict, prefijos: list[str], local: str, visitante: str) -> list[float] | None:
    for ref in prefijos:
        a, b = _cuota(fila, ref + local), _cuota(fila, ref + visitante)
        if a and b and 1 / a + 1 / b < 1.06:
            total = 1 / a + 1 / b
            return [1 / a / total, 1 / b / total]
    return None


def _linea(texto) -> float | None:
    try:
        return float(str(texto).replace(",", "."))
    except ValueError:
        return None


def oportunidad_handicap(fila: dict, casas: list[str], umbral: float, cuota_min: float,
                         cuota_max: float) -> Oportunidad | None:
    """Hándicap asiático: el mercado con más dinero del fútbol, cuotas alrededor de 2."""
    linea = _linea(fila.get("AHh"))
    if linea is None:
        return None
    probs = _justo_dos_lados(fila, ["PAH", "BFEAH"], "H", "A")
    if not probs:
        return None
    mejor = None
    for i, lado in enumerate("HA"):
        for casa in casas:
            cuota = _cuota(fila, f"{casa}AH{lado}")
            if not cuota or not cuota_min <= cuota <= cuota_max:
                continue
            l = linea if i == 0 else -linea
            equipo = "local" if i == 0 else "visitante"
            o = Oportunidad(_fecha(fila["Date"]), fila.get("Div", ""), fila["HomeTeam"], fila["AwayTeam"],
                            f"Hándicap {equipo} {l:+g}", casa, cuota, probs[i], "PS" if fila.get("PAHH") else "BFE",
                            familia="Hándicap asiático")
            if o.valor >= umbral and (mejor is None or o.valor > mejor[1].valor):
                mejor = (i, o)
    if not mejor:
        return None
    i, o = mejor
    if fila.get("FTHG") and fila.get("FTAG"):
        diferencia = int(fila["FTHG"]) - int(fila["FTAG"])
        o.beneficio = beneficio_handicap(diferencia if i == 0 else -diferencia,
                                         linea if i == 0 else -linea, o.cuota)
        o.resultado = o.beneficio > 0
    if _linea(fila.get("AHCh")) == linea:
        cierre = _justo_dos_lados(fila, ["PCAH", "BFECAH"], "H", "A")
        if cierre:
            o.clv = o.cuota * cierre[i] - 1
    return o


def oportunidades(fila: dict, casas: list[str], umbral: float = 0.02, cuota_min: float = 1.50,
                  cuota_max: float = 5.0, handicap: bool = True) -> list[Oportunidad]:
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
                                nombre, casa, cuota, probs[i], ref, familia=mercado)
                if o.valor >= umbral and (mejor is None or o.valor > mejor[1].valor):
                    mejor = (i, o)
        if mejor:
            i, o = mejor
            o.resultado = _acierto(fila, mercado, i)
            if o.resultado is not None:
                o.beneficio = o.cuota - 1 if o.resultado else -1.0
            cierre = precio_justo(fila, mercado, cierre=True)
            if cierre:
                o.clv = o.cuota * cierre[0][i] - 1
            resultado.append(o)
    if handicap:
        o = oportunidad_handicap(fila, casas, umbral, cuota_min, cuota_max)
        if o:
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
        self.aciertos += o.beneficio > 0
        self.beneficio += o.beneficio
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
            if o.beneficio is None:
                continue
            informe.por_temporada[(o.familia, temporada)].anotar(o)
            informe.total[o.familia].anotar(o)
    return informe


def liquidar(fila: dict, mercado: str, cuota: float) -> tuple[float | None, float | None]:
    """(beneficio por euro, CLV) de una apuesta ya jugada. None si aún no hay resultado.

    Vale para 1X2, goles ±2.5, hándicap asiático ("Hándicap local -0.25") y córners
    ("Córners +9.5", sin CLV porque no hay cuotas de cierre de córners).
    """
    try:
        gl, gv = int(fila["FTHG"]), int(fila["FTAG"])
    except (KeyError, ValueError, TypeError):
        return None, None
    clv = None
    if mercado in ("1", "X", "2"):
        i = "1X2".index(mercado)
        ok = i == (0 if gl > gv else 1 if gl == gv else 2)
        beneficio = cuota - 1 if ok else -1.0
        cierre = precio_justo(fila, "1X2", cierre=True)
        if cierre:
            clv = cuota * cierre[0][i] - 1
    elif mercado.startswith("Goles "):
        linea = float(mercado.split()[1][1:])
        mas = "+" in mercado
        ok = (gl + gv > linea) if mas else (gl + gv < linea)
        beneficio = cuota - 1 if ok else -1.0
        if linea == 2.5:
            cierre = precio_justo(fila, "Goles 2.5", cierre=True)
            if cierre:
                clv = cuota * cierre[0][0 if mas else 1] - 1
    elif mercado.startswith("Hándicap "):
        _, equipo, texto = mercado.split()
        linea = float(texto)
        local = equipo == "local"
        beneficio = beneficio_handicap(gl - gv if local else gv - gl, linea, cuota)
        linea_local = linea if local else -linea
        if _linea(fila.get("AHCh")) == linea_local:
            cierre = _justo_dos_lados(fila, ["PCAH", "BFECAH"], "H", "A")
            if cierre:
                clv = cuota * cierre[0 if local else 1] - 1
    elif mercado.startswith("Córners "):
        try:
            total = int(fila["HC"]) + int(fila["AC"])
        except (KeyError, ValueError, TypeError):
            return None, None
        linea = float(mercado.split()[1][1:])
        ok = total > linea if "+" in mercado else total < linea
        beneficio = cuota - 1 if ok else -1.0
    else:
        raise ValueError(f"No sé liquidar el mercado {mercado!r}")
    return beneficio, clv
