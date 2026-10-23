@echo off
REM Publica en la carpeta compartida la version generada por exe.bat.
REM Uso: publicar.bat "Notas de la version"   (sin argumentos las pide por pantalla)
cd /d "%~dp0"
if "%~1"=="" (
    python publicar.py
) else (
    python publicar.py --notas "%~1"
)
pause
