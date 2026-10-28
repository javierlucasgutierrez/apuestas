"""Lectura de partidos desde CSV.

Acepta el formato propio de la herramienta (columnas en español) y también el
formato de football-data.co.uk (HomeTeam, FTHG, B365H...), que es una de las
fuentes gratuitas de estadísticas y cuotas más usadas.
"""

import csv
import os
from dataclasses import dataclass
from datetime import date, datetime

# Para cada campo, los nombres de columna que se aceptan (en orden de preferencia).
COLUMNAS = {
    "liga": ["liga", "div"],
    "fecha": ["fecha", "date"],
    "local": ["local", "hometeam", "home"],
    "visitante": ["visitante", "awayteam", "away"],
    "goles_local": ["goles_local", "fthg", "hg"],
    "goles_visitante": ["goles_visitante", "ftag", "ag"],
    "corners_local": ["corners_local", "hc"],
    "corners_visitante": ["corners_visitante", "ac"],
    "cuota_1": ["cuota_1", "b365h", "psh", "avgh", "bbavh", "psch"],
    "cuota_x": ["cuota_x", "b365d", "psd", "avgd", "bbavd", "pscd"],
    "cuota_2": ["cuota_2", "b365a", "psa", "avga", "bbava", "psca"],
    "cuota_mas25": ["cuota_mas25", "b365>2.5", "p>2.5", "avg>2.5", "bbav>2.5"],
    "cuota_menos25": ["cuota_menos25", "b365<2.5", "p<2.5", "avg<2.5", "bbav<2.5"],
}

FORMATOS_FECHA = ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"]


@dataclass
class Partido:
    fecha: date
    local: str
    visitante: str
    goles_local: int | None = None
    goles_visitante: int | None = None
    corners_local: int | None = None
    corners_visitante: int | None = None
    liga: str = ""
    cuota_1: float | None = None
    cuota_x: float | None = None
    cuota_2: float | None = None
    cuota_mas25: float | None = None
    cuota_menos25: float | None = None

    @property
    def jugado(self) -> bool:
        return self.goles_local is not None and self.goles_visitante is not None

    @property
    def con_corners(self) -> bool:
        return self.corners_local is not None and self.corners_visitante is not None

    @property
    def resultado(self) -> str | None:
        """'1', 'X' o '2'."""
        if not self.jugado:
            return None
        if self.goles_local > self.goles_visitante:
            return "1"
        if self.goles_local < self.goles_visitante:
            return "2"
        return "X"


def _fecha(texto: str) -> date:
    texto = texto.strip()
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise ValueError(f"Fecha no reconocida: {texto!r}")


def _numero(texto: str | None) -> float | None:
    if texto is None:
        return None
    texto = texto.strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _leer_texto(ruta: str) -> str:
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            with open(ruta, encoding=codificacion, newline="") as f:
                return f.read()
        except UnicodeDecodeError:
            pass
    raise ValueError(f"No se puede leer {ruta}")


def cargar_csv(ruta: str) -> list[Partido]:
    """Lee un CSV de partidos (separado por comas o por punto y coma)."""
    texto = _leer_texto(ruta)
    primera_linea = texto.splitlines()[0] if texto else ""
    separador = ";" if primera_linea.count(";") > primera_linea.count(",") else ","
    lector = csv.DictReader(texto.splitlines(), delimiter=separador)

    cabecera = {nombre.strip().lower(): nombre for nombre in (lector.fieldnames or [])}
    columna = {}
    for campo, alias in COLUMNAS.items():
        for nombre in alias:
            if nombre in cabecera:
                columna[campo] = cabecera[nombre]
                break
    faltan = [c for c in ("fecha", "local", "visitante") if c not in columna]
    if faltan:
        raise ValueError(f"{ruta}: faltan las columnas {', '.join(faltan)}")

    partidos = []
    for fila in lector:
        if not (fila.get(columna["local"]) or "").strip():
            continue
        valores = {campo: fila.get(nombre) for campo, nombre in columna.items()}
        goles_local = _numero(valores.get("goles_local"))
        goles_visitante = _numero(valores.get("goles_visitante"))
        corners_local = _numero(valores.get("corners_local"))
        corners_visitante = _numero(valores.get("corners_visitante"))
        partidos.append(Partido(
            fecha=_fecha(valores["fecha"]),
            local=valores["local"].strip(),
            visitante=valores["visitante"].strip(),
            goles_local=None if goles_local is None else int(goles_local),
            goles_visitante=None if goles_visitante is None else int(goles_visitante),
            corners_local=None if corners_local is None else int(corners_local),
            corners_visitante=None if corners_visitante is None else int(corners_visitante),
            liga=(valores.get("liga") or "").strip(),
            cuota_1=_numero(valores.get("cuota_1")),
            cuota_x=_numero(valores.get("cuota_x")),
            cuota_2=_numero(valores.get("cuota_2")),
            cuota_mas25=_numero(valores.get("cuota_mas25")),
            cuota_menos25=_numero(valores.get("cuota_menos25")),
        ))
    partidos.sort(key=lambda p: p.fecha)
    return partidos


def cargar_varios(rutas: list[str]) -> list[Partido]:
    """Une varios CSV (por ejemplo, varias temporadas) en una sola lista ordenada.

    Si una ruta es una carpeta, se leen todos sus CSV menos el de próximos partidos.
    """
    archivos = []
    for ruta in rutas:
        if os.path.isdir(ruta):
            archivos += sorted(os.path.join(ruta, f) for f in os.listdir(ruta)
                               if f.lower().endswith(".csv") and not f.lower().startswith("proximos"))
        else:
            archivos.append(ruta)
    if not archivos:
        raise ValueError(f"No hay archivos CSV en {', '.join(rutas)}. ¿Has ejecutado 'python app.py descargar'?")
    partidos = [p for ruta in archivos for p in cargar_csv(ruta)]
    partidos.sort(key=lambda p: p.fecha)
    return partidos


def guardar_csv(ruta: str, partidos: list[Partido]) -> None:
    campos = list(COLUMNAS)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(campos)
        for p in partidos:
            fila = []
            for campo in campos:
                valor = getattr(p, campo)
                if isinstance(valor, date):
                    valor = valor.strftime("%d/%m/%Y")
                fila.append("" if valor is None else valor)
            escritor.writerow(fila)


@dataclass
class CaraACara:
    partidos: list[Partido]
    equipo_a: str
    equipo_b: str

    @property
    def n(self) -> int:
        return len(self.partidos)

    def _goles(self, equipo: str, p: Partido) -> int:
        return p.goles_local if p.local == equipo else p.goles_visitante

    @property
    def victorias_a(self) -> int:
        return sum(self._goles(self.equipo_a, p) > self._goles(self.equipo_b, p) for p in self.partidos)

    @property
    def victorias_b(self) -> int:
        return sum(self._goles(self.equipo_b, p) > self._goles(self.equipo_a, p) for p in self.partidos)

    @property
    def empates(self) -> int:
        return self.n - self.victorias_a - self.victorias_b

    @property
    def goles_a(self) -> float:
        return sum(self._goles(self.equipo_a, p) for p in self.partidos) / self.n if self.n else 0.0

    @property
    def goles_b(self) -> float:
        return sum(self._goles(self.equipo_b, p) for p in self.partidos) / self.n if self.n else 0.0

    @property
    def pct_mas25(self) -> float:
        return sum(p.goles_local + p.goles_visitante > 2 for p in self.partidos) / self.n if self.n else 0.0

    @property
    def corners_medios(self) -> float | None:
        con = [p for p in self.partidos if p.con_corners]
        return sum(p.corners_local + p.corners_visitante for p in con) / len(con) if con else None

    @property
    def pct_ambos_marcan(self) -> float:
        return sum(p.goles_local > 0 and p.goles_visitante > 0 for p in self.partidos) / self.n if self.n else 0.0


def cara_a_cara(partidos: list[Partido], equipo_a: str, equipo_b: str,
                hasta: date | None = None, ultimos: int = 10) -> CaraACara:
    """Últimos enfrentamientos entre dos equipos (en cualquier campo)."""
    pareja = {equipo_a, equipo_b}
    previos = [p for p in partidos
               if p.jugado and {p.local, p.visitante} == pareja
               and (hasta is None or p.fecha < hasta)]
    return CaraACara(previos[-ultimos:], equipo_a, equipo_b)
