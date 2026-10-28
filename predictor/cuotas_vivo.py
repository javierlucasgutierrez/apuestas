"""Cuotas en vivo de The Odds API (the-odds-api.com), con plan gratuito.

Descarga 1X2, hándicap asiático y más/menos 2,5 goles de muchas casas, incluidas
Pinnacle y la bolsa de Betfair (la referencia del precio justo), y lo guarda con
las mismas columnas que football-data. Así el resto del programa lo usa igual.

Cada liga y mercado gasta créditos del plan (el gratuito da 500 al mes): con 20
ligas y 3 mercados en una región son unos 60 por descarga.
"""

import csv
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

URL = "https://api.the-odds-api.com/v4/sports/{deporte}/odds"

# código de liga de football-data -> deporte de The Odds API
DEPORTES = {
    "E0": "soccer_epl", "E1": "soccer_efl_champ", "E2": "soccer_england_league1",
    "E3": "soccer_england_league2", "SP1": "soccer_spain_la_liga", "SP2": "soccer_spain_segunda_division",
    "I1": "soccer_italy_serie_a", "I2": "soccer_italy_serie_b", "D1": "soccer_germany_bundesliga",
    "D2": "soccer_germany_bundesliga2", "F1": "soccer_france_ligue_one", "F2": "soccer_france_ligue_two",
    "N1": "soccer_netherlands_eredivisie", "P1": "soccer_portugal_primeira_liga", "SC0": "soccer_spl",
    "B1": "soccer_belgium_first_div", "T1": "soccer_turkey_super_league", "G1": "soccer_greece_super_league",
}
# casas de referencia: su código en las columnas de football-data
REFERENCIAS = {"pinnacle": "PS", "betfair_ex_eu": "BFE", "betfair_ex_uk": "BFE"}


def _pedir(url: str) -> tuple[list, str | None]:
    peticion = urllib.request.Request(url, headers={"User-Agent": "predictor-apuestas/1.0"})
    with urllib.request.urlopen(peticion, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")), r.headers.get("x-requests-remaining")


def _columnas_goles(codigo: str) -> str:
    return {"PS": "P"}.get(codigo, codigo)


def evento_a_fila(evento: dict, liga: str) -> dict:
    """Convierte un partido de The Odds API en una fila con columnas de football-data."""
    inicio = datetime.fromisoformat(evento["commence_time"].replace("Z", "+00:00"))
    hora_es = inicio + timedelta(hours=1)  # hora peninsular aproximada (invierno)
    local, visitante = evento["home_team"], evento["away_team"]
    fila = {"Div": liga, "Date": f"{hora_es:%d/%m/%Y}", "Time": f"{hora_es:%H:%M}",
            "HomeTeam": local, "AwayTeam": visitante}
    mejores: dict[str, float] = {}

    def anotar(codigo: str, columna: str, cuota: float, referencia: bool) -> None:
        fila[columna] = cuota
        if not referencia:
            clave = "Max" + columna[len(codigo):]
            mejores[clave] = max(mejores.get(clave, 0.0), cuota)

    # Línea de hándicap: la de Pinnacle (o la de Betfair si no hay Pinnacle).
    linea = None
    for ref in ("pinnacle", "betfair_ex_eu", "betfair_ex_uk"):
        for casa in evento.get("bookmakers", []):
            if casa["key"] != ref:
                continue
            for mercado in casa.get("markets", []):
                if mercado["key"] == "spreads":
                    for o in mercado["outcomes"]:
                        if o["name"] == local and linea is None:
                            linea = float(o["point"])
    if linea is not None:
        fila["AHh"] = linea

    # Línea principal de goles de Pinnacle (o Betfair). Si no es 2,5 es una línea asiática
    # (2,25, 2,75, 3...) y se guarda en las columnas TL ("total line").
    linea_goles = None
    for ref in ("pinnacle", "betfair_ex_eu", "betfair_ex_uk"):
        for casa in evento.get("bookmakers", []):
            if casa["key"] == ref and linea_goles is None:
                for mercado in casa.get("markets", []):
                    if mercado["key"] == "totals" and mercado.get("outcomes"):
                        linea_goles = float(mercado["outcomes"][0].get("point", 2.5))
    if linea_goles is not None and linea_goles != 2.5:
        fila["TL"] = linea_goles

    for casa in evento.get("bookmakers", []):
        referencia = casa["key"] in REFERENCIAS
        codigo = REFERENCIAS.get(casa["key"], casa.get("title", casa["key"]))
        for mercado in casa.get("markets", []):
            salidas = mercado.get("outcomes", [])
            if mercado["key"] == "h2h":
                for o in salidas:
                    sufijo = "H" if o["name"] == local else "A" if o["name"] == visitante else "D"
                    anotar(codigo, codigo + sufijo, float(o["price"]), referencia)
            elif mercado["key"] == "totals":
                for o in salidas:
                    punto = float(o.get("point", 0))
                    c = _columnas_goles(codigo)
                    if punto == 2.5:
                        sufijo = ">2.5" if o["name"] == "Over" else "<2.5"
                        anotar(c, c + sufijo, float(o["price"]), referencia)
                    elif punto == fila.get("TL"):
                        anotar(c, c + ("TLO" if o["name"] == "Over" else "TLU"), float(o["price"]), referencia)
            elif mercado["key"] == "spreads" and linea is not None:
                for o in salidas:
                    if o["name"] == local and float(o["point"]) == linea:
                        anotar(codigo, codigo + "AHH", float(o["price"]), referencia)
                    elif o["name"] == visitante and float(o["point"]) == -linea:
                        anotar(codigo, codigo + "AHA", float(o["price"]), referencia)
    # Pinnacle en hándicap usa el prefijo PAH (como football-data).
    for lado in "HA":
        if f"PSAH{lado}" in fila:
            fila[f"PAH{lado}"] = fila.pop(f"PSAH{lado}")
    fila.update(mejores)
    return fila


def descargar_cuotas(clave: str, ligas: list[str], destino: str, regiones: str = "eu",
                     mercados: str = "h2h,spreads,totals", aviso=print) -> int:
    """Descarga los próximos partidos con cuotas y los guarda en `destino`. Devuelve cuántos."""
    filas, restantes = [], None
    for liga in ligas:
        deporte = DEPORTES.get(liga)
        if not deporte:
            continue
        parametros = urllib.parse.urlencode({"apiKey": clave, "regions": regiones, "markets": mercados,
                                             "oddsFormat": "decimal", "dateFormat": "iso"})
        try:
            eventos, restantes = _pedir(URL.format(deporte=deporte) + "?" + parametros)
        except Exception as e:  # noqa: BLE001 - se informa y se sigue con las demás ligas
            aviso(f"  {liga}: sin cuotas en vivo ({e})")
            continue
        filas += [evento_a_fila(ev, liga) for ev in eventos]
    if not filas:
        # No se sobrescribe nada: se seguirán usando los próximos partidos de football-data.
        aviso("  Cuotas en vivo: ninguna descargada (revisa la clave en the-odds-api.com)")
        return 0
    columnas = sorted({k for f in filas for k in f}, key=lambda k: (k not in ("Div", "Date", "Time", "HomeTeam",
                                                                            "AwayTeam"), k))
    # Además de usarse ahora, cada descarga se guarda: con el tiempo será nuestro propio
    # histórico de cuotas (asiático de goles incluido) para poder hacer backtest.
    historial = os.path.join(os.path.dirname(os.path.dirname(destino)), "historial_cuotas")
    os.makedirs(historial, exist_ok=True)
    for ruta in (destino, os.path.join(historial, f"vivo_{datetime.now():%Y%m%d_%H%M}.csv")):
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=columnas)
            escritor.writeheader()
            escritor.writerows(filas)
    aviso(f"  Cuotas en vivo: {len(filas)} partidos" + (f" · créditos restantes: {restantes}" if restantes else ""))
    return len(filas)


def archivo_proximos(carpeta: str, horas: int = 12) -> str:
    """El archivo de próximos partidos a usar: el de cuotas en vivo si es reciente."""
    vivo = os.path.join(carpeta, "proximos_vivo.csv")
    if os.path.exists(vivo) and datetime.now().timestamp() - os.path.getmtime(vivo) < horas * 3600:
        return vivo
    return os.path.join(carpeta, "proximos.csv")
