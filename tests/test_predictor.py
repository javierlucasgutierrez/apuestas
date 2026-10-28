import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predictor.backtest import backtest
from predictor.cuotas import kelly, margen, probabilidades_mercado, valor_esperado
from predictor.datos import cara_a_cara, cargar_csv
from predictor.ejemplo import generar_liga
from predictor.modelo import ModeloPoisson


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


class TestDatos(unittest.TestCase):
    def test_formato_football_data(self):
        contenido = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A,B365>2.5,B365<2.5\n"
                     "SP1,15/08/2025,Betis,Elche,2,1,1.80,3.60,4.50,1.90,1.95\n"
                     "SP1,16/08/25,Elche,Betis,,,2.9,3.2,2.5,,\n")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(contenido)
        try:
            partidos = cargar_csv(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(len(partidos), 2)
        p = partidos[0]
        self.assertEqual((p.fecha, p.local, p.goles_local, p.cuota_x, p.cuota_menos25),
                         (date(2025, 8, 15), "Betis", 2, 3.6, 1.95))
        self.assertEqual(p.resultado, "1")
        self.assertFalse(partidos[1].jugado)

    def test_formato_propio_punto_y_coma(self):
        contenido = "fecha;local;visitante;goles_local;goles_visitante;cuota_1;cuota_x;cuota_2\n" \
                    "2025-08-15;A;B;0;0;2,10;3,30;3,40\n"
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(contenido)
        try:
            p = cargar_csv(f.name)[0]
        finally:
            os.unlink(f.name)
        self.assertEqual((p.cuota_1, p.resultado), (2.1, "X"))


class TestModelo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jugados, cls.proxima = generar_liga()
        cls.modelo = ModeloPoisson().ajustar(cls.jugados)

    def test_probabilidades_suman_uno(self):
        pred = self.modelo.predecir(self.proxima[0].local, self.proxima[0].visitante)
        self.assertAlmostEqual(pred.prob_1 + pred.prob_x + pred.prob_2, 1.0)
        self.assertAlmostEqual(pred.prob_mas25 + pred.prob_menos25, 1.0)
        self.assertAlmostEqual(pred.prob_ambos_si + pred.prob_ambos_no, 1.0)

    def test_ventaja_de_campo_y_parametros_razonables(self):
        self.assertTrue(1.05 < self.modelo.ventaja_campo < 1.45)
        self.assertTrue(-0.25 <= self.modelo.rho <= 0.15)

    def test_nombre_sin_mayusculas_y_equipo_desconocido(self):
        self.assertEqual(self.modelo.buscar_equipo("real costa"), "Real Costa")
        with self.assertRaises(KeyError):
            self.modelo.buscar_equipo("Equipo Inventado")

    def test_no_usa_partidos_futuros(self):
        corte = self.jugados[500].fecha
        modelo = ModeloPoisson().ajustar(self.jugados, hasta=corte)
        self.assertTrue(all(p.fecha < corte for p in modelo.historial))

    def test_cara_a_cara(self):
        a, b = self.jugados[0].local, self.jugados[0].visitante
        h2h = cara_a_cara(self.jugados, a, b)
        self.assertGreater(h2h.n, 0)
        self.assertEqual(h2h.victorias_a + h2h.empates + h2h.victorias_b, h2h.n)

    def test_backtest(self):
        informe = backtest(self.jugados[:600], reajuste_dias=28)
        self.assertGreater(informe.partidos_evaluados, 0)
        self.assertGreater(informe.logloss_modelo, 0)


if __name__ == "__main__":
    unittest.main()
