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
from datetime import date, datetime, timedelta, timezone

import app as cli
from estrategias import CASAS_ESPANA
from predictor.cuotas_vivo import DEPORTES, _pedir
from predictor.modelo import emparejar_equipo
from predictor.valor import _fecha, leer_filas, precio_justo

REGISTRO = os.path.join(cli.CARPETA, "datos", "descanso.json")
HOY = os.path.join(cli.CARPETA, "datos", "descanso_hoy.json")
PROB_MINIMA_PREVIA = 0.50   # «más de 2,5» antes del partido: partidos normales o de muchos goles
MAXIMO_POR_DIA = 4
PARTE_2 = 0.55              # parte de los goles que llega en la 2ª parte
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


def preseleccionar(dia: date | None = None) -> dict:
    """Partidos del día con más goles esperados según el precio justo (necesita las cuotas en vivo)."""
    dia = dia or date.today()
    hoy = dia.strftime("%d/%m/%Y")
    candidatos = []
    for f in leer_filas([os.path.join(cli.DESCARGAS, "proximos_vivo.csv")]):
        if f.get("Date") != hoy or f.get("Div") not in DEPORTES:
            continue
        justo = precio_justo(f, "Goles 2.5")
        if not justo or justo[0][0] < PROB_MINIMA_PREVIA:
            continue
        # La hora del archivo es la peninsular de invierno (UTC+1).
        inicio = datetime.strptime(f"{f['Date']} {f['Time']}", "%d/%m/%Y %H:%M") - timedelta(hours=1)
        candidatos.append({"liga": f["Div"], "local": f["HomeTeam"], "visitante": f["AwayTeam"],
                           "inicio_utc": inicio.strftime("%Y-%m-%dT%H:%M"), "p_previa": round(justo[0][0], 4),
                           "goles_esperados": round(goles_esperados(justo[0][0]), 2)})
    elegidos = sorted(candidatos, key=lambda c: -c["p_previa"])[:MAXIMO_POR_DIA]
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
        lam2 = p["goles_esperados"] * PARTE_2
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
    url = f"https://api.the-odds-api.com/v4/sports/{DEPORTES[liga]}/scores?" + urllib.parse.urlencode({"apiKey": clave})
    marcadores, restantes = _pedir(url)
    registro, textos = leer(REGISTRO, []), []
    for p in plan:
        mc = next((m for m in marcadores if emparejar_equipo(p["local"], [m["home_team"]]) and
                   emparejar_equipo(p["visitante"], [m["away_team"]])), None)
        if not mc or not mc.get("scores"):
            textos.append(f"{p['local']} - {p['visitante']}: sin marcador todavía")
            continue
        g = {s["name"]: int(s["score"]) for s in mc["scores"]}
        gl, gv = g.get(mc["home_team"], 0), g.get(mc["away_team"], 0)
        lam2 = p["goles_esperados"] * PARTE_2
        partes = []
        for extra in (1, 2, 3):
            linea = gl + gv + extra - 0.5
            prob = prob_al_menos(extra, lam2)
            minima = max(1.50, (1 + VALOR_MINIMO) / prob)
            partes.append(f"Más de {str(linea).replace('.', ',')} → justa {1 / prob:.2f} · mínima {minima:.2f}".replace(".", ",", 2))
            registro.append({"fecha": inicio_utc[:10], "liga": liga, "local": p["local"], "visitante": p["visitante"],
                             "revisado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"), "goles_descanso": gl + gv,
                             "linea": linea, "cuota": None, "casa": None, "prob": round(prob, 4),
                             "cuota_justa": round(1 / prob, 2), "cuota_minima": round(minima, 2), "valor": None,
                             "aviso": True, "resultado": None, "unidades": None})
        textos.append(f"AVISO ⏸️ {mc['home_team']} {gl}-{gv} {mc['away_team']} (descanso): " + " · ".join(partes))
    escribir(REGISTRO, registro)
    print(f"Créditos restantes: {restantes}")
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
        r["unidades"] = round(r["cuota"] - 1 if gana else -1.0, 2) if r["cuota"] else None
        hechos += 1
    escribir(REGISTRO, registro)
    return hechos


def main() -> None:
    parser = argparse.ArgumentParser(description="Estrategia del descanso («más de» en partidos de muchos goles).")
    parser.add_argument("--preseleccionar", nargs="?", const="hoy", metavar="AAAA-MM-DD")
    parser.add_argument("--revisar", nargs=2, metavar=("LIGA", "INICIO_UTC"))
    parser.add_argument("--liquidar", action="store_true")
    parser.add_argument("--avisar", nargs=2, metavar=("LIGA", "INICIO_UTC"), help="Solo marcador y cuotas justas.")
    args = parser.parse_args()
    if args.liquidar:
        print(f"Liquidadas: {liquidar()}")
        avisos = [r for r in leer(REGISTRO, []) if r.get("acierto") is not None and r["cuota"] is None]
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
