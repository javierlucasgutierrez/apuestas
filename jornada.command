#!/bin/bash
# Mac/Linux: doble clic (o ./jornada.command) cada jornada.
cd "$(dirname "$0")"
python3 app.py actualizar
echo
python3 app.py sistema --guardar
echo
python3 app.py picks --publicar
echo
python3 app.py jornada --top 15
read -p "Pulsa Enter para cerrar..."
