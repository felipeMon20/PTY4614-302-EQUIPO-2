@echo off
REM Abre el ejecutable generado por exe.bat. No instala Python ni librerias.
set "EXE=%~dp0dist\Gestor_SSCC\Gestor_SSCC.exe"
if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)
echo No se encontro el ejecutable:
echo   %EXE%
echo Genera primero la aplicacion ejecutando exe.bat.
pause
exit /b 1
