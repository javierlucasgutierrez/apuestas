"""Trae el historial guardado en la página del móvil (documento historial/todo) al repositorio.

La página es la copia principal: así el aprendizaje no se pierde aunque un día falle el push.
Uso: python3 movil/importar_historial.py historial_todo.json
Solo añade o actualiza picks; nunca borra los que ya hay en datos/historial_top10.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import semana  # noqa: E402


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as f:
        remotos = json.load(f).get("picks", [])
    locales = {p["id"]: p for p in semana.leer_historial()}
    for p in remotos:
        actual = locales.get(p.get("id"))
        # Gana el que esté más avanzado: liquidado o anulado antes que pendiente.
        if p.get("id") and (actual is None or (actual.get("estado") == "pendiente" and p.get("estado") != "pendiente")):
            locales[p["id"]] = p
    picks = sorted(locales.values(), key=lambda p: (p["fecha"], p.get("generado", "")))
    semana.escribir_historial(picks)
    print(f"Historial: {len(picks)} picks ({len(remotos)} en la página)")


if __name__ == "__main__":
    main()
