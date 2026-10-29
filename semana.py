"""Top 10 de la semana: las 10 oportunidades de «más de» (goles y córners) con más valor y probabilidad.

Orden de preferencia:
1. Las que salen de comparar casas («más de» goles con valor frente a Pinnacle/Betfair):
   son las únicas con backtest de dinero, así que van primero, de más a menos valor.
2. Las del modelo (goles del partido, 1ª parte y córners, siempre la línea más alta posible),
   de más a menos probabilidad, ya corregida con lo aprendido del propio historial.
Como mucho una por partido y unas pocas de córners, para no concentrar el riesgo.

Aprendizaje: cada pick del Top 10 se guarda en el registro. Cuando se liquidan, se compara lo que
pasó con lo que se predijo para cada tipo (goles, 1ª parte, córners). Si un tipo acierta menos
de lo previsto, se le bajan las probabilidades; con suficientes datos y claramente peor, se deja
de proponer.

Uso:  python semana.py [--desde AAAA-MM-DD] [--dias 3] [--guardar] [--liquidar] [--json top10.json]
(por defecto, de hoy a dentro de 3 días; pensado para ejecutarse cada día)
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import app as cli
import panel
from predictor.descargar import LIGAS, expandir_ligas
from predictor.registro import estado_de
from predictor.valor import _fecha, leer_filas, liquidar

N_PICKS = 10
# Topes por tipo para repartir el riesgo; el resto, goles del partido.
MAXIMO_POR_TIPO = {"Córners": 4, "1ª parte": 3, "Goles": 10}
# Por encima de esta probabilidad la cuota justa baja de ~1,43 y la mínima (1,50) exigiría que la
# casa pagase mucho más de lo justo: casi nunca pasa, así que no se proponen.
PROB_MAXIMA_MODELO = 0.70
PERFIL = "top10"
# Cuántos días por delante se miran (hoy + 3): los picks salen con 3-4 días de antelación.
DIAS_VISTA = 3


def tipo_de(mercado: str) -> str:
    if mercado.startswith("Córners"):
        return "Córners"
    if mercado.startswith("1ª parte"):
        return "1ª parte"
    return "Goles"


HISTORIAL = os.path.join(cli.CARPETA, "datos", "historial_top10.json")
APUESTAS_MOVIL = os.path.join(cli.CARPETA, "datos", "apuestas_movil.json")


def leer_historial() -> list[dict]:
    if not os.path.exists(HISTORIAL):
        return []
    with open(HISTORIAL, encoding="utf-8") as f:
        return json.load(f)


def escribir_historial(picks: list[dict]) -> None:
    with open(HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=1)


def id_pick(p: dict) -> str:
    return f"{p['fecha']}_{p['local']}_{p['visitante']}_{p['mercado']}".replace(" ", "_").replace("/", "-")


def leer_apuestas_movil() -> list[dict]:
    """Las apuestas que el usuario eligió y apuntó en el móvil, ya con resultado (ver movil/aprender.py)."""
    if not os.path.exists(APUESTAS_MOVIL):
        return []
    with open(APUESTAS_MOVIL, encoding="utf-8") as f:
        return json.load(f)


def resumir_aprendizaje(registros: list[dict]) -> dict[str, dict]:
    """Por tipo de apuesta: cuántas, aciertos reales frente a esperados y el factor de corrección.

    factor: cuánto corregir las probabilidades del modelo (aciertos reales / aciertos esperados),
    suavizado con 15 «aciertos de prueba» para no reaccionar a rachas cortas.
    """
    resumen = {}
    for p in registros:
        if p.get("beneficio") is None:
            continue
        r = resumen.setdefault(tipo_de(p["mercado"]), {"n": 0, "aciertos": 0.0, "esperados": 0.0, "unidades": 0.0})
        r["n"] += 1
        r["aciertos"] += 1 if p["beneficio"] > 0 else (0.5 if p["beneficio"] == 0 else 0)
        r["esperados"] += p["prob"] / 100
        r["unidades"] += p["beneficio"]
    for r in resumen.values():
        r["factor"] = round(min(max((r["aciertos"] + 15) / (r["esperados"] + 15), 0.8), 1.1), 3)
        r["excluir"] = r["n"] >= 60 and r["aciertos"] < 0.85 * r["esperados"]
        r["esperados"], r["unidades"] = round(r["esperados"], 2), round(r["unidades"], 2)
    return resumen


def aprendizaje() -> dict[str, dict]:
    """Lo aprendido de los picks del Top 10 y de las apuestas que el usuario eligió en el móvil
    (reales y en papel): si un tipo acierta menos de lo que decía el modelo, se le bajan las probabilidades."""
    return resumir_aprendizaje(leer_historial() + leer_apuestas_movil())


def liquidar_historial() -> list[dict]:
    """Pone el resultado a los picks del historial ya jugados. Devuelve los liquidados ahora.

    Los del modelo se liquidan a su cuota mínima (lo mínimo que había que conseguir para apostarlos).
    """
    indice = {}
    for f in leer_filas([cli.DESCARGAS]):
        if f.get("FTHG") and f.get("HomeTeam"):
            try:
                indice[(_fecha(f["Date"]).isoformat(), f["HomeTeam"], f["AwayTeam"])] = f
            except ValueError:
                pass
    picks, hechos = leer_historial(), []
    for p in picks:
        if p.get("beneficio") is not None or p.get("estado") == "anulado":
            continue
        fila = indice.get((p["fecha"], p["local"], p["visitante"]))
        if not fila:
            continue
        beneficio, clv = liquidar(fila, p["mercado"], p["cuota"] or p["cuota_minima"])
        if beneficio is None:
            continue
        p["beneficio"] = round(beneficio, 3)
        p["estado"] = estado_de(beneficio, p["cuota"] or p["cuota_minima"])
        p["clv"] = None if clv is None else round(clv, 4)
        p["resultado"] = f"{fila['FTHG']}-{fila['FTAG']}" + (
            f" · córners {int(float(fila['HC'])) + int(float(fila['AC']))}" if fila.get("HC") and fila.get("AC") else "") + (
            f" · descanso {fila['HTHG']}-{fila['HTAG']}" if fila.get("HTHG") else "")
        hechos.append(p)
    escribir_historial(picks)
    return hechos


def top10(desde: date, dias: int, n: int = N_PICKS, ya: list[dict] | None = None) -> dict:
    """Los mejores picks del periodo. `ya` son los ya publicados (no se cambian ni se repiten:
    ocupan su hueco de los `n` y cuentan para los topes por tipo)."""
    ya = ya or []
    prefs = panel.preferencias()
    ligas = {LIGAS[l][0] for l in expandir_ligas(prefs.get("ligas", ["principales"])) if l in LIGAS}
    aprendido = aprendizaje()
    candidatos = []

    # 1) Comparando casas: «más de» goles con valor (backtest +10 %).
    prefs_goles = {**prefs, "perfil": "goles"}
    panel_prefs = panel.preferencias
    panel.preferencias = lambda: prefs_goles
    try:
        mercado = panel.datos_picks(dias, desde)["picks"]
    finally:
        panel.preferencias = panel_prefs
    for p in mercado:
        if p["liga"] in ligas and "+" in p["mercado"]:
            candidatos.append({**p, "origen": "mercado", "prob": round(100 / p["cuota_justa"], 1),
                               "puntos": 1000 + p["valor"]})

    # 2) Modelo: goles (partido y 1ª parte) y córners, la línea más alta posible.
    for tipo in ("goles", "corners"):
        for c in panel.datos_modelo(dias, tipo, desde)["selecciones"]:
            # Solo si hay cuotas reales y alguna casa ya paga la mínima: sin cuotas el modelo
            # pide más de lo que las casas suelen pagar (pasó con los primeros picks del calendario).
            if c["liga"] not in ligas or c["alcanzable"] != "si":
                continue
            a = aprendido.get(tipo_de(c["mercado"]), {})
            if a.get("excluir"):
                continue
            factor = a.get("factor", 1.0)
            prob = min(c["prob"] / 100 * factor, 0.95)
            cuota_minima = round(max(1.50, 1.05 / prob), 2)
            if cuota_minima > 2.50 or prob > PROB_MAXIMA_MODELO:
                continue
            candidatos.append({**c, "origen": "modelo", "prob": round(100 * prob, 1),
                               "cuota_justa": round(1 / prob, 2), "cuota_minima": cuota_minima,
                               "cuota": c.get("mercado_mejor"), "valor": None, "puntos": 100 * prob})

    candidatos.sort(key=lambda c: -c["puntos"])
    elegidos, partidos, por_tipo = [], {(p["fecha"], p["local"]) for p in ya}, {}
    for p in ya:
        por_tipo[tipo_de(p["mercado"])] = por_tipo.get(tipo_de(p["mercado"]), 0) + 1
    for c in candidatos:
        if len(ya) + len(elegidos) >= n:
            break
        clave = (c["fecha"], c["local"])
        tipo = tipo_de(c["mercado"])
        if clave in partidos or por_tipo.get(tipo, 0) >= MAXIMO_POR_TIPO[tipo]:
            continue
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        partidos.add(clave)
        elegidos.append(c)

    stake = prefs.get("plano", 0.01)
    salida = []
    for i, c in enumerate(sorted(elegidos, key=lambda c: (c["fecha"], -c["puntos"])), 1):
        salida.append({
            "n": i, "fecha": c["fecha"], "dia": c["dia"], "liga": c["liga"], "nombre_liga": c["nombre_liga"],
            "local": c["local"], "visitante": c["visitante"], "mercado": c["mercado"],
            "descripcion": c["descripcion"], "prob": c["prob"], "cuota_justa": c["cuota_justa"],
            "cuota_minima": c["cuota_minima"], "cuota": c.get("cuota"), "valor": c.get("valor"),
            "origen": c["origen"], "familia": tipo_de(c["mercado"]),
            "stake_pct": stake, "euros": round(prefs["bank"] * stake, 2),
        })
    return {"desde": desde.isoformat(), "dias": dias, "picks": salida, "aprendizaje": aprendido,
            "candidatos": len(candidatos)}


def guardar(resultado: dict) -> int:
    """Añade el Top 10 al historial (para liquidarlo y aprender). Devuelve cuántos son nuevos."""
    picks = leer_historial()
    vistos = {p["id"] for p in picks}
    nuevos = 0
    for p in resultado["picks"]:
        pid = id_pick(p)
        if pid in vistos:
            continue
        picks.append({**p, "id": pid, "generado": date.today().isoformat(), "estado": "pendiente",
                      "beneficio": None, "clv": None, "resultado": None})
        vistos.add(pid)
        nuevos += 1
    escribir_historial(picks)
    return nuevos


def resumen_historial() -> dict:
    """Totales del Top 10 ya liquidado, en unidades (1 unidad por pick)."""
    jugados = [p for p in leer_historial() if p.get("beneficio") is not None]
    total = {"picks": len(jugados), "acertados": sum(p["beneficio"] > 0 for p in jugados),
             "unidades": round(sum(p["beneficio"] for p in jugados), 2)}
    total["yield"] = round(100 * total["unidades"] / total["picks"], 1) if jugados else 0.0
    por_tipo = {}
    for p in jugados:
        t = por_tipo.setdefault(tipo_de(p["mercado"]), {"picks": 0, "acertados": 0, "unidades": 0.0})
        t["picks"] += 1
        t["acertados"] += p["beneficio"] > 0
        t["unidades"] = round(t["unidades"] + p["beneficio"], 2)
    return {"total": total, "por_tipo": por_tipo}


def publicados(desde: date, dias: int) -> list[dict]:
    """Picks del historial aún sin jugar dentro del periodo: ya publicados, se quedan fijos."""
    hasta = (desde + timedelta(days=dias)).isoformat()
    return sorted((p for p in leer_historial()
                   if p.get("estado") == "pendiente" and desde.isoformat() <= p["fecha"] <= hasta),
                  key=lambda p: (p["fecha"], p["local"]))


def proximo_fin_de_semana(hoy: date) -> tuple[date, int]:
    """Del viernes al lunes siguientes (o el que está en curso si hoy es viernes a lunes)."""
    if hoy.weekday() in (4, 5, 6, 0):
        return hoy, (0 - hoy.weekday()) % 7 + 1
    viernes = hoy + timedelta(days=(4 - hoy.weekday()) % 7)
    return viernes, 4


def main() -> None:
    parser = argparse.ArgumentParser(description="Top 10 de la semana (solo «más de» goles y córners).")
    parser.add_argument("--desde", help="Primer día AAAA-MM-DD (por defecto, el próximo fin de semana).")
    parser.add_argument("--dias", type=int, help="Cuántos días (por defecto, de viernes a lunes).")
    parser.add_argument("--guardar", action="store_true", help="Añadirlo al historial para aprender.")
    parser.add_argument("--liquidar", action="store_true", help="Poner resultado a los picks ya jugados.")
    parser.add_argument("--json", help="Guardar el Top 10, el resumen y lo aprendido en este JSON.")
    args = parser.parse_args()
    if args.liquidar:
        for p in liquidar_historial():
            print(f"  {p['estado'].upper():<14}{p['local']} - {p['visitante']}: {p['descripcion']} ({p['resultado']})")
    # Por defecto, de hoy a dentro de 3 días: cuanto antes se publica un pick, menos se ha movido
    # la cuota. Lo ya publicado se queda fijo y solo se rellenan los huecos hasta 10.
    desde = date.fromisoformat(args.desde) if args.desde else date.today()
    dias = DIAS_VISTA if args.dias is None else args.dias
    fijos = publicados(desde, dias)
    resultado = top10(desde, dias, ya=fijos)
    for p in resultado["picks"]:
        extra = f"valor +{p['valor']} % a {p['cuota']}" if p["origen"] == "mercado" else "modelo"
        print(f"{p['n']:>2}. {p['dia']}  {p['local']} - {p['visitante']} ({p['nombre_liga']}): "
              f"{p['descripcion']} · {p['prob']} % · cuota mínima {p['cuota_minima']} · {extra}")
    print(f"({resultado['candidatos']} candidatos; aprendizaje: "
          f"{ {k: v['factor'] for k, v in resultado['aprendizaje'].items()} })")
    if args.guardar:
        print(f"Añadidos al historial: {guardar(resultado)} nuevos")
        resultado["picks"] = publicados(desde, dias)
    else:
        resultado["picks"] = sorted(fijos + resultado["picks"], key=lambda p: (p["fecha"], p["local"]))
    for i, p in enumerate(resultado["picks"], 1):
        p["n"] = i
    if args.json:
        resultado["resumen"] = resumen_historial()
        resultado["historial"] = leer_historial()[-200:]
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
