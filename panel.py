"""Panel con botones en el navegador: todo el programa sin escribir comandos.

Se abre con doble clic en "Abrir panel.bat" (Windows) o "Abrir panel.command" (Mac).
Funciona solo en tu ordenador: la página se sirve en 127.0.0.1 y nadie más puede verla.
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app as cli
from predictor.cuotas import seleccionar
from predictor.cuotas_vivo import archivo_proximos
from predictor.datos import Partido, cargar_csv, cargar_varios
from predictor.descargar import GRANDES
from predictor.mercados import Ajustes, Predictor
from predictor.modelo import emparejar_equipo
from predictor.registro import Registro, descripcion, resumir, stake_10
from predictor.sistema import PERFILES, apuestas_del_sistema, stake
from predictor.valor import CASAS, Oportunidad, leer_filas, precio_justo

PUERTO = 8765
PREFERENCIAS_POR_DEFECTO = {"bank": 50.0, "perfil": "goles", "metodo": "plano", "plano": 0.01,
                            "kelly": 0.25, "tope": 0.03, "ligas": ["todas"], "casas": ["Max"], "dias": 7}


# ------------------------------------------------------------------ utilidades
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def dia(fecha: date) -> str:
    return f"{DIAS[fecha.weekday()]} {fecha:%d/%m}"


def preferencias() -> dict:
    return {**PREFERENCIAS_POR_DEFECTO, **cli.leer_preferencias()}


def guardar_preferencias(prefs: dict) -> None:
    with open(cli.PREFERENCIAS, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)


def hay_datos() -> bool:
    return os.path.isdir(cli.DESCARGAS) and any(f.endswith(".csv") and not f.startswith("proximos")
                                                 for f in os.listdir(cli.DESCARGAS))


def ultima_actualizacion() -> str | None:
    ruta = os.path.join(cli.DESCARGAS, "proximos.csv")
    if not os.path.exists(ruta):
        return None
    return datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%d/%m/%Y %H:%M")


_cache = {"clave": None, "predictor": None}
_cerrojo = threading.Lock()


def predictor() -> Predictor:
    """El modelo ajustado con los datos descargados (se recalcula solo si cambian los datos)."""
    archivos = sorted(os.listdir(cli.DESCARGAS))
    clave = tuple((f, os.path.getmtime(os.path.join(cli.DESCARGAS, f))) for f in archivos)
    clave += ((os.path.getmtime(cli.AJUSTES) if os.path.exists(cli.AJUSTES) else 0),)
    with _cerrojo:
        if _cache["clave"] != clave:
            partidos = cargar_varios([cli.DESCARGAS])
            _cache["predictor"] = Predictor(Ajustes.cargar(cli.AJUSTES)).ajustar(partidos)
            _cache["clave"] = clave
        return _cache["predictor"]


def ya_guardado(registro: Registro, fecha: date, local: str, visitante: str, mercado: str) -> bool:
    return bool(registro.picks("fecha_partido = ? AND local = ? AND visitante = ? AND mercado = ?",
                               (fecha.isoformat(), local, visitante, mercado)))


def pct_stake(o: Oportunidad, prefs: dict) -> float:
    return stake(o, prefs["metodo"], fraccion_kelly=prefs["kelly"], tope=prefs["tope"], plano=prefs["plano"])


# ------------------------------------------------------------------ datos para la página
def datos_inicio() -> dict:
    prefs = preferencias()
    registro = Registro(cli.BASE_DATOS)
    picks = registro.picks()
    registro.cerrar()
    total, _, _ = resumir(picks)
    return {
        "hay_datos": hay_datos(), "actualizado": ultima_actualizacion(), "bank": prefs["bank"],
        "perfil": prefs["perfil"], "pendientes": sum(p.estado == "pendiente" for p in picks),
        "liquidados": total.picks, "unidades": round(total.unidades, 2), "yield": round(total.yield_pct, 1),
        "clave_odds": bool(cli.clave_odds()),
    }


def datos_picks(dias: int) -> dict:
    prefs = preferencias()
    hoy = date.today()
    filas = [f for f in leer_filas([archivo_proximos(cli.DESCARGAS)]) if not f.get("FTHG")]
    elegidas = [o for _, o in apuestas_del_sistema(filas, prefs["perfil"], prefs["casas"])
                if hoy <= o.fecha <= hoy + timedelta(days=dias)]
    registro = Registro(cli.BASE_DATOS)
    lista = []
    for o in elegidas:
        p = pct_stake(o, prefs)
        lista.append({
            "fecha": o.fecha.isoformat(), "dia": dia(o.fecha), "liga": o.liga,
            "nombre_liga": cli.NOMBRE_LIGA.get(o.liga, o.liga), "local": o.local, "visitante": o.visitante,
            "mercado": o.mercado, "familia": o.familia, "descripcion": descripcion(o),
            "casa": CASAS.get(o.casa, o.casa), "cuota": o.cuota, "cuota_justa": round(o.cuota_justa, 2),
            "cuota_minima": round(o.cuota_justa * 1.02, 2), "valor": round(100 * o.valor, 1),
            "stake_pct": p, "euros": round(prefs["bank"] * p, 2), "stake": stake_10(p, prefs["tope"]),
            "guardado": ya_guardado(registro, o.fecha, o.local, o.visitante, o.mercado),
        })
    registro.cerrar()
    return {"picks": lista, "perfil": prefs["perfil"], "bank": prefs["bank"], "actualizado": ultima_actualizacion()}


# Qué se enseña en las pestañas de goles y córners (salen del modelo, no de comparar casas).
# Goles: "más de" 1,5 / 2,5 / 3,5 y 1ª parte (más/menos 0,5 y 1,5), con cuota mínima entre 1,60
# y 2,10. Córners: las dos direcciones.
MODELO = {
    "goles": {"prefijo": ("Goles +", "1ª parte goles"), "cuota_min": 1.60, "cuota_max": 2.10, "prob_minima": 0.45},
    "corners": {"prefijo": "Córners", "cuota_min": 1.50, "cuota_max": 2.60, "prob_minima": 0.55},
}


def proximos_partidos(modelo: Predictor) -> list[tuple]:
    """Próximos partidos (Partido con los nombres del histórico, fila de cuotas o None).

    Junta los de football-data (2-3 días antes) y los de las cuotas en vivo (hasta 1-2
    semanas antes), traduciendo los nombres de equipo de The Odds API a los del histórico.
    """
    resultado, vistos = [], set()
    filas_fd = {(f.get("Date"), f.get("HomeTeam")): f
                for f in leer_filas([os.path.join(cli.DESCARGAS, "proximos.csv")]) if not f.get("FTHG")}
    for p in cargar_csv(os.path.join(cli.DESCARGAS, "proximos.csv")):
        if not p.jugado:
            resultado.append((p, filas_fd.get((p.fecha.strftime("%d/%m/%Y"), p.local))))
            vistos.add((p.fecha, p.local))
    vivo = os.path.join(cli.DESCARGAS, "proximos_vivo.csv")
    if archivo_proximos(cli.DESCARGAS) == vivo:
        for fila in leer_filas([vivo]):
            liga = fila.get("Div", "")
            if liga not in modelo.goles:
                continue
            equipos = modelo.goles[liga].equipos
            local = emparejar_equipo(fila["HomeTeam"], equipos)
            visitante = emparejar_equipo(fila["AwayTeam"], equipos)
            if not local or not visitante or local == visitante:
                continue
            fecha = datetime.strptime(fila["Date"], "%d/%m/%Y").date()
            if (fecha, local) in vistos:
                continue
            vistos.add((fecha, local))
            resultado.append((Partido(fecha, local, visitante, liga=liga), fila))
    return resultado


def datos_modelo(dias: int, tipo: str) -> dict:
    """Selecciones de goles o córners según el modelo, con su cuota mínima."""
    reglas = MODELO[tipo]
    prefs = preferencias()
    hoy = date.today()
    modelo = predictor()
    partidos = proximos_partidos(modelo)
    registro = Registro(cli.BASE_DATOS)
    lista = []
    for p, fila in partidos:
        if not hoy <= p.fecha <= hoy + timedelta(days=dias):
            continue
        try:
            pred = modelo.predecir(p.local, p.visitante, fecha=p.fecha)
        except KeyError:
            continue
        if pred.avisos or (tipo == "corners" and pred.corners_local is None):
            continue
        for s in seleccionar(pred.probs, None, cuota_min=reglas["cuota_min"], umbral=0.05,
                             prob_minima=reglas["prob_minima"]):
            # Fuera si la cuota mínima no la va a pagar nadie (muy por encima de la justa) o se sale del rango.
            if (not s.mercado.startswith(reglas["prefijo"]) or s.cuota_minima > s.cuota_justa * 1.10
                    or s.cuota_minima > reglas["cuota_max"]):
                continue
            item = {
                "fecha": p.fecha.isoformat(), "dia": dia(p.fecha), "liga": p.liga,
                "nombre_liga": cli.NOMBRE_LIGA.get(p.liga, p.liga), "local": pred.local,
                "visitante": pred.visitante, "mercado": s.mercado, "familia": "Córners" if tipo == "corners" else "Goles",
                "descripcion": descripcion(Oportunidad(p.fecha, p.liga, pred.local, pred.visitante, s.mercado,
                                                       "", 0, 0, "")),
                "prob": round(100 * s.prob), "cuota_justa": round(s.cuota_justa, 2),
                "cuota_minima": round(s.cuota_minima, 2),
                "esperados": round(pred.corners_local + pred.corners_visitante, 1) if tipo == "corners"
                else round(pred.goles_local + pred.goles_visitante, 1),
                "guardado": ya_guardado(registro, p.fecha, pred.local, pred.visitante, s.mercado),
                "mercado_justa": None, "mercado_mejor": None, "alcanzable": None,
            }
            if fila and s.mercado == "Goles +2.5":
                justo = precio_justo(fila, "Goles 2.5")
                mejor = fila.get("Max>2.5")
                if justo:
                    item["mercado_justa"] = round(1 / justo[0][0], 2)
                if mejor:
                    item["mercado_mejor"] = float(mejor)
                    # "si": alguna casa paga la mínima y además supera el precio justo del mercado.
                    # "dudoso": la paga, pero el mercado lo ve menos probable que el modelo (en el
                    # backtest, apostar solo con el modelo contra el mercado perdía dinero).
                    if item["mercado_mejor"] < item["cuota_minima"]:
                        item["alcanzable"] = "no"
                    elif item["mercado_justa"] and item["mercado_mejor"] < item["mercado_justa"] * 1.01:
                        item["alcanzable"] = "dudoso"
                    else:
                        item["alcanzable"] = "si"
            lista.append(item)
    registro.cerrar()
    # Una sola línea por partido: la más probable de las que pasan el filtro.
    mejores: dict = {}
    for c in lista:
        # Una del partido completo y otra de la 1ª parte, como mucho.
        clave = (c["fecha"], c["local"], c["visitante"], c["mercado"].startswith("1ª parte"))
        if clave not in mejores or c["guardado"] or (c["prob"] > mejores[clave]["prob"]
                                                     and not mejores[clave]["guardado"]):
            mejores[clave] = c
    # Primero las que alguna casa ya paga a la cuota mínima; al final, las que ninguna paga.
    orden = {"si": 0, None: 1, "dudoso": 2, "no": 3}
    lista = sorted(mejores.values(), key=lambda x: (orden[x["alcanzable"]], -x["prob"]))
    stake_sugerido = max(1, stake_10(prefs["plano"], prefs["tope"]) - 1)
    return {"selecciones": lista[:30], "stake_sugerido": stake_sugerido}


CALCULADORA = ["Goles +1.5", "Goles -1.5", "Goles +2.5", "Goles -2.5", "Goles +3.5", "Goles -3.5",
               "1ª parte goles +0.5", "1ª parte goles -0.5", "1ª parte goles +1.5", "1ª parte goles -1.5"] + \
              [f"Córners {s}{l}" for l in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5) for s in "+-"]


def lista_partidos(dias: int) -> dict:
    """Partidos de los próximos días que el modelo puede calcular (para la calculadora)."""
    modelo = predictor()
    hoy = date.today()
    lista = []
    for p, _ in proximos_partidos(modelo):
        if not hoy <= p.fecha <= hoy + timedelta(days=dias):
            continue
        try:
            modelo.predecir(p.local, p.visitante)
        except KeyError:
            continue
        lista.append({"fecha": p.fecha.isoformat(), "dia": dia(p.fecha), "liga": p.liga,
                      "nombre_liga": cli.NOMBRE_LIGA.get(p.liga, p.liga), "local": p.local, "visitante": p.visitante})
    lista.sort(key=lambda x: (x["fecha"], x["nombre_liga"]))
    return {"partidos": lista}


def probabilidades_partido(fecha: str, local: str, visitante: str) -> dict:
    """Probabilidad, cuota justa y cuota mínima de cada mercado de goles y córners de un partido."""
    prefs = preferencias()
    modelo = predictor()
    pred = modelo.predecir(local, visitante, fecha=date.fromisoformat(fecha))
    fila = next((f for p, f in proximos_partidos(modelo)
                 if p.fecha.isoformat() == fecha and p.local == pred.local), None)
    justo_25 = precio_justo(fila, "Goles 2.5") if fila else None
    mercados = []
    for m in CALCULADORA:
        prob = pred.probs.get(m)
        if not prob:
            continue
        item = {"mercado": m, "familia": "Córners" if m.startswith("Córners") else "Goles",
                "descripcion": descripcion(Oportunidad(date.today(), "", pred.local, pred.visitante, m, "", 0, 0, "")),
                "prob": round(100 * prob, 1), "cuota_justa": round(1 / prob, 2),
                # Las apuestas que salen solo del modelo necesitan más margen: un 5 % de valor.
                "cuota_minima": round(max(1.50, 1.05 / prob), 2), "mercado_justa": None}
        if justo_25 and m in ("Goles +2.5", "Goles -2.5"):
            item["mercado_justa"] = round(1 / justo_25[0][0 if "+" in m else 1], 2)
        mercados.append(item)
    return {"local": pred.local, "visitante": pred.visitante, "liga": pred.liga,
            "goles": round(pred.goles_local + pred.goles_visitante, 2),
            "corners": None if pred.corners_local is None else round(pred.corners_local + pred.corners_visitante, 1),
            "avisos": pred.avisos, "mercados": mercados, "bank": prefs["bank"], "plano": prefs["plano"],
            "stake": stake_10(prefs["plano"], prefs["tope"])}


def datos_historial() -> dict:
    registro = Registro(cli.BASE_DATOS)
    picks = registro.picks()
    registro.cerrar()
    total, por_mes, por_familia = resumir(picks)

    def resumen(r):
        return {"picks": r.picks, "acierto": round(r.acierto_pct), "cuota": round(r.cuota_media, 2),
                "unidades": round(r.unidades, 2), "yield": round(r.yield_pct, 1),
                "clv": None if r.clv_pct is None else round(r.clv_pct, 1)}

    liquidados = [p for p in picks if p.unidades is not None]
    semanas: dict = {}
    for p in liquidados:
        clave = p.fecha_partido.isocalendar()[:2]
        semanas[clave] = semanas.get(clave, 0.0) + p.unidades
    return {
        "total": resumen(total),
        "por_mes": [{"mes": m, **resumen(r)} for m, r in sorted(por_mes.items(), reverse=True)],
        "por_mercado": [{"mercado": m, **resumen(r)} for m, r in sorted(por_familia.items())],
        "racha_picks": cli.peor_racha([p.unidades for p in liquidados]),
        "semanas_pos": sum(v > 0 for v in semanas.values()), "semanas_neg": sum(v < 0 for v in semanas.values()),
        "racha_semanas": cli.peor_racha([semanas[k] for k in sorted(semanas)]),
        "picks": [{"id": p.id, "fecha": p.fecha_partido.strftime("%d/%m/%Y"), "partido": f"{p.local} - {p.visitante}",
                   "apuesta": descripcion(p), "casa": CASAS.get(p.casa, p.casa), "cuota": p.cuota, "stake": p.stake,
                   "estado": p.estado, "unidades": None if p.unidades is None else round(p.unidades, 2),
                   "publicado": p.publicado} for p in reversed(picks[-300:])],
    }


def guardar_pick(d: dict) -> dict:
    prefs = preferencias()
    fecha = date.fromisoformat(d["fecha"])
    cuota = float(str(d["cuota"]).replace(",", "."))
    if cuota <= 1:
        return {"ok": False, "mensaje": "La cuota tiene que ser mayor que 1."}
    justa = float(d.get("cuota_justa") or cuota)
    o = Oportunidad(fecha, d.get("liga", ""), d["local"], d["visitante"], d["mercado"], d.get("casa") or "manual",
                    cuota, 1 / justa, "manual", familia=d.get("familia") or "Córners")
    if d.get("stake"):  # stake 1-10 elegido a mano
        pct = int(d["stake"]) * prefs["tope"] / 10
    else:
        pct = float(d.get("stake_pct") or prefs["plano"])
    registro = Registro(cli.BASE_DATOS)
    nuevo = registro.guardar(o, pct, prefs["perfil"] if d.get("familia") not in ("Córners", "Goles") else "manual", prefs["tope"])
    registro.cerrar()
    return {"ok": True, "mensaje": "Guardado en tu historial." if nuevo else "Ya estaba guardado."}


def texto_publicar() -> dict:
    registro = Registro(cli.BASE_DATOS)
    nuevos = [p for p in registro.pendientes() if not p.publicado]
    partes = []
    for p in nuevos:
        liga = cli.NOMBRE_LIGA.get(p.liga, p.liga)
        texto = (f"⚽ {p.local} - {p.visitante} · {liga} · {p.fecha_partido:%d/%m}\n➡️ {descripcion(p)}\n"
                 f"💰 Cuota {p.cuota:.2f} ({CASAS.get(p.casa, p.casa)})\n📊 Stake {p.stake}/10")
        if p.cuota_justa and p.cuota_justa * 1.02 < p.cuota:
            texto += f"\n🔻 No apostar por debajo de {p.cuota_justa * 1.02:.2f}"
        partes.append(texto)
    if nuevos:
        registro.marcar_publicados([p.id for p in nuevos])
        os.makedirs(cli.PUBLICAR, exist_ok=True)
        with open(os.path.join(cli.PUBLICAR, f"{date.today():%Y-%m-%d}.txt"), "a", encoding="utf-8") as f:
            f.write("\n\n".join(partes) + "\n\n")
    registro.cerrar()
    return {"texto": "\n\n".join(partes), "cuantos": len(nuevos)}


def guardar_config(d: dict) -> dict:
    prefs = cli.leer_preferencias()
    try:
        prefs["bank"] = round(float(str(d["bank"]).replace(",", ".")), 2)
        prefs["perfil"] = d["perfil"] if d["perfil"] in PERFILES else "goles"
        prefs["metodo"] = "kelly" if d["metodo"] == "kelly" else "plano"
        prefs["plano"] = min(max(float(str(d["plano"]).replace(",", ".")) / 100, 0.002), 0.03)
        prefs["ligas"] = ["todas"] if d["ligas"] == "todas" else GRANDES
        prefs.setdefault("casas", ["Max"])
        if d.get("clave_odds"):
            prefs["clave_odds"] = d["clave_odds"].strip()
        elif d.get("borrar_clave"):
            prefs.pop("clave_odds", None)
    except (KeyError, ValueError):
        return {"ok": False, "mensaje": "Revisa los datos: el bank y el porcentaje tienen que ser números."}
    guardar_preferencias(prefs)
    return {"ok": True, "mensaje": "Configuración guardada."}


# ------------------------------------------------------------------ tareas largas (actualizar, optimizar)
_tarea = {"activa": False, "nombre": "", "log": [], "terminada": None}


def lanzar_tarea(nombre: str) -> dict:
    if _tarea["activa"]:
        return {"ok": False, "mensaje": "Ya hay una tarea en marcha. Espera a que termine."}
    orden = {"actualizar": ["actualizar", "--ligas", *preferencias()["ligas"]],
             "optimizar": ["optimizar"]}.get(nombre)
    if not orden:
        return {"ok": False, "mensaje": "Tarea desconocida."}
    _tarea.update(activa=True, nombre=nombre, log=[], terminada=None)

    def correr():
        entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proceso = subprocess.Popen([sys.executable, "-u", os.path.join(cli.CARPETA, "app.py"), *orden],
                                   cwd=cli.CARPETA, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", env=entorno)
        for linea in proceso.stdout:
            _tarea["log"].append(linea.rstrip())
        proceso.wait()
        _tarea["log"].append("✅ Terminado." if proceso.returncode == 0 else "❌ Algo ha fallado (mira las líneas de arriba).")
        _tarea.update(activa=False, terminada=datetime.now().strftime("%H:%M"))

    threading.Thread(target=correr, daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ servidor
class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):  # sin ruido en la ventana
        pass

    def _responder(self, cuerpo, tipo="application/json; charset=utf-8", codigo=200):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        dias = int(q.get("dias", ["3"])[0])
        try:
            if url.path == "/":
                with open(os.path.join(cli.CARPETA, "panel.html"), "rb") as f:
                    return self._responder(f.read(), "text/html; charset=utf-8")
            if url.path == "/api/inicio":
                return self._responder(datos_inicio())
            if url.path == "/api/config":
                prefs = preferencias()
                prefs["clave_odds"] = bool(prefs.get("clave_odds"))
                return self._responder(prefs)
            if url.path == "/api/tarea":
                return self._responder(_tarea)
            if not hay_datos():
                return self._responder({"error": "Primero pulsa «Actualizar datos» en Inicio."})
            if url.path == "/api/picks":
                return self._responder(datos_picks(dias))
            if url.path == "/api/partidos":
                return self._responder(lista_partidos(dias))
            if url.path == "/api/probs":
                return self._responder(probabilidades_partido(q["fecha"][0], q["local"][0], q["visitante"][0]))
            if url.path in ("/api/corners", "/api/goles"):
                return self._responder(datos_modelo(dias, url.path.rsplit("/", 1)[1]))
            if url.path == "/api/historial":
                return self._responder(datos_historial())
            self._responder({"error": "No encontrado"}, codigo=404)
        except Exception as e:  # noqa: BLE001 - se enseña el error en la página
            self._responder({"error": f"{type(e).__name__}: {e}"}, codigo=500)

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        datos = json.loads(self.rfile.read(largo) or b"{}")
        try:
            ruta = urlparse(self.path).path
            if ruta == "/api/guardar":
                return self._responder(guardar_pick(datos))
            if ruta == "/api/publicar":
                return self._responder(texto_publicar())
            if ruta == "/api/config":
                return self._responder(guardar_config(datos))
            if ruta == "/api/tarea":
                return self._responder(lanzar_tarea(datos.get("nombre", "")))
            self._responder({"error": "No encontrado"}, codigo=404)
        except Exception as e:  # noqa: BLE001
            self._responder({"ok": False, "mensaje": f"Error: {e}"}, codigo=500)


def main() -> None:
    for puerto in range(PUERTO, PUERTO + 20):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            continue
    else:
        sys.exit("No hay ningún puerto libre para abrir el panel.")
    url = f"http://127.0.0.1:{puerto}/"
    print(f"Panel abierto en {url}")
    print("Deja esta ventana abierta mientras usas el panel. Para cerrarlo, cierra esta ventana.")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
