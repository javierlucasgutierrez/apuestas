# 📊 Predictor de goles y córners (grandes ligas)

Herramienta para buscar **apuestas con valor a largo plazo** en las 5 grandes ligas. Combina dos cosas:

1. **Comparar casas de apuestas** (1X2, más/menos 2,5 goles y **hándicap asiático**): avisa cuando una casa paga más de lo que vale el resultado.
2. **Estadística propia** (sobre todo córners): calcula la probabilidad de cada línea y te dice la **cuota mínima** que tienes que encontrar en Oddspedia.

Es independiente del resto del repositorio (la app K9 Club). Solo necesita **Python 3.10 o superior**.

---

## Explicado fácil

### ¿Qué es "valor"?

Imagina una moneda: sale cara la mitad de las veces. Si alguien te paga **2,20 €** por cada euro que apuestas a cara, a la larga ganas, aunque pierdas muchas tiradas. Si te paga 1,80 €, a la larga pierdes, aunque aciertes muchas.

- **Cuota justa** = 1 ÷ probabilidad. Moneda: 1 ÷ 0,5 = **2,00**.
- **Hay valor** cuando la cuota que te pagan es **mayor que la justa**.
- **Valor** = probabilidad × cuota − 1. Con la moneda a 2,20: 0,5 × 2,20 − 1 = **+10 %**. De media ganas 10 céntimos por cada euro apostado.

Lo importante: **ganar no es acertar mucho, es apostar cuando la cuota paga más de lo que debería.**

### Tu regla de la cuota 1,50

A 1,50, dos aciertos (+0,50 +0,50) cubren un fallo (−1). Es decir, hay que acertar **2 de cada 3** (66,7 %) solo para quedarse igual. La herramienta respeta tu mínimo de 1,50, pero además exige que la cuota tenga valor.

### ¿De dónde sale la probabilidad "real"?

De dos sitios:

**a) Del propio mercado (para 1X2 y goles 2,5).** Hay casas muy "finas": **Pinnacle** y la **bolsa de Betfair**. Ahí apuestan profesionales y sus cuotas, quitándoles el margen, son la mejor estimación que existe de la probabilidad real. Las casas normales (Bet365, bwin...) a veces se quedan atrás y pagan de más. Esa es la oportunidad.

> Ejemplo: Betfair dice que el empate vale 3,60 (28 %). Una casa lo paga a 3,90. Valor = 0,28 × 3,90 − 1 = **+9 %**.

Así lo propone el estudio *Beating the bookies with their own numbers* (Kaunitz, Zhong y Kreiner, 2017).

**b) De nuestro modelo estadístico (para córners, donde no hay casa "fina").** Se calcula en 4 pasos:

1. **Fuerza de cada equipo.** Cuánto genera y cuánto concede, comparado con la media de su liga, teniendo en cuenta el rival y si juega en casa. Por ejemplo: "el Barça saca un 45 % más de córners que la media; el Getafe concede un 20 % más".
2. **Córners esperados del partido** = media de la liga × ventaja de casa × ataque × defensa del rival. Por ejemplo: 5,8 del local + 4,1 del visitante = 9,9.
3. **Probabilidad de cada línea**, por ejemplo "más de 9,5". Los córners varían bastante de un partido a otro, así que se usa una fórmula (la binomial negativa) que tiene en cuenta esa variación. La herramienta la mide con los datos.
4. **Corrección con la experiencia.** La herramienta repasa lo que predijo en el pasado y lo que pasó de verdad. Si se pasaba de optimista, se corrige sola.

Los partidos recientes pesan más: uno de hace 1 año cuenta la mitad. No lo he decidido a ojo: la orden `optimizar` probó 60 combinaciones y eligió la que mejor predijo.

Para los goles se usa lo mismo con la distribución de Poisson y la corrección de Dixon y Coles (1997), que es el modelo clásico de la estadística del fútbol.

### ¿Cómo sé si algo tiene valor sin esperar años? El CLV

Las cuotas cambian hasta el inicio del partido. La cuota justo antes de empezar (la de **cierre**) es la más precisa, porque ya incluye alineaciones, lesiones y el dinero de los profesionales.

**CLV** = cuánto mejor era tu cuota que el precio justo de cierre. Si de media coges cuotas mejores que el cierre (**CLV positivo**), ganas a la larga, aunque una mala racha diga lo contrario. Es lo que miran los apostadores profesionales, porque la suerte casi no le afecta.

### ¿Cuánto apostar?

Con el criterio de Kelly: cuanto más valor y más probabilidad, más se apuesta. Se usa **una cuarta parte** de lo que dice Kelly y **nunca más del 3 % del bank** por apuesta. Así una mala racha no te hunde.

---

## Resultados del backtest (comprobado con datos reales)

"Backtest" = repetir el pasado como si fuera en directo: en cada partido solo se usa lo que se sabía antes de jugarse.

### 1. Comparando casas (1X2 y goles 2,5): sí da valor

Regla: apostar cuando la mejor cuota del mercado paga **≥ 2 % más que el precio justo** de Pinnacle o Betfair, con cuotas entre 1,50 y 5. Apuesta fija de 1 €. Datos: 5 grandes ligas, agosto 2023 – octubre 2026.

| Mercado | Temporada | Apuestas | Aciertos | Cuota media | Beneficio | Rentabilidad | CLV |
|---|---|---|---|---|---|---|---|
| 1X2 | 2023/24 | 396 | 30 % | 3,72 | +31,0 € | +7,8 % | +3,1 % |
| 1X2 | 2024/25 | 378 | 29 % | 3,73 | +17,9 € | +4,7 % | +3,5 % |
| 1X2 | 2025/26 | 101 | 32 % | 3,61 | +4,0 € | +4,0 % | +6,0 % |
| 1X2 | 2026/27 (en curso) | 28 | 50 % | 3,23 | +20,2 € | +72 % | +19 % |
| **1X2** | **TOTAL** | **903** | **30 %** | **3,70** | **+73,2 €** | **+8,1 %** | **+4,1 %** |
| Goles 2,5 | TOTAL | 179 | 36 % | 2,79 | −8,9 € | −4,9 % | +7,2 % |

Cómo leerlo:

- **1X2: positivo en todas las temporadas**, con CLV positivo. Es la señal más sólida.
- **Goles 2,5**: CLV muy positivo, pero pocas apuestas, así que el beneficio todavía depende de la suerte (una temporada +15 %, otra −17 %).
- **Ojo, se acierta poco (30 %)**: son sobre todo empates y no favoritos a cuota alta. Habrá **rachas de 10 o más fallos seguidos** y hay que aguantarlas. Si solo usas cuotas entre 1,50 y 2,50 hay muy pocas oportunidades (unas 60 en 3 años).
- **"Mejor cuota del mercado"** es la más alta entre decenas de casas, y algunas no operan en España. Solo con Bet365 y bwin salen unas 75 apuestas en 3 años (1X2: +6,5 %, CLV +0,9 %). **Cuantas más cuentas tengas en casas españolas, más oportunidades.** Oddspedia te enseña todas a la vez.

### 1 bis. Más volumen: hándicap asiático y más ligas

El **hándicap asiático** es el mercado de fútbol que más dinero mueve. Las cuotas rondan el 2,00 y se gana más o menos la mitad de las veces: justo tu perfil de "cuota por encima de 1,50". Como mueve tanto dinero, es muy eficiente y salen pocas oportunidades. Por eso hay que mirar **más ligas**.

Mismas reglas, ahora en **20 ligas** (las 5 grandes, sus segundas divisiones, League One y Two, National League, Escocia, Portugal, Países Bajos, Bélgica, Turquía y Grecia):

| Mercado | Apuestas (3 temporadas) | Aciertos | Cuota media | Beneficio | Rentabilidad | CLV |
|---|---|---|---|---|---|---|
| **Hándicap asiático** | **591** | **51 %** | **2,03** | **+67,7 €** | **+11,5 %** | **+2,9 %** |
| 1X2 | 2.951 | 31 % | 3,60 | +167,2 € | +5,7 % | +2,9 % |
| Goles 2,5 | 615 | 43 % | 2,46 | −2,0 € | −0,3 % | +3,5 % |

- **Hándicap asiático: positivo en todas las temporadas** (+14 %, +7 %, +11 %, +9 %), con medio partido acertado y cuota ~2. Es el mercado más estable de todos.
- **Más ligas = unas 4 veces más apuestas**, con un CLV algo menor que en las 5 grandes (+2–3 % frente a +4 %). El CLV es positivo **en las 15 ligas añadidas**.
- **Solo con Bet365** (20 ligas): 1X2 538 apuestas (+3,9 %) y hándicap asiático 90 (+8,8 %).
- En goles 2,5 el CLV es positivo, pero el beneficio sigue cerca de cero: por ahora, prudencia.

Para bajarlas todas: `python app.py descargar --ligas todas`.

### 2. Nuestro modelo solo, contra las casas (1X2 y goles): no da valor

Si se apuesta solo porque el modelo ve valor frente a Bet365, se pierde un 5–7 % y el CLV es negativo (−1,6 % / −2,6 %). En 1X2 y goles **la casa sabe más que las estadísticas**. Por eso la herramienta ya **no** recomienda 1X2 ni goles basándose solo en el modelo.

En cambio, cuando el mercado da valor **y el modelo está de acuerdo**, el CLV es algo mejor (goles: +11 % frente a +6 %). Por eso se muestra si el modelo está "de acuerdo ✔" o "en contra".

### 3. Córners: las probabilidades se cumplen

| El modelo dice | Pasó de verdad | Cuota necesaria para no perder |
|---|---|---|
| 55–60 % | 58 % | 1,72 |
| 60–65 % | 62 % | 1,60 |
| 65–70 % | 68 % | 1,46 |
| 70–75 % | 72 % | 1,39 |

(3.700 partidos, agosto 2024 – octubre 2026.) Cuando dice 68 %, pasa el 68 %. **Pero no existen cuotas históricas gratuitas de córners**, así que no se puede comprobar si las casas pagaban esas cuotas. Para córners, la regla es:

- **Una sola casa**: apuesta solo si su cuota llega a la **cuota mínima** del modelo.
- **Varias casas** (lo mejor): la herramienta calcula el precio justo **del mercado** a partir de todas, y solo dice APOSTAR si la mejor cuota supera ese precio en un 2 % **y** el modelo está de acuerdo.

**Lleva un registro de cada apuesta** (fecha, mercado, cuota, resultado) para comprobar con tu dinero, poco a poco, si funciona.

### Lo que no puede saber

Lesiones, alineaciones, rotaciones, el tiempo o la motivación. Por eso la cuota de cierre es tan buena: las casas sí lo saben. Las cuotas del archivo de próximos partidos se toman cuando se actualiza football-data, así que **compruébalas siempre en Oddspedia antes de apostar**.

---

## Paso a paso

Abre una terminal dentro de la carpeta `apuestas`.

### 1. Descargar los datos (antes de cada jornada)

```
python app.py descargar               # las 5 grandes
python app.py descargar --ligas todas # las 20 ligas (más oportunidades)
```

### 2. Ver la jornada

```
python app.py jornada
```

Te enseña dos listas:

1. **VALOR DE MERCADO** (1X2, goles 2,5 y hándicap asiático): "Partido X: empate en Bet365 @ 3,90 (justa 3,60, valor +8 %) → 1,20 € · modelo de acuerdo ✔" o "Hándicap local −0.25 en Bet365 @ 2,10".
2. **CÓRNERS PARA MIRAR EN ODDSPEDIA**: "Milan - Bologna: córners −10,5 · 70 % · cuota mínima 1,50".

Opciones: `--dias 7`, `--liga laliga`, `--bank 300`, y `--todos` para ver también goles y 1X2 del modelo.

### 3. Comprobar en Oddspedia y decidir

Copia las cuotas de varias casas, separadas por `/`, con el "más" y el "menos" de la misma línea:

```
python app.py partido --local Milan --visitante Bologna --cuota "corners+9.5=1.80/1.85/2.05/1.83" "corners-9.5=1.95/1.90/1.72/1.93"
```

```
Selección         Mejor Casas Justa mercado Justa modelo   Decisión
Córners +9.5       2.05     4          2.00         2.77   dudoso: el mercado da valor (+2%) pero el modelo no
Córners -9.5       1.95     4          2.00         1.56   no: la mejor cuota no supera lo justo del mercado (-2%)
```

Con una sola cuota (`"corners-10.5=1.62"`) decide el modelo y te dice si llega a la cuota mínima.

Mercados válidos: `1`, `X`, `2`, `1X`, `X2`, `12`, `goles+2.5`, `goles-1.5`, `corners+8.5`, `corners-11.5`, `ambos si`, `ambos no`.

### 4. Solo el comparador de casas

```
python app.py valor              # próximos partidos
python app.py valor --backtest   # la tabla de resultados de arriba
python app.py valor --backtest --casas B365 BW   # solo con Bet365 y bwin
```

### 5. Otras órdenes

- `python app.py equipos --liga SP1`: goles y córners a favor y en contra de cada equipo. Ligas: E0, SP1, I1, D1, F1.
- `python app.py backtest`: comprueba si se cumplen las probabilidades del modelo.
- `python app.py optimizar`: una vez al mes. Recalcula los ajustes y la corrección con los datos nuevos (tarda unos minutos).
- `python app.py ejemplo`: liga inventada para probar sin conexión.

---

## De dónde salen los datos

- **football-data.co.uk**, con descarga libre y gratuita: cada partido con goles, córners y cuotas de muchas casas (Pinnacle, bolsa de Betfair, Bet365, bwin...), más los próximos partidos.
- **SoccerStats, AdamChoi y Oddspedia** no permiten la lectura automática, así que la herramienta no los lee. Úsalos tú para mirar y contrastar. Oddspedia es el sitio donde comparar las cuotas de córners de las distintas casas.

## Juego responsable

Apuesta solo lo que puedas permitirte perder. Incluso con valor real hay rachas largas de pérdidas, y si ganas de forma constante, algunas casas limitan la cuenta. Si deja de ser un extra controlado: **jugarbien.es** · teléfono gratuito 900 200 225.

## Pruebas

```
python -m unittest discover -s tests
```

## Archivos

- `app.py`: la aplicación.
- `ajustes.json`: ajustes y corrección calculados por `optimizar`.
- `predictor/valor.py`: comparador de casas, precio justo y CLV.
- `predictor/modelo.py`: fuerzas de ataque y defensa, Poisson / Dixon-Coles y binomial negativa.
- `predictor/mercados.py`: probabilidad de cada mercado.
- `predictor/calibracion.py`: corrección con la experiencia.
- `predictor/cuotas.py`: cuota mínima, valor y Kelly.
- `predictor/backtest.py` y `predictor/optimizar.py`: pruebas con el histórico y búsqueda de ajustes.
- `predictor/descargar.py` y `predictor/datos.py`: descarga y lectura de datos.
