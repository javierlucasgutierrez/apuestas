@echo off
rem Doble clic cada jornada: baja datos, liquida picks, da los nuevos y prepara el texto para publicar.
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% app.py actualizar
echo.
%PY% app.py sistema --guardar
echo.
%PY% app.py picks --publicar
echo.
%PY% app.py jornada --top 15
pause
