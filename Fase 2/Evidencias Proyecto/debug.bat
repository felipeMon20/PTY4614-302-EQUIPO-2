@echo off
title Compilador Debug Empresa Demo
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

python -m PyInstaller --console --onedir --clean --name "Gestor_SSCC" --icon="src/assets/app.ico" --collect-all PyQt6.QtWebEngineWidgets --collect-all qtawesome --collect-all openpyxl --add-data "src/assets;src/assets" main.py

pause