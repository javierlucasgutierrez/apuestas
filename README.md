# 📊 Predictor de partidos (estadística y apuestas de valor)

Herramienta que, a partir de un histórico de partidos y cuotas, calcula **la probabilidad de cada resultado** y la compara con lo que paga la casa de apuestas para encontrar **apuestas de valor**: aquellas en las que la cuota es más alta de lo que debería según las estadísticas.

Es independiente del resto del repositorio (la app K9 Club). Solo necesita **Python 3.10 o superior**, sin instalar nada más.

## Lo importante antes de empezar

- **Ningún modelo adivina resultados.** Lo que da son probabilidades. Un equipo con un 60 % pierde o empata 4 de cada 10 veces.
- **Solo se gana a largo plazo apostando cuando hay valor**: cuando *probabilidad del modelo × cuota > 1*. Apostar al favorito "porque va a ganar" pierde dinero con el tiempo, porque la casa ya cobra su margen (normalmente un 4–8 %).
- **Las casas de apuestas son muy buenas** calculando probabilidades. Si el modelo dice que hay muchísimo valor, lo más probable es que el modelo se equivoque (lesiones, rotaciones, cosas que no salen en las estadísticas), no la casa.
- **Antes de poner un euro, haz el backtest** con tus datos reales. Si en el pasado no habría ganado dinero con cientos de apuestas, no lo hará en el futuro.
- Si las casas ven que ganas de forma constante, suelen **limitar la cuenta**.
- Apuesta solo dinero que puedas permitirte perder. Si el juego deja de ser un extra controlado: **jugarbien.es** · teléfono gratuito de ayuda 900 200 225.

## Cómo funciona (en sencillo)

1. **Fuerza de cada equipo.** Con todos los partidos del histórico calcula cuánto marca cada equipo (ataque) y cuánto encaja (defensa), teniendo en cuenta contra quién jugó y si fue en casa. Los partidos recientes pesan más (por defecto, un partido de hace 6 meses cuenta la mitad).
2. **Goles esperados.** Para un partido concreto estima los goles de cada equipo, por ejemplo 1,8 – 1,1.
3. **Probabilidades.** Con la distribución de Poisson (con la corrección de Dixon-Coles para los marcadores bajos) calcula la probabilidad de cada marcador y de ahí: 1X2, más/menos de 2,5 goles y ambos marcan.
4. **Cara a cara.** Muestra el historial entre los dos equipos y, si quieres, lo tiene en cuenta (`--peso-h2h`). Ojo: suelen ser pocos partidos y de temporadas con plantillas distintas, así que estadísticamente aporta poco. En la liga de ejemplo empeora las predicciones; compruébalo con tus datos con el backtest.
5. **Comparación con la casa.** Quita el margen de la casa a sus cuotas, compara probabilidades y calcula el valor esperado de cada apuesta.
6. **Cuánto apostar.** Usa el criterio de Kelly fraccionado (1/4) con un máximo del 3 % del bank por apuesta.

## Paso a paso

Abre una terminal dentro de la carpeta `apuestas`.

### 1. Probar con una liga de ejemplo

```
python app.py ejemplo
```

Crea `datos/ejemplo_historico.csv` y `datos/ejemplo_proxima_jornada.csv` con una liga **inventada** (sirve para ver cómo funciona; sus resultados no dicen nada de la realidad).

### 2. Ver la fuerza de los equipos

```
python app.py equipos --datos datos/ejemplo_historico.csv
```

### 3. Analizar un partido

```
python app.py predecir --datos datos/ejemplo_historico.csv --local "Real Costa" --visitante "CD Ribera" --cuotas 1.90 3.50 4.20 --cuotas-goles 1.95 1.90
```

Sale algo así:

```
Real Costa vs CD Ribera
Goles esperados: 1.89 - 1.27
1X2:        1  52.3%   X  21.8%   2  25.8%
...
Apuesta    Cuota  Justa  Modelo    Casa   Valor   Apostar
1           1.90   1.91   52.3%   50.1%   -0.5%   no
2           4.20   3.87   25.8%   22.7%   +8.5%   SÍ · 0.67 € (0.7% del bank)
```

- **Justa**: la cuota que debería pagar según el modelo.
- **Modelo / Casa**: probabilidad según el modelo y según la casa (sin su margen).
- **Valor**: lo que ganarías de media por cada euro a la larga si el modelo acierta con la probabilidad.

### 4. Analizar una jornada entera

```
python app.py jornada --datos datos/ejemplo_historico.csv --proximos datos/ejemplo_proxima_jornada.csv --bank 200
```

### 5. Backtest: ¿habría ganado dinero?

```
python app.py backtest --datos datos/ejemplo_historico.csv
```

Recorre el histórico como si fuera en directo (para cada partido solo usa lo que se sabía antes) y dice:

- Si el modelo predice **mejor o peor que la casa** (log-loss y Brier: más bajo es mejor).
- Cuántas apuestas habría hecho, cuántas acertó y el **beneficio** apostando 1 € fijo y con Kelly.

Prueba a cambiar `--umbral`, `--vida-media` o `--peso-h2h` y quédate con lo que funcione mejor **en varias temporadas**, no solo en una (si ajustas demasiado, el modelo "aprende" la suerte del pasado).

## Usar datos reales

Con el formato de **football-data.co.uk** funciona directamente: descarga los CSV de las temporadas que quieras (por ejemplo `SP1.csv` para LaLiga) y pásalos todos juntos:

```
python app.py backtest --datos datos/mis_SP1_2324.csv datos/mis_SP1_2425.csv datos/mis_SP1_2526.csv
```

(Los archivos que empiecen por `mis_` no se suben al repositorio.)

También puedes usar tu propio CSV (separado por comas o por punto y coma) con estas columnas:

| Columna | Obligatoria | Ejemplo |
|---|---|---|
| `fecha` | sí | `15/08/2025` o `2025-08-15` |
| `local`, `visitante` | sí | `Betis`, `Elche` |
| `goles_local`, `goles_visitante` | en el histórico | `2`, `1` (vacías en los partidos por jugar) |
| `cuota_1`, `cuota_x`, `cuota_2` | para buscar valor | `1.80`, `3.60`, `4.50` |
| `cuota_mas25`, `cuota_menos25` | opcional | `1.90`, `1.95` |

Consejos:

- Cuantas más temporadas, mejor (mínimo 2–3 de la misma liga).
- Los nombres de los equipos tienen que escribirse **igual** en todos los archivos.
- Para el backtest usa las cuotas que habrías podido coger de verdad (las de antes del partido, no las de cierre).

## Pruebas

```
python -m unittest discover -s tests
```

## Archivos

- `app.py` — la aplicación (órdenes `ejemplo`, `equipos`, `predecir`, `jornada`, `backtest`).
- `predictor/datos.py` — lectura de los CSV y estadísticas cara a cara.
- `predictor/modelo.py` — modelo de Poisson / Dixon-Coles.
- `predictor/cuotas.py` — margen, valor esperado y Kelly.
- `predictor/backtest.py` — prueba histórica.
- `predictor/ejemplo.py` — generador de la liga de ejemplo.
