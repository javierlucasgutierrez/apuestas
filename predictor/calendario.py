"""Calendario de las próximas jornadas (fixturedownload.com, gratis y sin clave).

football-data.co.uk solo publica los próximos partidos 2-3 días antes. Este calendario
trae la temporada entera, así que el modelo puede calcular los picks de «más de» con
días de antelación aunque todavía no haya cuotas. No cubre las segundas de España,
Alemania e Italia: esas siguen llegando por football-data o por las cuotas en vivo.
"""

import csv
import json
import os
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

URL = "https://fixturedownload.com/feed/json/{liga}-{temporada}"
FEEDS = {
    "E0": "epl", "E1": "championship", "SP1": "la-liga", "D1": "bundesliga", "I1": "serie-a",
    "F1": "ligue-1", "F2": "ligue-2", "N1": "eredivisie", "SC0": "scottish-premiership",
}
MADRID = ZoneInfo("Europe/Madrid")
ARCHIVO = "calendario.csv"


def partidos_feed(datos: list[dict], codigo: str) -> list[dict]:
    """Los partidos sin jugar del feed, con la fecha y hora de España."""
    filas = []
    for p in datos:
        if p.get("HomeTeamScore") is not None or not p.get("HomeTeam") or not p.get("AwayTeam"):
            continue
        utc = datetime.strptime(p["DateUtc"], "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
        hora = utc.astimezone(MADRID)
        filas.append({"Div": codigo, "Date": hora.strftime("%d/%m/%Y"), "Time": hora.strftime("%H:%M"),
                      "HomeTeam": p["HomeTeam"], "AwayTeam": p["AwayTeam"]})
    return filas


def descargar_calendario(carpeta: str, codigos: list[str], temporada: int, dias: int = 10,
                         aviso=print) -> int:
    """Guarda en calendario.csv los partidos de los próximos `dias` días."""
    hoy, filas = date.today(), []
    for codigo in codigos:
        if codigo not in FEEDS:
            continue
        try:
            peticion = urllib.request.Request(URL.format(liga=FEEDS[codigo], temporada=temporada),
                                              headers={"User-Agent": "predictor-apuestas/1.0"})
            with urllib.request.urlopen(peticion, timeout=30) as r:
                datos = json.load(r)
        except Exception as e:  # noqa: BLE001 - sin calendario se sigue con football-data
            aviso(f"  Calendario {codigo}: no disponible ({e})")
            continue
        for f in partidos_feed(datos, codigo):
            if hoy <= datetime.strptime(f["Date"], "%d/%m/%Y").date() <= hoy + timedelta(days=dias):
                filas.append(f)
    if filas:
        with open(os.path.join(carpeta, ARCHIVO), "w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=["Div", "Date", "Time", "HomeTeam", "AwayTeam"])
            escritor.writeheader()
            escritor.writerows(filas)
    aviso(f"  Calendario de los próximos {dias} días: {len(filas)} partidos")
    return len(filas)
