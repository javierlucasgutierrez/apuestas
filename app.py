"""Predictor de partidos basado en estadística y probabilidad.

Uso rápido:
    python app.py ejemplo
    python app.py equipos   --datos datos/ejemplo_historico.csv
    python app.py predecir  --datos datos/ejemplo_historico.csv --local "Real Costa" --visitante "CD Ribera" --cuotas 1.9 3.5 4.2
    python app.py jornada   --datos datos/ejemplo_historico.csv --proximos datos/ejemplo_proxima_jornada.csv
    python app.py backtest  --datos datos/ejemplo_historico.csv

Ejecuta `python app.py <orden> -h` para ver todas las opciones.
"""

import argparse
import os
import sys

from predictor.backtest import backtest
from predictor.cuotas import analizar, margen
from predictor.datos import cara_a_cara, cargar_csv, cargar_varios, guardar_csv
from predictor.ejemplo import generar_liga
from predictor.modelo import ModeloPoisson

CARPETA = os.path.dirname(os.path.abspath(__file__))


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def crear_modelo(args) -> ModeloPoisson:
    return ModeloPoisson(vida_media_dias=args.vida_media, regularizacion=args.regularizacion,
                         peso_h2h=args.peso_h2h)


def opciones_modelo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--datos", nargs="+", required=True,
                        help="Uno o varios CSV con el histórico de partidos (p. ej. varias temporadas).")
    parser.add_argument("--vida-media", type=float, default=180,
                        help="Días tras los que un partido cuenta la mitad (por defecto 180).")
    parser.add_argument("--regularizacion", type=float, default=3.0,
                        help="Cuánto se acerca a la media a los equipos con pocos datos (por defecto 3).")
    parser.add_argument("--peso-h2h", type=float, default=0.0,
                        help="Peso de los enfrentamientos directos entre 0 y 1 (por defecto 0).")


def opciones_apuesta(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--umbral", type=float, default=0.05,
                        help="Valor esperado mínimo para recomendar apuesta (0.05 = +5 %%).")
    parser.add_argument("--prob-minima", type=float, default=0.20,
                        help="No apostar a selecciones con menos probabilidad que esta.")
    parser.add_argument("--cuota-maxima", type=float, default=6.0, help="No apostar a cuotas mayores.")
    parser.add_argument("--kelly", type=float, default=0.25, help="Fracción de Kelly (por defecto 1/4).")
    parser.add_argument("--tope", type=float, default=0.03,
                        help="Máximo del bank en una sola apuesta (por defecto 3 %%).")
    parser.add_argument("--bank", type=float, default=100.0, help="Tu bank en euros (por defecto 100).")


# ------------------------------------------------------------------- órdenes
def orden_ejemplo(args) -> None:
    jugados, proxima = generar_liga()
    carpeta = os.path.join(CARPETA, "datos")
    os.makedirs(carpeta, exist_ok=True)
    historico = os.path.join(carpeta, "ejemplo_historico.csv")
    proximos = os.path.join(carpeta, "ejemplo_proxima_jornada.csv")
    guardar_csv(historico, jugados)
    guardar_csv(proximos, proxima)
    print(f"Liga ficticia creada: {len(jugados)} partidos jugados y {len(proxima)} por jugar.")
    print(f"  {os.path.relpath(historico)}\n  {os.path.relpath(proximos)}")


def orden_equipos(args) -> None:
    partidos = cargar_varios(args.datos)
    modelo = crear_modelo(args).ajustar(partidos)
    print(f"Modelo ajustado con datos hasta {modelo.fecha_ajuste:%d/%m/%Y}")
    print(f"Goles de media por equipo: {modelo.base:.2f} · ventaja de jugar en casa: x{modelo.ventaja_campo:.2f}\n")
    print(f"{'#':>2}  {'Equipo':<24}{'Ataque':>8}{'Defensa':>9}{'Índice':>8}{'PJ':>5}")
    for i, (t, a, d, indice) in enumerate(modelo.clasificacion_fuerzas(), 1):
        print(f"{i:>2}  {t:<24}{a:>8.2f}{d:>9.2f}{indice:>+8.2f}{modelo.partidos_equipo[t]:>5}")
    print("\nAtaque > 1: marca más que la media · Defensa < 1: encaja menos que la media.")
    print("Índice: diferencia de goles esperada contra un rival medio en campo neutral.")


def mostrar_prediccion(pred, modelo, args, cuotas_1x2=None, cuotas_goles=None) -> None:
    print(f"\n{pred.local} vs {pred.visitante}")
    print("-" * 60)
    print(f"Goles esperados: {pred.goles_local:.2f} - {pred.goles_visitante:.2f}")
    print(f"1X2:        1 {pct(pred.prob_1)}   X {pct(pred.prob_x)}   2 {pct(pred.prob_2)}")
    print(f"Goles:      +2.5 {pct(pred.prob_mas25)}   -2.5 {pct(pred.prob_menos25)}")
    print(f"Ambos marcan: sí {pct(pred.prob_ambos_si)}   no {pct(pred.prob_ambos_no)}")
    print("Marcadores más probables: " + ", ".join(f"{m} ({pct(p).strip()})" for m, p in pred.marcadores))

    h2h = cara_a_cara(modelo.historial, pred.local, pred.visitante)
    if h2h.n:
        print(f"Cara a cara (últimos {h2h.n}): {pred.local} {h2h.victorias_a} · empates {h2h.empates} · "
              f"{pred.visitante} {h2h.victorias_b} | goles {h2h.goles_a:.1f}-{h2h.goles_b:.1f} | "
              f"+2.5 {pct(h2h.pct_mas25).strip()} | ambos marcan {pct(h2h.pct_ambos_marcan).strip()}")
    for aviso in pred.avisos:
        print(f"⚠  {aviso}")

    selecciones = analizar(pred, cuotas_1x2, cuotas_goles, umbral=args.umbral, prob_minima=args.prob_minima,
                           cuota_maxima=args.cuota_maxima, fraccion_kelly=args.kelly, tope_kelly=args.tope)
    if not selecciones:
        print("(Sin cuotas: solo probabilidades. Añade --cuotas para buscar valor.)")
        return
    if cuotas_1x2 and all(cuotas_1x2):
        print(f"\nMargen de la casa en 1X2: {pct(margen(cuotas_1x2)).strip()}")
    print(f"{'Apuesta':<9}{'Cuota':>7}{'Justa':>7}{'Modelo':>8}{'Casa':>8}{'Valor':>8}   Apostar")
    for o, es_valor in selecciones:
        consejo = f"SÍ · {args.bank * o.stake:.2f} € ({pct(o.stake).strip()} del bank)" if es_valor else "no"
        if pred.avisos and es_valor:
            consejo = "dudoso (pocos datos)"
        print(f"{o.mercado:<9}{o.cuota:>7.2f}{o.cuota_justa:>7.2f}{pct(o.prob_modelo):>8}"
              f"{pct(o.prob_mercado):>8}{100 * o.valor:>+7.1f}%   {consejo}")


def orden_predecir(args) -> None:
    partidos = cargar_varios(args.datos)
    modelo = crear_modelo(args).ajustar(partidos)
    pred = modelo.predecir(args.local, args.visitante)
    mostrar_prediccion(pred, modelo, args, args.cuotas, args.cuotas_goles)


def orden_jornada(args) -> None:
    partidos = cargar_varios(args.datos)
    proximos = [p for p in cargar_csv(args.proximos) if not p.jugado]
    if not proximos:
        print("No hay partidos sin resultado en", args.proximos)
        return
    modelo = crear_modelo(args).ajustar(partidos, hasta=min(p.fecha for p in proximos))
    resumen = []
    for p in proximos:
        try:
            pred = modelo.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError as e:
            print(f"\n{p.local} vs {p.visitante}: {e.args[0]}")
            continue
        cuotas_1x2 = [p.cuota_1, p.cuota_x, p.cuota_2]
        cuotas_goles = [p.cuota_mas25, p.cuota_menos25]
        mostrar_prediccion(pred, modelo, args, cuotas_1x2, cuotas_goles)
        if not pred.avisos:
            for o, es_valor in analizar(pred, cuotas_1x2, cuotas_goles, umbral=args.umbral,
                                        prob_minima=args.prob_minima, cuota_maxima=args.cuota_maxima,
                                        fraccion_kelly=args.kelly, tope_kelly=args.tope):
                if es_valor:
                    resumen.append((p, o))

    print("\n" + "=" * 60)
    print("RESUMEN: apuestas con valor según el modelo")
    print("=" * 60)
    if not resumen:
        print("Ninguna. No apostar también es una decisión correcta.")
    for p, o in sorted(resumen, key=lambda x: -x[1].valor):
        print(f"{p.fecha:%d/%m}  {p.local} - {p.visitante}: {o.mercado} @ {o.cuota:.2f} "
              f"(valor {100 * o.valor:+.1f}%) → {args.bank * o.stake:.2f} €")


def orden_backtest(args) -> None:
    partidos = cargar_varios(args.datos)
    print("Calculando (el modelo se reajusta cada semana con lo que se sabía en ese momento)...")
    inf = backtest(partidos, crear_modelo=lambda: crear_modelo(args),
                   partidos_entrenamiento=args.entrenamiento, umbral=args.umbral, prob_minima=args.prob_minima,
                   cuota_maxima=args.cuota_maxima, fraccion_kelly=args.kelly, tope_kelly=args.tope,
                   bank_inicial=args.bank)
    print(f"\nPartidos evaluados: {inf.partidos_evaluados} (con cuotas 1X2: {inf.partidos_con_cuotas})")
    if inf.partidos_con_cuotas:
        print("\nPrecisión de las probabilidades en 1X2 (más bajo = mejor):")
        print(f"  Log-loss  modelo {inf.logloss_modelo:.4f} · casa {inf.logloss_mercado:.4f}")
        print(f"  Brier     modelo {inf.brier_modelo:.4f} · casa {inf.brier_mercado:.4f}")
        if inf.logloss_modelo > inf.logloss_mercado:
            print("  → La casa predice mejor que el modelo en general (lo normal).")
        else:
            print("  → El modelo predice mejor que la casa en general.")
    print(f"\nApuestas de valor: {len(inf.apuestas)} · aciertos {inf.aciertos_pct:.1f}% · cuota media {inf.cuota_media:.2f}")
    print(f"Apostando 1 € fijo a cada una: {inf.beneficio:+.2f} € · yield {inf.yield_pct:+.2f}%")
    for mercado, (n, b) in sorted(inf.por_mercado().items()):
        print(f"   {mercado:<6} {n:>4} apuestas  {b:+8.2f} €  ({100 * b / n:+.1f}%)")
    print(f"Con Kelly fraccionado: bank {inf.bank_inicial:.2f} € → {inf.bank_final:.2f} € "
          f"(peor caída {100 * inf.caida_maxima:.1f}%)")
    if len(inf.apuestas) < 300:
        print("\n⚠  Menos de 300 apuestas: el resultado puede deberse a la suerte. Usa más temporadas.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Predictor estadístico de partidos y apuestas de valor.")
    sub = parser.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("ejemplo", help="Crea una liga ficticia para probar la herramienta.")
    p.set_defaults(func=orden_ejemplo)

    p = sub.add_parser("equipos", help="Ranking de fuerza de ataque y defensa de cada equipo.")
    opciones_modelo(p)
    p.set_defaults(func=orden_equipos)

    p = sub.add_parser("predecir", help="Probabilidades de un partido y, con cuotas, si hay valor.")
    opciones_modelo(p)
    opciones_apuesta(p)
    p.add_argument("--local", required=True)
    p.add_argument("--visitante", required=True)
    p.add_argument("--cuotas", nargs=3, type=float, metavar=("C1", "CX", "C2"), help="Cuotas 1 X 2.")
    p.add_argument("--cuotas-goles", nargs=2, type=float, metavar=("MAS25", "MENOS25"),
                   help="Cuotas de más y menos de 2,5 goles.")
    p.set_defaults(func=orden_predecir)

    p = sub.add_parser("jornada", help="Analiza todos los partidos de un CSV de próximos partidos.")
    opciones_modelo(p)
    opciones_apuesta(p)
    p.add_argument("--proximos", required=True, help="CSV con los partidos por jugar y sus cuotas.")
    p.set_defaults(func=orden_jornada)

    p = sub.add_parser("backtest", help="Comprueba cuánto habría ganado o perdido la estrategia en el pasado.")
    opciones_modelo(p)
    opciones_apuesta(p)
    p.add_argument("--entrenamiento", type=int, default=150,
                   help="Partidos iniciales que solo sirven para aprender (por defecto 150).")
    p.set_defaults(func=orden_backtest)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"Error: {e.args[0] if e.args else e}")


if __name__ == "__main__":
    main()
