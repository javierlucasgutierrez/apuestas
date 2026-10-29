"""Prepara los dos documentos que lee la página del móvil (movil/top10.html).

Uso: python3 movil/exportar.py semana.json carpeta_salida
Escribe semana_actual.json y historial_todo.json, listos para subir al almacén de la página.
"""
import json
import os
import sys
from datetime import datetime


def main() -> None:
    entrada, salida = sys.argv[1], sys.argv[2]
    with open(entrada, encoding="utf-8") as f:
        datos = json.load(f)
    os.makedirs(salida, exist_ok=True)
    semana = {
        "actualizado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "desde": datos["desde"],
        "dias": datos["dias"],
        "picks": datos["picks"],
        "resumen": datos["resumen"],
        "aprendizaje": datos["aprendizaje"],
    }
    with open(os.path.join(salida, "semana_actual.json"), "w", encoding="utf-8") as f:
        json.dump(semana, f, ensure_ascii=False)
    with open(os.path.join(salida, "historial_todo.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": datos["historial"]}, f, ensure_ascii=False)
    print(f"{len(semana['picks'])} picks y {len(datos['historial'])} del historial listos en {salida}")


if __name__ == "__main__":
    main()
