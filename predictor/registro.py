"""Registro de picks en una base de datos local (SQLite, un solo archivo).

Cada pick que das queda guardado con su cuota, casa, stake y la hora a la que se
dio. Cuando se descargan los resultados, se liquida solo (ganada, perdida, nula,
medio ganada o medio perdida) y se calcula su CLV con la cuota de cierre. Así el
historial es completo y verificable: nada se borra ni se edita a mano.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from .valor import Oportunidad, _fecha, liquidar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado TEXT NOT NULL,
    fecha_partido TEXT NOT NULL,
    liga TEXT,
    local TEXT NOT NULL,
    visitante TEXT NOT NULL,
    mercado TEXT NOT NULL,
    familia TEXT,
    casa TEXT,
    cuota REAL NOT NULL,
    cuota_justa REAL,
    stake INTEGER NOT NULL,
    stake_pct REAL,
    perfil TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    beneficio REAL,
    clv REAL,
    liquidado TEXT,
    publicado INTEGER NOT NULL DEFAULT 0,
    UNIQUE (fecha_partido, local, visitante, mercado)
);
"""


def stake_10(stake_pct: float, tope: float = 0.03) -> int:
    """Stake de 1 a 10 al estilo tipster: 10 = el máximo que permite el sistema (tope)."""
    return max(1, min(10, round(10 * stake_pct / tope)))


def estado_de(beneficio: float, cuota: float) -> str:
    if beneficio == 0:
        return "nula"
    if abs(beneficio - (cuota - 1)) < 1e-9:
        return "ganada"
    if beneficio == -1:
        return "perdida"
    return "medio ganada" if beneficio > 0 else "medio perdida"


@dataclass
class Pick:
    id: int
    creado: str
    fecha_partido: date
    liga: str
    local: str
    visitante: str
    mercado: str
    familia: str
    casa: str
    cuota: float
    cuota_justa: float | None
    stake: int
    stake_pct: float | None
    perfil: str
    estado: str
    beneficio: float | None
    clv: float | None
    liquidado: str | None
    publicado: bool

    @property
    def unidades(self) -> float | None:
        """Unidades ganadas o perdidas (stake × beneficio por unidad)."""
        return None if self.beneficio is None else self.stake * self.beneficio


class Registro:
    def __init__(self, ruta: str):
        self.con = sqlite3.connect(ruta)
        self.con.executescript(ESQUEMA)

    def cerrar(self) -> None:
        self.con.close()

    def guardar(self, op: Oportunidad, stake_pct: float, perfil: str, tope: float = 0.03) -> bool:
        """Guarda un pick. Devuelve False si ya estaba (no se duplica ni se cambia)."""
        cur = self.con.execute(
            "INSERT OR IGNORE INTO picks (creado, fecha_partido, liga, local, visitante, mercado, familia, casa,"
            " cuota, cuota_justa, stake, stake_pct, perfil) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), op.fecha.isoformat(), op.liga, op.local,
             op.visitante, op.mercado, op.familia, op.casa, op.cuota, round(op.cuota_justa, 3),
             stake_10(stake_pct, tope), stake_pct, perfil))
        self.con.commit()
        return cur.rowcount == 1

    def picks(self, donde: str = "1=1", parametros: tuple = ()) -> list[Pick]:
        filas = self.con.execute(
            f"SELECT id, creado, fecha_partido, liga, local, visitante, mercado, familia, casa, cuota, cuota_justa,"
            f" stake, stake_pct, perfil, estado, beneficio, clv, liquidado, publicado FROM picks WHERE {donde}"
            f" ORDER BY fecha_partido, id", parametros).fetchall()
        return [Pick(f[0], f[1], date.fromisoformat(f[2]), *f[3:18], bool(f[18])) for f in filas]

    def pendientes(self) -> list[Pick]:
        return self.picks("estado = 'pendiente'")

    def marcar_publicados(self, ids: list[int]) -> None:
        self.con.executemany("UPDATE picks SET publicado = 1 WHERE id = ?", [(i,) for i in ids])
        self.con.commit()

    def liquidar(self, filas_resultados: list[dict]) -> list[Pick]:
        """Liquida los picks pendientes con los resultados descargados. Devuelve los liquidados."""
        indice = {}
        for f in filas_resultados:
            if f.get("FTHG") and f.get("HomeTeam") and f.get("Date"):
                try:
                    indice[(_fecha(f["Date"]), f["HomeTeam"], f["AwayTeam"])] = f
                except ValueError:
                    pass
        hechos = []
        for p in self.pendientes():
            fila = indice.get((p.fecha_partido, p.local, p.visitante))
            if not fila:
                continue
            beneficio, clv = liquidar(fila, p.mercado, p.cuota)
            if beneficio is None:
                continue
            estado = estado_de(beneficio, p.cuota)
            self.con.execute("UPDATE picks SET estado=?, beneficio=?, clv=?, liquidado=? WHERE id=?",
                             (estado, beneficio, clv, datetime.now().isoformat(timespec="seconds"), p.id))
            hechos.append(p)
        self.con.commit()
        return [q for q in self.picks("estado != 'pendiente'") if q.id in {p.id for p in hechos}]


def descripcion(p: "Pick") -> str:
    """El mercado en lenguaje normal, para publicar."""
    m = p.mercado
    if m == "1":
        return f"Gana {p.local}"
    if m == "2":
        return f"Gana {p.visitante}"
    if m == "X":
        return "Empate"
    if m in ("1X", "X2", "12"):
        return {"1X": f"{p.local} o empate", "X2": f"{p.visitante} o empate", "12": "No hay empate"}[m]
    if m.startswith("Hándicap "):
        _, equipo, linea = m.split()
        return f"{p.local if equipo == 'local' else p.visitante} {linea} (hándicap asiático)"
    if m.startswith("Goles asiático "):
        linea = m.split()[2]
        texto = "Más de" if linea.startswith("+") else "Menos de"
        return f"{texto} {linea[1:].replace('.', ',')} goles (asiático)"
    if m.startswith(("Goles ", "Córners ")):
        tipo, linea = m.split()
        texto = "Más de" if linea.startswith("+") else "Menos de"
        return f"{texto} {linea[1:].replace('.', ',')} {tipo.lower()}"
    return m


@dataclass
class Resumen:
    picks: int = 0
    ganadas: int = 0
    nulas: int = 0
    stake_total: float = 0.0
    unidades: float = 0.0
    suma_cuotas: float = 0.0
    suma_clv: float = 0.0
    con_clv: int = 0

    def anotar(self, p: Pick) -> None:
        self.picks += 1
        self.ganadas += p.beneficio > 0
        self.nulas += p.beneficio == 0
        self.stake_total += p.stake
        self.unidades += p.unidades
        self.suma_cuotas += p.cuota
        if p.clv is not None:
            self.suma_clv += p.clv
            self.con_clv += 1

    @property
    def yield_pct(self) -> float:
        """Beneficio sobre lo apostado (en unidades de stake)."""
        return 100 * self.unidades / self.stake_total if self.stake_total else 0.0

    @property
    def acierto_pct(self) -> float:
        return 100 * self.ganadas / self.picks if self.picks else 0.0

    @property
    def cuota_media(self) -> float:
        return self.suma_cuotas / self.picks if self.picks else 0.0

    @property
    def clv_pct(self) -> float | None:
        return 100 * self.suma_clv / self.con_clv if self.con_clv else None


def resumir(picks: list[Pick]) -> tuple[Resumen, dict[str, Resumen], dict[str, Resumen]]:
    """(total, por mes, por mercado) de los picks ya liquidados."""
    total, por_mes, por_familia = Resumen(), defaultdict(Resumen), defaultdict(Resumen)
    for p in picks:
        if p.beneficio is None:
            continue
        total.anotar(p)
        por_mes[f"{p.fecha_partido:%Y-%m}"].anotar(p)
        por_familia[p.familia or p.mercado].anotar(p)
    return total, dict(por_mes), dict(por_familia)
