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

Uso:  python semana.py --desde 2026-10-31 --dias 2 [--guardar] [--json top10.json]
"""

import argparse
import json
import sys
from datetime import date

import app as cli
import panel
from predictor.descargar import LIGAS, expandir_ligas
from predictor.registro import Registro, descripcion
from predictor.valor import Oportunidad

N_PICKS = 10
# Topes por tipo para repartir el riesgo; el resto, goles del partido.
MAXIMO_POR_TIPO = {"Córners": 4, "1ª parte": 3, "Goles": 10}
# Por encima de esta probabilidad la cuota justa baja de ~1,43 y la mínima (1,50) exigiría que la
# casa pagase mucho más de lo justo: casi nunca pasa, así que no se proponen.
PROB_MAXIMA_MODELO = 0.70
PERFIL = "top10"


def tipo_de(mercado: str) -> str:
    if mercado.startswith("Córners"):
        return "Córners"
    if mercado.startswith("1ª parte"):
        return "1ª parte"
    return "Goles"


def aprendizaje() -> dict[str, dict]:
    """Lo aprendido del propio historial del Top 10, por tipo de pick.

    factor: cuánto corregir las probabilidades del modelo (aciertos reales / aciertos esperados),
    suavizado con 15 «aciertos de prueba» para no reaccionar a rachas cortas.
    """
    registro = Registro(cli.BASE_DATOS)
    picks = [p for p in registro.picks("perfil = ? AND estado != 'pendiente'", (PERFIL,))]
    registro.cerrar()
    resumen = {}
    for p in picks:
        if not p.cuota_justa or p.beneficio is None:
            continue
        r = resumen.setdefault(tipo_de(p.mercado), {"n": 0, "aciertos": 0.0, "esperados": 0.0, "unidades": 0.0})
        r["n"] += 1
        r["aciertos"] += 1 if p.beneficio > 0 else (0.5 if p.beneficio == 0 else 0)
        r["esperados"] += 1 / p.cuota_justa
        r["unidades"] += p.beneficio
    for r in resumen.values():
        r["factor"] = min(max((r["aciertos"] + 15) / (r["esperados"] + 15), 0.8), 1.1)
        r["excluir"] = r["n"] >= 60 and r["aciertos"] < 0.85 * r["esperados"]
    return resumen


def top10(desde: date, dias: int, n: int = N_PICKS) -> dict:
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
            if c["liga"] not in ligas or c["alcanzable"] in ("no", "dudoso"):
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
    elegidos, partidos, por_tipo = [], set(), {}
    for c in candidatos:
        clave = (c["fecha"], c["local"])
        tipo = tipo_de(c["mercado"])
        if clave in partidos or por_tipo.get(tipo, 0) >= MAXIMO_POR_TIPO[tipo]:
            continue
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        partidos.add(clave)
        elegidos.append(c)
        if len(elegidos) == n:
            break

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
    """Guarda el Top 10 en el registro (para liquidarlo y aprender). Devuelve cuántos son nuevos."""
    prefs = panel.preferencias()
    registro = Registro(cli.BASE_DATOS)
    nuevos = 0
    for p in resultado["picks"]:
        o = Oportunidad(date.fromisoformat(p["fecha"]), p["liga"], p["local"], p["visitante"], p["mercado"],
                        "Max" if p["origen"] == "mercado" else "modelo", p["cuota"] or p["cuota_minima"],
                        1 / p["cuota_justa"], p["origen"], familia=p["familia"])
        nuevos += registro.guardar(o, p["stake_pct"], PERFIL, prefs.get("tope", 0.03))
    registro.cerrar()
    return nuevos


def main() -> None:
    parser = argparse.ArgumentParser(description="Top 10 de la semana (solo «más de» goles y córners).")
    parser.add_argument("--desde", help="Primer día AAAA-MM-DD (por defecto hoy).")
    parser.add_argument("--dias", type=int, default=3)
    parser.add_argument("--guardar", action="store_true", help="Guardar en el registro para aprender.")
    parser.add_argument("--json", help="Guardar el resultado en este archivo JSON.")
    args = parser.parse_args()
    desde = date.fromisoformat(args.desde) if args.desde else date.today()
    resultado = top10(desde, args.dias)
    for p in resultado["picks"]:
        extra = f"valor +{p['valor']} % a {p['cuota']}" if p["origen"] == "mercado" else "modelo"
        print(f"{p['n']:>2}. {p['dia']}  {p['local']} - {p['visitante']} ({p['nombre_liga']}): "
              f"{p['descripcion']} · {p['prob']} % · cuota mínima {p['cuota_minima']} · {extra}")
    print(f"({resultado['candidatos']} candidatos; aprendizaje: "
          f"{ {k: round(v['factor'], 3) for k, v in resultado['aprendizaje'].items()} })")
    if args.guardar:
        print(f"Guardados en el registro: {guardar(resultado)} nuevos")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
