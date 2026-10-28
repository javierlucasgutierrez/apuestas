"""Corrección de las probabilidades con los aciertos y fallos pasados del modelo.

Si en el pasado el modelo decía "67 %" y aquello pasó el 58 % de las veces, la
calibración aprende a bajar esas probabilidades. Se usa una regresión logística
sobre la probabilidad original (escalado de Platt):

    p_corregida = 1 / (1 + exp(-(a + b * logit(p))))

con a = 0 y b = 1 si no hay nada que corregir. Se ajusta por grupo de mercados
(cada línea de goles y de córners, ambos marcan) sobre el lado "más" / "sí"; el otro
lado es el complementario. En 1X2 se corrigen la victoria local y la visitante por separado.
"""

import math

GRUPOS = {"goles": "Goles +", "corners": "Córners +", "ambos": "Ambos marcan: sí",
          "victoria_local": "1", "victoria_visitante": "2"}
MINIMO_CASOS = 400


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def grupo_de(mercado: str) -> str | None:
    """Grupo de calibración. Cada línea de goles y córners va por separado: el modelo no
    se equivoca igual en "más de 1,5" que en "más de 3,5"."""
    if mercado in ("1", "2"):
        return "victoria_local" if mercado == "1" else "victoria_visitante"
    if mercado.startswith("1ª parte goles +"):
        return f"1t goles {mercado.split()[-1][1:]}"
    if mercado.startswith(("Goles +", "Córners +")):
        tipo, linea = mercado.split()
        return f"{'goles' if tipo == 'Goles' else 'corners'} {linea[1:]}"
    if mercado == "Ambos marcan: sí":
        return "ambos"
    return None


def ajustar_platt(pares: list[tuple[float, bool]], suavizado: float = 20.0) -> tuple[float, float]:
    """(a, b) por máxima verosimilitud, con un empujón hacia (0, 1) para no sobreajustar."""
    a, b = 0.0, 1.0
    xs = [(_logit(p), 1.0 if ok else 0.0) for p, ok in pares]
    for _ in range(25):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in xs:
            q = 1 / (1 + math.exp(-(a + b * x)))
            ga += y - q
            gb += (y - q) * x
            w = q * (1 - q)
            haa += w
            hab += w * x
            hbb += w * x * x
        ga -= suavizado * a
        gb -= suavizado * (b - 1)
        haa += suavizado
        hbb += suavizado
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-8:
            break
    return a, b


def ajustar_calibradores(pares: dict[str, list[tuple[float, bool]]]) -> dict[str, list[float]]:
    return {g: list(ajustar_platt(lista)) for g, lista in pares.items() if len(lista) >= MINIMO_CASOS}


def _corregir(p: float, calibrador: list[float]) -> float:
    a, b = calibrador
    return 1 / (1 + math.exp(-(a + b * _logit(p))))


def aplicar(probs: dict[str, float], calibradores: dict[str, list[float]]) -> dict[str, float]:
    """Devuelve las probabilidades corregidas."""
    if not calibradores:
        return probs
    corregidas = dict(probs)
    for mercado, p in probs.items():
        grupo = grupo_de(mercado)
        if grupo not in calibradores or grupo.startswith("victoria"):
            continue
        q = _corregir(p, calibradores[grupo])
        corregidas[mercado] = q
        if "+" in mercado:
            corregidas[mercado.replace("+", "-")] = 1 - q
        else:
            corregidas["Ambos marcan: no"] = 1 - q

    # 1X2: se corrigen la victoria local y la visitante; el empate es lo que queda.
    if "1" in probs and ("victoria_local" in calibradores or "victoria_visitante" in calibradores):
        p1, p2 = probs["1"], probs["2"]
        if "victoria_local" in calibradores:
            p1 = _corregir(p1, calibradores["victoria_local"])
        if "victoria_visitante" in calibradores:
            p2 = _corregir(p2, calibradores["victoria_visitante"])
        px = max(1 - p1 - p2, 0.05)
        total = p1 + px + p2
        p1, px, p2 = p1 / total, px / total, p2 / total
        corregidas.update({"1": p1, "X": px, "2": p2, "1X": p1 + px, "X2": px + p2, "12": p1 + p2})
    return corregidas
