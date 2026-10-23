@echo off
title Empaquetador Produccion - Volvo Connect
color 0B
cls

echo =================================================================
echo             COMPILADOR DE PRODUCCION - GESTOR SSCC
echo =================================================================
echo.

echo [PASO 1] Eliminando compilaciones anteriores (Limpieza profunda)...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Gestor_SSCC.spec" del /q "Gestor_SSCC.spec"
echo Limpieza completada.
echo.

echo [PASO 2] Empaquetando la aplicacion...
echo (A continuacion veras el progreso real de los archivos empaquetandose)
echo =================================================================
echo.

REM Hemos quitado el silenciador para que veas el progreso y cambiado el icono a .ico
python -m PyInstaller --noconsole --windowed --onedir --clean --name "Gestor_SSCC" --icon="src/assets/volvo.ico" --collect-all qtawesome --collect-all openpyxl --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.QtWebChannel --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuickWidgets --exclude-module PyQt6.QtPositioning --exclude-module matplotlib --add-data "src/assets;src/assets" main.py

echo.
echo =================================================================
echo [EXITO] ¡COMPILACION FINALIZADA!
echo =================================================================
echo Tu aplicacion esta lista.
echo Recuerda que debes entrar a la carpeta: dist\Gestor_SSCC
echo Y hacer doble clic en: Gestor_SSCC.exe
echo.
pause