"""Prueba las reglas de estrategias.py en el pasado y guarda el resultado en datos/estrategias_pasado.json.

Necesita el archivo de partidos ya calculados «antes de jugarse» (lo crea el estudio de la ⭐:
probabilidad del modelo reajustado cada 14 días, estadística de los últimos 10, mercado y cuotas).
Uso: python3 movil/estrategias_pasado.py partidos_pasado.pkl
"""
import os
import pickle
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import estrategias as e  # noqa: E402


def main() -> None:
    with open(sys.argv[1], "rb") as f:
        datos = pickle.load(f)
    salida = {}
    for regla in e.REGLAS:
        m = regla["mercado"]
        if m not in e.LINEAS_FRECUENCIA:
            salida[regla["id"]] = {"total": {"n": 0}, "mitades": [], "nota": "sin datos del pasado"}
            continue
        t, linea = e.LINEAS_FRECUENCIA[m]
        por_dia = defaultdict(list)
        for f in datos:
            if not f["mod"].get(m):
                continue
            c = {"prob": f["mod"][m], "frec": f["frec"][m], "pm": f["pm"] if m == "Goles +2.5" else None,
                 "cuota": f["max_o"] if m == "Goles +2.5" else None, "mercado": m}
            if regla["si"](c):
                por_dia[(f["fecha"], f["liga"][:1])].append((c, f))
        registros = []
        for lista in por_dia.values():
            for c, f in sorted(lista, key=lambda x: -regla["orden"](x[0]))[:e.MAXIMO_POR_DIA * 3]:
                acierto = f[t] > linea
                registros.append({"temp": f["temp"], "prob": c["prob"], "acierto": acierto,
                                  "beneficio": ((c["cuota"] - 1) if acierto else -1.0) if c["cuota"] else None})
        salida[regla["id"]] = {"total": e.resumen(registros),
                               "mitades": [e.resumen([r for r in registros if r["temp"] == "2425"]),
                                           e.resumen([r for r in registros if r["temp"] != "2425"])]}
        print(f"{regla['nombre']:<56} {salida[regla['id']]}")
    e.escribir(e.PASADO, salida)


if __name__ == "__main__":
    main()
