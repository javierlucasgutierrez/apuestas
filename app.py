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
import json
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
from predictor.sistema import PERFILES, apuestas_del_sistema, comparar_perfiles, montecarlo, simular_bank, stake
from predictor.registro import Registro, descripcion, resumir, stake_10
from predictor.valor import CASAS, backtest_valor, leer_filas, oportunidades, probabilidad_consenso

CARPETA = os.path.dirname(os.path.abspath(__file__))
DESCARGAS = os.path.join(CARPETA, "datos", "descargas")
AJUSTES = os.path.join(CARPETA, "ajustes.json")
PREFERENCIAS = os.path.join(CARPETA, "preferencias.json")
BASE_DATOS = os.path.join(CARPETA, "datos", "apuestas.db")
PUBLICAR = os.path.join(CARPETA, "datos", "publicar")
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


def leer_preferencias() -> dict:
    if os.path.exists(PREFERENCIAS):
        with open(PREFERENCIAS, encoding="utf-8") as f:
            return json.load(f)
    return {}


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


def orden_sistema(args) -> None:
    kw = {"fraccion_kelly": args.kelly, "tope": args.tope, "plano": args.plano}
    if args.backtest:
        filas = leer_filas(args.datos)
        print("Cada perfil, en temporadas de ENTRENAMIENTO (2023-25, con las que se diseñó) y de")
        print("PRUEBA (2025-27, que el sistema no había visto). Lo que vale es la prueba.\n")
        print(f"{'Perfil':<13}{'Periodo':<10}{'Apuestas':>9}{'Por semana':>11}{'Ganadas':>9}{'Cuota':>7}"
              f"{'Yield':>8}{'CLV':>7}")
        resultados = comparar_perfiles(filas, args.casas, args.cuota_min)
        for r in resultados:
            for nombre, ops in (("entreno", r.entreno), ("prueba", r.prueba)):
                if not ops:
                    continue
                semanas = max((ops[-1].fecha - ops[0].fecha).days / 7, 1)
                clv = [o.clv for o in ops if o.clv is not None]
                print(f"{r.perfil:<13}{nombre:<10}{len(ops):>9}{len(ops) / semanas:>11.1f}"
                      f"{100 * sum(o.beneficio > 0 for o in ops) / len(ops):>8.0f}%"
                      f"{sum(o.cuota for o in ops) / len(ops):>7.2f}"
                      f"{100 * sum(o.beneficio for o in ops) / len(ops):>+7.1f}%"
                      f"{100 * sum(clv) / max(len(clv), 1):>+6.1f}%")
        print(f"\nBANK de {args.bank:.0f} € en las temporadas de prueba, apostando con "
              f"{'Kelly x' + str(args.kelly) if args.metodo == 'kelly' else f'{100 * args.plano:.0f} % fijo'}:")
        for r in resultados:
            if not r.prueba:
                continue
            sim = simular_bank(r.prueba, args.bank, args.metodo, **kw)
            print(f"  {r.perfil:<13}{args.bank:.0f} € → {sim.bank_final:.0f} € ({sim.rentabilidad_bank:+.0f} %) · "
                  f"apostado {sim.apostado:.0f} € · peor caída {100 * sim.caida_maxima:.0f} %")
        print("\nUNA TEMPORADA SIMULADA 2.000 veces (sorteando apuestas reales del histórico):")
        print(f"  {'Perfil':<13}{'Apuestas':>9}{'Mala (5 %)':>12}{'Normal':>9}{'Buena (5 %)':>13}"
              f"{'P(perder)':>11}{'Caída típica':>14}")
        for r in resultados:
            todas = r.entreno + r.prueba
            if not todas:
                continue
            temporadas = max((todas[-1].fecha - todas[0].fecha).days / 365, 1)
            n = int(len(todas) / temporadas)
            mc = montecarlo(todas, n, 2000, args.metodo, **kw)
            print(f"  {r.perfil:<13}{n:>9}{mc['peor_5']:>+11.0f}%{mc['mediana']:>+8.0f}%{mc['mejor_5']:>+12.0f}%"
                  f"{mc['prob_perder']:>10.0f}%{mc['caida_mediana']:>13.0f}%")
        print("\nSupone que el futuro se parece al pasado y que consigues las cuotas indicadas.")
        return

    hoy = date.today() if not args.desde else date.fromisoformat(args.desde)
    filas = [f for f in leer_filas([args.proximos]) if not f.get("FTHG")]
    codigos = {LIGAS[l][0] if l in LIGAS else l for l in (args.liga or [])}
    elegidas = [o for _, o in apuestas_del_sistema(filas, args.perfil, args.casas, args.cuota_min)
                if hoy <= o.fecha <= hoy + timedelta(days=args.dias) and (not codigos or o.liga in codigos)]
    print(f"SISTEMA · perfil {args.perfil} · bank {args.bank:.0f} € · "
          f"{'Kelly x' + str(args.kelly) if args.metodo == 'kelly' else f'{100 * args.plano:.0f} % fijo'}")
    print("=" * 66)
    if not elegidas:
        print("Ninguna apuesta ahora mismo. Vuelve tras 'python app.py descargar'.")
        return
    total = 0.0
    registro = Registro(BASE_DATOS) if args.guardar else None
    nuevos = 0
    for o in elegidas:
        pct_bank = stake(o, args.metodo, **kw)
        importe = args.bank * pct_bank
        total += importe
        liga = NOMBRE_LIGA.get(o.liga, o.liga)
        print(f"{o.fecha:%a %d/%m}  {o.local} - {o.visitante} [{liga}]")
        print(f"      {o.mercado} en {CASAS.get(o.casa, o.casa)} @ {o.cuota:.2f}  (justa {o.cuota_justa:.2f}, "
              f"valor {100 * o.valor:+.1f} %)  →  {importe:.2f} € · stake {stake_10(pct_bank, args.tope)}/10")
        if registro and registro.guardar(o, pct_bank, args.perfil, args.tope):
            nuevos += 1
    print("-" * 66)
    print(f"{len(elegidas)} apuestas · total {total:.2f} € ({100 * total / args.bank:.1f} % del bank)")
    if registro:
        print(f"Guardados en el registro: {nuevos} nuevos ({len(elegidas) - nuevos} ya estaban).")
        registro.cerrar()
    print("Comprueba cada cuota en Oddspedia: si ha bajado de la justa × 1,02, ya no tiene valor.")
    print("'Mejor cuota del mercado' puede ser de una casa que no opera en España: busca esa cuota")
    print("(o más) entre tus casas. Sin varias cuentas abiertas, el sistema pierde casi toda su ventaja.")


def mostrar_pick(p) -> str:
    return (f"{p.fecha_partido:%d/%m} {p.local} - {p.visitante} · {p.mercado} @ {p.cuota:.2f} "
            f"({CASAS.get(p.casa, p.casa)}) · stake {p.stake}/10")


def orden_configurar(args) -> None:
    prefs = leer_preferencias()
    cambios = {k: v for k, v in vars(args).items() if k not in ("func", "orden") and v is not None}
    prefs.update(cambios)
    with open(PREFERENCIAS, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)
    print("Preferencias guardadas (se usan por defecto en todas las órdenes):")
    for k, v in prefs.items():
        print(f"  {k}: {' '.join(v) if isinstance(v, list) else v}")


def orden_actualizar(args) -> None:
    ligas = args.ligas or GRANDES
    print("1) Descargando datos nuevos de football-data.co.uk...")
    descargar(DESCARGAS, TODAS if "todas" in ligas else ligas, args.temporadas)
    print("\n2) Liquidando picks pendientes...")
    registro = Registro(BASE_DATOS)
    liquidados = registro.liquidar(leer_filas([DESCARGAS]))
    for p in liquidados:
        signo = f"{p.unidades:+.2f} u" if p.unidades is not None else ""
        print(f"  {p.estado.upper():<14}{mostrar_pick(p)} → {signo}")
    pendientes = registro.pendientes()
    print(f"  {len(liquidados)} liquidados · {len(pendientes)} siguen pendientes")
    total, _, _ = resumir(registro.picks())
    if total.picks:
        print(f"\nHistorial: {total.picks} picks · {total.unidades:+.2f} unidades · yield {total.yield_pct:+.1f} %")
    registro.cerrar()
    if os.path.exists(AJUSTES):
        dias = (date.today() - date.fromtimestamp(os.path.getmtime(AJUSTES))).days
        if dias > 30:
            print(f"\nLos ajustes del modelo tienen {dias} días: conviene ejecutar 'python app.py optimizar'.")


def orden_anotar(args) -> None:
    """Pick manual (por ejemplo, de córners) para que entre en el registro y se liquide solo."""
    from predictor.valor import Oportunidad
    mercado = normalizar_mercado(args.mercado)
    fecha = date.fromisoformat(args.fecha)
    familia = "Córners" if mercado.startswith("Córners") else "Manual"
    o = Oportunidad(fecha, args.liga or "", args.local, args.visitante, mercado, args.casa, args.cuota,
                    1 / args.cuota, "manual", familia=familia)
    registro = Registro(BASE_DATOS)
    pct = args.stake * args.tope / 10
    if registro.guardar(o, pct, "manual", args.tope):
        print(f"Anotado: {args.local} - {args.visitante} · {mercado} @ {args.cuota:.2f} · stake {args.stake}/10")
    else:
        print("Ese pick ya estaba en el registro.")
    registro.cerrar()


def orden_picks(args) -> None:
    registro = Registro(BASE_DATOS)
    pendientes = registro.pendientes()
    if not pendientes:
        print("No hay picks pendientes.")
    for p in pendientes:
        print(("   " if p.publicado else " * ") + mostrar_pick(p))
    if pendientes:
        print("(* = sin publicar)")
    if args.publicar:
        nuevos = [p for p in pendientes if not p.publicado]
        if not nuevos:
            print("Nada nuevo que publicar.")
        else:
            os.makedirs(PUBLICAR, exist_ok=True)
            ruta = os.path.join(PUBLICAR, f"{date.today():%Y-%m-%d}.txt")
            with open(ruta, "a", encoding="utf-8") as f:
                for p in nuevos:
                    liga = NOMBRE_LIGA.get(p.liga, p.liga)
                    f.write(f"⚽ {p.local} - {p.visitante} · {liga} · {p.fecha_partido:%d/%m}\n"
                            f"➡️ {descripcion(p)}\n💰 Cuota {p.cuota:.2f} ({CASAS.get(p.casa, p.casa)})\n"
                            f"📊 Stake {p.stake}/10\n")
                    if p.cuota_justa and p.cuota_justa * 1.02 < p.cuota:
                        f.write(f"🔻 No apostar por debajo de {p.cuota_justa * 1.02:.2f}\n")
                    f.write("\n")
            registro.marcar_publicados([p.id for p in nuevos])
            print(f"\nTexto para publicar ({len(nuevos)} picks): {os.path.relpath(ruta)}")
    registro.cerrar()


def orden_informe(args) -> None:
    registro = Registro(BASE_DATOS)
    picks = registro.picks()
    registro.cerrar()
    total, por_mes, por_familia = resumir(picks)
    if args.exportar:
        with open(args.exportar, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "dado", "fecha", "liga", "local", "visitante", "mercado", "casa", "cuota",
                        "stake", "estado", "unidades", "clv"])
            for p in picks:
                w.writerow([p.id, p.creado, p.fecha_partido, p.liga, p.local, p.visitante, p.mercado, p.casa,
                            p.cuota, p.stake, p.estado, "" if p.unidades is None else round(p.unidades, 3),
                            "" if p.clv is None else round(p.clv, 4)])
        print(f"Historial completo exportado a {args.exportar}")
    if not total.picks:
        print("Todavía no hay picks liquidados.")
        return

    def fila(nombre, r):
        clv = f"{r.clv_pct:+.1f}%" if r.clv_pct is not None else "-"
        return (f"{nombre:<20}{r.picks:>6}{r.acierto_pct:>8.0f}%{r.cuota_media:>7.2f}{r.stake_total:>8.0f}"
                f"{r.unidades:>+10.2f}{r.yield_pct:>+8.1f}%{clv:>8}")

    cabecera = f"{'':<20}{'Picks':>6}{'Acierto':>9}{'Cuota':>7}{'Stake':>8}{'Unidades':>10}{'Yield':>9}{'CLV':>8}"
    print("HISTORIAL DE PICKS (todos los liquidados, sin quitar ninguno)\n" + cabecera)
    print(fila("TOTAL", total))
    print("\nPor mes\n" + cabecera)
    for mes, r in sorted(por_mes.items()):
        print(fila(mes, r))
    print("\nPor mercado\n" + cabecera)
    for familia, r in sorted(por_familia.items()):
        print(fila(familia, r))
    if total.picks < 300:
        print(f"\n⚠  Con {total.picks} picks el resultado aún puede ser suerte. El CLV es mejor indicador.")


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

    p = sub.add_parser("sistema", help="El sistema completo: qué apostar hoy y cuánto (o su backtest).")
    opciones_datos(p)
    opciones_seleccion(p)
    p.add_argument("--perfil", choices=list(PERFILES), default="equilibrado",
                   help="conservador, equilibrado (por defecto) o volumen.")
    p.add_argument("--metodo", choices=["kelly", "plano"], default="kelly", help="Cómo calcular el importe.")
    p.add_argument("--kelly", type=float, default=0.25, help="Fracción de Kelly (0.25).")
    p.add_argument("--tope", type=float, default=0.03, help="Máximo del bank por apuesta (0.03).")
    p.add_argument("--plano", type=float, default=0.01, help="Con --metodo plano, parte del bank (0.01).")
    p.add_argument("--proximos", default=os.path.join(DESCARGAS, "proximos.csv"))
    p.add_argument("--dias", type=int, default=3, help="Partidos de los próximos N días (3).")
    p.add_argument("--desde", help="Fecha inicial AAAA-MM-DD (por defecto hoy).")
    p.add_argument("--liga", nargs="+", help="Solo estas ligas.")
    p.add_argument("--backtest", action="store_true", help="Probar los perfiles con el histórico.")
    p.add_argument("--guardar", action="store_true", help="Guardar los picks en el registro.")
    p.set_defaults(func=orden_sistema)

    p = sub.add_parser("configurar", help="Guarda tus preferencias (bank, casas, ligas, perfil...).")
    p.add_argument("--bank", type=float)
    p.add_argument("--casas", nargs="+", metavar="CASA", help=f"Tus casas: {' '.join(CASAS)}.")
    p.add_argument("--ligas", nargs="+", choices=list(LIGAS) + ["todas"])
    p.add_argument("--perfil", choices=list(PERFILES))
    p.add_argument("--metodo", choices=["kelly", "plano"])
    p.add_argument("--kelly", type=float)
    p.add_argument("--tope", type=float)
    p.add_argument("--dias", type=int)
    p.set_defaults(func=orden_configurar)

    p = sub.add_parser("actualizar", help="Cada jornada: baja datos nuevos y liquida los picks jugados.")
    p.add_argument("--ligas", nargs="+", choices=list(LIGAS) + ["todas"])
    p.add_argument("--temporadas", type=int, default=4)
    p.set_defaults(func=orden_actualizar)

    p = sub.add_parser("anotar", help="Añade un pick a mano (p. ej. de córners) al registro.")
    p.add_argument("--fecha", required=True, help="Fecha del partido AAAA-MM-DD.")
    p.add_argument("--local", required=True, help="Como aparece en los datos (mira 'equipos').")
    p.add_argument("--visitante", required=True)
    p.add_argument("--mercado", required=True, help="corners+9.5, goles-2.5, 1, X, 2...")
    p.add_argument("--cuota", type=float, required=True)
    p.add_argument("--casa", default="manual")
    p.add_argument("--stake", type=int, default=5, choices=range(1, 11), metavar="1-10")
    p.add_argument("--liga", help="Código de liga (SP1, E0...).")
    p.add_argument("--tope", type=float, default=0.03)
    p.set_defaults(func=orden_anotar)

    p = sub.add_parser("picks", help="Picks pendientes; con --publicar crea el texto para publicarlos.")
    p.add_argument("--publicar", action="store_true")
    p.set_defaults(func=orden_picks)

    p = sub.add_parser("informe", help="Historial de tus picks: yield, unidades, CLV, por mes y mercado.")
    p.add_argument("--exportar", metavar="ARCHIVO.csv", help="Exportar todos los picks a CSV.")
    p.set_defaults(func=orden_informe)

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

    # Las preferencias guardadas con 'configurar' pasan a ser los valores por defecto.
    prefs = leer_preferencias()
    for subparser in sub.choices.values():
        if subparser.prog.endswith(" configurar"):
            continue
        destinos = {a.dest for a in subparser._actions}
        subparser.set_defaults(**{k: v for k, v in prefs.items() if k in destinos})

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"Error: {e.args[0] if e.args else e}")


if __name__ == "__main__":
    main()
