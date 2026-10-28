@echo off
rem Doble clic: abre el panel de apuestas en el navegador.
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% panel.py
pause
