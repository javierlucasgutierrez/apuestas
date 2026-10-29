"""Partidos de los próximos días con sus probabilidades de «más de», para la calculadora del móvil.

Uso: python3 movil/calculadora.py salida.json [--dias 7]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import panel  # noqa: E402
import semana  # noqa: E402
from predictor.descargar import LIGAS, expandir_ligas  # noqa: E402


def resumen_tuyas(registros: list[dict]) -> dict:
    """Cómo van las apuestas que eligió el usuario: reales y en papel, por tipo y por línea."""
    def bloque(lista):
        n = len(lista)
        unidades = sum(r["beneficio"] for r in lista)
        return {"n": n, "aciertos": sum(r["beneficio"] > 0 for r in lista),
                "esperados": round(sum(r["prob"] for r in lista) / 100, 1),
                "unidades": round(unidades, 2), "yield": round(100 * unidades / n, 1) if n else 0.0}
    salida = {}
    for clase, lista in (("reales", [r for r in registros if not r["papel"]]),
                         ("papel", [r for r in registros if r["papel"]])):
        salida[clase] = {"total": bloque(lista),
                         "por_linea": {m: bloque([r for r in lista if r["mercado"] == m])
                                       for m in sorted({r["mercado"] for r in lista})}}
    return salida


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("salida")
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args()
    ligas = {LIGAS[l][0] for l in expandir_ligas(panel.preferencias().get("ligas", ["principales"])) if l in LIGAS}
    aprendido = semana.aprendizaje()
    partidos = []
    for p in panel.lista_partidos(args.dias)["partidos"]:
        if p["liga"] not in ligas:
            continue
        try:
            datos = panel.probabilidades_partido(p["fecha"], p["local"], p["visitante"])
        except KeyError:
            continue
        # Por mercado: [probabilidad del modelo en %, cuota justa del mercado o null]
        # Las probabilidades del modelo se corrigen con lo aprendido (Top 10 y apuestas del usuario).
        mercados = {}
        for m in datos["mercados"]:
            if "+" in m["mercado"]:
                factor = aprendido.get(semana.tipo_de(m["mercado"]), {}).get("factor", 1.0)
                mercados[m["mercado"]] = [round(min(m["prob"] * factor, 95.0), 1), m["mercado_justa"]]
        partidos.append({**p, "goles": datos["goles"], "corners": datos["corners"], "mercados": mercados})
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump({"actualizado": datetime.now().strftime("%d/%m/%Y %H:%M"), "partidos": partidos,
                   "aprendizaje": aprendido, "tuyas": resumen_tuyas(semana.leer_apuestas_movil())}, f,
                  ensure_ascii=False)
    print(f"{len(partidos)} partidos para la calculadora en {args.salida}")


if __name__ == "__main__":
    main()
