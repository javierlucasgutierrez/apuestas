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
from predictor.descargar import LIGAS, expandir_ligas  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("salida")
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args()
    ligas = {LIGAS[l][0] for l in expandir_ligas(panel.preferencias().get("ligas", ["principales"])) if l in LIGAS}
    partidos = []
    for p in panel.lista_partidos(args.dias)["partidos"]:
        if p["liga"] not in ligas:
            continue
        try:
            datos = panel.probabilidades_partido(p["fecha"], p["local"], p["visitante"])
        except KeyError:
            continue
        # Por mercado: [probabilidad del modelo en %, cuota justa del mercado o null]
        mercados = {m["mercado"]: [m["prob"], m["mercado_justa"]] for m in datos["mercados"] if "+" in m["mercado"]}
        partidos.append({**p, "goles": datos["goles"], "corners": datos["corners"], "mercados": mercados})
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump({"actualizado": datetime.now().strftime("%d/%m/%Y %H:%M"), "partidos": partidos}, f,
                  ensure_ascii=False)
    print(f"{len(partidos)} partidos para la calculadora en {args.salida}")


if __name__ == "__main__":
    main()
