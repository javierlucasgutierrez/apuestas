# 📊 Predictor de goles y córners (grandes ligas)

Herramienta que calcula, solo con estadística, la probabilidad de cada mercado de un partido (**córners, goles, 1X2**) y te dice **la cuota mínima** que tienes que encontrar en la casa de apuestas (por ejemplo, en Oddspedia) para que la apuesta tenga valor.

Es independiente del resto del repositorio (la app K9 Club). Solo necesita **Python 3.10 o superior**, sin instalar nada más.

## Lo importante antes de empezar

- **La regla de la cuota 1,50.** A cuota 1,50, dos aciertos (+0,50 +0,50) cubren un fallo (−1). Eso quiere decir que **hay que acertar 2 de cada 3 (66,7 %) solo para no perder**. A cuota 1,80 basta con acertar el 55,6 %. La herramienta no busca "acertar mucho": busca apuestas donde **la probabilidad real sea mayor que la que paga la cuota**. Eso es lo único que da dinero a la larga.
- **Ningún modelo adivina.** Da probabilidades: si dice 70 %, falla 3 de cada 10.
- **En 1X2 y goles, la casa sabe más que el modelo** (ver resultados del backtest más abajo). Donde más sentido tiene es en **córners**, un mercado en el que las casas suelen afinar menos. Aun así, no hay cuotas históricas gratuitas de córners, así que ahí no se puede demostrar que se gane dinero; sí se puede comprobar que **las probabilidades se cumplen**.
- Si ganas de forma constante, las casas suelen **limitar la cuenta**.
- Apuesta solo dinero que puedas permitirte perder. Si deja de ser un extra controlado: **jugarbien.es** · teléfono gratuito 900 200 225.

## De dónde salen los datos

- **football-data.co.uk**: resultados, **córners** y cuotas (1X2 y más/menos 2,5 goles) de cada partido de las 5 grandes ligas desde hace años, más los próximos partidos con sus cuotas. Son descargas gratuitas pensadas para esto, y la herramienta las baja sola.
- **SoccerStats**: tiene los mismos datos, pero solo como medias por equipo, no partido a partido. Además bloquea el acceso automático, así que la herramienta no lo lee. Úsalo para echar un ojo y contrastar.
- **Oddspedia**: también bloquea el acceso automático. Allí miras tú las cuotas de córners y las comparas con la cuota mínima que te da la herramienta. Si quieres que haga las cuentas con esas cuotas, se las pasas (ver más abajo).

## Cómo funciona

1. **Fuerza de cada equipo, por separado para goles y para córners**: cuánto genera (a favor) y cuánto concede (en contra), teniendo en cuenta el rival y si juega en casa.
2. **Más peso a lo reciente.** Cuánto pasado usar no lo he decidido a ojo: lo ha decidido la orden `optimizar`, que prueba muchas combinaciones contra 2 temporadas de partidos y se queda con la que **mejor predijo**. Ahora mismo es una vida media de **1 año** para goles y para córners (un partido de hace un año cuenta la mitad), y además los equipos con pocos partidos se acercan bastante a la media de la liga.
3. **Probabilidades**:
   - Goles: distribución de Poisson con la corrección de Dixon-Coles para 0-0, 1-0, 0-1 y 1-1.
   - Córners: una binomial negativa, porque los córners varían más de un partido a otro que los goles.
4. **Corrección con la experiencia (calibración).** La herramienta revisa los aciertos y fallos pasados del modelo y corrige las probabilidades. Por ejemplo, ha aprendido que el modelo apenas sabe predecir "ambos marcan", así que esas probabilidades se quedan cerca de la media y casi nunca salen como selección.
5. **Cuota mínima** = la mayor de dos: **1,50** (tu regla) o la cuota que deja al menos un **5 % de valor** según el modelo.

## Paso a paso

Abre una terminal dentro de la carpeta `apuestas`.

### 1. Descargar los datos (cada vez que vayas a apostar: se actualizan cada semana)

```
python app.py descargar
```

Baja 4 temporadas de Premier, LaLiga, Serie A, Bundesliga y Ligue 1, y los próximos partidos. Para otras ligas: `--ligas premier laliga championship eredivisie portugal`.

### 2. Ver los próximos partidos

```
python app.py jornada
```

Para cada partido de los próximos 3 días (`--dias 7` para una semana, `--liga laliga` para una sola liga) muestra los goles y córners esperados y las selecciones más probables, con su **cuota mínima**:

```
Milan vs Bologna   [Serie A (Italia)]
Esperado: goles 1.43-0.98 · córners 5.6-4.1 (total 9.7)
Selección            Prob.  Justa  Mínima  Cuota
Córners -10.5          66%   1.52    1.59      -   busca cuota ≥ 1.59
Goles -2.5             58%   1.72    1.81   2.00   APOSTAR 2.53 € (valor +10%)
```

- **Justa**: la cuota que correspondería a esa probabilidad, sin margen.
- **Mínima**: por debajo de esta, no apuestes.
- **Cuota**: si se conoce (1X2 y ±2,5 goles vienen en los datos), te dice directamente si llega y cuánto apostar (Kelly fraccionado, máximo 3 % del bank; cambia el bank con `--bank 300`).

Al final hay dos resúmenes: **apuestas con valor** (cuota conocida y suficiente) y **para mirar en Oddspedia** (las más probables con su cuota mínima).

### 3. Comprobar en Oddspedia y decidir

Si en Oddspedia ves *Milan–Bologna, más de 9,5 córners a 1,85*:

```
python app.py partido --local Milan --visitante Bologna --cuota "corners+9.5=1.85"
```

Puedes poner varias: `--cuota "corners+9.5=1.85" "goles-2.5=2.00" "1=1.70"`. Mercados válidos: `1`, `X`, `2`, `1X`, `X2`, `12`, `goles+2.5`, `goles-1.5`, `corners+8.5`, `corners-11.5`, `ambos si`, `ambos no`.

Si tienes muchas, cópialas en un CSV como `datos/cuotas_plantilla.csv` y pásalo a la jornada:

```
python app.py jornada --cuotas datos/mis_cuotas.csv
```

### 4. Ver cómo está cada equipo

```
python app.py equipos --liga SP1
```

Goles y córners a favor y en contra por partido, contra un rival medio. Los códigos de liga son E0, SP1, I1, D1 y F1.

### 5. Una vez al mes: reoptimizar

```
python app.py optimizar
```

Vuelve a buscar los mejores ajustes y la corrección con los datos nuevos, y los guarda en `ajustes.json`. Tarda unos minutos.

### 6. Backtest: ¿se cumplen las probabilidades? ¿habría ganado dinero?

```
python app.py backtest
```

Recorre el pasado como si fuera en directo: para cada partido el modelo solo sabe lo anterior a esa fecha.

## Resultados del backtest (3.700 partidos, agosto 2024 – octubre 2026)

**¿Se cumplen las probabilidades?** Sí, bastante bien. Ejemplo con córners:

| El modelo dice | Pasó de verdad | Cuota para no perder |
|---|---|---|
| 55–60 % | 58 % | 1,72 |
| 60–65 % | 62 % | 1,60 |
| 65–70 % | 68 % | 1,46 |
| 70–75 % | 72 % | 1,39 |

Es decir: si te quedas con las selecciones de córners del **60–70 %** y solo apuestas cuando encuentras **cuota ≥ 1,50–1,60**, en el pasado se habría acertado más de lo necesario para no perder (en el tramo de 65–70 %, por ejemplo, basta una cuota de 1,46). **Pero no hay cuotas históricas de córners para comprobar si las casas pagaban esas cuotas.** Lleva tu propio registro de las apuestas (fecha, mercado, cuota, resultado) para comprobarlo con dinero real y poco a poco.

**¿Habría ganado dinero en 1X2 y ±2,5 goles con las cuotas reales de Bet365?** **No.** Siguiendo las reglas (cuota ≥ 1,50, valor ≥ 5 %), se pierde en torno a un **10 %** de lo apostado (unas 1.300 apuestas, con un 47 % de aciertos a cuota media de 1,94). Cuando el modelo y la casa no están de acuerdo, suele tener razón la casa: tiene información que las estadísticas no tienen (lesiones, rotaciones, motivación...). Por eso, en esos mercados, toma las "apuestas con valor" con mucha cautela.

## Usar tus propios datos

Acepta los CSV de football-data.co.uk tal cual o un CSV propio (separado por comas o por punto y coma) con estas columnas:

| Columna | Obligatoria | Ejemplo |
|---|---|---|
| `liga` | recomendable | `SP1` |
| `fecha` | sí | `15/08/2025` o `2025-08-15` |
| `local`, `visitante` | sí | `Betis`, `Elche` |
| `goles_local`, `goles_visitante` | en el histórico | `2`, `1` |
| `corners_local`, `corners_visitante` | para córners | `7`, `3` |
| `cuota_1`, `cuota_x`, `cuota_2`, `cuota_mas25`, `cuota_menos25` | opcional | `1.80` |

```
python app.py jornada --datos datos/mis_datos.csv --proximos datos/mis_proximos.csv
```

Los archivos que empiecen por `mis_` no se suben al repositorio. Los nombres de los equipos tienen que escribirse igual en todos los archivos.

Para probar sin conexión hay una liga inventada: `python app.py ejemplo`.

## Pruebas

```
python -m unittest discover -s tests
```

## Archivos

- `app.py`: la aplicación (`descargar`, `jornada`, `partido`, `equipos`, `backtest`, `optimizar`, `ejemplo`).
- `ajustes.json`: ajustes y corrección que ha calculado `optimizar`.
- `predictor/descargar.py`: descarga de football-data.co.uk.
- `predictor/datos.py`: lectura de los CSV y estadísticas cara a cara.
- `predictor/modelo.py`: fuerzas de ataque y defensa, Poisson / Dixon-Coles y binomial negativa.
- `predictor/mercados.py`: probabilidad de cada mercado.
- `predictor/calibracion.py`: corrección con los aciertos y fallos pasados.
- `predictor/cuotas.py`: cuota mínima, valor y Kelly.
- `predictor/backtest.py` y `predictor/optimizar.py`: prueba histórica y búsqueda de ajustes.
