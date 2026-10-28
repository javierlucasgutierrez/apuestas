"""Modelo de fuerzas de ataque y defensa para goles y córners.

Cada equipo tiene una fuerza de ataque (cuánto genera) y otra de defensa (cuánto
concede). Para un partido:

    esperado local     = base * ventaja_campo * ataque_local     * defensa_visitante
    esperado visitante = base *                 ataque_visitante * defensa_local

Los parámetros se estiman por máxima verosimilitud, dando más peso a los
partidos recientes (vida media configurable) y acercando a la media a los
equipos con pocos partidos (regularización).

- Goles: distribución de Poisson con la corrección de Dixon-Coles para los
  marcadores bajos (0-0, 1-0, 0-1, 1-1).
- Córners: varían más de lo que diría Poisson, así que el total se modela con
  una binomial negativa cuya dispersión se estima con los datos.
"""

import difflib
import math
from collections import defaultdict
from datetime import date

from .datos import Partido


def poisson(k: int, lam: float) -> float:
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1)) if lam > 0 else float(k == 0)


def binomial_negativa(k: int, media: float, dispersion: float) -> float:
    """P(X = k) con la media dada y varianza = dispersion * media."""
    if dispersion <= 1.001:
        return poisson(k, media)
    r = media / (dispersion - 1)
    p = r / (r + media)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))


def tau(i: int, j: int, lam: float, mu: float, rho: float) -> float:
    """Corrección de Dixon-Coles para los marcadores bajos."""
    if i == 0 and j == 0:
        return 1 - lam * mu * rho
    if i == 0 and j == 1:
        return 1 + lam * rho
    if i == 1 and j == 0:
        return 1 + mu * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


class ModeloFuerzas:
    def __init__(self, variable: str = "goles", vida_media_dias: float = 180.0,
                 regularizacion: float = 2.0, min_partidos: int = 6):
        if variable not in ("goles", "corners"):
            raise ValueError("variable debe ser 'goles' o 'corners'")
        self.variable = variable
        self.vida_media_dias = vida_media_dias
        self.regularizacion = regularizacion  # en "partidos de un equipo medio"
        self.min_partidos = min_partidos
        self.ataque: dict[str, float] = {}
        self.defensa: dict[str, float] = {}
        self.partidos_equipo: dict[str, int] = {}
        self.base = 1.3
        self.ventaja_campo = 1.2
        self.rho = 0.0
        self.dispersion = 1.0
        self.fecha_ajuste: date | None = None

    def valores(self, p: Partido) -> tuple[int, int] | None:
        if self.variable == "goles":
            return (p.goles_local, p.goles_visitante) if p.jugado else None
        return (p.corners_local, p.corners_visitante) if p.con_corners else None

    # ------------------------------------------------------------------ ajuste
    def ajustar(self, partidos: list[Partido], hasta: date | None = None,
                previo: "ModeloFuerzas | None" = None) -> "ModeloFuerzas":
        """Estima las fuerzas con los partidos anteriores a `hasta` (o todos).

        `previo` es un ajuste anterior del que partir: converge mucho antes.
        """
        datos = [(p, v) for p in partidos
                 if (hasta is None or p.fecha < hasta) and (v := self.valores(p)) is not None]
        if len(datos) < 20:
            raise ValueError(f"Hacen falta al menos 20 partidos con {self.variable} para ajustar el modelo.")
        referencia = hasta or max(p.fecha for p, _ in datos)
        if self.vida_media_dias:
            k = math.log(2) / self.vida_media_dias
            # Lo que pesa menos de un 3 % no aporta y solo ralentiza.
            datos = [(p, v) for p, v in datos if (referencia - p.fecha).days <= 5 * self.vida_media_dias]
            pesos = [math.exp(-k * max(0, (referencia - p.fecha).days)) for p, _ in datos]
        else:
            pesos = [1.0] * len(datos)
        filas = [(p.local, p.visitante, v[0], v[1], w) for (p, v), w in zip(datos, pesos)]
        equipos = sorted({f[0] for f in filas} | {f[1] for f in filas})

        total_w = sum(f[4] for f in filas)
        media = sum(w * (x + y) for _, _, x, y, w in filas) / (2 * total_w)
        if previo is not None and previo.ataque:
            a = {t: previo.ataque.get(t, 1.0) for t in equipos}
            d = {t: previo.defensa.get(t, 1.0) for t in equipos}
            c, h = previo.base, previo.ventaja_campo
        else:
            a = {t: 1.0 for t in equipos}
            d = {t: 1.0 for t in equipos}
            c, h = media, 1.2
        r = self.regularizacion * media

        for _ in range(300):
            a0, d0, c0, h0 = a, d, c, h
            num, den = defaultdict(float), defaultdict(float)
            for loc, vis, x, y, w in filas:
                num[loc] += w * x
                den[loc] += w * c * h * d[vis]
                num[vis] += w * y
                den[vis] += w * c * d[loc]
            a = {t: (num[t] + r) / (den[t] + r) for t in equipos}

            num, den = defaultdict(float), defaultdict(float)
            for loc, vis, x, y, w in filas:
                num[vis] += w * x
                den[vis] += w * c * h * a[loc]
                num[loc] += w * y
                den[loc] += w * c * a[vis]
            d = {t: (num[t] + r) / (den[t] + r) for t in equipos}

            ma = sum(a.values()) / len(a)
            md = sum(d.values()) / len(d)
            a = {t: v / ma for t, v in a.items()}
            d = {t: v / md for t, v in d.items()}

            h = (sum(w * x for _, _, x, _, w in filas)
                 / sum(w * c * a[loc] * d[vis] for loc, vis, _, _, w in filas))
            c = (sum(w * (x + y) for _, _, x, y, w in filas)
                 / sum(w * (h * a[loc] * d[vis] + a[vis] * d[loc]) for loc, vis, _, _, w in filas))

            cambio = max(max(abs(a[t] - a0[t]) for t in equipos),
                         max(abs(d[t] - d0[t]) for t in equipos),
                         abs(c - c0), abs(h - h0))
            if cambio < 1e-6:
                break

        self.ataque, self.defensa, self.base, self.ventaja_campo = a, d, c, h
        self.partidos_equipo = defaultdict(int)
        for loc, vis, *_ in filas:
            self.partidos_equipo[loc] += 1
            self.partidos_equipo[vis] += 1
        if self.variable == "goles":
            self.rho = self._estimar_rho(filas)
        else:
            self.dispersion = self._estimar_dispersion(filas)
        self.fecha_ajuste = referencia
        return self

    def _estimar_rho(self, filas) -> float:
        bajos = [(self.esperados(loc, vis), x, y, w) for loc, vis, x, y, w in filas if x <= 1 and y <= 1]
        mejor, mejor_ll = 0.0, -math.inf
        for paso in range(-25, 16):
            rho = paso / 100
            ll = 0.0
            for (lam, mu), x, y, w in bajos:
                t = tau(x, y, lam, mu, rho)
                if t <= 0:
                    ll = -math.inf
                    break
                ll += w * math.log(t)
            if ll > mejor_ll:
                mejor, mejor_ll = rho, ll
        return mejor

    def _estimar_dispersion(self, filas) -> float:
        """Varianza / media del total de córners, una vez descontado lo que explica el modelo."""
        num = den = 0.0
        for loc, vis, x, y, w in filas:
            m = sum(self.esperados(loc, vis))
            num += w * (x + y - m) ** 2
            den += w * m
        return min(max(num / den, 1.0), 3.0)

    # -------------------------------------------------------------- predicción
    @property
    def equipos(self) -> list[str]:
        return sorted(self.ataque)

    def conoce(self, equipo: str) -> bool:
        return equipo in self.ataque

    def esperados(self, local: str, visitante: str) -> tuple[float, float]:
        lam = self.base * self.ventaja_campo * self.ataque[local] * self.defensa[visitante]
        mu = self.base * self.ataque[visitante] * self.defensa[local]
        return lam, mu

    def matriz_goles(self, lam: float, mu: float, max_goles: int = 10) -> list[list[float]]:
        n = max_goles + 1
        pl = [poisson(i, lam) for i in range(n)]
        pv = [poisson(j, mu) for j in range(n)]
        m = [[pl[i] * pv[j] * tau(i, j, lam, mu, self.rho) for j in range(n)] for i in range(n)]
        total = sum(map(sum, m))
        return [[x / total for x in fila] for fila in m]

    def distribucion_total(self, media: float, maximo: int = 30) -> list[float]:
        """Probabilidad de cada número total de córners (0..maximo)."""
        dist = [binomial_negativa(k, media, self.dispersion) for k in range(maximo + 1)]
        total = sum(dist)
        return [x / total for x in dist]

    def clasificacion(self) -> list[tuple[str, float, float, float]]:
        """(equipo, a favor, en contra, diferencia) por partido contra un rival medio en campo neutral."""
        filas = [(t, self.base * self.ataque[t], self.base * self.defensa[t],
                  self.base * (self.ataque[t] - self.defensa[t])) for t in self.equipos]
        return sorted(filas, key=lambda x: -x[3])


# Nombres que otras webs escriben muy distinto a football-data (ya normalizados).
ALIAS = {
    "wolverhampton wanderers": "wolves", "inter milan": "inter", "internazionale": "inter",
    "paris saint germain": "paris sg", "psg": "paris sg", "borussia dortmund": "dortmund",
    "borussia monchengladbach": "m'gladbach", "bayer leverkusen": "leverkusen",
    "eintracht frankfurt": "ein frankfurt", "olympique marseille": "marseille", "olympique lyonnais": "lyon",
    "sporting lisbon": "sp lisbon", "sporting cp": "sp lisbon", "sporting braga": "sp braga",
    "nottingham forest": "nott'm forest", "sheffield united": "sheffield united",
    "queens park rangers": "qpr", "west bromwich albion": "west brom", "athletic club": "ath bilbao",
}


def _normalizar_nombre(nombre: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", nombre.lower()).encode("ascii", "ignore").decode()
    t = " ".join(t.replace("-", " ").replace(".", " ").split())
    t = ALIAS.get(t, t)
    # football-data escribe "Ath" tanto para Atlético como para Athletic.
    t = " ".join("ath" if w in ("atletico", "athletic", "atl") else w for w in t.split())
    for palabra in ("fc", "cf", "ac", "afc", "sc", "ssc", "as", "ud", "cd", "rc", "rcd", "sd", "real", "club",
                    "de", "calcio", "deportivo"):
        t = f" {t} ".replace(f" {palabra} ", " ").strip()
    return ALIAS.get(t, t)


def emparejar_equipo(nombre: str, equipos: list[str], minimo: float = 0.6) -> str | None:
    """El equipo de `equipos` que corresponde a `nombre` aunque se escriba distinto en otra web
    ("Real Betis" → "Betis", "Atlético Madrid" → "Ath Madrid"). None si no hay uno claro."""
    objetivo = _normalizar_nombre(nombre)
    normalizados = {t: _normalizar_nombre(t) for t in equipos}
    for t, n in normalizados.items():
        if n == objetivo:
            return t
    contienen = [t for t, n in normalizados.items() if len(n) >= 4 and len(objetivo) >= 4
                 and (n in objetivo or objetivo in n)]
    if len(contienen) == 1:
        return contienen[0]
    puntos = sorted(((difflib.SequenceMatcher(None, objetivo, n).ratio(), t) for t, n in normalizados.items()),
                    reverse=True)
    if puntos and puntos[0][0] >= minimo and (len(puntos) == 1 or puntos[0][0] - puntos[1][0] >= 0.08):
        return puntos[0][1]
    return None


def buscar_equipo(nombre: str, equipos: list[str]) -> str:
    """Nombre exacto del equipo (sin distinguir mayúsculas) o error con sugerencias."""
    for t in equipos:
        if t.lower() == nombre.strip().lower():
            return t
    parecidos = difflib.get_close_matches(nombre, equipos, n=3, cutoff=0.5)
    if not parecidos:
        parecidos = [t for t in equipos if nombre.strip().lower() in t.lower()][:3]
    sugerencia = f" ¿Quizás: {', '.join(parecidos)}?" if parecidos else ""
    raise KeyError(f"Equipo desconocido: {nombre!r}.{sugerencia}")
