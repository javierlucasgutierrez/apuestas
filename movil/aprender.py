"""Junta las apuestas que el usuario apuntó en el móvil (ya con resultado) para aprender de ellas.

Uso: python3 movil/aprender.py carpeta_apuestas cambios.json
- carpeta_apuestas: lo que deja ArtifactData list con out_dir (un .json por apuesta).
- cambios.json: los resultados nuevos que acaba de calcular liquidar_apuestas.py.
Escribe datos/apuestas_movil.json (no se sube al repositorio: se rehace cada día desde la página).
semana.aprendizaje() lo usa para corregir las probabilidades del modelo por tipo de apuesta.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import semana  # noqa: E402


def main() -> None:
    carpeta, cambios = sys.argv[1], sys.argv[2]
    nuevos = {}
    if os.path.exists(cambios):
        with open(cambios, encoding="utf-8") as f:
            nuevos = {c["doc_id"]: c for c in json.load(f)}
    registros = []
    for nombre in sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []:
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
            a = json.load(f)
        a.update({k: v for k, v in nuevos.get(nombre[:-5], {}).items() if k != "doc_id"})
        if a.get("beneficio") is None or not a.get("prob_modelo") or not a.get("mercado"):
            continue
        registros.append({"fecha": a.get("fecha"), "mercado": a["mercado"], "prob": float(a["prob_modelo"]),
                          "cuota": a.get("cuota"), "beneficio": float(a["beneficio"]),
                          "estado": a.get("estado"), "papel": bool(a.get("papel"))})
    with open(semana.APUESTAS_MOVIL, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=1)
    print(f"{len(registros)} apuestas tuyas con resultado; aprendizaje: "
          f"{ {k: v['factor'] for k, v in semana.aprendizaje().items()} }")


if __name__ == "__main__":
    main()
