"""Gestión del bank del usuario: unidades, euros y cómo va.

Reglas acordadas: se empieza con 50 € el 1/11/2026, se reinvierte todo y 1 unidad = 5 % del bank,
recalculada cada lunes con el bank de ese momento. Cada apuesta es 1 unidad.

Las apuestas reales son las que el usuario marca «La he apostado» en la página (o me dice en el chat y
apunto yo): se leen de la carpeta que deja db_list de la colección «apuestas», ya liquidadas.
Uso: python3 gestion.py carpeta_apuestas [cambios.json]  → escribe datos/gestion_estado.json y lo resume.
"""

import json
import os
import sys
from datetime import date, timedelta

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONFIG = {"inicio": "2026-11-01", "bank_inicial": 50.0, "unidad_pct": 0.05}
ESTADO = os.path.join(CARPETA, "datos", "gestion_estado.json")


def lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def calcular(apuestas: list[dict]) -> dict:
    """Recorre las apuestas liquidadas en orden y lleva el bank con la unidad de cada semana."""
    bank = CONFIG["bank_inicial"]
    semana, unidad = None, bank * CONFIG["unidad_pct"]
    hechas = sorted((a for a in apuestas if a.get("beneficio") is not None), key=lambda a: a.get("fecha", ""))
    por_mes = {}
    for a in hechas:
        dia = date.fromisoformat(a["fecha"])
        if lunes(dia) != semana:
            semana, unidad = lunes(dia), round(bank * CONFIG["unidad_pct"], 2)
        bank += unidad * a["beneficio"]
        m = por_mes.setdefault(a["fecha"][:7], {"apuestas": 0, "aciertos": 0, "unidades": 0.0})
        m["apuestas"] += 1
        m["aciertos"] += a["beneficio"] > 0
        m["unidades"] = round(m["unidades"] + a["beneficio"], 2)
    hoy = date.today()
    unidad_hoy = unidad if semana == lunes(hoy) else round(bank * CONFIG["unidad_pct"], 2)
    n = len(hechas)
    unidades = round(sum(a["beneficio"] for a in hechas), 2)
    return {"bank": round(bank, 2), "unidad_euros": unidad_hoy, "apuestas": n,
            "aciertos": sum(a["beneficio"] > 0 for a in hechas), "unidades": unidades,
            "yield": round(100 * unidades / n, 1) if n else 0.0,
            "pendientes": sum(1 for a in apuestas if a.get("beneficio") is None), "por_mes": por_mes,
            "actualizado": hoy.isoformat()}


def estado() -> dict:
    """El último estado guardado (lo usan los avisos para decir cuánto apostar)."""
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return calcular([])


def main() -> None:
    carpeta = sys.argv[1]
    cambios = {}
    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        with open(sys.argv[2], encoding="utf-8") as f:
            cambios = {c["doc_id"]: c for c in json.load(f)}
    apuestas = []
    for nombre in sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []:
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
            a = json.load(f)
        a.update({k: v for k, v in cambios.get(nombre[:-5], {}).items() if k != "doc_id"})
        if a.get("papel") or a.get("fecha", "") < CONFIG["inicio"]:
            continue
        apuestas.append(a)
    e = calcular(apuestas)
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    print(f"Bank {e['bank']:.2f} € · 1 unidad = {e['unidad_euros']:.2f} € · {e['apuestas']} apuestas, "
          f"{e['aciertos']} acertadas · {e['unidades']:+.2f} u · yield {e['yield']:+.1f} % · pendientes {e['pendientes']}")


if __name__ == "__main__":
    main()
