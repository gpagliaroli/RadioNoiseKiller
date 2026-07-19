@echo off
REM Corre toda la suite de regresión de RadioNoiseKiller.
REM Uso: test   (desde la raíz del proyecto)
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" tests\run_all.py %*
