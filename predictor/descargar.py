"""Descarga de datos de football-data.co.uk (gratuitos y pensados para descargarse).

Cada partido trae goles, córners y cuotas de 1X2 y de más/menos 2,5 goles.
El archivo de próximos partidos trae el calendario de los próximos días con cuotas.
"""

import os
import time
import urllib.request
from datetime import date

LIGAS = {
    "premier": ("E0", "Premier League (Inglaterra)"),
    "laliga": ("SP1", "LaLiga (España)"),
    "seriea": ("I1", "Serie A (Italia)"),
    "bundesliga": ("D1", "Bundesliga (Alemania)"),
    "ligue1": ("F1", "Ligue 1 (Francia)"),
    "championship": ("E1", "Championship (Inglaterra)"),
    "eredivisie": ("N1", "Eredivisie (Países Bajos)"),
    "portugal": ("P1", "Primeira Liga (Portugal)"),
}
GRANDES = ["premier", "laliga", "seriea", "bundesliga", "ligue1"]

URL_TEMPORADA = "https://www.football-data.co.uk/mmz4281/{temporada}/{codigo}.csv"
URL_PROXIMOS = "https://www.football-data.co.uk/fixtures.csv"


def temporada_actual(hoy: date | None = None) -> int:
    """Año en que empezó la temporada en curso (las ligas empiezan en agosto)."""
    hoy = hoy or date.today()
    return hoy.year if hoy.month >= 7 else hoy.year - 1


def codigo_temporada(inicio: int) -> str:
    return f"{inicio % 100:02d}{(inicio + 1) % 100:02d}"


def _bajar(url: str, destino: str) -> int:
    peticion = urllib.request.Request(url, headers={"User-Agent": "predictor-apuestas/1.0"})
    with urllib.request.urlopen(peticion, timeout=60) as r:
        contenido = r.read()
    with open(destino, "wb") as f:
        f.write(contenido)
    return contenido.count(b"\n")


def descargar(carpeta: str, ligas: list[str], temporadas: int = 4, aviso=print) -> None:
    """Baja las últimas `temporadas` de cada liga y los próximos partidos.

    Las temporadas pasadas ya descargadas no se vuelven a bajar; la actual sí,
    porque se actualiza cada semana.
    """
    os.makedirs(carpeta, exist_ok=True)
    actual = temporada_actual()
    codigos = []
    for nombre in ligas:
        if nombre not in LIGAS:
            raise ValueError(f"Liga desconocida: {nombre}. Disponibles: {', '.join(LIGAS)}")
        codigo, descripcion = LIGAS[nombre]
        codigos.append(codigo)
        for inicio in range(actual - temporadas + 1, actual + 1):
            temporada = codigo_temporada(inicio)
            destino = os.path.join(carpeta, f"{codigo}_{temporada}.csv")
            if os.path.exists(destino) and inicio != actual:
                continue
            try:
                lineas = _bajar(URL_TEMPORADA.format(temporada=temporada, codigo=codigo), destino)
                aviso(f"  {descripcion} {inicio}/{inicio + 1}: {lineas - 1} partidos")
            except Exception as e:  # noqa: BLE001 - se informa y se sigue con lo demás
                aviso(f"  {descripcion} {inicio}/{inicio + 1}: no disponible ({e})")
            time.sleep(1)  # sin prisas: no saturar la web

    destino = os.path.join(carpeta, "proximos.csv")
    temporal = destino + ".tmp"
    _bajar(URL_PROXIMOS, temporal)
    with open(temporal, encoding="utf-8-sig", errors="replace") as f:
        lineas = f.read().splitlines()
    os.remove(temporal)
    elegidas = [lineas[0]] + [l for l in lineas[1:] if l.split(",", 1)[0] in codigos]
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(elegidas) + "\n")
    aviso(f"  Próximos partidos: {len(elegidas) - 1}")
