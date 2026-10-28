"""Predictor estadístico de goles y córners para las grandes ligas.

Uso rápido:
    python app.py descargar
    python app.py jornada
    python app.py partido --local "Real Madrid" --visitante Getafe --cuota "corners+9.5=1.80"
    python app.py backtest
    python app.py optimizar

Ejecuta `python app.py <orden> -h` para ver todas las opciones.
"""

import argparse
import csv
import os
import sys
from dataclasses import replace
from datetime import date, timedelta

from predictor.backtest import backtest
from predictor.cuotas import kelly, normalizar_mercado, seleccionar
from predictor.datos import cara_a_cara, cargar_csv, cargar_varios, guardar_csv
from predictor.descargar import GRANDES, LIGAS, TODAS, descargar
from predictor.ejemplo import generar_liga
from predictor.mercados import Ajustes, Predictor, familia
from predictor.modelo import buscar_equipo
from predictor.optimizar import optimizar
from predictor.valor import CASAS, backtest_valor, leer_filas, oportunidades, probabilidad_consenso

CARPETA = os.path.dirname(os.path.abspath(__file__))
DESCARGAS = os.path.join(CARPETA, "datos", "descargas")
AJUSTES = os.path.join(CARPETA, "ajustes.json")
NOMBRE_LIGA = {codigo: nombre for codigo, nombre in LIGAS.values()}


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


# ------------------------------------------------------------------ opciones
def opciones_datos(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--datos", nargs="+", default=[DESCARGAS],
                        help="CSV o carpetas con el histórico (por defecto, lo descargado).")
    parser.add_argument("--vida-media", type=float,
                        help="Días tras los que un partido cuenta la mitad (goles y córners).")
    parser.add_argument("--peso-h2h", type=float, help="Peso de los enfrentamientos directos (0 a 1).")


def opciones_seleccion(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cuota-min", type=float, default=1.50, help="Cuota mínima que aceptas (1.50).")
    parser.add_argument("--umbral", type=float, default=0.05,
                        help="Valor mínimo según el modelo: 0.05 = la cuota debe pagar un 5%% más de lo justo.")
    parser.add_argument("--prob-minima", type=float, default=0.55,
                        help="Solo selecciones con al menos esta probabilidad (0.55).")
    parser.add_argument("--bank", type=float, default=100.0, help="Tu bank en euros (100).")
    parser.add_argument("--umbral-mercado", type=float, default=0.02,
                        help="Valor mínimo frente al precio justo del mercado (0.02 = 2%%).")
    parser.add_argument("--cuota-max", type=float, default=5.0, help="Cuota máxima en valor de mercado (5).")
    parser.add_argument("--casas", nargs="+", default=list(CASAS), metavar="CASA",
                        help=f"Casas a comparar: {' '.join(CASAS)} (por defecto todas).")


def leer_ajustes(args) -> Ajustes:
    ajustes = Ajustes.cargar(AJUSTES)
    if getattr(args, "vida_media", None):
        ajustes = replace(ajustes, vida_media_goles=args.vida_media, vida_media_corners=args.vida_media)
    if getattr(args, "peso_h2h", None) is not None:
        ajustes = replace(ajustes, peso_h2h=args.peso_h2h)
    return ajustes


def preparar(args, hasta: date | None = None):
    partidos = cargar_varios(args.datos)
    return partidos, Predictor(leer_ajustes(args)).ajustar(partidos, hasta=hasta)


# ------------------------------------------------------------------ salida
def mostrar_partido(pred, predictor, args, cuotas: dict[str, float], detalle: bool = True,
                    solo_corners: bool = False):
    """Imprime el análisis y devuelve las selecciones."""
    liga = NOMBRE_LIGA.get(pred.liga, pred.liga)
    print(f"\n{pred.local} vs {pred.visitante}   [{liga}]")
    print("-" * 66)
    linea = f"Esperado: goles {pred.goles_local:.2f}-{pred.goles_visitante:.2f}"
    if pred.corners_local is not None:
        linea += (f" · córners {pred.corners_local:.1f}-{pred.corners_visitante:.1f}"
                  f" (total {pred.corners_local + pred.corners_visitante:.1f})")
    print(linea)
    pr = pred.probs
    print(f"1X2: {pct(pr['1'])} / {pct(pr['X'])} / {pct(pr['2'])} · "
          f"+2.5 goles {pct(pr['Goles +2.5'])} · ambos marcan {pct(pr['Ambos marcan: sí'])}")
    if detalle:
        print("Marcadores más probables: " + ", ".join(f"{m} ({pct(p)})" for m, p in pred.marcadores))
        h2h = cara_a_cara(predictor.historial, pred.local, pred.visitante)
        if h2h.n:
            corners = f" · córners {h2h.corners_medios:.1f}" if h2h.corners_medios is not None else ""
            print(f"Cara a cara ({h2h.n}): {h2h.victorias_a}-{h2h.empates}-{h2h.victorias_b} · goles "
                  f"{h2h.goles_a:.1f}-{h2h.goles_b:.1f} · +2.5 {pct(h2h.pct_mas25)}{corners}")
    for aviso in pred.avisos:
        print(f"⚠  {aviso}")

    # Sin cuota conocida, se omiten las selecciones cuya cuota mínima queda muy por encima
    # de la justa (más del ~73 %): ninguna casa las va a pagar a ese precio.
    selecciones = [s for s in seleccionar(pred.probs, cuotas, args.cuota_min, args.umbral, args.prob_minima)
                   if s.cuota is not None or s.cuota_minima <= s.cuota_justa * 1.10]
    if solo_corners:
        selecciones = [s for s in selecciones if s.mercado.startswith("Córners") or s.cuota is not None]
    if not selecciones:
        print("Ninguna selección llega a la probabilidad mínima.")
        return []
    print(f"{'Selección':<20}{'Prob.':>6}{'Justa':>7}{'Mínima':>8}{'Cuota':>7}   ")
    for s in selecciones:
        if s.cuota is None:
            consejo = f"busca cuota ≥ {s.cuota_minima:.2f}"
            cuota = "-"
        elif s.recomendada and not pred.avisos:
            consejo = f"APOSTAR {args.bank * s.stake:.2f} € (valor {100 * s.valor:+.0f}%)"
            cuota = f"{s.cuota:.2f}"
        else:
            consejo = "no llega" if not s.recomendada else "dudoso: pocos datos"
            cuota = f"{s.cuota:.2f}"
        print(f"{s.mercado:<20}{pct(s.prob):>6}{s.cuota_justa:>7.2f}{s.cuota_minima:>8.2f}{cuota:>7}   {consejo}")
    return selecciones


def leer_cuotas_manuales(ruta: str, equipos: list[str]) -> dict[tuple[str, str], dict[str, float]]:
    """CSV con columnas local, visitante, mercado, cuota (copiadas de Oddspedia)."""
    resultado: dict[tuple[str, str], dict[str, float]] = {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        texto = f.read()
    separador = ";" if texto.splitlines()[0].count(";") > texto.splitlines()[0].count(",") else ","
    for fila in csv.DictReader(texto.splitlines(), delimiter=separador):
        fila = {k.strip().lower(): (v or "").strip() for k, v in fila.items() if k}
        if not fila.get("local"):
            continue
        clave = (buscar_equipo(fila["local"], equipos), buscar_equipo(fila["visitante"], equipos))
        resultado.setdefault(clave, {})[normalizar_mercado(fila["mercado"])] = float(fila["cuota"].replace(",", "."))
    return resultado


# ------------------------------------------------------------------ órdenes
def orden_descargar(args) -> None:
    print("Descargando de football-data.co.uk...")
    descargar(args.carpeta, TODAS if "todas" in args.ligas else args.ligas, args.temporadas)
    print(f"Listo. Datos en {os.path.relpath(args.carpeta)}")


def orden_equipos(args) -> None:
    _, predictor = preparar(args)
    for liga, mg in sorted(predictor.goles.items()):
        if args.liga and args.liga.lower() not in (liga.lower(), NOMBRE_LIGA.get(liga, "").lower()):
            continue
        mc = predictor.corners.get(liga)
        print(f"\n{NOMBRE_LIGA.get(liga, liga)} · datos hasta {mg.fecha_ajuste:%d/%m/%Y}")
        print(f"Por partido contra un rival medio en campo neutral (ventaja de casa en goles x{mg.ventaja_campo:.2f})")
        print(f"{'#':>2}  {'Equipo':<22}{'Goles F':>8}{'Goles C':>8}{'Dif':>6}   {'Córn. F':>8}{'Córn. C':>8}{'Total':>7}")
        for i, (t, gf, gc, dif) in enumerate(mg.clasificacion(), 1):
            if mc and mc.conoce(t):
                cf, cc = mc.base * mc.ataque[t], mc.base * mc.defensa[t]
                corners = f"{cf:>8.1f}{cc:>8.1f}{cf + cc:>7.1f}"
            else:
                corners = ""
            print(f"{i:>2}  {t:<22}{gf:>8.2f}{gc:>8.2f}{dif:>+6.2f}   {corners}")


def contrario(mercado: str) -> str | None:
    if "+" in mercado:
        return mercado.replace("+", "-")
    if mercado.startswith(("Goles -", "Córners -")):
        return mercado.replace("-", "+")
    return {"Ambos marcan: sí": "Ambos marcan: no", "Ambos marcan: no": "Ambos marcan: sí"}.get(mercado)


def mostrar_comparador(pred, listas: dict[str, list[float]], args) -> None:
    """Con las cuotas de varias casas: precio justo del mercado + opinión del modelo."""
    print(f"\nCOMPARANDO CASAS (valor de mercado ≥ {pct(args.umbral_mercado)} y modelo de acuerdo)")
    print(f"{'Selección':<17}{'Mejor':>6}{'Casas':>6}{'Justa mercado':>14}{'Justa modelo':>13}   Decisión")
    for mercado, cuotas in listas.items():
        mejor = max(cuotas)
        p_modelo = pred.probs.get(mercado)
        p_mercado = probabilidad_consenso(cuotas, listas.get(contrario(mercado))) if len(cuotas) >= 2 else None
        if p_modelo is None:
            continue
        valor_modelo = mejor * p_modelo - 1
        justa_mercado = f"{1 / p_mercado:.2f}" if p_mercado else "-"
        if mejor < args.cuota_min:
            decision = f"no: cuota < {args.cuota_min:.2f}"
        elif p_mercado is None:
            decision = ("solo modelo: " + ("vale" if mejor * p_modelo >= 1 + args.umbral else "no llega")
                        + " (pon más casas para comparar)")
        else:
            valor_mercado = mejor * p_mercado - 1
            if valor_mercado >= args.umbral_mercado and valor_modelo >= 0:
                p = (p_mercado + p_modelo) / 2
                decision = (f"APOSTAR {args.bank * kelly(p, mejor):.2f} € (valor mercado {100 * valor_mercado:+.0f}%,"
                            f" modelo {100 * valor_modelo:+.0f}%)")
            elif valor_mercado >= args.umbral_mercado:
                decision = f"dudoso: el mercado da valor ({100 * valor_mercado:+.0f}%) pero el modelo no"
            else:
                decision = f"no: la mejor cuota no supera lo justo del mercado ({100 * valor_mercado:+.0f}%)"
        print(f"{mercado:<17}{mejor:>6.2f}{len(cuotas):>6}{justa_mercado:>14}{1 / p_modelo:>13.2f}   {decision}")


def orden_partido(args) -> None:
    _, predictor = preparar(args)
    listas: dict[str, list[float]] = {}
    for texto in args.cuota or []:
        mercado, _, valores = texto.partition("=")
        if not valores:
            sys.exit(f"Error: escribe la cuota como mercado=cuota, por ejemplo corners+9.5=1.80 (recibido {texto!r})")
        listas[normalizar_mercado(mercado)] = [float(v.replace(",", ".")) for v in valores.split("/") if v.strip()]
    pred = predictor.predecir(args.local, args.visitante)
    # Con una sola cuota decide el modelo; con varias casas decide el comparador.
    mostrar_partido(pred, predictor, args, {m: c[0] for m, c in listas.items() if len(c) == 1})
    if listas:
        mostrar_comparador(pred, listas, args)


def orden_jornada(args) -> None:
    proximos = [p for p in cargar_csv(args.proximos) if not p.jugado]
    hoy = date.today() if not args.desde else date.fromisoformat(args.desde)
    proximos = [p for p in proximos if hoy <= p.fecha <= hoy + timedelta(days=args.dias)]
    if args.liga:
        codigos = {LIGAS[l][0] if l in LIGAS else l for l in args.liga}
        proximos = [p for p in proximos if p.liga in codigos]
    if not proximos:
        print("No hay próximos partidos en esas fechas. Prueba 'python app.py descargar' o amplía --dias.")
        return
    _, predictor = preparar(args)
    manuales = leer_cuotas_manuales(args.cuotas, predictor.equipos) if args.cuotas else {}

    # Las cuotas de 1X2 y goles del archivo no se comparan con el modelo: el backtest dice que
    # ahí la casa sabe más. Se usan en la sección de valor de mercado (comparando casas).
    apostar, mirar = [], []
    for p in proximos:
        try:
            pred = predictor.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError as e:
            print(f"\n{p.local} vs {p.visitante}: {e.args[0]}")
            continue
        cuotas = manuales.get((pred.local, pred.visitante), {})
        print(f"\n{p.fecha:%a %d/%m}", end="")
        for s in mostrar_partido(pred, predictor, args, cuotas, detalle=False, solo_corners=not args.todos):
            if pred.avisos:
                continue
            if s.recomendada:
                apostar.append((p, s))
            elif s.cuota is None:
                mirar.append((p, s))

    print("\n" + "=" * 66)
    print("1) VALOR DE MERCADO: una casa paga más que el precio justo (1X2, goles 2,5, hándicap asiático)")
    print("=" * 66)
    filas = [f for f in leer_filas([args.proximos]) if not f.get("FTHG")]
    mostrar_valor_mercado(filas, predictor, args, hoy)

    if apostar:
        print("\nCON TUS CUOTAS (archivo --cuotas)")
        for p, s in sorted(apostar, key=lambda x: -x[1].valor):
            print(f"{p.fecha:%d/%m}  {p.local} - {p.visitante}: {s.mercado} @ {s.cuota:.2f} "
                  f"({pct(s.prob)}, valor {100 * s.valor:+.0f}%) → {args.bank * s.stake:.2f} €")
    tipo = "SELECCIONES" if args.todos else "CÓRNERS"
    print(f"\n2) {tipo} PARA MIRAR EN ODDSPEDIA (apuesta solo si encuentras la cuota mínima o más)")
    print("-" * 66)
    for p, s in sorted(mirar, key=lambda x: -x[1].prob)[:args.top]:
        print(f"{p.fecha:%d/%m}  {p.local} - {p.visitante}: {s.mercado:<16} {pct(s.prob):>4}  "
              f"cuota mínima {s.cuota_minima:.2f}")


def mostrar_valor_mercado(filas: list[dict], predictor, args, hoy: date) -> None:
    """Oportunidades de los próximos partidos según el precio justo de Pinnacle o Betfair."""
    codigos = {LIGAS[l][0] if l in LIGAS else l for l in (args.liga or [])}
    encontradas = []
    for fila in filas:
        try:
            ops = oportunidades(fila, args.casas, args.umbral_mercado, args.cuota_min, args.cuota_max)
        except ValueError:
            continue
        for o in ops:
            if not hoy <= o.fecha <= hoy + timedelta(days=args.dias) or (codigos and o.liga not in codigos):
                continue
            try:
                p_modelo = predictor.predecir(o.local, o.visitante).probs.get(o.mercado)
            except KeyError:
                p_modelo = None
            encontradas.append((o, p_modelo))
    if not encontradas:
        print("Ninguna ahora mismo. No apostar también es una decisión correcta.")
        return
    for o, p_modelo in sorted(encontradas, key=lambda x: -x[0].valor):
        modelo = "sin datos"
        if p_modelo is not None:
            modelo = "de acuerdo ✔" if o.cuota * p_modelo >= 1 else "en contra"
        stake = args.bank * kelly(o.prob_justa, o.cuota)
        print(f"{o.fecha:%d/%m}  {o.local} - {o.visitante}: {o.mercado} en {CASAS.get(o.casa, o.casa)} "
              f"@ {o.cuota:.2f} (justa {o.cuota_justa:.2f}, valor {100 * o.valor:+.1f}%) "
              f"→ {stake:.2f} € · modelo {modelo}")
    print("Cuotas tomadas cuando se actualizó football-data: compruébalas en Oddspedia antes de apostar.")


def orden_valor(args) -> None:
    if args.backtest:
        filas = leer_filas(args.datos)
        print(f"Valor de mercado en el histórico: apostar cuando {', '.join(CASAS.get(c, c) for c in args.casas)}"
              f" paga ≥ {pct(args.umbral_mercado)} más que el precio justo (Pinnacle o Betfair),")
        print(f"con cuotas entre {args.cuota_min:.2f} y {args.cuota_max:.2f}. Apuesta fija de 1 €.\n")
        inf = backtest_valor(filas, args.casas, args.umbral_mercado, args.cuota_min, args.cuota_max)
        print(f"{'Mercado':<19}{'Temporada':<11}{'Apuestas':>9}{'Aciertos':>10}{'Cuota media':>12}"
              f"{'Beneficio':>11}{'Yield':>8}{'CLV':>8}")
        for (familia, temporada), r in sorted(inf.por_temporada.items()):
            print(f"{familia:<19}{temporada:<11}{r.n:>9}{100 * r.aciertos / r.n:>9.0f}%{r.suma_cuotas / r.n:>12.2f}"
                  f"{r.beneficio:>+10.1f}€{r.yield_pct:>+7.1f}%{r.clv_pct:>+7.1f}%")
        for familia, r in sorted(inf.total.items()):
            print(f"{familia:<19}{'TOTAL':<11}{r.n:>9}{100 * r.aciertos / r.n:>9.0f}%{r.suma_cuotas / r.n:>12.2f}"
                  f"{r.beneficio:>+10.1f}€{r.yield_pct:>+7.1f}%{r.clv_pct:>+7.1f}%")
        print("\nCLV: cuánto mejor que el precio justo final (justo antes del partido) era la cuota cogida.")
        print("Positivo y estable = valor real a largo plazo, aunque el beneficio de una temporada dependa de la suerte.")
        return
    hoy = date.today() if not args.desde else date.fromisoformat(args.desde)
    _, predictor = preparar(args)
    filas = [f for f in leer_filas([args.proximos]) if not f.get("FTHG")]
    mostrar_valor_mercado(filas, predictor, args, hoy)


def orden_backtest(args) -> None:
    partidos = cargar_varios(args.datos)
    print("Calculando: el modelo se reajusta cada semana solo con lo que se sabía en ese momento...")
    desde = date.fromisoformat(args.desde) if args.desde else None
    inf = backtest(partidos, leer_ajustes(args), desde=desde, reajuste_dias=args.reajuste,
                   cuota_min=args.cuota_min, umbral=args.umbral, prob_minima=args.prob_minima,
                   aviso=lambda f: print(f"  {f:%m/%Y}", end="\r", flush=True))
    print(f"\nPartidos evaluados: {inf.partidos} ({inf.desde:%d/%m/%Y} - {inf.hasta:%d/%m/%Y})")

    print("\n1) ¿SE CUMPLEN LAS PROBABILIDADES?  (prob. del modelo vs. lo que pasó de verdad)")
    for nombre in ("1X2", "Doble oportunidad", "Goles más/menos", "Ambos marcan", "Córners más/menos"):
        cal = inf.calibracion.get(nombre)
        if not cal or not cal.casos:
            continue
        print(f"\n  {nombre} · mejora frente a usar el % medio: {100 * cal.mejora_sobre_media():+.1f}%")
        print(f"  {'Tramo':<11}{'Casos':>7}{'Modelo':>8}{'Real':>7}{'Cuota para no perder':>23}")
        for desde_t, hasta_t, n, prob, real in cal.filas():
            if n < 20:
                continue
            print(f"  {pct(desde_t):>4}-{pct(hasta_t):<5}{n:>8}{pct(prob):>8}{pct(real):>7}{1 / real if real else 0:>15.2f}")

    print("\n2) DINERO CON LAS CUOTAS REALES DEL HISTÓRICO (1X2 y más/menos 2,5 goles, apuesta fija de 1 €)")
    print(f"   Reglas: cuota ≥ {args.cuota_min:.2f}, valor ≥ {pct(args.umbral)}, probabilidad ≥ {pct(args.prob_minima)}")
    n, aciertos, beneficio, cuota = inf.resumen_apuestas()
    if not n:
        print("   Ninguna apuesta cumple las reglas.")
    else:
        print(f"   Total: {n} apuestas · aciertos {aciertos:.1f}% · cuota media {cuota:.2f} · "
              f"beneficio {beneficio:+.2f} € (yield {100 * beneficio / n:+.1f}%)")
        for mercado in ("1", "X", "2", "Goles +2.5", "Goles -2.5"):
            n, aciertos, beneficio, cuota = inf.resumen_apuestas(lambda a: a.mercado == mercado)
            if n:
                print(f"     {mercado:<11}{n:>5} apuestas · aciertos {aciertos:5.1f}% · cuota media {cuota:.2f}"
                      f" · {beneficio:+8.2f} € ({100 * beneficio / n:+.1f}%)")
        if inf.resumen_apuestas()[0] < 300:
            print("   ⚠  Menos de 300 apuestas: el resultado puede ser pura suerte.")


def orden_optimizar(args) -> None:
    partidos = cargar_varios(args.datos)
    print("Probando combinaciones (puede tardar varios minutos)...")
    mejor = optimizar(partidos)
    ajustes = Ajustes.cargar(AJUSTES)
    if "goles" in mejor:
        ajustes.vida_media_goles = mejor["goles"]["vida_media"]
        ajustes.regularizacion_goles = mejor["goles"]["regularizacion"]
    if "corners" in mejor:
        ajustes.vida_media_corners = mejor["corners"]["vida_media"]
        ajustes.regularizacion_corners = mejor["corners"]["regularizacion"]
    print("\nAprendiendo la corrección de probabilidades con los aciertos y fallos pasados...")
    ajustes.calibracion = backtest(partidos, ajustes).calibradores
    ajustes.guardar(AJUSTES)
    print(f"\nMejores ajustes guardados en {os.path.relpath(AJUSTES)}:")
    print(f"  Goles:   vida media {ajustes.vida_media_goles:.0f} días · regularización {ajustes.regularizacion_goles}")
    print(f"  Córners: vida media {ajustes.vida_media_corners:.0f} días · regularización {ajustes.regularizacion_corners}")
    print("Se usarán automáticamente en el resto de órdenes.")


def orden_ejemplo(args) -> None:
    jugados, proxima = generar_liga()
    carpeta = os.path.join(CARPETA, "datos", "ejemplo")
    os.makedirs(carpeta, exist_ok=True)
    guardar_csv(os.path.join(carpeta, "historico.csv"), jugados)
    guardar_csv(os.path.join(carpeta, "proximos.csv"), proxima)
    print(f"Liga ficticia creada en {os.path.relpath(carpeta)}: {len(jugados)} partidos jugados y "
          f"{len(proxima)} por jugar.\nPruébala con:  python app.py jornada --datos {os.path.relpath(carpeta)} "
          f"--proximos {os.path.relpath(os.path.join(carpeta, 'proximos.csv'))} --desde {proxima[0].fecha}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Predictor estadístico de goles y córners.")
    sub = parser.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("descargar", help="Baja resultados, córners y cuotas de las grandes ligas.")
    p.add_argument("--ligas", nargs="+", default=GRANDES, choices=list(LIGAS) + ["todas"],
                   help=f"Por defecto: {' '.join(GRANDES)}. 'todas' baja las {len(LIGAS)} ligas.")
    p.add_argument("--temporadas", type=int, default=4, help="Cuántas temporadas (4).")
    p.add_argument("--carpeta", default=DESCARGAS)
    p.set_defaults(func=orden_descargar)

    p = sub.add_parser("equipos", help="Goles y córners a favor y en contra de cada equipo.")
    opciones_datos(p)
    p.add_argument("--liga", help="Solo una liga (por ejemplo SP1).")
    p.set_defaults(func=orden_equipos)

    p = sub.add_parser("partido", help="Analiza un partido. Añade --cuota para saber si apostar.")
    opciones_datos(p)
    opciones_seleccion(p)
    p.add_argument("--local", required=True)
    p.add_argument("--visitante", required=True)
    p.add_argument("--cuota", nargs="+", metavar="MERCADO=CUOTA",
                   help='Cuotas que ves en Oddspedia, p. ej. "corners+9.5=1.80" "goles-2.5=1.70". '
                        'Con varias casas, sepáralas con /: "corners+9.5=1.80/1.85/2.05" "corners-9.5=1.95/1.90/1.75".')
    p.set_defaults(func=orden_partido)

    p = sub.add_parser("jornada", help="Analiza los próximos partidos y dice qué mirar en Oddspedia.")
    opciones_datos(p)
    opciones_seleccion(p)
    p.add_argument("--proximos", default=os.path.join(DESCARGAS, "proximos.csv"))
    p.add_argument("--cuotas", help="CSV con cuotas copiadas (columnas local, visitante, mercado, cuota).")
    p.add_argument("--dias", type=int, default=3, help="Partidos de los próximos N días (3).")
    p.add_argument("--desde", help="Fecha inicial AAAA-MM-DD (por defecto hoy).")
    p.add_argument("--liga", nargs="+", help="Solo estas ligas (laliga, premier... o SP1, E0...).")
    p.add_argument("--top", type=int, default=20, help="Cuántas selecciones listar para mirar (20).")
    p.add_argument("--todos", action="store_true",
                   help="Mostrar también goles y 1X2 del modelo (por defecto solo córners).")
    p.set_defaults(func=orden_jornada)

    p = sub.add_parser("valor", help="Comparador de casas: dónde se paga más que el precio justo.")
    opciones_datos(p)
    opciones_seleccion(p)
    p.add_argument("--proximos", default=os.path.join(DESCARGAS, "proximos.csv"))
    p.add_argument("--dias", type=int, default=3, help="Partidos de los próximos N días (3).")
    p.add_argument("--desde", help="Fecha inicial AAAA-MM-DD (por defecto hoy).")
    p.add_argument("--liga", nargs="+", help="Solo estas ligas (laliga, premier... o SP1, E0...).")
    p.add_argument("--backtest", action="store_true", help="Probar la estrategia con el histórico.")
    p.set_defaults(func=orden_valor)

    p = sub.add_parser("backtest", help="¿Se cumplen las probabilidades? ¿Habría ganado dinero?")
    opciones_datos(p)
    opciones_seleccion(p)
    p.add_argument("--desde", help="Evaluar desde esta fecha AAAA-MM-DD (por defecto, tras la 1.ª temporada).")
    p.add_argument("--reajuste", type=int, default=7, help="Cada cuántos días se reajusta el modelo (7).")
    p.set_defaults(func=orden_backtest)

    p = sub.add_parser("optimizar", help="Busca cuánto pasado usar para predecir mejor y lo guarda.")
    opciones_datos(p)
    p.set_defaults(func=orden_optimizar)

    p = sub.add_parser("ejemplo", help="Crea una liga ficticia para probar sin conexión.")
    p.set_defaults(func=orden_ejemplo)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"Error: {e.args[0] if e.args else e}")


if __name__ == "__main__":
    main()
