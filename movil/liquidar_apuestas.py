"""Pone el resultado a las apuestas apuntadas en el móvil (colección «apuestas» de la página).

Uso: python3 movil/liquidar_apuestas.py carpeta_con_los_json salida.json
La carpeta es la que deja ArtifactData list con out_dir (un .json por apuesta). La salida es la
lista de cambios [{doc_id, estado, resultado, beneficio}] para escribir con «update».
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as cli  # noqa: E402
from predictor.registro import estado_de  # noqa: E402
from predictor.valor import _fecha, leer_filas, liquidar  # noqa: E402


def main() -> None:
    carpeta, salida = sys.argv[1], sys.argv[2]
    indice = {}
    for f in leer_filas([cli.DESCARGAS]):
        if f.get("FTHG") and f.get("HomeTeam"):
            try:
                indice[(_fecha(f["Date"]).isoformat(), f["HomeTeam"], f["AwayTeam"])] = f
            except ValueError:
                pass
    cambios = []
    for nombre in sorted(os.listdir(carpeta)):
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
            a = json.load(f)
        if a.get("estado") or not a.get("mercado") or not a.get("cuota"):
            continue
        local, visitante = a.get("local"), a.get("visitante")
        if not local and " – " in a.get("partido", ""):
            local, visitante = a["partido"].split(" – ", 1)
        fila = indice.get((a.get("fecha"), local, visitante))
        if not fila:
            continue
        beneficio, _ = liquidar(fila, a["mercado"], float(a["cuota"]))
        if beneficio is None:
            continue
        resultado = f"{fila['FTHG']}-{fila['FTAG']}"
        if a["mercado"].startswith("Córners") and fila.get("HC"):
            resultado += f", {int(fila['HC']) + int(fila['AC'])} córners"
        elif a["mercado"].startswith("1ª parte") and fila.get("HTHG"):
            resultado += f" (descanso {fila['HTHG']}-{fila['HTAG']})"
        cambios.append({"doc_id": nombre[:-5], "estado": estado_de(beneficio, float(a["cuota"])),
                        "resultado": resultado, "beneficio": round(beneficio, 3)})
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(cambios, f, ensure_ascii=False, indent=1)
    print(f"{len(cambios)} apuestas con resultado nuevo en {salida}")
    for c in cambios:
        print(f"  {c['doc_id']}: {c['estado']} ({c['resultado']})")


if __name__ == "__main__":
    main()
