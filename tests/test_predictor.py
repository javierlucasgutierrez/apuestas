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
from predictor.valor import backtest_valor, oportunidades, precio_justo, probabilidad_consenso


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
        corregidas = aplicar({"Córners +9.5": 0.70, "Córners -9.5": 0.30}, {"corners": [a, b]})
        self.assertAlmostEqual(corregidas["Córners +9.5"], 0.55, places=2)
        self.assertAlmostEqual(corregidas["Córners -9.5"], 0.45, places=2)

    def test_1x2_sigue_sumando_uno(self):
        probs = {"1": 0.60, "X": 0.25, "2": 0.15, "1X": 0.85, "X2": 0.40, "12": 0.75}
        c = aplicar(probs, {"victoria_local": [0.1, 1.2], "victoria_visitante": [0.1, 1.2]})
        self.assertAlmostEqual(c["1"] + c["X"] + c["2"], 1.0)
        self.assertAlmostEqual(c["1X"], c["1"] + c["X"])
        self.assertGreater(c["1"], 0.60)

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

    def test_consenso(self):
        # Dos casas con 1.90 / 1.90: justo 50 %.
        self.assertAlmostEqual(probabilidad_consenso([1.90, 1.90], [1.90, 1.90]), 0.5)
        self.assertLess(probabilidad_consenso([2.0]), 0.5)


if __name__ == "__main__":
    unittest.main()
