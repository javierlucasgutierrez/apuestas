import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predictor.backtest import backtest
from predictor.calibracion import ajustar_platt, aplicar
from predictor.cuotas import kelly, margen, normalizar_mercado, probabilidades_mercado, seleccionar, valor_esperado
from predictor.datos import Partido, cara_a_cara, cargar_csv
from predictor.descargar import codigo_temporada, temporada_actual
from predictor.ejemplo import generar_liga
from predictor.mercados import Predictor, acierta
from predictor.modelo import binomial_negativa
from predictor.valor import (backtest_valor, beneficio_handicap, oportunidades, precio_justo,
                             probabilidad_consenso)


def csv_temporal(contenido: str) -> list[Partido]:
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(contenido)
    try:
        return cargar_csv(f.name)
    finally:
        os.unlink(f.name)


class TestCuotas(unittest.TestCase):
    def test_margen_y_probabilidades(self):
        cuotas = [2.0, 3.4, 3.8]
        self.assertAlmostEqual(margen(cuotas), 1 / 2 + 1 / 3.4 + 1 / 3.8 - 1)
        self.assertAlmostEqual(sum(probabilidades_mercado(cuotas)), 1.0)

    def test_valor_y_kelly(self):
        self.assertAlmostEqual(valor_esperado(0.55, 2.0), 0.10)
        self.assertAlmostEqual(kelly(0.55, 2.0, fraccion=1, tope=1), 0.10)
        self.assertAlmostEqual(kelly(0.55, 2.0, fraccion=0.25, tope=0.02), 0.02)
        self.assertEqual(kelly(0.40, 2.0), 0.0)

    def test_normalizar_mercado(self):
        self.assertEqual(normalizar_mercado("Córners +9,5"), "Córners +9.5")
        self.assertEqual(normalizar_mercado("corners-10.5"), "Córners -10.5")
        self.assertEqual(normalizar_mercado("goles +2.5"), "Goles +2.5")
        self.assertEqual(normalizar_mercado("x2"), "X2")
        self.assertEqual(normalizar_mercado("ambos si"), "Ambos marcan: sí")
        with self.assertRaises(ValueError):
            normalizar_mercado("tarjetas +4.5")

    def test_cuota_minima(self):
        probs = {"Córners +9.5": 0.60, "Goles +2.5": 0.80, "1": 0.40}
        s = {x.mercado: x for x in seleccionar(probs, {"Goles +2.5": 1.55}, cuota_min=1.5, umbral=0.05,
                                                prob_minima=0.5)}
        self.assertNotIn("1", s)
        self.assertAlmostEqual(s["Córners +9.5"].cuota_minima, 1.05 / 0.60)
        self.assertEqual(s["Goles +2.5"].cuota_minima, 1.5)
        self.assertTrue(s["Goles +2.5"].recomendada)
        self.assertFalse(s["Córners +9.5"].recomendada)


class TestDatos(unittest.TestCase):
    def test_formato_football_data(self):
        partidos = csv_temporal(
            "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HC,AC,B365H,B365D,B365A,B365>2.5,B365<2.5\n"
            "SP1,15/08/2025,Betis,Elche,2,1,7,3,1.80,3.60,4.50,1.90,1.95\n"
            "SP1,16/08/25,Elche,Betis,,,,,2.9,3.2,2.5,,\n")
        self.assertEqual(len(partidos), 2)
        p = partidos[0]
        self.assertEqual((p.liga, p.fecha, p.local, p.goles_local, p.corners_local, p.cuota_x, p.cuota_menos25),
                         ("SP1", date(2025, 8, 15), "Betis", 2, 7, 3.6, 1.95))
        self.assertEqual(p.resultado, "1")
        self.assertFalse(partidos[1].jugado)
        self.assertFalse(partidos[1].con_corners)

    def test_formato_propio_punto_y_coma(self):
        p = csv_temporal("fecha;local;visitante;goles_local;goles_visitante;cuota_1;cuota_x;cuota_2\n"
                         "2025-08-15;A;B;0;0;2,10;3,30;3,40\n")[0]
        self.assertEqual((p.cuota_1, p.resultado), (2.1, "X"))

    def test_acierta(self):
        p = Partido(date(2025, 1, 1), "A", "B", 2, 1, corners_local=6, corners_visitante=4)
        self.assertTrue(acierta("Goles +2.5", p))
        self.assertFalse(acierta("Goles -2.5", p))
        self.assertTrue(acierta("Córners +9.5", p))
        self.assertFalse(acierta("Córners +10.5", p))
        self.assertTrue(acierta("1X", p))
        self.assertFalse(acierta("X2", p))
        self.assertTrue(acierta("Ambos marcan: sí", p))

    def test_temporadas(self):
        self.assertEqual(temporada_actual(date(2026, 10, 28)), 2026)
        self.assertEqual(temporada_actual(date(2027, 3, 1)), 2026)
        self.assertEqual(codigo_temporada(2026), "2627")
        self.assertEqual(codigo_temporada(1999), "9900")


class TestModelo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jugados, cls.proxima = generar_liga()
        cls.predictor = Predictor().ajustar(cls.jugados)

    def test_probabilidades_coherentes(self):
        pred = self.predictor.predecir(self.proxima[0].local, self.proxima[0].visitante)
        pr = pred.probs
        self.assertAlmostEqual(pr["1"] + pr["X"] + pr["2"], 1.0)
        self.assertAlmostEqual(pr["Goles +2.5"] + pr["Goles -2.5"], 1.0)
        self.assertAlmostEqual(pr["Córners +9.5"] + pr["Córners -9.5"], 1.0)
        self.assertGreater(pr["Córners +8.5"], pr["Córners +9.5"])
        self.assertGreater(pred.corners_local, 0)

    def test_parametros_razonables(self):
        goles = self.predictor.goles["EJ"]
        corners = self.predictor.corners["EJ"]
        self.assertTrue(1.05 < goles.ventaja_campo < 1.45)
        self.assertTrue(-0.25 <= goles.rho <= 0.15)
        self.assertTrue(8 < corners.base * 2 * corners.ventaja_campo ** 0.5 < 12)
        self.assertGreater(corners.dispersion, 1.0)  # los córners varían más que un Poisson

    def test_binomial_negativa(self):
        dist = [binomial_negativa(k, 10, 1.5) for k in range(80)]
        media = sum(k * p for k, p in enumerate(dist))
        varianza = sum((k - media) ** 2 * p for k, p in enumerate(dist))
        self.assertAlmostEqual(sum(dist), 1.0, places=6)
        self.assertAlmostEqual(media, 10, places=4)
        self.assertAlmostEqual(varianza, 15, places=3)

    def test_nombre_sin_mayusculas_y_equipo_desconocido(self):
        pred = self.predictor.predecir("real costa", "cd ribera")
        self.assertEqual(pred.local, "Real Costa")
        with self.assertRaises(KeyError):
            self.predictor.predecir("Equipo Inventado", "CD Ribera")

    def test_no_usa_partidos_futuros(self):
        corte = self.jugados[500].fecha
        predictor = Predictor().ajustar(self.jugados, hasta=corte)
        self.assertTrue(all(p.fecha < corte for p in predictor.historial))
        self.assertLess(predictor.goles["EJ"].fecha_ajuste, self.jugados[-1].fecha)

    def test_cara_a_cara(self):
        a, b = self.jugados[0].local, self.jugados[0].visitante
        h2h = cara_a_cara(self.jugados, a, b)
        self.assertGreater(h2h.n, 0)
        self.assertEqual(h2h.victorias_a + h2h.empates + h2h.victorias_b, h2h.n)
        self.assertIsNotNone(h2h.corners_medios)

    def test_backtest(self):
        informe = backtest(self.jugados[:700], reajuste_dias=28)
        self.assertGreater(informe.partidos, 0)
        self.assertIn("Córners más/menos", informe.calibracion)


class TestCalibracion(unittest.TestCase):
    def test_corrige_un_modelo_demasiado_seguro(self):
        # El "modelo" dice 70 % pero solo pasa el 55 % de las veces.
        pares = [(0.70, i % 20 < 11) for i in range(2000)] + [(0.30, i % 20 < 9) for i in range(2000)]
        a, b = ajustar_platt(pares, suavizado=0.0)
        corregidas = aplicar({"Córners +9.5": 0.70, "Córners -9.5": 0.30}, {"corners 9.5": [a, b]})
        self.assertAlmostEqual(corregidas["Córners +9.5"], 0.55, places=2)
        self.assertAlmostEqual(corregidas["Córners -9.5"], 0.45, places=2)

    def test_1x2_sigue_sumando_uno(self):
        probs = {"1": 0.60, "X": 0.25, "2": 0.15, "1X": 0.85, "X2": 0.40, "12": 0.75}
        c = aplicar(probs, {"victoria_local": [0.1, 1.2], "victoria_visitante": [0.1, 1.2]})
        self.assertAlmostEqual(c["1"] + c["X"] + c["2"], 1.0)
        self.assertAlmostEqual(c["1X"], c["1"] + c["X"])
        self.assertGreater(c["1"], 0.60)

    def test_cada_linea_tiene_su_grupo(self):
        from predictor.calibracion import grupo_de
        self.assertEqual(grupo_de("Goles +3.5"), "goles 3.5")
        self.assertEqual(grupo_de("Córners +9.5"), "corners 9.5")
        self.assertIsNone(grupo_de("Goles -3.5"))  # el lado "menos" es el complementario
        c = aplicar({"Goles +1.5": 0.7, "Goles -1.5": 0.3, "Goles +3.5": 0.4, "Goles -3.5": 0.6},
                    {"goles 3.5": [-0.3, 1.0]})
        self.assertEqual(c["Goles +1.5"], 0.7)
        self.assertLess(c["Goles +3.5"], 0.4)
        self.assertAlmostEqual(c["Goles +3.5"] + c["Goles -3.5"], 1.0)

    def test_sin_calibrador_no_cambia(self):
        probs = {"1": 0.5, "Goles +2.5": 0.6, "Goles -2.5": 0.4}
        self.assertEqual(aplicar(probs, {}), probs)


class TestValorMercado(unittest.TestCase):
    FILA = {"Div": "SP1", "Date": "01/09/2025", "HomeTeam": "Betis", "AwayTeam": "Elche",
            "FTHG": "0", "FTAG": "0", "_archivo": "SP1_2526.csv",
            # Pinnacle: casi sin margen. Bet365 paga de más en el empate.
            "PSH": "1.90", "PSD": "3.60", "PSA": "4.60", "B365H": "1.85", "B365D": "3.90", "B365A": "4.40",
            "PSCH": "1.95", "PSCD": "3.40", "PSCA": "4.60"}

    def test_precio_justo(self):
        probs, ref = precio_justo(self.FILA, "1X2")
        self.assertEqual(ref, "PS")
        self.assertAlmostEqual(sum(probs), 1.0)

    def test_detecta_la_cuota_que_paga_de_mas(self):
        ops = oportunidades(self.FILA, ["B365"], umbral=0.02)
        self.assertEqual(len(ops), 1)
        o = ops[0]
        self.assertEqual((o.mercado, o.casa, o.cuota, o.resultado), ("X", "B365", 3.90, True))
        self.assertGreater(o.valor, 0.02)
        self.assertGreater(o.clv, 0)  # la cuota de cierre del empate bajó: se cogió mejor precio

    def test_sin_valor_no_hay_oportunidad(self):
        self.assertEqual(oportunidades(self.FILA, ["B365"], umbral=0.20), [])

    def test_backtest_valor(self):
        inf = backtest_valor([self.FILA], ["B365"])
        self.assertEqual(inf.total["1X2"].n, 1)
        self.assertAlmostEqual(inf.total["1X2"].beneficio, 2.90)

    def test_handicap_asiatico(self):
        # Local -0.5: gana si gana el partido.
        self.assertAlmostEqual(beneficio_handicap(1, -0.5, 2.0), 1.0)
        self.assertAlmostEqual(beneficio_handicap(0, -0.5, 2.0), -1.0)
        # Línea 0: empate = se devuelve el dinero.
        self.assertAlmostEqual(beneficio_handicap(0, 0, 2.0), 0.0)
        # -0.25 con empate: medio perdido; +0.25 con empate: medio ganado.
        self.assertAlmostEqual(beneficio_handicap(0, -0.25, 2.0), -0.5)
        self.assertAlmostEqual(beneficio_handicap(0, 0.25, 2.0), 0.5)
        # -1.0 ganando por 1: se devuelve; -0.75 ganando por 1: medio ganado.
        self.assertAlmostEqual(beneficio_handicap(1, -1.0, 1.9), 0.0)
        self.assertAlmostEqual(beneficio_handicap(1, -0.75, 1.9), 0.45)

    def test_oportunidad_handicap(self):
        fila = dict(self.FILA, AHh="-0.25", PAHH="1.95", PAHA="1.95", B365AHH="2.10", B365AHA="1.80")
        ops = [o for o in oportunidades(fila, ["B365"], umbral=0.02) if o.familia == "Hándicap asiático"]
        self.assertEqual(len(ops), 1)
        self.assertEqual((ops[0].mercado, ops[0].cuota), ("Hándicap local -0.25", 2.10))
        self.assertAlmostEqual(ops[0].beneficio, -0.5)  # 0-0: medio perdido

    def test_consenso(self):
        # Dos casas con 1.90 / 1.90: justo 50 %.
        self.assertAlmostEqual(probabilidad_consenso([1.90, 1.90], [1.90, 1.90]), 0.5)
        self.assertLess(probabilidad_consenso([2.0]), 0.5)


class TestSistema(unittest.TestCase):
    def op(self, dia, cuota, prob, beneficio):
        from predictor.valor import Oportunidad
        return Oportunidad(date(2025, 9, dia), "SP1", "A", "B", "1", "B365", cuota, prob, "PS",
                           familia="1X2", beneficio=beneficio)

    def test_stake(self):
        from predictor.sistema import stake
        o = self.op(1, 2.0, 0.52, 1.0)  # Kelly completo: 4 %
        self.assertAlmostEqual(stake(o, "kelly", fraccion_kelly=0.25), 0.01)
        self.assertAlmostEqual(stake(o, "kelly", fraccion_kelly=1.0, tope=0.03), 0.03)
        self.assertAlmostEqual(stake(o, "plano", plano=0.02), 0.02)

    def test_simular_bank(self):
        from predictor.sistema import simular_bank
        ops = [self.op(1, 2.0, 0.6, 1.0), self.op(1, 2.0, 0.6, -1.0), self.op(2, 2.0, 0.6, 1.0)]
        sim = simular_bank(ops, 1000, "plano", plano=0.10)
        # Día 1: +100 y -100 sobre 1000 → 1000. Día 2: +100 → 1100.
        self.assertAlmostEqual(sim.bank_final, 1100)
        self.assertEqual(sim.apuestas, 3)


class TestRegistro(unittest.TestCase):
    def test_guardar_liquidar_y_resumir(self):
        from predictor.registro import Registro, descripcion, estado_de, resumir, stake_10
        from predictor.valor import Oportunidad, liquidar
        with tempfile.TemporaryDirectory() as carpeta:
            r = Registro(os.path.join(carpeta, "prueba.db"))
            o = Oportunidad(date(2025, 9, 1), "SP1", "Betis", "Elche", "Hándicap local -0.25", "B365", 2.10,
                            0.5, "PS", familia="Hándicap asiático")
            self.assertTrue(r.guardar(o, 0.015, "equilibrado"))
            self.assertFalse(r.guardar(o, 0.015, "equilibrado"))  # no se duplica
            fila = {"Date": "01/09/2025", "HomeTeam": "Betis", "AwayTeam": "Elche", "FTHG": "1", "FTAG": "1"}
            hechos = r.liquidar([fila])
            self.assertEqual(len(hechos), 1)
            p = hechos[0]
            self.assertEqual((p.estado, p.stake), ("medio perdida", 5))
            self.assertAlmostEqual(p.unidades, -2.5)
            total, por_mes, _ = resumir(r.picks())
            self.assertEqual((total.picks, list(por_mes)), (1, ["2025-09"]))
            self.assertEqual(descripcion(p), "Betis -0.25 (hándicap asiático)")
            r.cerrar()
        self.assertEqual(stake_10(0.03), 10)
        self.assertEqual(stake_10(0.001), 1)
        self.assertEqual(estado_de(1.1, 2.1), "ganada")
        self.assertEqual(estado_de(0.0, 2.1), "nula")
        self.assertAlmostEqual(liquidar({"FTHG": "2", "FTAG": "1", "HC": "7", "AC": "2"}, "Córners -9.5", 1.9)[0], 0.9)
        self.assertEqual(liquidar({"FTHG": "2", "FTAG": "1", "HC": "7", "AC": "4"}, "Córners -9.5", 1.9)[0], -1.0)


class TestCuotasVivo(unittest.TestCase):
    EVENTO = {
        "id": "abc", "sport_key": "soccer_spain_la_liga", "commence_time": "2026-10-31T19:00:00Z",
        "home_team": "Real Betis", "away_team": "Sevilla",
        "bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "markets": [
                {"key": "h2h", "outcomes": [{"name": "Real Betis", "price": 2.0}, {"name": "Sevilla", "price": 4.0},
                                            {"name": "Draw", "price": 3.6}]},
                {"key": "spreads", "outcomes": [{"name": "Real Betis", "price": 1.95, "point": -0.25},
                                                {"name": "Sevilla", "price": 1.95, "point": 0.25}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": 2.0, "point": 2.5},
                                               {"name": "Under", "price": 1.9, "point": 2.5}]}]},
            {"key": "unibet_eu", "title": "Unibet", "markets": [
                {"key": "h2h", "outcomes": [{"name": "Real Betis", "price": 1.95}, {"name": "Sevilla", "price": 3.8},
                                            {"name": "Draw", "price": 3.95}]},
                {"key": "spreads", "outcomes": [{"name": "Real Betis", "price": 2.10, "point": -0.25},
                                                {"name": "Sevilla", "price": 1.75, "point": 0.25}]}]},
        ]}

    def test_convierte_a_columnas_de_football_data(self):
        from predictor.cuotas_vivo import evento_a_fila
        f = evento_a_fila(self.EVENTO, "SP1")
        self.assertEqual((f["Date"], f["Time"], f["HomeTeam"]), ("31/10/2026", "20:00", "Real Betis"))
        self.assertEqual((f["PSH"], f["PSD"], f["P>2.5"], f["AHh"], f["PAHH"]), (2.0, 3.6, 2.0, -0.25, 1.95))
        self.assertEqual((f["MaxD"], f["MaxAHH"]), (3.95, 2.10))  # Pinnacle no cuenta para la mejor cuota
        self.assertNotIn("Max>2.5", f)

    def test_detecta_valor_con_cuotas_en_vivo(self):
        from predictor.cuotas_vivo import evento_a_fila
        ops = {o.familia: o for o in oportunidades(evento_a_fila(self.EVENTO, "SP1"), ["Max"], umbral=0.02)}
        self.assertEqual((ops["1X2"].mercado, ops["1X2"].cuota), ("X", 3.95))
        self.assertEqual((ops["Hándicap asiático"].mercado, ops["Hándicap asiático"].cuota),
                         ("Hándicap local -0.25", 2.10))


class TestGolesAsiaticos(unittest.TestCase):
    def test_como_se_paga(self):
        from predictor.valor import beneficio_total_asiatico as b
        # Más de 3: con 3 goles se devuelve, con 4 se gana, con 2 se pierde.
        self.assertAlmostEqual(b(3, 3.0, True, 2.0), 0.0)
        self.assertAlmostEqual(b(4, 3.0, True, 2.0), 1.0)
        self.assertAlmostEqual(b(2, 3.0, True, 2.0), -1.0)
        # Más de 2,75: con 3 goles, media ganada y media devuelta.
        self.assertAlmostEqual(b(3, 2.75, True, 2.0), 0.5)
        # Más de 2,25: con 2 goles, media perdida.
        self.assertAlmostEqual(b(2, 2.25, True, 2.0), -0.5)
        # Menos de 2,75: con 3 goles, media perdida; con 2, ganada.
        self.assertAlmostEqual(b(3, 2.75, False, 1.9), -0.5)
        self.assertAlmostEqual(b(2, 2.75, False, 1.9), 0.9)

    def test_desde_cuotas_en_vivo(self):
        from predictor.cuotas_vivo import evento_a_fila
        from predictor.registro import descripcion
        from predictor.valor import liquidar
        evento = {"commence_time": "2026-10-31T19:00:00Z", "home_team": "A", "away_team": "B", "bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "markets": [
                {"key": "totals", "outcomes": [{"name": "Over", "price": 1.95, "point": 2.75},
                                               {"name": "Under", "price": 1.95, "point": 2.75}]}]},
            {"key": "unibet_eu", "title": "Unibet", "markets": [
                {"key": "totals", "outcomes": [{"name": "Over", "price": 2.08, "point": 2.75},
                                               {"name": "Under", "price": 1.80, "point": 2.75},
                                               {"name": "Over", "price": 1.70, "point": 2.5}]}]}]}
        fila = evento_a_fila(evento, "SP1")
        self.assertEqual((fila["TL"], fila["PTLO"], fila["MaxTLO"]), (2.75, 1.95, 2.08))
        ops = [o for o in oportunidades(fila, ["Max"], umbral=0.02) if o.familia == "Goles asiático"]
        self.assertEqual((len(ops), ops[0].mercado, ops[0].cuota), (1, "Goles asiático +2.75", 2.08))
        self.assertEqual(descripcion(ops[0]), "Más de 2,75 goles (asiático)")
        self.assertAlmostEqual(liquidar({"FTHG": "2", "FTAG": "1"}, ops[0].mercado, 2.08)[0], 0.54)


class TestPrimeraParte(unittest.TestCase):
    def test_probabilidades_y_liquidacion(self):
        from predictor.mercados import acierta
        from predictor.registro import descripcion
        from predictor.valor import Oportunidad, liquidar
        p = Partido(date(2025, 1, 1), "A", "B", 2, 1, goles_local_1t=1, goles_visitante_1t=0)
        self.assertTrue(acierta("1ª parte goles +0.5", p))
        self.assertFalse(acierta("1ª parte goles +1.5", p))
        self.assertTrue(acierta("1ª parte goles -1.5", p))
        self.assertAlmostEqual(liquidar({"FTHG": "2", "FTAG": "1", "HTHG": "0", "HTAG": "0"},
                                        "1ª parte goles +0.5", 1.7)[0], -1.0)
        o = Oportunidad(date(2025, 1, 1), "", "A", "B", "1ª parte goles -1.5", "", 1.7, 0.6, "")
        self.assertEqual(descripcion(o), "Menos de 1,5 goles en la 1ª parte")

    def test_el_modelo_da_la_primera_parte(self):
        jugados, proxima = generar_liga()
        for i, p in enumerate(jugados):  # la liga de ejemplo no trae descanso: se inventa uno coherente
            p.goles_local_1t, p.goles_visitante_1t = p.goles_local // 2, p.goles_visitante // 2 + i % 2 * 0
        pred = Predictor().ajustar(jugados).predecir(proxima[0].local, proxima[0].visitante)
        self.assertAlmostEqual(pred.probs["1ª parte goles +0.5"] + pred.probs["1ª parte goles -0.5"], 1.0)
        self.assertGreater(pred.probs["1ª parte goles +0.5"], pred.probs["1ª parte goles +1.5"])
        self.assertLess(pred.probs["1ª parte goles +0.5"], pred.probs["Goles +0.5"] if "Goles +0.5" in pred.probs else 1)


class TestNombresDeEquipos(unittest.TestCase):
    def test_empareja_nombres_de_otras_webs(self):
        from predictor.modelo import emparejar_equipo
        liga = ["Real Madrid", "Ath Madrid", "Betis", "Ath Bilbao", "Sociedad", "Espanol", "Vallecano"]
        self.assertEqual(emparejar_equipo("Atlético Madrid", liga), "Ath Madrid")  # ¡no el Real Madrid!
        self.assertEqual(emparejar_equipo("Real Betis", liga), "Betis")
        self.assertEqual(emparejar_equipo("Athletic Club", liga), "Ath Bilbao")
        self.assertEqual(emparejar_equipo("Espanyol", liga), "Espanol")
        self.assertEqual(emparejar_equipo("Rayo Vallecano", liga), "Vallecano")
        self.assertIsNone(emparejar_equipo("Equipo Inventado", liga))
        self.assertEqual(emparejar_equipo("Wolverhampton Wanderers", ["Wolves", "Man City"]), "Wolves")
        self.assertEqual(emparejar_equipo("Inter Milan", ["Inter", "Milan"]), "Inter")
        # Nombres del calendario (fixturedownload.com)
        self.assertEqual(emparejar_equipo("RCD Espanyol de Barcelona", ["Barcelona", "Espanol"]), "Espanol")
        self.assertEqual(emparejar_equipo("Spurs", ["Tottenham", "Man United"]), "Tottenham")
        self.assertEqual(emparejar_equipo("Man Utd", ["Man City", "Man United"]), "Man United")


class TestCalendario(unittest.TestCase):
    def test_solo_partidos_sin_jugar_y_en_hora_de_espana(self):
        from predictor.calendario import partidos_feed
        feed = [{"DateUtc": "2026-10-31 19:00:00Z", "HomeTeam": "Chelsea", "AwayTeam": "Man Utd", "HomeTeamScore": None},
                {"DateUtc": "2026-10-24 14:00:00Z", "HomeTeam": "Spurs", "AwayTeam": "Leeds", "HomeTeamScore": 2},
                {"DateUtc": "2026-12-31 23:30:00Z", "HomeTeam": "Wolves", "AwayTeam": "Fulham", "HomeTeamScore": None}]
        filas = partidos_feed(feed, "E0")
        self.assertEqual(len(filas), 2)
        self.assertEqual((filas[0]["Date"], filas[0]["Time"], filas[0]["Div"]), ("31/10/2026", "20:00", "E0"))
        self.assertEqual(filas[1]["Date"], "01/01/2027")  # medianoche y media en España: ya es otro día


if __name__ == "__main__":
    unittest.main()
