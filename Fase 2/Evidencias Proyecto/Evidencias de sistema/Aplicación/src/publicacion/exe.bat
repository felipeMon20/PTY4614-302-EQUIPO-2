@echo off
REM Se ejecuta siempre desde la raiz del proyecto (dos carpetas mas arriba)
cd /d "%~dp0..\.."
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
python -m PyInstaller --noconsole --windowed --onedir --clean --name "Gestor_SSCC" --icon="src/assets/volvo.ico" --collect-all qtawesome --collect-all openpyxl --exclude-module setuptools --exclude-module pkg_resources --exclude-module _distutils_hack --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.QtWebChannel --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuickWidgets --exclude-module PyQt6.QtPositioning --exclude-module matplotlib --exclude-module PIL --add-data "src/assets;src/assets" main.py

REM Piezas de Qt que la aplicacion no usa (sin traducciones, sin visor PDF, sin OpenGL por software ni formatos de imagen que no usamos)
set "QT=dist\Gestor_SSCC\_internal\PyQt6\Qt6"
if exist "%QT%\translations" rmdir /s /q "%QT%\translations"
if exist "%QT%\bin\Qt6Pdf.dll" del /q "%QT%\bin\Qt6Pdf.dll"
if exist "%QT%\bin\opengl32sw.dll" del /q "%QT%\bin\opengl32sw.dll"
for %%F in (qpdf qtiff qwebp qicns qtga qwbmp) do if exist "%QT%\plugins\imageformats\%%F.dll" del /q "%QT%\plugins\imageformats\%%F.dll"

echo.
echo =================================================================
echo [EXITO] ¡COMPILACION FINALIZADA!
echo =================================================================
echo Tu aplicacion esta lista.
echo Recuerda que debes entrar a la carpeta: dist\Gestor_SSCC
echo Y hacer doble clic en: Gestor_SSCC.exe
echo.
if /i not "%~1"=="sinpausa" pause