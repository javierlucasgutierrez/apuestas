"""El sistema elige solo: prueba varias reglas de selección («algoritmos») y se queda con las que ganan.

Cada regla mira lo mismo que tú en la tabla (probabilidad del modelo, estadística de los últimos 10
partidos, precio justo de Pinnacle/Betfair y la mejor cuota) y decide si apuesta o no.

- PASADO: cada regla se prueba en las temporadas 2024/25 a 2026/27, con cada partido calculado
  solo con lo que se sabía antes de jugarse (lo genera movil/estrategias_pasado.py una vez).
- EN VIVO: cada día cada regla elige sus partidos de hoy a dentro de 3 días; se guardan «en papel»
  y se liquidan solos. Así se ve si una regla sigue funcionando con partidos nuevos.
- ASCENSO: una regla es «recomendada» solo si ganó dinero en las dos mitades del pasado con al
  menos 100 apuestas; si en vivo, tras 50 apuestas, pierde más de un 10 %, deja de serlo.
  Las reglas sin cuotas antiguas (córners, 1ª parte, otras líneas) solo pueden demostrar acierto,
  no dinero: se enseña la cuota que haría falta para ganar.

Uso: python3 estrategias.py --guardar --liquidar --json salida.json
"""

import argparse
import json
import math
import os
from collections import defaultdict, deque
from datetime import date, timedelta

import app as cli
import panel
from predictor.datos import cargar_varios
from predictor.descargar import LIGAS, expandir_ligas
from datetime import datetime

from predictor.registro import estado_de, stake_10
from predictor.valor import _cuota, _fecha, leer_filas, liquidar, precio_justo

VIVO = os.path.join(cli.CARPETA, "datos", "estrategias_vivo.json")
PASADO = os.path.join(cli.CARPETA, "datos", "estrategias_pasado.json")
# Los pronósticos «oficiales» (los que se apuestan y se venderían): una vez publicados no se tocan.
PRONOSTICOS = os.path.join(cli.CARPETA, "datos", "pronosticos.json")
MAXIMO_POR_DIA = 3  # por regla, los mejores de cada día
# Casas con licencia en España que vienen en los datos (football-data: B365; The Odds API: el resto).
# Solo con ellas se publica un pronóstico oficial: si ninguna llega a la mínima, no se publica.
CASAS_ESPANA = {"B365": "Bet365", "William Hill": "William Hill", "Marathon Bet": "Marathonbet",
                "Unibet (NL)": "Unibet", "Unibet (SE)": "Unibet", "LeoVegas (SE)": "LeoVegas", "Codere (IT)": "Codere"}
# Seguridad: stake máximo 3/10 (0,9 % del bank), como mucho 3 pronósticos por día y pausa si en los
# últimos 30 días se pierden más de 15 unidades (vuelve sola cuando la ventana mejora).
STAKE_MAXIMO = 3
PRONOSTICOS_POR_DIA = 3
STOP_LOSS_30_DIAS = -15.0
DIAS_VISTA = 3
LINEAS_FRECUENCIA = {"Goles +1.5": ("g", 1.5), "Goles +2.5": ("g", 2.5), "Goles +3.5": ("g", 3.5),
                     "Córners +8.5": ("c", 8.5), "Córners +9.5": ("c", 9.5), "Córners +10.5": ("c", 10.5)}


def _valor(c, prob):
    return prob * c["cuota"] - 1 if c.get("cuota") and prob else None


def _rango(c):
    return c.get("cuota") is not None and 1.50 <= c["cuota"] <= 2.50


# Cada regla: mercado que mira, si se puede medir en dinero (hay cuotas) y la condición.
REGLAS = [
    {"id": "valor1", "nombre": "Una casa paga más que Pinnacle/Betfair (valor ≥1 %)", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: c.get("pm") and _rango(c) and _valor(c, c["pm"]) >= 0.01, "orden": lambda c: _valor(c, c["pm"])},
    {"id": "valor3", "nombre": "Una casa paga más que Pinnacle/Betfair (valor ≥3 %)", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: c.get("pm") and _rango(c) and _valor(c, c["pm"]) >= 0.03, "orden": lambda c: _valor(c, c["pm"])},
    {"id": "valor_y_modelo", "nombre": "Valor ≥1 % y el modelo lo ve aún más probable", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: c.get("pm") and _rango(c) and _valor(c, c["pm"]) >= 0.01 and c["prob"] >= c["pm"],
     "orden": lambda c: _valor(c, c["pm"])},
    {"id": "modelo_valor", "nombre": "El modelo ve valor ≥5 % en la mejor cuota", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: _rango(c) and _valor(c, c["prob"]) >= 0.05, "orden": lambda c: _valor(c, c["prob"])},
    {"id": "tres", "nombre": "Estadística, modelo y mercado ≥60 % (la ⭐)", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: _rango(c) and c.get("pm") and min(c["prob"], c["frec"] or 0, c["pm"]) >= 0.60,
     "orden": lambda c: c["prob"]},
    {"id": "estad70", "nombre": "Estadística ≥70 % y modelo ≥65 %", "mercado": "Goles +2.5", "dinero": True,
     "si": lambda c: _rango(c) and (c["frec"] or 0) >= 0.70 and c["prob"] >= 0.65, "orden": lambda c: c["prob"]},
    {"id": "g15", "nombre": "Más de 1,5 goles muy probable (modelo ≥80 %)", "mercado": "Goles +1.5", "dinero": False,
     "si": lambda c: c["prob"] >= 0.80, "orden": lambda c: c["prob"]},
    {"id": "g35", "nombre": "Más de 3,5 goles con modelo ≥45 %", "mercado": "Goles +3.5", "dinero": False,
     "si": lambda c: c["prob"] >= 0.45, "orden": lambda c: c["prob"]},
    {"id": "c85", "nombre": "Más de 8,5 córners: modelo y estadística ≥70 %", "mercado": "Córners +8.5", "dinero": False,
     "si": lambda c: c["prob"] >= 0.70 and (c["frec"] or 0) >= 0.70, "orden": lambda c: c["prob"]},
    {"id": "c95", "nombre": "Más de 9,5 córners: modelo y estadística ≥60 %", "mercado": "Córners +9.5", "dinero": False,
     "si": lambda c: c["prob"] >= 0.60 and (c["frec"] or 0) >= 0.60, "orden": lambda c: c["prob"]},
    {"id": "t05", "nombre": "Gol en la 1ª parte muy probable (modelo ≥78 %)", "mercado": "1ª parte goles +0.5", "dinero": False,
     "si": lambda c: c["prob"] >= 0.78, "orden": lambda c: c["prob"]},
]
POR_ID = {r["id"]: r for r in REGLAS}


def leer(ruta: str, defecto):
    if not os.path.exists(ruta):
        return defecto
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def escribir(ruta: str, datos) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def frecuencias(partidos) -> dict:
    """Últimos 10 partidos de cada equipo: total de goles y de córners."""
    hist = defaultdict(lambda: deque(maxlen=10))
    for p in sorted((p for p in partidos if p.jugado), key=lambda p: p.fecha):
        corners = (p.corners_local + p.corners_visitante) if p.corners_local is not None else None
        for eq in (p.local, p.visitante):
            hist[(p.liga, eq)].append({"g": p.goles_local + p.goles_visitante, "c": corners})
    return hist


def frecuencia(hist, liga, local, visitante, mercado) -> float | None:
    if mercado not in LINEAS_FRECUENCIA:
        return None
    t, linea = LINEAS_FRECUENCIA[mercado]
    datos = [x[t] for x in list(hist[(liga, local)]) + list(hist[(liga, visitante)]) if x[t] is not None]
    if len(hist[(liga, local)]) < 8 or len(hist[(liga, visitante)]) < 8 or not datos:
        return None
    return sum(v > linea for v in datos) / len(datos)


def candidatos(desde: date, dias: int) -> list[dict]:
    """Todos los partidos y líneas de los próximos días con lo que miran las reglas."""
    prefs = panel.preferencias()
    ligas = {LIGAS[l][0] for l in expandir_ligas(prefs.get("ligas", ["principales"])) if l in LIGAS}
    modelo = panel.predictor()
    hist = frecuencias(cargar_varios([cli.DESCARGAS]))
    salida = []
    for p, fila in panel.proximos_partidos(modelo):
        if p.liga not in ligas or not desde <= p.fecha <= desde + timedelta(days=dias):
            continue
        try:
            pred = modelo.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError:
            continue
        justo = precio_justo(fila, "Goles 2.5") if fila else None
        for m in sorted({r["mercado"] for r in REGLAS}):
            if m not in pred.probs:
                continue
            c = {"fecha": p.fecha.isoformat(), "liga": p.liga, "local": p.local, "visitante": p.visitante,
                 "mercado": m, "prob": round(pred.probs[m], 4),
                 "frec": frecuencia(hist, p.liga, p.local, p.visitante, m), "pm": None, "cuota": None, "b365": None}
            if m == "Goles +2.5" and fila:
                c["pm"] = round(justo[0][0], 4) if justo else None
                c["cuota"] = _cuota(fila, "Max>2.5")
                c["b365"] = _cuota(fila, "B365>2.5")
                espanolas = [(_cuota(fila, f"{k}>2.5"), nombre) for k, nombre in CASAS_ESPANA.items()]
                espanolas = [x for x in espanolas if x[0]]
                if espanolas:
                    c["cuota_es"], c["casa_es"] = max(espanolas)
            salida.append(c)
    return salida


def elegir(cands: list[dict]) -> list[dict]:
    """Lo que elige cada regla: como mucho MAXIMO_POR_DIA por día, los mejores según la regla."""
    elegidos = []
    for regla in REGLAS:
        por_dia = defaultdict(list)
        for c in cands:
            if c["mercado"] == regla["mercado"] and regla["si"](c):
                por_dia[c["fecha"]].append(c)
        for lista in por_dia.values():
            for c in sorted(lista, key=lambda c: -regla["orden"](c))[:MAXIMO_POR_DIA]:
                elegidos.append({**c, "regla": regla["id"]})
    return elegidos


def guardar(elegidos: list[dict]) -> int:
    registro = leer(VIVO, [])
    vistos = {(r["regla"], r["fecha"], r["local"], r["mercado"]) for r in registro}
    nuevos = 0
    for e in elegidos:
        clave = (e["regla"], e["fecha"], e["local"], e["mercado"])
        if clave not in vistos:
            registro.append({**e, "generado": date.today().isoformat(), "acierto": None, "beneficio": None})
            vistos.add(clave)
            nuevos += 1
    escribir(VIVO, registro)
    return nuevos


def liquidar_vivo() -> int:
    """Pone el resultado: acierto (sí/no) y, si había cuota, beneficio a la mejor cuota."""
    indice = {}
    for f in leer_filas([cli.DESCARGAS]):
        if f.get("FTHG") and f.get("HomeTeam"):
            try:
                indice[(_fecha(f["Date"]).isoformat(), f["HomeTeam"], f["AwayTeam"])] = f
            except ValueError:
                pass
    liquidar_pronosticos(indice)
    registro, hechos = leer(VIVO, []), 0
    for r in registro:
        if r["acierto"] is not None:
            continue
        fila = indice.get((r["fecha"], r["local"], r["visitante"]))
        if not fila:
            continue
        beneficio, _ = liquidar(fila, r["mercado"], r["cuota"] or 2.0)
        if beneficio is None:
            continue
        r["acierto"] = beneficio > 0
        r["beneficio"] = round(beneficio, 3) if r["cuota"] else None
        hechos += 1
    escribir(VIVO, registro)
    return hechos


def publicar(elegidos: list[dict], recomendadas: set[str]) -> int:
    """Convierte en pronóstico oficial lo que eligen las reglas ★ (uno por partido).

    Solo se publica si una casa que opera en España paga la mínima: la cuota y la casa publicadas son
    esas, así el historial se calcula con cuotas que de verdad se pueden coger.
    Stake 1-10: un cuarto de Kelly con la probabilidad justa (10 = 3 % del bank), con tope STAKE_MAXIMO.
    """
    pron = leer(PRONOSTICOS, [])
    hace_30 = (date.today() - timedelta(days=30)).isoformat()
    ultimos = sum(p["unidades"] for p in pron if p["unidades"] is not None and p["fecha"] >= hace_30)
    if ultimos <= STOP_LOSS_30_DIAS:
        print(f"Pausa de seguridad: {ultimos:+.1f} unidades en 30 días. No se publica nada hasta que mejore.")
        return 0
    por_dia = defaultdict(int)
    for p in pron:
        por_dia[p["fecha"]] += 1
    vistos = {(p["fecha"], p["local"]) for p in pron}
    nuevos = 0
    orden = {r["id"]: i for i, r in enumerate(REGLAS)}
    for e in sorted(elegidos, key=lambda e: orden[e["regla"]]):
        if e["regla"] not in recomendadas or not e.get("pm") or (e["fecha"], e["local"]) in vistos:
            continue
        # Mínima = la que pide la regla (valor ≥1 % sobre el precio justo), redondeada hacia arriba.
        minima = math.ceil(max(1.50, 1.01 / e["pm"]) * 100) / 100
        if not e.get("cuota_es") or e["cuota_es"] < minima or por_dia[e["fecha"]] >= PRONOSTICOS_POR_DIA:
            continue
        cuota, casa = e["cuota_es"], e["casa_es"]
        kelly = (e["pm"] * cuota - 1) / (cuota - 1)
        pron.append({"id": f"{e['fecha']}_{e['local']}_{e['mercado']}", "publicado": datetime.now().isoformat(timespec="minutes"),
                     "fecha": e["fecha"], "liga": e["liga"], "local": e["local"], "visitante": e["visitante"],
                     "mercado": e["mercado"], "cuota": cuota, "casa": casa, "cuota_minima": minima,
                     "prob": round(e["pm"], 4), "stake": min(STAKE_MAXIMO, stake_10(min(0.25 * kelly, 0.03))), "regla": e["regla"],
                     "estado": "pendiente", "resultado": None, "unidades": None})
        vistos.add((e["fecha"], e["local"]))
        por_dia[e["fecha"]] += 1
        nuevos += 1
    escribir(PRONOSTICOS, pron)
    return nuevos


def liquidar_pronosticos(indice: dict) -> int:
    pron, hechos = leer(PRONOSTICOS, []), 0
    for p in pron:
        if p["estado"] != "pendiente":
            continue
        fila = indice.get((p["fecha"], p["local"], p["visitante"]))
        if not fila:
            continue
        beneficio, _ = liquidar(fila, p["mercado"], p["cuota"])
        if beneficio is None:
            continue
        p["estado"] = estado_de(beneficio, p["cuota"])
        p["resultado"] = f"{fila['FTHG']}-{fila['FTAG']}"
        p["unidades"] = round(beneficio * p["stake"], 2)
        hechos += 1
    escribir(PRONOSTICOS, pron)
    return hechos


def resumen_pronosticos(pron: list[dict]) -> dict:
    """El historial que se enseña a quien compra: unidades, yield (ganado / apostado) y por mes."""
    def bloque(lista):
        apostado = sum(p["stake"] for p in lista)
        ganado = sum(p["unidades"] for p in lista)
        return {"picks": len(lista), "aciertos": sum(p["unidades"] > 0 for p in lista), "apostado": apostado,
                "unidades": round(ganado, 2), "yield": round(100 * ganado / apostado, 1) if apostado else 0.0,
                "cuota_media": round(sum(p["cuota"] for p in lista) / len(lista), 2) if lista else 0}
    hechos = [p for p in pron if p["estado"] != "pendiente" and p["unidades"] is not None]
    meses = sorted({p["fecha"][:7] for p in hechos}, reverse=True)
    peor, racha = 0, 0
    for p in sorted(hechos, key=lambda p: p["fecha"]):
        racha = racha + 1 if p["unidades"] < 0 else 0
        peor = max(peor, racha)
    return {"total": bloque(hechos), "por_mes": [{"mes": m, **bloque([p for p in hechos if p["fecha"][:7] == m])} for m in meses],
            "peor_racha": peor}


def resumen(registros: list[dict]) -> dict:
    hechos = [r for r in registros if r.get("acierto") is not None]
    n = len(hechos)
    if not n:
        return {"n": 0}
    aciertos = sum(r["acierto"] for r in hechos)
    salida = {"n": n, "acierto": round(100 * aciertos / n, 1), "esperado": round(100 * sum(r["prob"] for r in hechos) / n, 1),
              "cuota_necesaria": round(n / aciertos, 2) if aciertos else None}
    con_dinero = [r for r in hechos if r.get("beneficio") is not None]
    if con_dinero:
        salida["yield"] = round(100 * sum(r["beneficio"] for r in con_dinero) / len(con_dinero), 1)
        salida["n_dinero"] = len(con_dinero)
    return salida


def ranking() -> list[dict]:
    pasado = leer(PASADO, {})
    vivo = leer(VIVO, [])
    filas = []
    for regla in REGLAS:
        p = pasado.get(regla["id"], {})
        v = resumen([r for r in vivo if r["regla"] == regla["id"]])
        mitades = p.get("mitades", [])
        recomendada = (regla["dinero"] and len(mitades) == 2 and all(m.get("yield", -1) > 0 for m in mitades)
                       and p.get("total", {}).get("n_dinero", 0) >= 100)
        if recomendada and v.get("n_dinero", 0) >= 50 and v.get("yield", 0) < -10:
            recomendada = False
        filas.append({"id": regla["id"], "nombre": regla["nombre"], "mercado": regla["mercado"], "dinero": regla["dinero"],
                      "pasado": p.get("total", {"n": 0}), "mitades": mitades, "vivo": v, "recomendada": recomendada})
    return filas


def main() -> None:
    parser = argparse.ArgumentParser(description="El sistema elige: reglas probadas en el pasado y en vivo.")
    parser.add_argument("--guardar", action="store_true")
    parser.add_argument("--liquidar", action="store_true")
    parser.add_argument("--json")
    parser.add_argument("--importar", help="JSON del documento sistema/vivo de la página (copia principal del registro).")
    args = parser.parse_args()
    if args.importar and os.path.exists(args.importar):
        with open(args.importar, encoding="utf-8") as f:
            remotos = json.load(f).get("registro", [])
        locales = {(r["regla"], r["fecha"], r["local"], r["mercado"]): r for r in leer(VIVO, [])}
        for r in remotos:
            clave = (r["regla"], r["fecha"], r["local"], r["mercado"])
            if clave not in locales or (locales[clave]["acierto"] is None and r.get("acierto") is not None):
                locales[clave] = r
        escribir(VIVO, sorted(locales.values(), key=lambda r: (r["fecha"], r["regla"])))
        with open(args.importar, encoding="utf-8") as f:
            remotos = json.load(f).get("pronosticos", [])
        pron = {p["id"]: p for p in leer(PRONOSTICOS, [])}
        for p in remotos:  # lo publicado no se cambia: solo se añade lo que falte o su resultado
            if p["id"] not in pron or (pron[p["id"]]["estado"] == "pendiente" and p["estado"] != "pendiente"):
                pron[p["id"]] = p
        escribir(PRONOSTICOS, sorted(pron.values(), key=lambda p: (p["publicado"], p["fecha"])))
    if args.liquidar:
        print(f"Liquidadas: {liquidar_vivo()}")
    hoy = date.today()
    elegidos = elegir(candidatos(hoy, DIAS_VISTA))
    if args.guardar:
        print(f"Nuevas selecciones guardadas: {guardar(elegidos)}")
    filas = ranking()
    if args.guardar:
        nuevos = publicar(elegidos, {f["id"] for f in filas if f["recomendada"]})
        print(f"Pronósticos nuevos publicados: {nuevos}")
        for p in leer(PRONOSTICOS, [])[-nuevos:] if nuevos else []:
            print(f"  {p['fecha']} {p['local']} - {p['visitante']}: {p['mercado']} @{p['cuota']} ({p['casa']}) stake {p['stake']}")
    for f in filas:
        print(f"{'★' if f['recomendada'] else ' '} {f['nombre']:<56} pasado {f['pasado']} · vivo {f['vivo']}")
    if args.json:
        recomendadas = {f["id"] for f in filas if f["recomendada"]}
        nombres = {r["id"]: r["nombre"] for r in REGLAS}
        hoy_s = hoy.isoformat()
        proximos = sorted(({**e, "nombre_regla": nombres[e["regla"]], "recomendada": e["regla"] in recomendadas,
                            "dia": panel.dia(date.fromisoformat(e["fecha"])),
                            "nombre_liga": cli.NOMBRE_LIGA.get(e["liga"], e["liga"])}
                           for e in leer(VIVO, []) if e["fecha"] >= hoy_s and e["acierto"] is None),
                          key=lambda e: (not e["recomendada"], e["fecha"], e["regla"]))
        ultimos = [r for r in leer(VIVO, []) if r["acierto"] is not None][-300:]
        pron = leer(PRONOSTICOS, [])
        pendientes = [{**p, "dia": panel.dia(date.fromisoformat(p["fecha"])), "nombre_liga": cli.NOMBRE_LIGA.get(p["liga"], p["liga"]),
                       "nombre_regla": nombres[p["regla"]]} for p in pron if p["estado"] == "pendiente"]
        escribir(args.json, {"actualizado": hoy.strftime("%d/%m/%Y"), "ranking": filas, "proximos": proximos,
                             "ultimos": ultimos,
                             "pronosticos": {"pendientes": pendientes, "resumen": resumen_pronosticos(pron),
                                             "ultimos": [p for p in pron if p["estado"] != "pendiente"][-100:][::-1]}})
        # Copia del registro para la página (los últimos 1500): de ahí se recupera si falla el push.
        with open(os.path.join(os.path.dirname(args.json), "sistema_vivo.json"), "w", encoding="utf-8") as f:
            json.dump({"registro": leer(VIVO, [])[-1500:], "pronosticos": leer(PRONOSTICOS, [])}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
