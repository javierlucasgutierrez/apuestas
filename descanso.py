"""Estrategia del descanso: en partidos «de muchos goles», mirar en el descanso si hay valor en los «más de».

Base (23.909 partidos): los goles de la 2ª parte casi no dependen de cómo vaya al descanso, sino de lo
que se esperaba del partido antes de empezar. Un 0-0 al descanso en un partido de muchos goles no lo
convierte en «cerrado». Si la casa en directo lo cree, paga de más por los «más de».

- preseleccionar: por la mañana, los partidos del día con más goles esperados (precio justo de
  Pinnacle/Betfair) y su hora; guarda datos/descanso_hoy.json para programar las revisiones.
- revisar: en el descanso, marcador y cuotas en directo (The Odds API, ~2 créditos por grupo de
  partidos de la misma liga y hora). Probabilidad de la 2ª parte: Poisson con el 55 % de los goles
  esperados. Avisa si una casa con licencia en España paga ≥5 % por encima de lo justo.
- Todo se apunta (avise o no) en datos/descanso.json, y se liquida con los resultados descargados.

Uso: python3 descanso.py --preseleccionar | --revisar E0 2026-11-01T14:00 | --liquidar
"""

import argparse
import json
import math
import os
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app as cli
from estrategias import CASAS_ESPANA
from predictor.cuotas_vivo import DEPORTES, _pedir
from predictor.modelo import emparejar_equipo
from predictor.valor import _fecha, leer_filas, precio_justo

REGISTRO = os.path.join(cli.CARPETA, "datos", "descanso.json")
HOY = os.path.join(cli.CARPETA, "datos", "descanso_hoy.json")
PROB_MINIMA_PREVIA = 0.40   # «más de 2,5» antes del partido (los de pocos goles rinden igual o mejor)
MAXIMO_POR_DIA = 4         # 2 créditos por revisión (marcador y cuotas; menos si coinciden liga y hora)
PARTE_2 = 0.55              # parte de los goles que llega en la 2ª parte
# Corrección según el marcador al descanso (ajustada en 11.876 partidos, estable en 2023-25 y 2025-27):
# con 0 goles la 2ª parte trae algo menos de lo esperado; con 1 gol, algo más.
FACTOR_DESCANSO = {0: 0.95, 1: 1.02}
# Con 1 gol importa quién gana: si gana el visitante, el local aprieta y llegan más goles (estable en ambos periodos).
FACTOR_MARCADOR = {(0, 0): 0.95, (1, 0): 1.01, (0, 1): 1.05}
# Marcadores que mejor rindieron en el backtest (línea +1,5): se destacan en el aviso.
# CONDICIÓN ÓPTIMA (backtest a la cuota habitual de la casa, 4.050 partidos, +6,8 %: +6,5 / +7,4 en cada
# periodo; +9,3 % si además era de pocos goles): al descanso 1-0 o 0-1 y va perdiendo el favorito o el
# partido estaba igualado (el que pierde tenía al menos la probabilidad de ganar del otro menos 10 puntos).
# Entonces «2 goles más» se apuesta en cuanto la casa paga la cuota justa. Si pierde el más débil: −2 %.
MARGEN_IGUALADO = 0.10


def condicion_optima(local: int, visitante: int, p_local: float | None, p_visitante: float | None) -> bool:
    if (local, visitante) not in ((1, 0), (0, 1)) or p_local is None or p_visitante is None:
        return False
    pierde, gana = (p_local, p_visitante) if (local, visitante) == (0, 1) else (p_visitante, p_local)
    return pierde >= gana - MARGEN_IGUALADO


def factor(local: int, visitante: int) -> float:
    return FACTOR_MARCADOR.get((local, visitante), FACTOR_DESCANSO.get(local + visitante, 1.0))
VALOR_MINIMO = 0.05
MINUTOS_HASTA_DESCANSO = 52
CASAS = {k: v for k, v in CASAS_ESPANA.items() if k != "B365"}  # Bet365 no está en The Odds API


def leer(ruta, defecto):
    if not os.path.exists(ruta):
        return defecto
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def escribir(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def goles_esperados(p_mas25: float) -> float:
    """Goles esperados (Poisson) que dan esa probabilidad de «más de 2,5»."""
    bajo, alto = 0.2, 6.0
    for _ in range(60):
        lam = (bajo + alto) / 2
        p = 1 - math.exp(-lam) * (1 + lam + lam * lam / 2)
        bajo, alto = (lam, alto) if p < p_mas25 else (bajo, lam)
    return (bajo + alto) / 2


def prob_al_menos(k: int, lam: float) -> float:
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))


# Rentabilidad de la línea +1,5 del descanso por liga en el backtest (2023-26, a la cuota mínima).
# Ordena qué partidos se vigilan; con resultados reales se corrige (ver prioridad_ligas).
BACKTEST_LIGAS = {"SP2": 17.9, "E0": 13.1, "N1": 12.6, "D1": 9.3, "I2": 8.5, "I1": 8.5, "F2": 8.2,
                  "SP1": 8.0, "F1": 7.5, "SC0": 7.4, "E1": 6.0}
LIGAS_FUERA = {"D2"}  # 2. Bundesliga: +2,7 % e inestable


def prioridad_ligas() -> dict[str, float]:
    """Backtest por liga, corregido con los avisos reales ya liquidados (cuanto más datos, más pesan).

    Cada aviso real cuenta: acertar por encima de lo previsto sube la liga y quedarse por debajo la baja.
    Se mezcla como si el backtest valiera 200 avisos, para no reaccionar a rachas cortas.
    """
    reales = defaultdict(lambda: [0, 0.0])
    for r in leer(REGISTRO, []):
        if r.get("acierto") is not None and r.get("cuota_minima") and round(r["linea"] - r["goles_descanso"], 1) == 1.5:
            gana = (r["cuota_minima"] - 1) if r["acierto"] else -1
            reales[r["liga"]][0] += 1
            reales[r["liga"]][1] += 100 * gana
    return {liga: (BACKTEST_LIGAS.get(liga, 5.0) * 200 + reales[liga][1]) / (200 + reales[liga][0])
            for liga in set(BACKTEST_LIGAS) | set(reales)}


def preseleccionar(dia: date | None = None) -> dict:
    """Partidos del día que más rinden en el descanso: ligas mejores primero (backtest + resultados reales).

    Goles esperados: del precio justo de Pinnacle/Betfair si lo hay; si no, del modelo propio.
    Entran todos los tipos de partido desde un 40 % de «más de 2,5» (los de pocos goles rinden igual o mejor).
    """
    import panel  # el modelo propio solo hace falta aquí
    dia = dia or date.today()
    hoy = dia.strftime("%d/%m/%Y")
    madrid = ZoneInfo("Europe/Madrid")
    prioridad = prioridad_ligas()
    modelo = None
    vistos, candidatos = set(), []
    for archivo in ("proximos_vivo.csv", "calendario.csv"):
        for f in leer_filas([os.path.join(cli.DESCARGAS, archivo)]):
            liga = f.get("Div")
            if f.get("Date") != hoy or liga not in DEPORTES or liga in LIGAS_FUERA:
                continue
            modelo = modelo or panel.predictor()
            equipos = modelo.goles[liga].equipos if liga in modelo.goles else []
            local, visitante = emparejar_equipo(f["HomeTeam"], equipos), emparejar_equipo(f["AwayTeam"], equipos)
            if not local or not visitante:
                continue
            pred = modelo.predecir(local, visitante, fecha=dia)
            justo = precio_justo(f, "Goles 2.5")
            if justo:
                p = justo[0][0]
                lam = goles_esperados(p)
            else:
                p, lam = pred.probs["Goles +2.5"], pred.goles_local + pred.goles_visitante
            if p < PROB_MINIMA_PREVIA:
                continue
            inicio = datetime.strptime(f"{f['Date']} {f['Time']}", "%d/%m/%Y %H:%M").replace(tzinfo=madrid)
            inicio = inicio.astimezone(timezone.utc)
            clave = (liga, inicio.strftime("%Y-%m-%dT%H"), emparejar_equipo(f["HomeTeam"], [c[2] for c in vistos if c[0] == liga]) or f["HomeTeam"])
            if any(v[0] == liga and v[1] == clave[1] and emparejar_equipo(f["HomeTeam"], [v[2]]) for v in vistos):
                continue
            vistos.add(clave)
            candidatos.append({"liga": liga, "local": f["HomeTeam"], "visitante": f["AwayTeam"],
                               "inicio_utc": inicio.strftime("%Y-%m-%dT%H:%M"), "p_previa": round(p, 4),
                               "goles_esperados": round(lam, 2), "origen": "mercado" if justo else "modelo",
                               "prioridad": round(prioridad.get(liga, 5.0), 1),
                               "p_local": round(pred.probs["1"], 3), "p_visitante": round(pred.probs["2"], 3)})
    # Se eligen los partidos donde es más probable la condición óptima: igualados (cualquier 1-0 o 0-1 la
    # cumple) y de pocos goles (rinden más); la liga solo desempata.
    def puntos(c):
        return (10 * (abs(c["p_local"] - c["p_visitante"]) <= MARGEN_IGUALADO) + 5 * (c["p_previa"] < 0.5)
                + c["prioridad"] / 3)
    elegidos = sorted(candidatos, key=lambda c: (-puntos(c), c["inicio_utc"]))[:MAXIMO_POR_DIA]
    # Una revisión por liga y hora de inicio: así una sola consulta sirve para varios partidos.
    revisiones = sorted({(c["liga"], c["inicio_utc"]) for c in elegidos}, key=lambda x: x[1])
    salida = {"fecha": dia.isoformat(), "partidos": elegidos,
              "revisiones": [{"liga": l, "inicio_utc": i,
                              "revisar_utc": (datetime.fromisoformat(i) + timedelta(minutes=MINUTOS_HASTA_DESCANSO)).strftime("%Y-%m-%dT%H:%M:00Z")}
                             for l, i in revisiones]}
    escribir(HOY, salida)
    return salida


def revisar(liga: str, inicio_utc: str) -> list[dict]:
    """En el descanso: marcador y cuotas en directo de los partidos preseleccionados de esa liga y hora."""
    clave = os.environ.get("ODDS_API_KEY") or cli.clave_odds()
    plan = [p for p in leer(HOY, {}).get("partidos", []) if p["liga"] == liga and p["inicio_utc"] == inicio_utc]
    if not plan or not clave:
        return []
    deporte = DEPORTES[liga]
    base = "https://api.the-odds-api.com/v4/sports/" + deporte
    marcadores, _ = _pedir(f"{base}/scores?" + urllib.parse.urlencode({"apiKey": clave}))
    eventos, restantes = _pedir(f"{base}/odds?" + urllib.parse.urlencode(
        {"apiKey": clave, "regions": "eu", "markets": "totals", "oddsFormat": "decimal"}))
    registro, salida = leer(REGISTRO, []), []
    for p in plan:
        ev = next((e for e in eventos if emparejar_equipo(p["local"], [e["home_team"]]) and
                   emparejar_equipo(p["visitante"], [e["away_team"]])), None)
        mc = next((m for m in marcadores if ev and m["id"] == ev["id"]), None)
        if not ev or not mc or not mc.get("scores"):
            salida.append({**p, "nota": "sin marcador o sin cuotas en directo"})
            continue
        goles = sum(int(s["score"]) for s in mc["scores"])
        lam2 = p["goles_esperados"] * PARTE_2 * FACTOR_DESCANSO.get(goles, 1.0)
        mejores = {}
        for casa in ev.get("bookmakers", []):
            nombre = CASAS.get(casa["title"])
            if not nombre:
                continue
            for m in casa.get("markets", []):
                for o in m.get("outcomes", []) if m["key"] == "totals" else []:
                    # Solo líneas x,5 (las asiáticas ,25/,75 se liquidan a medias: aquí no).
                    if o["name"] == "Over" and float(o["point"]) > goles and float(o["point"]) % 1 == 0.5:
                        linea = float(o["point"])
                        if linea not in mejores or o["price"] > mejores[linea][0]:
                            mejores[linea] = (float(o["price"]), nombre)
        for linea, (cuota, nombre) in sorted(mejores.items()):
            prob = prob_al_menos(math.floor(linea) + 1 - goles, lam2)
            valor = prob * cuota - 1
            entrada = {"fecha": inicio_utc[:10], "liga": liga, "local": p["local"], "visitante": p["visitante"],
                       "revisado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"), "goles_descanso": goles,
                       "linea": linea, "cuota": cuota, "casa": nombre, "prob": round(prob, 4),
                       "cuota_justa": round(1 / prob, 2), "valor": round(valor, 4),
                       "aviso": valor >= VALOR_MINIMO and cuota >= 1.50, "resultado": None, "unidades": None}
            registro.append(entrada)
            salida.append(entrada)
    escribir(REGISTRO, registro)
    print(f"Créditos restantes: {restantes}")
    return salida


def avisar(liga: str, inicio_utc: str) -> list[str]:
    """En el descanso: solo el marcador (1 crédito) y la cuota justa y mínima de cada «más de».

    Es lo que pidió el usuario: se le avisa siempre y él mira la cuota en su casa.
    Se apunta en el registro (sin cuota) para medir con el tiempo si esas líneas aciertan lo previsto.
    """
    clave = os.environ.get("ODDS_API_KEY") or cli.clave_odds()
    plan = [p for p in leer(HOY, {}).get("partidos", []) if p["liga"] == liga and p["inicio_utc"] == inicio_utc]
    if not plan or not clave:
        return []
    base = f"https://api.the-odds-api.com/v4/sports/{DEPORTES[liga]}"
    marcadores, restantes = _pedir(f"{base}/scores?" + urllib.parse.urlencode({"apiKey": clave}))
    try:  # cuotas en directo de las casas españolas (1 crédito más); sin ellas, el aviso sale igual
        eventos, restantes = _pedir(f"{base}/odds?" + urllib.parse.urlencode(
            {"apiKey": clave, "regions": "eu", "markets": "totals", "oddsFormat": "decimal"}))
    except Exception:  # noqa: BLE001
        eventos = []
    registro, textos = leer(REGISTRO, []), []
    for p in plan:
        local = emparejar_equipo(p["local"], [m["home_team"] for m in marcadores])
        mc = next((m for m in marcadores if m["home_team"] == local), None)
        if not mc or not mc.get("scores"):
            textos.append(f"{p['local']} - {p['visitante']}: sin marcador todavía")
            continue
        g = {s["name"]: int(s["score"]) for s in mc["scores"]}
        gl, gv = g.get(mc["home_team"], 0), g.get(mc["away_team"], 0)
        lam2 = p["goles_esperados"] * PARTE_2 * factor(gl, gv)
        ev = next((e for e in eventos if e["id"] == mc["id"]), None)
        pagan = {}  # línea -> (mejor cuota de una casa española, casa)
        for casa in (ev or {}).get("bookmakers", []):
            nombre = CASAS.get(casa["title"])
            for m in casa.get("markets", []) if nombre else []:
                for o in m.get("outcomes", []) if m["key"] == "totals" else []:
                    linea_o = float(o.get("point", 0))
                    if o["name"] == "Over" and linea_o % 1 == 0.5 and float(o["price"]) > pagan.get(linea_o, (0,))[0]:
                        pagan[linea_o] = (float(o["price"]), nombre)
        partes = []
        optima = condicion_optima(gl, gv, p.get("p_local"), p.get("p_visitante"))
        for extra in (1, 2, 3):
            linea = gl + gv + extra - 0.5
            prob = prob_al_menos(extra, lam2)
            # En la condición óptima, «2 goles más» vale desde la cuota justa; lo demás pide un 5 % extra.
            minima = max(1.50, (1.0 if optima and extra == 2 else 1 + VALOR_MINIMO) / prob)
            texto = f"Más de {linea:.1f} → justa {1 / prob:.2f} · mínima {minima:.2f}"
            if linea in pagan:
                cuota, casa = pagan[linea]
                texto += f" · {casa} paga {cuota:.2f} {'✅' if cuota >= minima else '❌'}"
            partes.append(texto.replace(".", ","))
            registro.append({"fecha": inicio_utc[:10], "liga": liga, "local": p["local"], "visitante": p["visitante"],
                             "revisado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"), "goles_descanso": gl + gv,
                             "linea": linea, "cuota": pagan.get(linea, (None,))[0], "casa": pagan.get(linea, (None, None))[1],
                             "prob": round(prob, 4),
                             "cuota_justa": round(1 / prob, 2), "cuota_minima": round(minima, 2), "valor": None,
                             # aviso = una casa española pagaba la mínima: solo esas cuentan como apuesta
                             "aviso": linea in pagan and pagan[linea][0] >= minima, "optima": optima and extra == 2,
                             "resultado": None, "unidades": None})
        textos.append(f"AVISO ⏸️ {mc['home_team']} {gl}-{gv} {mc['away_team']} (descanso)"
                      + (f" ⭐ CONDICIÓN ÓPTIMA: pierde el favorito o el partido estaba igualado → más de {gl + gv + 1.5:.1f} "
                         f"si tu casa paga la mínima" if optima else "") + ": " + " · ".join(partes))
    escribir(REGISTRO, registro)
    print(f"Créditos restantes: {restantes}")
    return textos


def repaso(dia: date) -> list[str]:
    """Qué habría avisado el sistema en los descansos de un día ya jugado y si se cumplió.

    Usa los resultados descargados (marcador al descanso y final) y la misma selección por liga.
    Las cuotas en directo de entonces no se conocen: se dice la mínima que habría hecho falta.
    """
    from predictor.descargar import LIGAS, PRINCIPALES
    principales = {LIGAS[l][0] for l in PRINCIPALES} - LIGAS_FUERA
    prioridad = prioridad_ligas()
    candidatos = []
    for f in leer_filas([cli.DESCARGAS]):
        if not f.get("HTHG") or f.get("Div") not in principales:
            continue
        try:
            if _fecha(f["Date"]) != dia:
                continue
        except ValueError:
            continue
        justo = precio_justo(f, "Goles 2.5")
        if not justo or justo[0][0] < PROB_MINIMA_PREVIA:
            continue
        candidatos.append((prioridad.get(f["Div"], 5.0), f, justo[0][0]))
    textos = []
    for _, f, p in sorted(candidatos, key=lambda c: -c[0])[:MAXIMO_POR_DIA]:
        ht, ft = int(f["HTHG"]) + int(f["HTAG"]), int(f["FTHG"]) + int(f["FTAG"])
        lam2 = goles_esperados(p) * PARTE_2 * factor(int(f["HTHG"]), int(f["HTAG"]))
        prob = prob_al_menos(2, lam2)
        minima = max(1.50, (1 + VALOR_MINIMO) / prob)
        cumple = ft - ht >= 2
        textos.append(f"{f['HomeTeam']} - {f['AwayTeam']}: descanso {f['HTHG']}-{f['HTAG']}, final {f['FTHG']}-{f['FTAG']} · "
                      f"«más de {ht + 1.5:.1f}» (mínima {minima:.2f}) {'✅ se cumplió' if cumple else '❌ no se cumplió'}".replace(".", ","))
    return textos


def liquidar() -> int:
    finales = {}
    for f in leer_filas([cli.DESCARGAS]):
        if f.get("FTHG") and f.get("HomeTeam"):
            try:
                finales[(_fecha(f["Date"]).isoformat(), f["HomeTeam"])] = (f, int(f["FTHG"]) + int(f["FTAG"]))
            except ValueError:
                pass
    registro, hechos = leer(REGISTRO, []), 0
    equipos = sorted({k[1] for k in finales})
    for r in registro:
        if r["resultado"] is not None:
            continue
        local = emparejar_equipo(r["local"], equipos)
        fin = finales.get((r["fecha"], local))
        if not fin:
            continue
        total = fin[1]
        gana = total > r["linea"]
        r["resultado"] = f"{fin[0]['FTHG']}-{fin[0]['FTAG']}"
        r["acierto"] = gana
        # Sin cuota (avisos de solo marcador) se mide el acierto frente a lo previsto, no el dinero.
        r["unidades"] = round(r["cuota"] - 1 if gana else -1.0, 2) if r["cuota"] and r["aviso"] else None
        hechos += 1
    escribir(REGISTRO, registro)
    return hechos


def main() -> None:
    parser = argparse.ArgumentParser(description="Estrategia del descanso («más de» en partidos de muchos goles).")
    parser.add_argument("--preseleccionar", nargs="?", const="hoy", metavar="AAAA-MM-DD")
    parser.add_argument("--revisar", nargs=2, metavar=("LIGA", "INICIO_UTC"))
    parser.add_argument("--liquidar", action="store_true")
    parser.add_argument("--repaso", metavar="AAAA-MM-DD", help="Qué habría avisado un día ya jugado.")
    parser.add_argument("--avisar", nargs=2, metavar=("LIGA", "INICIO_UTC"), help="Solo marcador y cuotas justas.")
    args = parser.parse_args()
    if args.liquidar:
        print(f"Liquidadas: {liquidar()}")
        avisos = [r for r in leer(REGISTRO, []) if r.get("acierto") is not None and r.get("cuota_minima")]
        if avisos:
            print(f"  avisos de descanso: {len(avisos)} líneas · acertadas {sum(r['acierto'] for r in avisos)} "
                  f"(se esperaban {sum(r['prob'] for r in avisos):.1f})")
        hechos = [r for r in leer(REGISTRO, []) if r["unidades"] is not None]
        for grupo, lista in (("con aviso", [r for r in hechos if r["aviso"]]), ("todas", hechos)):
            if lista:
                print(f"  {grupo}: {len(lista)} · {sum(r['unidades'] > 0 for r in lista)} ganadas · "
                      f"{sum(r['unidades'] for r in lista):+.2f} unidades")
    if args.preseleccionar:
        sel = preseleccionar(None if args.preseleccionar == "hoy" else date.fromisoformat(args.preseleccionar))
        for p in sel["partidos"]:
            print(f"  {p['inicio_utc']} UTC  {p['local']} - {p['visitante']} ({p['liga']}): "
                  f"más de 2,5 al {100 * p['p_previa']:.0f} %, {p['goles_esperados']} goles esperados")
        for r in sel["revisiones"]:
            print(f"  revisar {r['liga']} {r['inicio_utc']} a las {r['revisar_utc']}")
    if args.repaso:
        for t in repaso(date.fromisoformat(args.repaso)) or ["Aún no están los resultados con el descanso de ese día."]:
            print(t)
    if args.avisar:
        for t in avisar(*args.avisar):
            print(t)
    if args.revisar:
        for e in revisar(*args.revisar):
            if "nota" in e:
                print(f"  {e['local']} - {e['visitante']}: {e['nota']}")
            else:
                print(f"  {'AVISO ' if e['aviso'] else ''}{e['local']} - {e['visitante']} va {e['goles_descanso']} goles: "
                      f"más de {e['linea']} @{e['cuota']} ({e['casa']}) · justa {e['cuota_justa']} · valor {100 * e['valor']:+.1f} %")


if __name__ == "__main__":
    main()
