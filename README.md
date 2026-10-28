# 📊 Predictor de goles y córners (grandes ligas)

Herramienta para buscar **apuestas con valor a largo plazo** en las 5 grandes ligas. Combina dos cosas:

1. **Comparar casas de apuestas** (1X2, más/menos 2,5 goles y **hándicap asiático**): avisa cuando una casa paga más de lo que vale el resultado.
2. **Estadística propia** (sobre todo córners): calcula la probabilidad de cada línea y te dice la **cuota mínima** que tienes que encontrar en Oddspedia.

Solo necesita **Python 3.10 o superior**, sin instalar nada más.

---

## 🖱️ La forma fácil: el panel (sin comandos)

Haz **doble clic en `Abrir panel.bat`** (en Mac, `Abrir panel.command`). Se abre una ventana negra (déjala abierta) y el **panel en tu navegador**, con estas pestañas:

| Pestaña | Para qué |
|---|---|
| 🏠 **Inicio** | Botón **Actualizar ahora**: baja los resultados reales, los próximos partidos y liquida tus picks. Botón **Mejorar el modelo**, una vez al mes. |
| 🎯 **Picks** | Los picks del sistema, con la cuota mínima y cuánto apostar. Si apuestas uno, escribe la cuota que conseguiste y pulsa **Guardar**. Botón **Copiar texto para publicar**. |
| 🚩 **Córners** | Los córners que vale la pena mirar, con su probabilidad y su cuota mínima. También se guardan con un botón. |
| 📊 **Mi historial** | Aciertos, unidades, yield, CLV, rachas, por mes y por mercado, y la lista de todos tus picks. |
| ⚙️ **Configuración** | Tu bank, estilo de apuestas, cuánto apostar, ligas y clave de cuotas en vivo. |
| ❓ **Cómo funciona** | La explicación en sencillo. |

El panel funciona **solo en tu ordenador** (nadie más puede verlo). Para cerrarlo, cierra la ventana negra.

---

## Uso diario en tu ordenador (con comandos, para quien lo prefiera)

### Instalarlo (una sola vez)

1. Instala **Python** desde https://www.python.org/downloads. En Windows, marca la casilla **"Add Python to PATH"** al instalar.
2. Descarga el proyecto (en GitHub: **Code → Download ZIP**, o directamente https://github.com/javierlucasgutierrez/apuestas/archive/refs/heads/main.zip), descomprímelo y pon la carpeta donde quieras (por ejemplo, en el Escritorio con el nombre `apuestas`).
3. Abre una terminal en la carpeta `apuestas` (en Windows, escribe `cmd` en la barra de direcciones de la carpeta y pulsa Enter) y guarda tus preferencias:

   ```
   python app.py configurar --bank 1000 --casas B365 BW WH Max --ligas todas --perfil equilibrado
   ```

   Se guardan en `preferencias.json` y se usan solas a partir de ahora. Puedes cambiarlas cuando quieras repitiendo la orden.

### Cada jornada: doble clic en `jornada.bat` (en Mac, `jornada.command`)

Hace todo seguido:

1. **Actualiza los datos**: baja los resultados y cuotas nuevos. **Los datos se van sumando**: la temporada en curso se actualiza y las anteriores se quedan guardadas, así que con los años cada vez hay más historia.
2. **Liquida tus picks** ya jugados (ganada, perdida, nula, medio ganada/perdida) y calcula su CLV con la cuota de cierre.
3. **Da los picks nuevos** del sistema con su **stake del 1 al 10** y los **guarda en el registro** (`datos/apuestas.db`).
4. **Prepara el texto para publicar** en `datos/publicar/AAAA-MM-DD.txt`:

   ```
   ⚽ Newcastle - Chelsea · Premier League (Inglaterra) · 20/12
   ➡️ Empate
   💰 Cuota 3.65 (BetMGM)
   📊 Stake 1/10
   🔻 No apostar por debajo de 3.60
   ```

5. Te enseña los **córners para mirar en Oddspedia**.

Si das un pick a mano (por ejemplo, de córners), anótalo para que entre en el historial y se liquide solo:

```
python app.py anotar --fecha 2026-11-01 --local Betis --visitante Sevilla --mercado corners+9.5 --cuota 1.85 --casa B365 --stake 4 --liga SP1
```

### Una vez al mes

`python app.py optimizar`: recalcula el modelo con todos los datos acumulados. La orden `actualizar` te avisa cuando toca.

### Tu historial: doble clic en `informe.bat`

```
HISTORIAL DE PICKS (todos los liquidados, sin quitar ninguno)
                     Picks  Acierto  Cuota   Stake  Unidades    Yield     CLV
TOTAL                  412      37%   3.21    1236    +98.40    +8.0%   +2.7%
```

Lo saca **por mes y por mercado**, y lo exporta completo a `datos/historial.csv`, con la fecha y hora a la que se dio cada pick.

### ¿Qué stake usar? (comprobado con los datos)

| Perfil | Mejor método | Año normal | Probabilidad de acabar el año perdiendo | Bajón típico |
|---|---|---|---|---|
| **Cuotas cortas** | **Fijo 1 % del bank** (stake 3/10) | +19 % | 9 % | 8 % |
| Cuotas cortas | Kelly 1/4 | +13 % | 16 % | 9 % |
| **Equilibrado** | **Kelly 1/4** | +60 % | 3 % | 16 % |
| Equilibrado | Fijo 1 % | +89 % | 10 % | 31 % |

Con cuotas cortas funciona mejor **apostar siempre lo mismo** (1 % del bank). Con el perfil equilibrado, que tiene cuotas muy distintas, es mejor **Kelly 1/4**: apuesta más cuando hay más valor y menos en las cuotas altas. Apostar más fuerte (2 %, Kelly 1/2 o completo) gana más en un año normal, pero los bajones pasan del 30–50 %.

```
python app.py configurar --perfil cuotas_cortas --metodo plano --plano 0.01
```

### Los stakes 1–10

El stake sale del criterio de Kelly. **Stake 10 = el máximo que permite el sistema (3 % del bank)**; stake 5 = 1,5 %; stake 1 = 0,3 % o menos. Con el sistema, la mayoría de los picks salen con stake 1–4: son apuestas de valor a cuotas medias-altas, y apostar más fuerte hundiría el bank en las rachas malas.

### Si vendes los picks

- **Publica el historial completo**, con las pérdidas y los nulos incluidos. El registro no deja borrar ni cambiar picks, y el CSV lleva la hora a la que se dio cada uno. Es tu mejor argumento de venta, y lo honesto con quien te paga.
- **No prometas ganancias.** Con 30–40 % de aciertos habrá meses en negativo aunque el sistema funcione. Enseña el **CLV**: es lo que demuestra el valor a largo plazo.
- **Tus clientes no consiguen tu cuota.** Cuando muchos apuestan lo mismo, la cuota baja. Por eso el texto para publicar ya incluye la **cuota mínima** ("No apostar por debajo de..."): por debajo, el pick ya no tiene valor.
- **Revisa la normativa** antes de cobrar: la publicidad y la promoción del juego en España están reguladas (Ley 13/2011 y Real Decreto 958/2020). Si promocionas casas o usas enlaces de afiliado, tiene sus propias reglas. Revisa también las condiciones de la plataforma donde vendes y consulta a un asesor si tienes dudas.

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

### ⚽ Estrategia de goles (la que viene por defecto: solo goles y córners)

**Más/menos 2,5 goles, cuotas de 1,60 a 2,10, solo cuando una casa paga al menos un 1 % más que el precio justo de Pinnacle o Betfair (método odds ratio).** Apuesta fija del 1 % del bank. 20 ligas.

| Temporada | Apuestas | Rentabilidad |
|---|---|---|
| 2023/24 | 336 | +1,9 % |
| 2024/25 | 244 | +2,7 % |
| 2025/26 | 133 | +6,1 % |
| 2026/27 (en curso) | 11 | −30,7 % |
| **Total** | **724** | **+2,5 %** (CLV +1,7 %) |

- Se gana el 55 % a una cuota media de 1,88. Positiva en cada temporada completa, pero **con margen pequeño**: en un año simulado, lo normal es +5 % y hay un 37 % de probabilidad de acabar el año perdiendo, porque salen pocas apuestas (unas 230 al año).
- Los goles son el mercado que más vigilan las casas; por eso la ventaja es pequeña. Los córners (pestaña Córners) salen del modelo: sus probabilidades se cumplen, pero no hay cuotas históricas para comprobar si dan dinero.

### ⭐ La estrategia de resultados (la más rentable, pero no es de goles)

**Hándicap asiático y 1X2, cuotas de 1,50 a 2,50, solo cuando una casa paga al menos un 2 % más que el precio justo de Pinnacle o Betfair.** Apuesta fija del **1,5 % del bank**. 20 ligas.

| Temporada | Apuestas | Rentabilidad |
|---|---|---|
| 2023/24 | 451 | +14,8 % |
| 2024/25 | 265 | +6,3 % |
| 2025/26 | 257 | +14,3 % |
| 2026/27 (en curso) | 24 | −3,5 % |
| **Total** | **997** | **+12,0 %** (CLV +2,8 %) |

- Diseñada con 2023–2025 (+10,2 %) y comprobada con 2025–2027, que no había visto (**+12,4 %**, CLV +3,6 %). Con solo Betfair como referencia (como en directo desde esta temporada) también gana.
- Se gana algo más de la mitad (52–53 %) a una cuota media de 2,03. Unas 4–8 apuestas por semana.
- Bank de 1.000 € en las temporadas de prueba: **1.634 €** (peor bajón, 8 %).
- Un año simulado 2.000 veces: normal **+65 %**, malo (1 de cada 20) +7 %. **Probabilidad de acabar el año perdiendo: 2 %.** Bajón típico: 15 %.

**Cómo se calcula el precio justo: método "odds ratio".** Las casas meten más margen en los resultados poco probables (sesgo favorito-sorpresa). Probé cuatro formas de quitar ese margen:

| Método | Apuestas | Rentabilidad | Beneficio total |
|---|---|---|---|
| Proporcional | 781 | +13,2 % | +103 u |
| Potencia | 1.256 | +9,0 % | +113 u |
| **Odds ratio** | **997** | **+12,0 %** | **+120 u** |
| Shin | 1.056 | +10,7 % | +113 u |

**Lo que se probó y NO mejora:** exigir que nuestro modelo también esté de acuerdo (+6,4 % frente a +11,4 %: en estos mercados el mercado sabe más), las rachas recientes, y separar estadísticas de local y visitante.

**Cuánto apostar:** con el 1 % del bank el año normal da +23 % y el peor bajón ronda el 15 %; con el 1,5 %, +35 % y 22 %; con el 2 %, +49 % y 28 %. La probabilidad de acabar el año perdiendo apenas cambia (5–7 %); lo que crece son los bajones.

**Local o visitante, ¿estadísticas por separado?** No. La fuerza general de un equipo se repite mucho de una temporada a otra (correlación 0,72), pero su ventaja "propia" de jugar en casa es pura suerte (0,02). Por eso el modelo usa todos los partidos y una ventaja de campo igual para todos los equipos de la liga.


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

### 1 ter. El sistema completo (`python app.py sistema`)

Junta lo que ha aguantado la prueba: **hándicap asiático + 1X2 con cuota hasta 5**, solo cuando una casa paga por encima del precio justo. **Goles 2,5 queda fuera**: ganaba en 2023-25 y perdía en 2025-27.

Se diseñó con las temporadas 2023/24 y 2024/25 y se comprobó con **2025/26 y 2026/27, que el sistema no había visto**. Datos de 20 ligas, con la mejor cuota del mercado:

| Perfil | Apuestas (prueba) | Por semana | Ganadas | Cuota media | Rentabilidad | CLV | Bank de 1.000 € (Kelly 1/4) | Peor caída |
|---|---|---|---|---|---|---|---|---|
| Conservador (valor ≥ 3 %) | 495 | 8 | 35 % | 3,24 | +3,7 % | +4,5 % | 1.513 € | 24 % |
| **Equilibrado (≥ 2 %)** | **828** | **13** | **36 %** | **3,24** | **+8,7 %** | **+2,9 %** | **1.784 €** | **21 %** |
| Volumen (hándicap ≥ 1 %) | 919 | 14 | 37 % | 3,11 | +8,5 % | +2,7 % | 1.832 € | 20 % |

**Perfil "cuotas cortas" (solo cuotas de 1,60 a 2,10)**: en las temporadas de prueba, 167 apuestas (unas 3 por semana), **55 % ganadas**, cuota media 1,95, **+14,7 %** y CLV +2,7 %. La peor racha fue de **7 fallos seguidos** (frente a 19 en el equilibrado) y la peor caída del bank, del 7 %. Gana más por apuesta, pero salen 5 veces menos apuestas, así que **el beneficio total es menor**. Con 50 €/mes: 650 € → 725 € (cuotas cortas) frente a 650 € → 824 € (equilibrado). Es ideal para vender picks, porque se acierta la mitad: `python app.py sistema --perfil cuotas_cortas`.

**Una temporada simulada 2.000 veces** (sorteando apuestas reales), perfil equilibrado y unas 1.090 apuestas al año: en un año normal el bank sube un **+58 %**; en un año malo (el peor 5 %), se queda **igual**; la probabilidad de acabar el año perdiendo es del **5 %**; y lo normal es pasar por una caída del **17 %** en algún momento.

⚠ **La condición más importante: tener cuenta en muchas casas.** Con solo Bet365 y bwin, el mismo sistema **queda en tablas** en la prueba (+0,7 %, unas 3 apuestas por semana). La ventaja sale de coger siempre la mejor cuota. "Mejor cuota del mercado" es la más alta entre decenas de casas, y algunas no operan en España. Cuantas más casas españolas tengas (Bet365, bwin, William Hill, Betfair, Codere, Sportium, Betway, 888, Winamax, Kirolbet, Retabet...), más te acercas a la tabla de arriba.

Otros riesgos: la cuota puede moverse antes de que apuestes (compruébala siempre) y las casas limitan a quien gana de forma constante.

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

### 4. El sistema: qué apostar hoy y cuánto

```
python app.py sistema --bank 1000                       # perfil equilibrado, Kelly 1/4
python app.py sistema --bank 1000 --perfil volumen
python app.py sistema --backtest --casas B365 BW WH     # pruébalo solo con TUS casas
```

### 5. Solo el comparador de casas

```
python app.py valor              # próximos partidos
python app.py valor --backtest   # la tabla de resultados de arriba
python app.py valor --backtest --casas B365 BW   # solo con Bet365 y bwin
```

### 6. Otras órdenes

- `python app.py equipos --liga SP1`: goles y córners a favor y en contra de cada equipo. Ligas: E0, SP1, I1, D1, F1.
- `python app.py backtest`: comprueba si se cumplen las probabilidades del modelo.
- `python app.py optimizar`: una vez al mes. Recalcula los ajustes y la corrección con los datos nuevos (tarda unos minutos).
- `python app.py ejemplo`: liga inventada para probar sin conexión.

---

## Cuotas en vivo (opcional, recomendado)

Por defecto, las cuotas de los próximos partidos son las que football-data tomó al actualizar su archivo, que pueden tener horas o días. Con **The Odds API** el programa baja las cuotas **del momento** de muchas casas, incluidas Pinnacle y la bolsa de Betfair:

1. Regístrate gratis en **the-odds-api.com** (plan gratuito: 500 créditos al mes). Te mandan una clave por email.
2. Guárdala una vez: `python app.py configurar --clave-odds TU_CLAVE`
3. Listo: `jornada.bat` bajará también las cuotas en vivo y el sistema las usará durante las 12 horas siguientes.

Cada descarga de 20 ligas gasta unos 60 créditos, así que el plan gratuito da para unas 8 descargas al mes (2 por semana). Si quieres gastar menos, configura menos ligas. La clave se guarda solo en tu ordenador (`preferencias.json`) y no se sube a ningún sitio.

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
- `Abrir panel.bat` / `Abrir panel.command`, `panel.py` y `panel.html`: el panel con botones en el navegador.
- `jornada.bat` / `jornada.command`: lo de cada jornada, con doble clic. `informe.bat`: tu historial.
- `predictor/registro.py`: registro de picks (base de datos local), liquidación automática y estadísticas.
- `predictor/sistema.py`: perfiles del sistema, importe de cada apuesta y simulación del bank.
- `predictor/valor.py`: comparador de casas, precio justo y CLV.
- `predictor/modelo.py`: fuerzas de ataque y defensa, Poisson / Dixon-Coles y binomial negativa.
- `predictor/mercados.py`: probabilidad de cada mercado.
- `predictor/calibracion.py`: corrección con la experiencia.
- `predictor/cuotas.py`: cuota mínima, valor y Kelly.
- `predictor/backtest.py` y `predictor/optimizar.py`: pruebas con el histórico y búsqueda de ajustes.
- `predictor/descargar.py` y `predictor/datos.py`: descarga y lectura de datos.
- `predictor/cuotas_vivo.py`: cuotas en vivo de The Odds API.
