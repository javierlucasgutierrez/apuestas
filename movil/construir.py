"""Prepara movil/datos/index.html (la página completa) para publicarla junto a los datos del día.

top10.html es la fuente; aquí se le pone el esqueleto HTML que pide el servidor de páginas.
Uso: python3 movil/construir.py
"""
import os

aqui = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(aqui, "top10.html"), encoding="utf-8") as f:
    cuerpo = f.read()
with open(os.path.join(aqui, "datos", "index.html"), "w", encoding="utf-8") as f:
    f.write('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>html,body{margin:0}</style></head><body>' + cuerpo + "</body></html>\n")
print("movil/datos/index.html listo")
