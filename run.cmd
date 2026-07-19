@echo off
REM Lanza RadioNoiseKiller (modo desarrollo).
REM Uso: run   (desde la raíz del proyecto)
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" src\main.py %*
